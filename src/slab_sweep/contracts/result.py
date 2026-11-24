"""The result contract: what a model writes back after a run.

When a model finishes a run it writes ``result.json`` into the run directory. The engine's
collector reads it to learn whether the run succeeded, where the produced artefacts are, and
any scalar metrics worth indexing. This is the counterpart to the run spec: run spec in,
result out.

A model should write a result even on failure (status ``failed`` with an ``error``), so the
collector can record the failure rather than having to infer it from an exit code alone.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any

from slab_sweep.contracts.errors import ContractError

#: Version of the result *format*.
RESULT_SCHEMA_VERSION = "1.0"


class ResultError(ContractError):
    """A result document is missing required data, is malformed, or has an incompatible schema."""


class RunStatus(StrEnum):
    """Terminal state of a run."""

    SUCCESS = "success"
    FAILED = "failed"


@dataclass(frozen=True)
class RunResult:
    """The outcome of a single run. Serialises to/from ``result.json``."""

    run_id: str
    status: RunStatus
    outputs: dict[str, str] = field(default_factory=dict)
    metrics: dict[str, float] = field(default_factory=dict)
    message: str = ""
    error: str | None = None
    duration_s: float | None = None
    schema: str = RESULT_SCHEMA_VERSION

    @property
    def ok(self) -> bool:
        return self.status is RunStatus.SUCCESS

    # -- convenience constructors ------------------------------------------------------
    @classmethod
    def success(
        cls,
        run_id: str,
        outputs: dict[str, str],
        *,
        metrics: dict[str, float] | None = None,
        message: str = "",
        duration_s: float | None = None,
    ) -> RunResult:
        return cls(
            run_id=run_id,
            status=RunStatus.SUCCESS,
            outputs=dict(outputs),
            metrics=dict(metrics or {}),
            message=message,
            duration_s=duration_s,
        )

    @classmethod
    def failure(
        cls,
        run_id: str,
        error: str,
        *,
        message: str = "",
        duration_s: float | None = None,
    ) -> RunResult:
        return cls(
            run_id=run_id,
            status=RunStatus.FAILED,
            error=error,
            message=message,
            duration_s=duration_s,
        )

    # -- serialisation -----------------------------------------------------------------
    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "run_id": self.run_id,
            "status": str(self.status),
            "outputs": dict(self.outputs),
            "metrics": dict(self.metrics),
            "message": self.message,
            "error": self.error,
            "duration_s": self.duration_s,
        }

    def write(self, path: str | Path) -> Path:
        p = Path(path)
        p.write_text(json.dumps(self.to_dict(), indent=2), encoding="utf-8")
        return p

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RunResult:
        schema = str(data.get("schema", RESULT_SCHEMA_VERSION))
        if schema.split(".")[0] != RESULT_SCHEMA_VERSION.split(".")[0]:
            raise ResultError(
                f"result schema {schema!r} is incompatible with {RESULT_SCHEMA_VERSION!r}"
            )
        if (
            "run_id" not in data
            or not isinstance(data["run_id"], str)
            or not data["run_id"].strip()
        ):
            raise ResultError("run_id is required and must be a non-empty string")
        try:
            status = RunStatus(data["status"])
        except (KeyError, ValueError):
            raise ResultError(
                f"status is required and must be one of {[s.value for s in RunStatus]}"
            ) from None
        return cls(
            run_id=data["run_id"],
            status=status,
            outputs=_str_map(data.get("outputs", {}), "outputs"),
            metrics=_number_map(data.get("metrics", {}), "metrics"),
            message=str(data.get("message", "")),
            error=(str(data["error"]) if data.get("error") is not None else None),
            duration_s=_optional_number(data.get("duration_s"), "duration_s"),
            schema=schema,
        )

    @classmethod
    def read(cls, path: str | Path) -> RunResult:
        p = Path(path)
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except OSError as exc:  # pragma: no cover - trivial passthrough
            raise ResultError(f"cannot read result {p}: {exc}") from exc
        except json.JSONDecodeError as exc:
            raise ResultError(f"{p} is not valid JSON: {exc}") from exc
        if not isinstance(data, dict):
            raise ResultError(f"{p} must contain a JSON object")
        return cls.from_dict(data)


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------
def _str_map(value: Any, path: str) -> dict[str, str]:
    if not isinstance(value, dict) or not all(
        isinstance(k, str) and isinstance(v, str) for k, v in value.items()
    ):
        raise ResultError(f"{path} must map strings to strings")
    return dict(value)


def _number_map(value: Any, path: str) -> dict[str, float]:
    if not isinstance(value, dict):
        raise ResultError(f"{path} must be a table of numbers")
    out: dict[str, float] = {}
    for k, v in value.items():
        if not isinstance(k, str) or isinstance(v, bool) or not isinstance(v, (int, float)):
            raise ResultError(f"{path}.{k} must be a number")
        out[k] = float(v)
    return out


def _optional_number(value: Any, path: str) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ResultError(f"{path} must be a number")
    return float(value)
