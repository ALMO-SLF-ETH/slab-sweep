"""The model manifest contract: ``model.toml``.

A **manifest** is the declarative description a simulation model publishes about itself.
It is the single source of truth that lets a client (the QGIS plugin, a CLI, a notebook)
build a parameter form, wire up inputs and outputs, and invoke the model -- without any
model-specific code baked into the client. Swapping models or model versions is therefore
just a matter of pointing at a different manifest.

A manifest declares four things:

* **identity**   -- ``[model]``: name, version, and the manifest-schema version.
* **invocation** -- ``[invocation]``: how the engine spawns the model process.
* **inputs**     -- ``[inputs.*]``: the spatial data the model consumes (rasters, vectors).
* **params**     -- ``[params.*]``: the scalar knobs, with type, unit, bounds and default.
                    Numeric params may be *swept* (a distribution assigned at study time).
* **outputs**    -- ``[outputs.*]``: the artefacts the model produces, and whether storing
                    each one is optional.

The manifest declares the *parameter space*. It does **not** declare distributions or
sample counts -- those belong to a user-authored sweep config that is validated against
this manifest (a later contract).

This module is standard-library only so it can be imported inside QGIS's interpreter.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from enum import Enum, StrEnum
from pathlib import Path
from typing import Any

from almo_sweep.contracts.errors import ManifestError

#: Version of the manifest *format* understood by this module. A manifest declares the
#: format it was written against in ``[model].schema``; a mismatch in the major component
#: is rejected because the meaning of fields may have changed.
MANIFEST_SCHEMA_VERSION = "1.0"


class ParamType(StrEnum):
    """The scalar type of a model parameter."""

    FLOAT = "float"
    INT = "int"
    BOOL = "bool"
    CHOICE = "choice"


class InputKind(StrEnum):
    """The spatial data kind of a model input."""

    RASTER = "raster"
    VECTOR = "vector"


class OutputKind(StrEnum):
    """The kind of artefact a model produces."""

    RASTER = "raster"
    VECTOR = "vector"
    TABLE = "table"
    FILE = "file"


@dataclass(frozen=True)
class ParamSpec:
    """One scalar model parameter.

    ``sweepable`` marks a numeric parameter as eligible for a probabilistic study; the
    manifest only *permits* sweeping, it never assigns a distribution.
    """

    name: str
    type: ParamType
    default: Any
    description: str = ""
    unit: str | None = None
    min: float | None = None
    max: float | None = None
    choices: tuple[Any, ...] = ()
    sweepable: bool = False

    @property
    def is_numeric(self) -> bool:
        return self.type in (ParamType.FLOAT, ParamType.INT)


@dataclass(frozen=True)
class InputSpec:
    """One spatial input the model consumes."""

    name: str
    kind: InputKind
    required: bool = True
    description: str = ""
    #: For rasters: the 1-based band index the model reads (``None`` = model's choice).
    band: int | None = None
    #: For vectors: the required geometry type, e.g. ``"polygon"`` (``None`` = any).
    geometry: str | None = None


@dataclass(frozen=True)
class OutputSpec:
    """One artefact the model produces.

    ``optional`` means the user may choose *not* to keep this output for a run.
    """

    name: str
    kind: OutputKind
    description: str = ""
    #: Driver / file format hint, e.g. ``"GTiff"`` for a raster.
    format: str | None = None
    optional: bool = False


@dataclass(frozen=True)
class Invocation:
    """How the engine spawns the model as a subprocess.

    ``command`` is the base argv. ``args_template`` is appended and may contain
    ``{placeholder}`` tokens the engine substitutes with resolved run paths (for example
    ``{runspec}``). Substitution itself is the executor's job; the manifest only records
    the template.
    """

    command: tuple[str, ...]
    args_template: tuple[str, ...] = ()
    timeout_s: float | None = None


@dataclass(frozen=True)
class ModelManifest:
    """A parsed, validated ``model.toml``."""

    name: str
    version: str
    schema: str
    invocation: Invocation
    description: str = ""
    inputs: dict[str, InputSpec] = field(default_factory=dict)
    params: dict[str, ParamSpec] = field(default_factory=dict)
    outputs: dict[str, OutputSpec] = field(default_factory=dict)

    @property
    def sweepable_params(self) -> dict[str, ParamSpec]:
        """The subset of parameters that may take a distribution in a study."""
        return {n: p for n, p in self.params.items() if p.sweepable}

    @classmethod
    def from_toml(cls, path: str | Path) -> ModelManifest:
        return load_manifest(path)


# ---------------------------------------------------------------------------
# Loading & parsing
# ---------------------------------------------------------------------------
def load_manifest(path: str | Path) -> ModelManifest:
    """Read and validate a manifest from a ``model.toml`` file.

    :raises ManifestError: if the file is missing, is not valid TOML, or violates the
        manifest contract.
    """
    p = Path(path)
    try:
        raw = p.read_bytes()
    except OSError as exc:  # pragma: no cover - trivial passthrough
        raise ManifestError(f"cannot read manifest {p}: {exc}") from exc
    try:
        data = tomllib.loads(raw.decode("utf-8"))
    except (tomllib.TOMLDecodeError, UnicodeDecodeError) as exc:
        raise ManifestError(f"{p} is not valid TOML: {exc}") from exc
    return parse_manifest(data)


def parse_manifest(data: dict[str, Any]) -> ModelManifest:
    """Validate an already-decoded manifest mapping and build a :class:`ModelManifest`."""
    model = _require_table(data, "model")
    name = _require_str(model, "model.name")
    version = _require_str(model, "model.version")
    schema = str(model.get("schema", MANIFEST_SCHEMA_VERSION))
    _check_schema_version(schema)
    description = str(model.get("description", ""))

    invocation = _parse_invocation(_require_table(data, "invocation"))
    inputs = {
        n: _parse_input(n, _as_table(v, f"inputs.{n}")) for n, v in data.get("inputs", {}).items()
    }
    params = {
        n: _parse_param(n, _as_table(v, f"params.{n}")) for n, v in data.get("params", {}).items()
    }
    outputs = {
        n: _parse_output(n, _as_table(v, f"outputs.{n}"))
        for n, v in data.get("outputs", {}).items()
    }

    return ModelManifest(
        name=name,
        version=version,
        schema=schema,
        invocation=invocation,
        description=description,
        inputs=inputs,
        params=params,
        outputs=outputs,
    )


def _parse_invocation(t: dict[str, Any]) -> Invocation:
    command = _require_str_list(t, "invocation.command")
    if not command:
        raise ManifestError("invocation.command must contain at least one element")
    args_template = tuple(_optional_str_list(t, "invocation.args_template"))
    timeout = t.get("timeout_s")
    if timeout is not None and (not isinstance(timeout, (int, float)) or timeout <= 0):
        raise ManifestError("invocation.timeout_s must be a positive number")
    return Invocation(
        command=tuple(command),
        args_template=args_template,
        timeout_s=float(timeout) if timeout is not None else None,
    )


def _parse_input(name: str, t: dict[str, Any]) -> InputSpec:
    kind = _require_enum(t, f"inputs.{name}.kind", InputKind)
    band = t.get("band")
    if band is not None and (not isinstance(band, int) or isinstance(band, bool) or band < 1):
        raise ManifestError(f"inputs.{name}.band must be a positive integer")
    return InputSpec(
        name=name,
        kind=kind,
        required=bool(t.get("required", True)),
        description=str(t.get("description", "")),
        band=band,
        geometry=(str(t["geometry"]) if "geometry" in t else None),
    )


def _parse_param(name: str, t: dict[str, Any]) -> ParamSpec:
    ptype = _require_enum(t, f"params.{name}.type", ParamType)
    if "default" not in t:
        raise ManifestError(f"params.{name}.default is required")
    default = t["default"]
    minimum = _opt_number(t, f"params.{name}.min")
    maximum = _opt_number(t, f"params.{name}.max")
    choices = tuple(t.get("choices", ()))
    sweepable = bool(t.get("sweepable", False))

    if ptype is ParamType.CHOICE:
        if not choices:
            raise ManifestError(f"params.{name}.choices is required for a choice parameter")
        if default not in choices:
            raise ManifestError(f"params.{name}.default must be one of {list(choices)}")
        if sweepable:
            raise ManifestError(f"params.{name}: choice parameters cannot be swept")
    elif ptype is ParamType.BOOL:
        if not isinstance(default, bool):
            raise ManifestError(f"params.{name}.default must be a boolean")
        if sweepable:
            raise ManifestError(f"params.{name}: boolean parameters cannot be swept")
    else:  # FLOAT / INT
        if isinstance(default, bool) or not isinstance(default, (int, float)):
            raise ManifestError(f"params.{name}.default must be a number")
        if minimum is not None and maximum is not None and minimum > maximum:
            raise ManifestError(f"params.{name}: min ({minimum}) is greater than max ({maximum})")
        if minimum is not None and default < minimum:
            raise ManifestError(f"params.{name}.default ({default}) is below min ({minimum})")
        if maximum is not None and default > maximum:
            raise ManifestError(f"params.{name}.default ({default}) is above max ({maximum})")

    return ParamSpec(
        name=name,
        type=ptype,
        default=default,
        description=str(t.get("description", "")),
        unit=(str(t["unit"]) if "unit" in t else None),
        min=minimum,
        max=maximum,
        choices=choices,
        sweepable=sweepable,
    )


def _parse_output(name: str, t: dict[str, Any]) -> OutputSpec:
    kind = _require_enum(t, f"outputs.{name}.kind", OutputKind)
    return OutputSpec(
        name=name,
        kind=kind,
        description=str(t.get("description", "")),
        format=(str(t["format"]) if "format" in t else None),
        optional=bool(t.get("optional", False)),
    )


# ---------------------------------------------------------------------------
# Low-level validation helpers
# ---------------------------------------------------------------------------
def _check_schema_version(schema: str) -> None:
    supported_major = MANIFEST_SCHEMA_VERSION.split(".")[0]
    given_major = schema.split(".")[0]
    if given_major != supported_major:
        raise ManifestError(
            f"manifest schema {schema!r} is incompatible with supported "
            f"{MANIFEST_SCHEMA_VERSION!r} (major version differs)"
        )


def _require_table(data: dict[str, Any], key: str) -> dict[str, Any]:
    if key not in data:
        raise ManifestError(f"[{key}] table is required")
    return _as_table(data[key], key)


def _as_table(value: Any, path: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ManifestError(f"{path} must be a table")
    return value


def _require_str(t: dict[str, Any], path: str) -> str:
    key = path.split(".")[-1]
    value = t.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ManifestError(f"{path} is required and must be a non-empty string")
    return value


def _require_str_list(t: dict[str, Any], path: str) -> list[str]:
    key = path.split(".")[-1]
    if key not in t:
        raise ManifestError(f"{path} is required")
    return _coerce_str_list(t[key], path)


def _optional_str_list(t: dict[str, Any], path: str) -> list[str]:
    key = path.split(".")[-1]
    if key not in t:
        return []
    return _coerce_str_list(t[key], path)


def _coerce_str_list(value: Any, path: str) -> list[str]:
    if not isinstance(value, list) or not all(isinstance(x, str) for x in value):
        raise ManifestError(f"{path} must be a list of strings")
    return list(value)


def _require_enum(t: dict[str, Any], path: str, enum: type[Enum]) -> Any:
    key = path.split(".")[-1]
    value = t.get(key)
    try:
        return enum(value)
    except ValueError:
        allowed = ", ".join(repr(e.value) for e in enum)
        raise ManifestError(f"{path}={value!r} is invalid; expected one of {allowed}") from None


def _opt_number(t: dict[str, Any], path: str) -> float | None:
    key = path.split(".")[-1]
    if key not in t:
        return None
    value = t[key]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ManifestError(f"{path} must be a number")
    return float(value)
