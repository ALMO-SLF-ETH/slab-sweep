"""Tests for the project run index."""

from __future__ import annotations

import json
from pathlib import Path

from almo_sweep.run.run_index import RUN_INDEX_SCHEMA_VERSION, RunIndex, run_entry


def test_add_appends_and_rewrites(tmp_path: Path) -> None:
    idx = RunIndex(path=tmp_path / "runs.json", manifest={"name": "m"}, study={"scheme": "grid"})
    idx.add(run_entry(run_id="a", status="success", output_dir="a", params={"x": 1}, weight=0.5))
    idx.add(run_entry(run_id="b", status="failed", output_dir="b", params={"x": 2}, error="boom"))

    doc = json.loads((tmp_path / "runs.json").read_text(encoding="utf-8"))
    assert doc["schema"] == RUN_INDEX_SCHEMA_VERSION
    assert doc["manifest"]["name"] == "m"
    assert doc["study"]["scheme"] == "grid"
    assert [r["run_id"] for r in doc["runs"]] == ["a", "b"]
    assert doc["runs"][0]["weight"] == 0.5
    assert doc["runs"][1]["error"] == "boom"


def test_run_entry_defaults() -> None:
    e = run_entry(run_id="a", status="success", output_dir="a", params={})
    assert e["weight"] == 1.0
    assert e["attempts"] == 1
    assert e["seed"] is None
    assert "recorded" in e


def test_write_creates_parent_dirs(tmp_path: Path) -> None:
    idx = RunIndex(path=tmp_path / "nested" / "deep" / "runs.json")
    idx.write()
    assert (tmp_path / "nested" / "deep" / "runs.json").exists()
