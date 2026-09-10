"""Frozen data contracts shared across the engine, the models, and every client.

These modules define the *shape* of the data that flows between components:

- :mod:`almo_sweep.contracts.manifest` -- ``model.toml``: what a model declares.

They are intentionally dependency-light (standard library only) so that clients such
as the QGIS plugin can import them inside constrained interpreters.
"""

from __future__ import annotations

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

__all__ = [
    "MANIFEST_SCHEMA_VERSION",
    "ContractError",
    "InputKind",
    "InputSpec",
    "Invocation",
    "ManifestError",
    "ModelManifest",
    "OutputKind",
    "OutputSpec",
    "ParamSpec",
    "ParamType",
    "load_manifest",
    "parse_manifest",
]
