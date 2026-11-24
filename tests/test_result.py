"""Tests for the result contract."""

from __future__ import annotations

from pathlib import Path

import pytest

from slab_sweep.contracts import ResultError, RunResult, RunStatus


def test_success_constructor() -> None:
    r = RunResult.success(
        "run-1",
        {"max_depth": "/runs/run-1/max_depth.tif"},
        metrics={"max_depth_m": 3.2},
        message="done",
        duration_s=12.5,
    )
    assert r.ok
    assert r.status is RunStatus.SUCCESS
    assert r.outputs["max_depth"].endswith("max_depth.tif")
    assert r.metrics == {"max_depth_m": 3.2}
    assert r.error is None


def test_failure_constructor() -> None:
    r = RunResult.failure("run-2", "boom", message="model crashed")
    assert not r.ok
    assert r.status is RunStatus.FAILED
    assert r.error == "boom"
    assert r.outputs == {}


def test_roundtrip_through_dict() -> None:
    r = RunResult.success("run-1", {"a": "/p/a.tif"}, metrics={"m": 1.0})
    assert RunResult.from_dict(r.to_dict()) == r


def test_roundtrip_through_file(tmp_path: Path) -> None:
    r = RunResult.failure("run-3", "traceback...", duration_s=0.1)
    path = r.write(tmp_path / "result.json")
    assert RunResult.read(path) == r


def test_metrics_ints_become_floats() -> None:
    r = RunResult.from_dict({"run_id": "r", "status": "success", "metrics": {"count": 5}})
    assert r.metrics["count"] == 5.0
    assert isinstance(r.metrics["count"], float)


# --- validation -----------------------------------------------------------------------
def test_missing_status_is_rejected() -> None:
    with pytest.raises(ResultError, match="status is required"):
        RunResult.from_dict({"run_id": "r"})


def test_unknown_status_is_rejected() -> None:
    with pytest.raises(ResultError, match="status is required"):
        RunResult.from_dict({"run_id": "r", "status": "halfway"})


def test_missing_run_id_is_rejected() -> None:
    with pytest.raises(ResultError, match="run_id is required"):
        RunResult.from_dict({"status": "success"})


def test_non_numeric_metric_is_rejected() -> None:
    with pytest.raises(ResultError, match=r"metrics\.bad must be a number"):
        RunResult.from_dict({"run_id": "r", "status": "success", "metrics": {"bad": "x"}})


def test_bool_metric_is_rejected() -> None:
    # bools are ints in Python; the contract must not silently accept them as numbers.
    with pytest.raises(ResultError, match="must be a number"):
        RunResult.from_dict({"run_id": "r", "status": "success", "metrics": {"flag": True}})


def test_incompatible_schema_is_rejected() -> None:
    with pytest.raises(ResultError, match="incompatible"):
        RunResult.from_dict({"run_id": "r", "status": "success", "schema": "9.0"})
