"""The run-spec contract: one fully-resolved job handed to a model process.

A **run spec** is the complete, concrete description of a *single* simulation run. The
engine writes it as ``runspec.json`` into the run directory and passes its path to the
spawned model (via the ``{runspec}`` placeholder in the manifest's invocation). It is the
model's sole input: everything the model needs to execute exactly one run and nothing about
the wider study.

It carries:

* **identity**   -- a unique ``run_id`` and the model name/version it was resolved for, so a
  model can refuse a spec meant for a different model.
* **params**     -- the concrete scalar values for this run (one row from
  :meth:`~almo_sweep.contracts.sweep.SweepConfig.samples`).
* **inputs**     -- each logical input name mapped to an absolute path on disk.
* **outputs**    -- the directory to write into and which named outputs to keep.
* **seed**       -- an optional per-run seed for a stochastic model.

On :meth:`RunSpec.write` each input file is also hashed and the digests are recorded in the
written ``runspec.json`` under ``input_digests`` (content SHA-256 + byte size, per input). This
pins each run to the *content* of the files it used, not just their paths, so a later audit can
confirm a re-run used the identical DEM / release layer even if the file was edited or moved.
Study-level provenance (manifest hashes, tool versions) remains the collector's concern and
lives in the run index.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from almo_sweep.contracts.errors import ContractError

#: Version of the run-spec *format*. Bumped when the on-disk JSON shape changes.
RUNSPEC_SCHEMA_VERSION = "1.0"

#: Read size for streaming file hashes (1 MiB) -- keeps large DEMs off the heap.
_HASH_CHUNK = 1 << 20


class RunSpecError(ContractError):
    """A run spec is missing required data, is malformed, or has an incompatible schema."""


@dataclass(frozen=True)
class RunSpec:
    """A single resolved run. Serialises to/from ``runspec.json``."""

    run_id: str
    model_name: str
    params: dict[str, Any]
    inputs: dict[str, str]
    output_dir: str
    store_outputs: tuple[str, ...] = ()
    model_version: str | None = None
    seed: int | None = None
    #: Optional CRS per input name (e.g. {"dem": "EPSG:2056"}), so a model can georeference its
    #: outputs when the input file carries no CRS inline (an ESRI ASCII grid, for one). Supplied by
    #: the client that knows the data's CRS (e.g. the QGIS plugin from the layer).
    input_crs: dict[str, str] = field(default_factory=dict)
    schema: str = RUNSPEC_SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "run_id": self.run_id,
            "model": {"name": self.model_name, "version": self.model_version},
            "params": dict(self.params),
            "inputs": dict(self.inputs),
            "input_crs": dict(self.input_crs),
            "outputs": {"dir": self.output_dir, "store": list(self.store_outputs)},
            "seed": self.seed,
        }

    def write(self, path: str | Path) -> Path:
        """Write the run spec as pretty JSON and return the path written.

        Each input file is hashed (content SHA-256 + byte size) and the digests are added to the
        written JSON under ``input_digests`` for file-identity provenance. Hashing a single input
        never fails the write: an unreadable/missing file is recorded with an ``error`` field
        instead (the model reports the real failure when it tries to use it).
        """
        p = Path(path)
        data = self.to_dict()
        data["input_digests"] = self._input_digests()
        p.write_text(json.dumps(data, indent=2), encoding="utf-8")
        return p

    def _input_digests(self) -> dict[str, dict[str, Any]]:
        """Path, filename and content digest of each input file, keyed by input name.

        Each entry records the input's file ``path`` and ``filename`` alongside its SHA-256 + byte
        size, so provenance identifies *which* file was used, not only its content hash (see
        :meth:`write`)."""
        return {name: _file_digest(path) for name, path in self.inputs.items()}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RunSpec:
        schema = str(data.get("schema", RUNSPEC_SCHEMA_VERSION))
        _check_schema(schema)
        model = _require(data, "model", dict)
        outputs = _require(data, "outputs", dict)
        return cls(
            run_id=_require_nonempty_str(data, "run_id"),
            model_name=_require_nonempty_str(model, "name", prefix="model."),
            model_version=(str(model["version"]) if model.get("version") is not None else None),
            params=_require(data, "params", dict),
            inputs=_require_str_map(data, "inputs"),
            input_crs=_optional_str_map(data, "input_crs"),
            output_dir=_require_nonempty_str(outputs, "dir", prefix="outputs."),
            store_outputs=tuple(_require_str_list(outputs, "store", prefix="outputs.")),
            seed=_optional_int(data, "seed"),
            schema=schema,
        )

    @classmethod
    def read(cls, path: str | Path) -> RunSpec:
        p = Path(path)
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except OSError as exc:  # pragma: no cover - trivial passthrough
            raise RunSpecError(f"cannot read run spec {p}: {exc}") from exc
        except json.JSONDecodeError as exc:
            raise RunSpecError(f"{p} is not valid JSON: {exc}") from exc
        if not isinstance(data, dict):
            raise RunSpecError(f"{p} must contain a JSON object")
        return cls.from_dict(data)


# ---------------------------------------------------------------------------
# Input provenance
# ---------------------------------------------------------------------------
def _file_digest(path: str) -> dict[str, Any]:
    """File path/name plus content SHA-256 (hex) and byte size of ``path``.

    ``path`` is recorded as given and ``filename`` is its basename, so a run folder names the exact
    input files it used. An unreadable/missing file keeps its path/filename and carries an
    ``error`` entry in place of the hash."""
    p = Path(path)
    info: dict[str, Any] = {"path": str(p), "filename": p.name}
    try:
        h = hashlib.sha256()
        size = 0
        with p.open("rb") as f:
            for chunk in iter(lambda: f.read(_HASH_CHUNK), b""):
                h.update(chunk)
                size += len(chunk)
        info["sha256"] = h.hexdigest()
        info["bytes"] = size
    except OSError as exc:
        info["error"] = str(exc)
    return info


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------
def _check_schema(schema: str) -> None:
    if schema.split(".")[0] != RUNSPEC_SCHEMA_VERSION.split(".")[0]:
        raise RunSpecError(
            f"run-spec schema {schema!r} is incompatible with {RUNSPEC_SCHEMA_VERSION!r}"
        )


def _require(data: dict[str, Any], key: str, typ: type, *, prefix: str = "") -> Any:
    if key not in data:
        raise RunSpecError(f"{prefix}{key} is required")
    value = data[key]
    if not isinstance(value, typ):
        raise RunSpecError(f"{prefix}{key} must be a {typ.__name__}")
    return value


def _require_nonempty_str(data: dict[str, Any], key: str, *, prefix: str = "") -> str:
    value: str = _require(data, key, str, prefix=prefix)
    if not value.strip():
        raise RunSpecError(f"{prefix}{key} must be a non-empty string")
    return value


def _require_str_map(data: dict[str, Any], key: str, *, prefix: str = "") -> dict[str, str]:
    value = _require(data, key, dict, prefix=prefix)
    if not all(isinstance(k, str) and isinstance(v, str) for k, v in value.items()):
        raise RunSpecError(f"{prefix}{key} must map strings to strings")
    return dict(value)


def _optional_str_map(data: dict[str, Any], key: str) -> dict[str, str]:
    if key not in data or data[key] is None:
        return {}
    return _require_str_map(data, key)


def _require_str_list(data: dict[str, Any], key: str, *, prefix: str = "") -> list[str]:
    if key not in data:
        return []
    value = data[key]
    if not isinstance(value, list) or not all(isinstance(x, str) for x in value):
        raise RunSpecError(f"{prefix}{key} must be a list of strings")
    return list(value)


def _optional_int(data: dict[str, Any], key: str) -> int | None:
    if data.get(key) is None:
        return None
    value = data[key]
    if not isinstance(value, int) or isinstance(value, bool):
        raise RunSpecError(f"{key} must be an integer")
    return value
