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

Provenance for the *study* (manifest hashes, input checksums, tool versions) is the
collector's concern and lives in the run index, not here.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from almo_sweep.contracts.errors import ContractError

#: Version of the run-spec *format*. Bumped when the on-disk JSON shape changes.
RUNSPEC_SCHEMA_VERSION = "1.0"


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
    schema: str = RUNSPEC_SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "run_id": self.run_id,
            "model": {"name": self.model_name, "version": self.model_version},
            "params": dict(self.params),
            "inputs": dict(self.inputs),
            "outputs": {"dir": self.output_dir, "store": list(self.store_outputs)},
            "seed": self.seed,
        }

    def write(self, path: str | Path) -> Path:
        """Write the run spec as pretty JSON and return the path written."""
        p = Path(path)
        p.write_text(json.dumps(self.to_dict(), indent=2), encoding="utf-8")
        return p

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
