"""Run the many simulations of a sweep, with concurrency, retries and cancellation.

:func:`run_sweep` is the engine's batch boundary: it takes the resolved runs a study expands to
and drives each through :func:`~slab_sweep.run.executor.run_one`, adding what a single run cannot
provide on its own:

* **concurrency** -- up to ``max_workers`` runs execute at once, each its own model process.
  Models here are single-threaded, so the natural setting is one run per physical core (see
  :func:`default_max_workers`; one per *logical* CPU oversubscribes hyper-threaded / hybrid parts).
  For a model that is itself multi-threaded (e.g. OpenMP), ``cap_model_threads`` (opt-in) shares the
  CPU out by limiting each run to ``cpu_count // max_workers`` threads so runs do not oversubscribe.
* **retries** -- a failed run is re-attempted up to ``retries`` extra times (a cancelled run is
  never retried), for models that fail transiently.
* **cancellation** -- one ``cancel_check`` is shared by every run; when it trips, in-flight runs
  are killed and still-queued runs short-circuit without spawning (see ``run_one``), so a Stop
  button stops the whole batch promptly.
* **a run index** -- when ``index`` is given, each run is appended to the project's ``runs.json``
  as it finishes, carrying its parameters and post-processing weight (so results inspection has a
  catalogue even if the sweep is interrupted).

Progress is reported through optional callbacks. They fire from worker threads, so a GUI host must
marshal back to its UI thread; the callbacks are invoked under a lock so they never overlap.
"""

from __future__ import annotations

import os
import threading
from collections.abc import Callable, Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from slab_sweep.contracts.manifest import ModelManifest
from slab_sweep.contracts.process import ProgressEvent
from slab_sweep.contracts.result import RunResult
from slab_sweep.contracts.runspec import RunSpec
from slab_sweep.run.executor import run_one
from slab_sweep.run.run_index import RunIndex, run_entry


@dataclass(frozen=True)
class SweepRun:
    """One run to execute in a sweep: its resolved spec plus the sample's weight.

    ``weight`` is the post-processing weight of the sample (decoupled from selection); it is
    recorded in the run index and never affects execution. ``substitutions`` overrides the
    sweep-wide invocation placeholders for this one run (rarely needed).
    """

    runspec: RunSpec
    weight: float = 1.0
    substitutions: Mapping[str, str] | None = None


@dataclass(frozen=True)
class SweepReport:
    """The outcome of a sweep: every run's result, in submission order."""

    results: list[RunResult]
    cancelled: bool = False

    @property
    def n_succeeded(self) -> int:
        return sum(1 for r in self.results if r.ok)

    @property
    def n_failed(self) -> int:
        return sum(1 for r in self.results if not r.ok)

    @property
    def ok(self) -> bool:
        """True if every run succeeded (and the sweep was not cancelled)."""
        return not self.cancelled and all(r.ok for r in self.results)


# Optional progress callbacks, each tagged with the run's submission index.
OnStarted = Callable[[int, SweepRun], None]
OnProgress = Callable[[int, ProgressEvent], None]
OnFinished = Callable[[int, RunResult], None]


@dataclass
class _Hooks:
    """Progress callbacks, invoked under one lock so they never overlap across worker threads."""

    started: OnStarted | None = None
    progress: OnProgress | None = None
    finished: OnFinished | None = None
    _lock: threading.Lock = field(default_factory=threading.Lock, init=False, repr=False)

    def on_started(self, i: int, run: SweepRun) -> None:
        if self.started is not None:
            with self._lock:
                self.started(i, run)

    def on_progress(self, i: int, event: ProgressEvent) -> None:
        if self.progress is not None:
            with self._lock:
                self.progress(i, event)

    def on_finished(self, i: int, result: RunResult) -> None:
        if self.finished is not None:
            with self._lock:
                self.finished(i, result)


def run_sweep(
    manifest: ModelManifest,
    runs: Sequence[SweepRun],
    *,
    max_workers: int = 1,
    retries: int = 0,
    env: Mapping[str, str] | None = None,
    substitutions: Mapping[str, str] | None = None,
    tool_versions: Mapping[str, Mapping[str, Any]] | None = None,
    cancel_check: Callable[[], bool] | None = None,
    cap_model_threads: bool = False,
    on_started: OnStarted | None = None,
    on_progress: OnProgress | None = None,
    on_finished: OnFinished | None = None,
    index: RunIndex | None = None,
) -> SweepReport:
    """Execute every run in ``runs`` and return a :class:`SweepReport` (results in input order).

    See the module docstring for the concurrency, retry, cancellation and indexing behaviour.
    ``substitutions`` applies to every run (a :class:`SweepRun` may override it per run);
    ``tool_versions`` and ``env`` apply to all.

    Raising ``max_workers`` runs that many models at once. The models run here are single-threaded,
    so the natural setting is one run per logical CPU and no thread management is needed. For a
    model that is itself multi-threaded (OpenMP), set ``cap_model_threads`` to share the machine
    out: it sets ``OMP_NUM_THREADS`` to ``cpu_count // max_workers`` for each run (unless the caller
    already set it), so parallel runs do not each grab every core and oversubscribe.
    """
    if max_workers < 1:
        raise ValueError("max_workers must be >= 1")
    if retries < 0:
        raise ValueError("retries must be >= 0")

    effective_env = _thread_capped_env(env, max_workers) if cap_model_threads else env
    hooks = _Hooks(on_started, on_progress, on_finished)
    results: list[RunResult | None] = [None] * len(runs)
    index_lock = threading.Lock()

    def execute(i: int, run: SweepRun) -> None:
        hooks.on_started(i, run)
        merged_subs = {**(substitutions or {}), **(run.substitutions or {})}

        forward: Callable[[ProgressEvent], None] | None = None
        if on_progress is not None:

            def forward(event: ProgressEvent, _i: int = i) -> None:
                hooks.on_progress(_i, event)

        result, attempts = _run_with_retries(
            manifest,
            run.runspec,
            retries=retries,
            env=effective_env,
            substitutions=merged_subs or None,
            tool_versions=tool_versions,
            cancel_check=cancel_check,
            on_progress=forward,
        )
        results[i] = result
        if index is not None:
            with index_lock:
                index.add(
                    run_entry(
                        run_id=run.runspec.run_id,
                        status="success" if result.ok else "failed",
                        output_dir=run.runspec.output_dir,
                        params=run.runspec.params,
                        weight=run.weight,
                        seed=run.runspec.seed,
                        duration_s=result.duration_s,
                        error=result.error,
                        attempts=attempts,
                    )
                )
        hooks.on_finished(i, result)

    if max_workers == 1:
        for i, run in enumerate(runs):
            execute(i, run)
    else:
        with ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="slab-sweep") as pool:
            futures = [pool.submit(execute, i, run) for i, run in enumerate(runs)]
            for fut in futures:
                fut.result()  # re-raise any unexpected worker exception

    final = [r for r in results if r is not None]
    cancelled = cancel_check is not None and cancel_check()
    return SweepReport(results=final, cancelled=cancelled)


def _run_with_retries(
    manifest: ModelManifest,
    runspec: RunSpec,
    *,
    retries: int,
    env: Mapping[str, str] | None,
    substitutions: Mapping[str, str] | None,
    tool_versions: Mapping[str, Mapping[str, Any]] | None,
    cancel_check: Callable[[], bool] | None,
    on_progress: Callable[[ProgressEvent], None] | None,
) -> tuple[RunResult, int]:
    """Run once, re-attempting a failure up to ``retries`` times. Returns the result and the
    number of attempts made. A cancelled run is returned immediately and never retried."""
    attempt = 0
    result = run_one(
        manifest,
        runspec,
        on_progress=on_progress,
        env=env,
        substitutions=substitutions,
        cancel_check=cancel_check,
        tool_versions=tool_versions,
    )
    attempt += 1
    while not result.ok and attempt <= retries and not _is_cancelled(result, cancel_check):
        result = run_one(
            manifest,
            runspec,
            on_progress=on_progress,
            env=env,
            substitutions=substitutions,
            cancel_check=cancel_check,
            tool_versions=tool_versions,
        )
        attempt += 1
    return result, attempt


def _is_cancelled(result: RunResult, cancel_check: Callable[[], bool] | None) -> bool:
    """Whether a failed run was cancelled (so it must not be retried)."""
    if cancel_check is not None and cancel_check():
        return True
    return bool(result.error and "cancelled" in result.error)


def default_max_workers() -> int:
    """A sensible default (and upper bound) for ``max_workers`` on this machine.

    Prefers the number of **physical** CPU cores, falling back to the logical count when that is
    unavailable. The models run here are single-threaded and FP-bound, so running one per *logical*
    CPU oversubscribes hyper-threaded / hybrid (P+E) processors: sibling threads and E-cores add
    contention that lowers total throughput and inflates per-run latency. One run per physical core
    is the better default; the caller can still raise it toward the logical count if desired.
    """
    physical = _physical_cpu_count()
    if physical:
        return max(1, physical)
    return max(1, os.cpu_count() or 1)


def _physical_cpu_count() -> int | None:
    """Physical CPU cores via :mod:`psutil`, or ``None`` if it is unavailable."""
    try:
        import psutil
    except ImportError:
        return None
    count = psutil.cpu_count(logical=False)
    return int(count) if count else None


def _thread_capped_env(env: Mapping[str, str] | None, max_workers: int) -> Mapping[str, str] | None:
    """Return ``env`` with ``OMP_NUM_THREADS`` set so ``max_workers`` runs share the CPU fairly.

    Each run is limited to ``cpu_count // max_workers`` threads (at least 1), so parallel runs of a
    multi-threaded (OpenMP) model do not each grab every core. Left untouched when running serially
    or when the caller already set ``OMP_NUM_THREADS``.
    """
    if max_workers <= 1:
        return env
    base = dict(env) if env is not None else dict(os.environ)
    if "OMP_NUM_THREADS" in base:
        return env  # respect an explicit choice
    per_run = max(1, (os.cpu_count() or max_workers) // max_workers)
    base["OMP_NUM_THREADS"] = str(per_run)
    return base


def default_index(project_root: str | Path, manifest: ModelManifest, **study: Any) -> RunIndex:
    """A :class:`RunIndex` at ``<project_root>/runs.json``, seeded with manifest + study info."""
    from slab_sweep.run.run_index import RUN_INDEX_FILENAME

    return RunIndex(
        path=Path(project_root) / RUN_INDEX_FILENAME,
        manifest={
            "name": manifest.name,
            "version": manifest.version,
            "sha256": manifest.source_sha256,
        },
        study=dict(study),
    )


__all__ = [
    "SweepReport",
    "SweepRun",
    "default_index",
    "default_max_workers",
    "run_sweep",
]
