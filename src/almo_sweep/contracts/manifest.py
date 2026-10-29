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
                    A param may carry a human ``label``, a ``group`` it belongs to, and
                    ``visible_when`` conditions that gate its display on other params' values.
* **groups**     -- ``[[groups]]``: an ordered list of sections a client lays its parameter
                    form out in; each param names the group it belongs to.
* **outputs**    -- ``[outputs.*]``: the artefacts the model produces, and whether storing
                    each one is optional.

Every declarable thing may carry a ``label`` (a human-readable name) and a ``description``;
together with groups and ``visible_when`` these are what a client needs to render a form and
what a generator needs to write parameter documentation -- so the two never drift.

The manifest declares the *parameter space*. It does **not** declare distributions or
sample counts -- those belong to a user-authored sweep config that is validated against
this manifest (a later contract).

This module is standard-library only so it can be imported inside QGIS's interpreter.
"""

from __future__ import annotations

import hashlib
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from enum import Enum, StrEnum
from pathlib import Path
from typing import Any

from almo_sweep.contracts.errors import ManifestError

#: Version of the manifest *format* understood by this module. A manifest declares the
#: format it was written against in ``[model].schema``; a mismatch in the major component
#: is rejected because the meaning of fields may have changed. 1.1 added the optional
#: presentation vocabulary (``label``, ``[[groups]]`` + param ``group``, ``visible_when``);
#: 1.0 manifests remain valid since the new fields are optional.
MANIFEST_SCHEMA_VERSION = "1.1"


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


class RuntimeKind(StrEnum):
    """The kind of value a runtime setting holds (drives the UI control that edits it)."""

    FILE = "file"
    DIRECTORY = "directory"
    STRING = "string"


@dataclass(frozen=True)
class RuntimeSpec:
    """A machine-specific runtime setting the model needs (e.g. the path to its binary).

    Declared in the manifest so a client can prompt for it, persist it, and supply it to the
    model at run time as an environment variable of the same name. Not part of a study -- it
    is host configuration, not a parameter.
    """

    name: str
    kind: RuntimeKind
    description: str = ""
    required: bool = True


@dataclass(frozen=True)
class GroupSpec:
    """A labelled section a client lays parameters out in.

    Groups are declared as an ordered list; a client renders them in that order, and renders
    the params that name each group (in manifest order) beneath it.
    """

    id: str
    label: str = ""
    description: str = ""

    @property
    def display_label(self) -> str:
        return self.label or self.id


@dataclass(frozen=True)
class VisibilityClause:
    """One condition gating a parameter's display: ``param`` must hold one of ``values``.

    A parameter's ``visible_when`` is a tuple of these, combined with logical **and** -- the
    parameter is shown only while *every* clause is satisfied. Visibility is a presentation
    concern: a hidden parameter keeps its value (its default, or whatever was last set) and is
    still passed to the model, so this never changes what the model receives.
    """

    param: str
    values: tuple[Any, ...]

    def satisfied_by(self, current: Mapping[str, Any]) -> bool:
        return current.get(self.param) in self.values


@dataclass(frozen=True)
class ParamSpec:
    """One scalar model parameter.

    ``sweepable`` marks a numeric parameter as eligible for a probabilistic study; the
    manifest only *permits* sweeping, it never assigns a distribution.

    ``label`` is a human-readable name for the control and documentation (the ``name`` key
    stays the unique code identifier). ``group`` names the :class:`GroupSpec` the param is laid
    out under. ``visible_when`` gates the param's display on other params' current values.
    """

    name: str
    type: ParamType
    default: Any
    label: str = ""
    description: str = ""
    unit: str | None = None
    min: float | None = None
    max: float | None = None
    choices: tuple[Any, ...] = ()
    sweepable: bool = False
    group: str | None = None
    visible_when: tuple[VisibilityClause, ...] = ()

    @property
    def is_numeric(self) -> bool:
        return self.type in (ParamType.FLOAT, ParamType.INT)

    @property
    def display_label(self) -> str:
        return self.label or self.name

    def is_visible(self, current: Mapping[str, Any]) -> bool:
        """Whether this param should be shown given the other params' ``current`` values."""
        return all(clause.satisfied_by(current) for clause in self.visible_when)


@dataclass(frozen=True)
class InputSpec:
    """One spatial input the model consumes."""

    name: str
    kind: InputKind
    required: bool = True
    label: str = ""
    description: str = ""
    #: For rasters: the 1-based band index the model reads (``None`` = model's choice).
    band: int | None = None
    #: For vectors: the required geometry type, e.g. ``"polygon"`` (``None`` = any).
    geometry: str | None = None
    #: Presentation (same vocabulary as params): the group this input is laid out under and
    #: the conditions that gate its display on other params' values.
    group: str | None = None
    visible_when: tuple[VisibilityClause, ...] = ()

    @property
    def display_label(self) -> str:
        return self.label or self.name

    def is_visible(self, current: Mapping[str, Any]) -> bool:
        """Whether this input should be shown given the params' ``current`` values."""
        return all(clause.satisfied_by(current) for clause in self.visible_when)


@dataclass(frozen=True)
class OutputSpec:
    """One artefact the model produces.

    ``optional`` means the user may choose *not* to keep this output for a run.
    """

    name: str
    kind: OutputKind
    label: str = ""
    description: str = ""
    #: Driver / file format hint, e.g. ``"GTiff"`` for a raster.
    format: str | None = None
    optional: bool = False

    @property
    def display_label(self) -> str:
        return self.label or self.name


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
    runtime: dict[str, RuntimeSpec] = field(default_factory=dict)
    groups: tuple[GroupSpec, ...] = ()
    #: SHA-256 (hex) of the source ``model.toml`` bytes, set by :func:`load_manifest`; ``None`` for
    #: a manifest built directly from a dict (no source file). Recorded in run provenance so a
    #: result pins the exact manifest that produced it.
    source_sha256: str | None = None

    @property
    def sweepable_params(self) -> dict[str, ParamSpec]:
        """The subset of parameters that may take a distribution in a study."""
        return {n: p for n, p in self.params.items() if p.sweepable}

    def grouped_params(self) -> list[tuple[GroupSpec, list[ParamSpec]]]:
        """Params bucketed by group, in group-declaration then param-declaration order.

        Every declared group is returned (even if empty). Params whose ``group`` is unset or
        names no declared group are collected under a trailing synthetic ``""`` group, so a
        client can always render every parameter. A manifest with no ``[[groups]]`` therefore
        yields a single unnamed bucket holding all params, in manifest order.
        """
        known = {g.id: g for g in self.groups}
        buckets: dict[str, list[ParamSpec]] = {g.id: [] for g in self.groups}
        leftover: list[ParamSpec] = []
        for spec in self.params.values():
            if spec.group is not None and spec.group in known:
                buckets[spec.group].append(spec)
            else:
                leftover.append(spec)
        result = [(known[gid], buckets[gid]) for gid in buckets]
        if leftover:
            result.append((GroupSpec(id="", label=""), leftover))
        return result

    def grouped_items(self) -> list[tuple[GroupSpec, list[ParamSpec], list[InputSpec]]]:
        """Params **and** inputs bucketed by group, for a combined form.

        Each returned tuple is ``(group, params, inputs)`` -- the params and the inputs that
        name that group, each in manifest order. Group order follows ``[[groups]]``; a trailing
        synthetic ``""`` group collects anything ungrouped. A client typically renders the
        params then the inputs within each group. Mirrors :meth:`grouped_params` but spans both
        sections, so inputs (e.g. a release-zone layer) can sit beside the params they relate to
        and share their ``visible_when`` gating.
        """
        known = {g.id: g for g in self.groups}
        pbuckets: dict[str, list[ParamSpec]] = {g.id: [] for g in self.groups}
        ibuckets: dict[str, list[InputSpec]] = {g.id: [] for g in self.groups}
        ploose: list[ParamSpec] = []
        iloose: list[InputSpec] = []
        for p in self.params.values():
            (pbuckets[p.group] if p.group in known else ploose).append(p)
        for i in self.inputs.values():
            (ibuckets[i.group] if i.group in known else iloose).append(i)
        result = [(known[gid], pbuckets[gid], ibuckets[gid]) for gid in known]
        if ploose or iloose:
            result.append((GroupSpec(id="", label=""), ploose, iloose))
        return result

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
    return replace(parse_manifest(data), source_sha256=hashlib.sha256(raw).hexdigest())


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
    runtime = {
        n: _parse_runtime(n, _as_table(v, f"runtime.{n}"))
        for n, v in data.get("runtime", {}).items()
    }
    groups = _parse_groups(data.get("groups", []))
    _validate_references(params, inputs, groups)

    return ModelManifest(
        name=name,
        version=version,
        schema=schema,
        invocation=invocation,
        description=description,
        inputs=inputs,
        params=params,
        outputs=outputs,
        runtime=runtime,
        groups=groups,
    )


def _parse_groups(raw: Any) -> tuple[GroupSpec, ...]:
    if not isinstance(raw, list):
        raise ManifestError("groups must be an array of tables ([[groups]])")
    groups: list[GroupSpec] = []
    seen: set[str] = set()
    for i, item in enumerate(raw):
        t = _as_table(item, f"groups[{i}]")
        gid = _require_str(t, f"groups[{i}].id")
        if gid in seen:
            raise ManifestError(f"duplicate group id {gid!r}")
        seen.add(gid)
        groups.append(
            GroupSpec(
                id=gid,
                label=str(t.get("label", "")),
                description=str(t.get("description", "")),
            )
        )
    return tuple(groups)


def _validate_references(
    params: dict[str, ParamSpec],
    inputs: dict[str, InputSpec],
    groups: tuple[GroupSpec, ...],
) -> None:
    """Every ``group`` (on a param or input) must name a declared group, and every
    ``visible_when`` must name a declared param (a param may never gate on itself)."""
    group_ids = {g.id for g in groups}

    def _check(
        section: str, name: str, group: str | None, clauses: tuple[VisibilityClause, ...]
    ) -> None:
        if group is not None and group not in group_ids:
            raise ManifestError(
                f"{section}.{name}.group={group!r} is not a declared group "
                f"(declare it with [[groups]])"
            )
        for clause in clauses:
            if section == "params" and clause.param == name:
                raise ManifestError(f"params.{name}.visible_when cannot depend on itself")
            if clause.param not in params:
                raise ManifestError(
                    f"{section}.{name}.visible_when references unknown param {clause.param!r}"
                )

    for name, spec in params.items():
        _check("params", name, spec.group, spec.visible_when)
    for name, ispec in inputs.items():
        _check("inputs", name, ispec.group, ispec.visible_when)


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
        label=str(t.get("label", "")),
        description=str(t.get("description", "")),
        band=band,
        geometry=(str(t["geometry"]) if "geometry" in t else None),
        group=(str(t["group"]) if "group" in t else None),
        visible_when=_parse_visible_when(name, t.get("visible_when", []), section="inputs"),
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

    group = str(t["group"]) if "group" in t else None
    visible_when = _parse_visible_when(name, t.get("visible_when", []))

    return ParamSpec(
        name=name,
        type=ptype,
        default=default,
        label=str(t.get("label", "")),
        description=str(t.get("description", "")),
        unit=(str(t["unit"]) if "unit" in t else None),
        min=minimum,
        max=maximum,
        choices=choices,
        sweepable=sweepable,
        group=group,
        visible_when=visible_when,
    )


def _parse_visible_when(
    name: str, raw: Any, section: str = "params"
) -> tuple[VisibilityClause, ...]:
    if not isinstance(raw, list):
        raise ManifestError(
            f"{section}.{name}.visible_when must be an array of tables "
            f"([[{section}.{name}.visible_when]])"
        )
    clauses: list[VisibilityClause] = []
    for i, item in enumerate(raw):
        path = f"{section}.{name}.visible_when[{i}]"
        t = _as_table(item, path)
        controlling = _require_str(t, f"{path}.param")
        if "in" in t and "equals" in t:
            raise ManifestError(f"{path}: give either 'in' or 'equals', not both")
        if "in" in t:
            values = t["in"]
            if not isinstance(values, list) or not values:
                raise ManifestError(f"{path}.in must be a non-empty array")
            clauses.append(VisibilityClause(param=controlling, values=tuple(values)))
        elif "equals" in t:
            clauses.append(VisibilityClause(param=controlling, values=(t["equals"],)))
        else:
            raise ManifestError(f"{path}: a clause needs 'in' or 'equals'")
    return tuple(clauses)


def _parse_output(name: str, t: dict[str, Any]) -> OutputSpec:
    kind = _require_enum(t, f"outputs.{name}.kind", OutputKind)
    return OutputSpec(
        name=name,
        kind=kind,
        label=str(t.get("label", "")),
        description=str(t.get("description", "")),
        format=(str(t["format"]) if "format" in t else None),
        optional=bool(t.get("optional", False)),
    )


def _parse_runtime(name: str, t: dict[str, Any]) -> RuntimeSpec:
    kind = _require_enum(t, f"runtime.{name}.kind", RuntimeKind)
    return RuntimeSpec(
        name=name,
        kind=kind,
        description=str(t.get("description", "")),
        required=bool(t.get("required", True)),
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
