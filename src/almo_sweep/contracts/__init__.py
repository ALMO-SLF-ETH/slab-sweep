"""Frozen data contracts shared across the engine, the models, and every client.

These modules define the *shape* of the data that flows between components:

- :mod:`almo_sweep.contracts.manifest` -- ``model.toml``: what a model declares.
- :mod:`almo_sweep.contracts.distributions` / :mod:`~almo_sweep.contracts.sweep` -- a study:
  distributions per parameter and the sampling that expands them.
- :mod:`almo_sweep.contracts.runspec` -- ``runspec.json``: one resolved job into a model.
- :mod:`almo_sweep.contracts.result` -- ``result.json``: the outcome a model writes back.
- :mod:`almo_sweep.contracts.process` -- the spawn / progress / exit protocol between them.

They are intentionally dependency-light (standard library only) so that clients such
as the QGIS plugin can import them inside constrained interpreters.
"""

from __future__ import annotations

from almo_sweep.contracts.distributions import (
    Constant,
    Distribution,
    DistributionError,
    Normal,
)
from almo_sweep.contracts.errors import ContractError, ManifestError
from almo_sweep.contracts.manifest import (
    MANIFEST_SCHEMA_VERSION,
    InputKind,
    InputSpec,
    Invocation,
    ModelManifest,
    OutputKind,
    OutputSpec,
    ParamSpec,
    ParamType,
    load_manifest,
    parse_manifest,
)
from almo_sweep.contracts.process import (
    RESULT_FILENAME,
    RUNSPEC_FILENAME,
    ProcessError,
    ProgressEvent,
    build_argv,
    emit_progress,
    parse_progress_line,
)
from almo_sweep.contracts.result import (
    RESULT_SCHEMA_VERSION,
    ResultError,
    RunResult,
    RunStatus,
)
from almo_sweep.contracts.runspec import (
    RUNSPEC_SCHEMA_VERSION,
    RunSpec,
    RunSpecError,
)
from almo_sweep.contracts.sweep import SweepConfig, SweepError, build_sweep

__all__ = [
    "MANIFEST_SCHEMA_VERSION",
    "RESULT_FILENAME",
    "RESULT_SCHEMA_VERSION",
    "RUNSPEC_FILENAME",
    "RUNSPEC_SCHEMA_VERSION",
    "Constant",
    "ContractError",
    "Distribution",
    "DistributionError",
    "InputKind",
    "InputSpec",
    "Invocation",
    "ManifestError",
    "ModelManifest",
    "Normal",
    "OutputKind",
    "OutputSpec",
    "ParamSpec",
    "ParamType",
    "ProcessError",
    "ProgressEvent",
    "ResultError",
    "RunResult",
    "RunSpec",
    "RunSpecError",
    "RunStatus",
    "SweepConfig",
    "SweepError",
    "build_argv",
    "build_sweep",
    "emit_progress",
    "load_manifest",
    "parse_manifest",
    "parse_progress_line",
]
