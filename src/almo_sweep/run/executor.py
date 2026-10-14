"""Run a single model process per the process contract.

:func:`run_one` is the engine's boundary with a model. It uses the run's directory
(``runspec.output_dir``) as the working directory: it writes ``runspec.json`` there, spawns
the model, streams progress from stdout, enforces the manifest timeout, and reads back
``result.json``. If the model does not leave a valid result (crash, timeout, or a
non-conforming model), a failure :class:`RunResult` is synthesised so callers always get a
terminal outcome.
"""

from __future__ import annotations

import os
import subprocess
import sys
import threading
import time
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from almo_sweep.contracts.manifest import ModelManifest
from almo_sweep.contracts.process import (
    RESULT_FILENAME,
    RUNSPEC_FILENAME,
    ProgressEvent,
    build_argv,
    parse_progress_line,
)
from almo_sweep.contracts.result import RunResult
from almo_sweep.contracts.runspec import RunSpec

#: Called with each progress event parsed from the model's stdout.
ProgressCallback = Callable[[ProgressEvent], None]

#: How many trailing log lines to keep for a failure message.
_LOG_TAIL = 20

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


def run_one(
    manifest: ModelManifest,
    runspec: RunSpec,
    *,
    on_progress: ProgressCallback | None = None,
    env: Mapping[str, str] | None = None,
    substitutions: Mapping[str, str] | None = None,
) -> RunResult:
    """Execute one run and return its result.

    The run's directory is ``runspec.output_dir``; it is created if needed. ``env``, if given,
    replaces the child environment (default: inherit the parent's).

    Invocation placeholders resolved by default: ``{runspec}``, ``{rundir}``, ``{outdir}``,
    and ``{python}`` (the interpreter running the engine). ``substitutions`` adds or overrides
    these -- e.g. a QGIS client passing the QGIS interpreter as ``{python}``.
    """
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

    started = time.monotonic()
    log_lines, timed_out, exit_code = _spawn_and_stream(
        argv,
        cwd=run_dir,
        env=dict(env) if env is not None else None,
        timeout_s=manifest.invocation.timeout_s,
        on_progress=on_progress,
    )
    duration = time.monotonic() - started
    log_tail = "\n".join(log_lines[-_LOG_TAIL:])

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


def _spawn_and_stream(
    argv: list[str],
    *,
    cwd: Path,
    env: dict[str, str] | None,
    timeout_s: float | None,
    on_progress: ProgressCallback | None,
) -> tuple[list[str], bool, int]:
    """Spawn the process, forward progress, and collect non-progress stdout as log lines.

    stderr is merged into stdout so a single pipe cannot deadlock. Returns the collected log
    lines, whether the run timed out, and the process exit code.
    """
    log_lines: list[str] = []
    timed_out = False
    with subprocess.Popen(
        argv,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        cwd=str(cwd),
        env=env,
        **_no_window_kwargs(),
    ) as proc:
        timer: threading.Timer | None = None
        if timeout_s is not None:

            def _kill() -> None:
                nonlocal timed_out
                timed_out = True
                proc.kill()

            timer = threading.Timer(timeout_s, _kill)
            timer.start()

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

    return log_lines, timed_out, exit_code
