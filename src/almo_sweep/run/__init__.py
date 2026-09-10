"""The execution layer: resolve a run into a spec, then run it as a subprocess.

- :func:`resolve_runspec` turns a manifest plus concrete input paths and parameter values
  into a validated :class:`~almo_sweep.contracts.runspec.RunSpec`.
- :func:`run_one` spawns the model per the process contract, streams progress, enforces the
  timeout, and returns the :class:`~almo_sweep.contracts.result.RunResult`.

This subpackage may import the contracts, but like the rest of the engine it never imports
``qgis``.
"""

from __future__ import annotations

from almo_sweep.run.executor import ProgressCallback, run_one
from almo_sweep.run.resolve import RunError, resolve_runspec

__all__ = ["ProgressCallback", "RunError", "resolve_runspec", "run_one"]
