"""The execution layer: resolve a run into a spec, then run it (one run, or a whole sweep).

- :func:`resolve_runspec` turns a manifest plus concrete input paths and parameter values
  into a validated :class:`~slab_sweep.contracts.runspec.RunSpec`.
- :func:`run_one` spawns the model per the process contract, streams progress, enforces the
  timeout, and returns the :class:`~slab_sweep.contracts.result.RunResult`.
- :func:`run_sweep` drives many runs with concurrency, retries and cancellation, and writes a
  project :class:`~slab_sweep.run.run_index.RunIndex`.

This subpackage may import the contracts, but like the rest of the engine it never imports
``qgis``.
"""

from __future__ import annotations

from slab_sweep.run.executor import ProgressCallback, run_one
from slab_sweep.run.resolve import RunError, resolve_runspec
from slab_sweep.run.run_index import RunIndex, run_entry
from slab_sweep.run.scheduler import (
    SweepReport,
    SweepRun,
    default_index,
    default_max_workers,
    run_sweep,
)

__all__ = [
    "ProgressCallback",
    "RunError",
    "RunIndex",
    "SweepReport",
    "SweepRun",
    "default_index",
    "default_max_workers",
    "resolve_runspec",
    "run_entry",
    "run_one",
    "run_sweep",
]
