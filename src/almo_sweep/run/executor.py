"""Run a single model process per the process contract.

:func:`run_one` is the engine's boundary with a model. It uses the run's directory
(``runspec.output_dir``) as the working directory: it writes ``runspec.json`` there, spawns
the model, streams progress from stdout, enforces the manifest timeout, and reads back
``result.json``. If the model does not leave a valid result (crash, timeout, or a
non-conforming model), a failure :class:`RunResult` is synthesised so callers always get a
terminal outcome.
"""

from __future__ import annotations

import contextlib
import json
import os
import signal
import subprocess
import sys
import threading
import time
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from almo_sweep.contracts.manifest import ModelManifest
from almo_sweep.contracts.process import (
    CANCEL_ENV,
    CANCEL_FILENAME,
    RESULT_FILENAME,
    RUNSPEC_FILENAME,
    ProgressEvent,
    build_argv,
    parse_progress_line,
)
from almo_sweep.contracts.result import RunResult
from almo_sweep.contracts.runspec import RunSpec
from almo_sweep.provenance import engine_provenance

#: Called with each progress event parsed from the model's stdout.
ProgressCallback = Callable[[ProgressEvent], None]

#: Per-run record of the code that produced it (engine + tools + model), written beside result.json.
PROVENANCE_FILENAME = "provenance.json"

#: How many trailing log lines to keep for a failure message.
_LOG_TAIL = 20

#: Grace period after raising the cancel sentinel before the process tree is hard-killed. Long
#: enough for a cooperating model to stop cleanly and write a final log note; a model that does
#: not cooperate is killed after it.
_CANCEL_GRACE_S = 5.0

#: On Windows, suppress the console window a GUI host (e.g. QGIS) would otherwise flash when
#: spawning a console subprocess. The flag does not exist on other platforms (0 = no-op).
_CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def _no_window_kwargs() -> dict[str, Any]:
    """Popen kwargs that keep a console subprocess windowless on Windows (no-op elsewhere)."""
    kwargs: dict[str, Any] = {"creationflags": _CREATE_NO_WINDOW}
    if os.name == "nt":
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startupinfo.wShowWindow = subprocess.SW_HIDE
        kwargs["startupinfo"] = startupinfo
    return kwargs


def _spawn_kwargs() -> dict[str, Any]:
    """Popen kwargs for spawning a model so its whole tree can be killed later.

    On POSIX the child starts its own session, making it a process-group leader, so a single
    ``killpg`` takes down the model *and* anything it spawns (e.g. an adapter that runs the real
    binary). On Windows ``taskkill /T`` walks the PID tree instead, so nothing extra is needed
    there. Keeps the windowless console flags either way.
    """
    kwargs = _no_window_kwargs()
    if os.name != "nt":
        kwargs["start_new_session"] = True
    return kwargs


def _terminate_tree(proc: subprocess.Popen[str]) -> None:
    """Kill ``proc`` and every descendant it spawned.

    Models are often launched through a thin launcher (here ``python -m dampm_interface run``)
    that itself spawns the real binary. Killing only the direct child would orphan that
    grandchild, which keeps running to completion -- producing outputs and holding the stdout
    pipe open. Killing the whole tree stops the actual computation.
    """
    if proc.poll() is not None:
        return  # already gone
    if os.name == "nt":
        # /T terminates the tree rooted at the PID, /F forces it. Fall back to a direct kill.
        try:
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                capture_output=True,
                check=False,
                **_no_window_kwargs(),
            )
            return
        except Exception:
            proc.kill()
            return
    try:
        os.killpg(os.getpgid(proc.pid), signal.SIGKILL)  # type: ignore[attr-defined]
    except Exception:
        proc.kill()


def run_one(
    manifest: ModelManifest,
    runspec: RunSpec,
    *,
    on_progress: ProgressCallback | None = None,
    env: Mapping[str, str] | None = None,
    substitutions: Mapping[str, str] | None = None,
    cancel_check: Callable[[], bool] | None = None,
    tool_versions: Mapping[str, Mapping[str, Any]] | None = None,
) -> RunResult:
    """Execute one run and return its result.

    The run's directory is ``runspec.output_dir``; it is created if needed. ``env``, if given,
    replaces the child environment (default: inherit the parent's).

    Invocation placeholders resolved by default: ``{runspec}``, ``{rundir}``, ``{outdir}``,
    and ``{python}`` (the interpreter running the engine). ``substitutions`` adds or overrides
    these -- e.g. a QGIS client passing the QGIS interpreter as ``{python}``.

    ``cancel_check``, if given, is polled while the model runs; as soon as it returns True the
    model process is killed and a ``cancelled``-flagged failure result is returned. A GUI host
    can pass e.g. a task's ``isCanceled`` so a Stop button terminates the actual subprocess.

    ``tool_versions`` maps a label (e.g. ``"gui"``) to a provenance record for a client that drove
    this run; together with the engine's own version and the model's (from ``result.json``) they
    are written to ``provenance.json`` in the run folder, so each result records the code that
    produced it.
    """
    # Already cancelled before we start? Don't spawn anything. This is what lets a future sweep
    # stop: cancelling the batch means every still-queued run returns here at once, untouched,
    # instead of each starting its model only to be killed.
    if cancel_check is not None and cancel_check():
        return RunResult.failure(runspec.run_id, error="cancelled by user", duration_s=0.0)

    run_dir = Path(runspec.output_dir)
    run_dir.mkdir(parents=True, exist_ok=True)
    runspec_path = run_dir / RUNSPEC_FILENAME
    runspec.write(runspec_path)

    resolved = {
        "runspec": str(runspec_path),
        "rundir": str(run_dir),
        "outdir": str(run_dir),
        "python": sys.executable,
    }
    if substitutions:
        resolved.update(substitutions)
    argv = build_argv(manifest.invocation, resolved)

    # Cooperative-cancel sentinel (see the process contract): advertise its path to the model and
    # make sure no stale one is left over from a previous run of this directory.
    cancel_file = run_dir / CANCEL_FILENAME
    cancel_file.unlink(missing_ok=True)
    child_env = dict(env) if env is not None else dict(os.environ)
    child_env[CANCEL_ENV] = str(cancel_file)

    started = time.monotonic()
    log_lines, timed_out, cancelled, exit_code = _spawn_and_stream(
        argv,
        cwd=run_dir,
        env=child_env,
        timeout_s=manifest.invocation.timeout_s,
        on_progress=on_progress,
        cancel_check=cancel_check,
        cancel_file=cancel_file,
    )
    duration = time.monotonic() - started
    log_tail = "\n".join(log_lines[-_LOG_TAIL:])

    # Record what produced this run (engine + any client tools + the model's own provenance from
    # result.json), whatever the outcome -- an executed run folder should explain its origin.
    _write_provenance(run_dir, tool_versions)

    if cancelled:
        # A cancel takes precedence over any other outcome: the process was killed on request.
        return RunResult.failure(
            runspec.run_id,
            error="cancelled by user",
            message=log_tail,
            duration_s=duration,
        )
    if timed_out:
        return RunResult.failure(
            runspec.run_id,
            error=f"timed out after {manifest.invocation.timeout_s}s",
            message=log_tail,
            duration_s=duration,
        )

    result_path = run_dir / RESULT_FILENAME
    if not result_path.exists():
        return RunResult.failure(
            runspec.run_id,
            error=f"model exited with code {exit_code} without writing {RESULT_FILENAME}",
            message=log_tail,
            duration_s=duration,
        )
    try:
        return RunResult.read(result_path)
    except Exception as exc:
        return RunResult.failure(
            runspec.run_id,
            error=f"invalid {RESULT_FILENAME}: {exc}",
            message=log_tail,
            duration_s=duration,
        )


def _write_provenance(run_dir: Path, tool_versions: Mapping[str, Mapping[str, Any]] | None) -> None:
    """Write ``provenance.json`` recording the code that produced this run.

    Always includes the engine's own version and any client ``tool_versions``. If the model wrote a
    ``provenance`` block into ``result.json`` (e.g. a model binary's version + its adapter's), it is
    folded in under ``model`` so one file holds every component. Best-effort: never fails the run.
    """
    record: dict[str, Any] = {
        "schema": "1.0",
        "engine": engine_provenance(),
        "tools": {k: dict(v) for k, v in (tool_versions or {}).items()},
    }
    result_file = run_dir / RESULT_FILENAME
    if result_file.exists():
        try:
            raw = json.loads(result_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            raw = {}
        model = raw.get("provenance") if isinstance(raw, dict) else None
        if isinstance(model, dict):
            record["model"] = model
    with contextlib.suppress(OSError):
        (run_dir / PROVENANCE_FILENAME).write_text(json.dumps(record, indent=2), encoding="utf-8")


def _spawn_and_stream(
    argv: list[str],
    *,
    cwd: Path,
    env: dict[str, str] | None,
    timeout_s: float | None,
    on_progress: ProgressCallback | None,
    cancel_check: Callable[[], bool] | None = None,
    cancel_file: Path | None = None,
) -> tuple[list[str], bool, bool, int]:
    """Spawn the process, forward progress, and collect non-progress stdout as log lines.

    stderr is merged into stdout so a single pipe cannot deadlock. Returns the collected log
    lines, whether the run timed out, whether it was cancelled, and the process exit code.

    On cancel the watcher first creates ``cancel_file`` (the cooperative stop sentinel) and gives
    the model a short grace period to stop cleanly on its own; if it does not, the whole process
    tree is hard-killed. The timeout path hard-kills immediately. Killing the process closes its
    stdout, which ends the streaming loop below, so a model that emits no output (or is
    mid-compute) is still interrupted promptly.
    """
    log_lines: list[str] = []
    timed_out = False
    cancelled = False
    with subprocess.Popen(
        argv,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        cwd=str(cwd),
        env=env,
        **_spawn_kwargs(),
    ) as proc:
        timer: threading.Timer | None = None
        if timeout_s is not None:

            def _kill() -> None:
                nonlocal timed_out
                timed_out = True
                _terminate_tree(proc)

            timer = threading.Timer(timeout_s, _kill)
            timer.start()

        # A cancel watcher polls ``cancel_check`` off-thread. On a stop it raises the cooperative
        # sentinel, waits a grace period for the model to exit on its own (so it can write a final
        # log note), then hard-kills the tree. ``watch_stop`` retires it the instant the process
        # ends -- including the moment it exits cleanly during that grace wait.
        watcher: threading.Thread | None = None
        watch_stop = threading.Event()
        if cancel_check is not None:

            def _watch() -> None:
                nonlocal cancelled
                while not watch_stop.wait(0.1):
                    if cancel_check():
                        cancelled = True
                        if cancel_file is not None:
                            with contextlib.suppress(OSError):
                                cancel_file.write_text("1", encoding="utf-8")
                        deadline = time.monotonic() + _CANCEL_GRACE_S
                        while proc.poll() is None and time.monotonic() < deadline:
                            if watch_stop.wait(0.1):
                                break  # exited on its own -> no hard kill needed
                        if proc.poll() is None:
                            _terminate_tree(proc)
                        return

            watcher = threading.Thread(target=_watch, name="almo-run-cancel", daemon=True)
            watcher.start()

        try:
            assert proc.stdout is not None  # PIPE guarantees a stream
            for line in proc.stdout:
                event = parse_progress_line(line)
                if event is not None:
                    if on_progress is not None:
                        on_progress(event)
                else:
                    text = line.rstrip("\n")
                    if text:
                        log_lines.append(text)
            exit_code = proc.wait()
        finally:
            if timer is not None:
                timer.cancel()
            watch_stop.set()
            if watcher is not None:
                watcher.join(timeout=1.0)

    return log_lines, timed_out, cancelled, exit_code
