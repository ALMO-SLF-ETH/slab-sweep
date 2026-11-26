"""Tests for the project run index."""

from __future__ import annotations

import json
from pathlib import Path

from slab_sweep.run.run_index import RUN_INDEX_SCHEMA_VERSION, RunIndex, run_entry


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


def test_run_entry_carries_counter() -> None:
    e = run_entry(run_id="a", status="success", output_dir="a", params={}, counter=7)
    assert e["counter"] == 7
    # Omitted by default (e.g. a sweep's entries), so next_counter ignores it.
    assert run_entry(run_id="b", status="success", output_dir="b", params={})["counter"] is None


def test_load_or_create_appends_to_existing_index(tmp_path: Path) -> None:
    path = tmp_path / "runs.json"
    first = RunIndex.load_or_create(path, manifest={"name": "m"}, study={"scheme": "manual"})
    first.add(run_entry(run_id="p_000001", status="success", output_dir="d1", params={}, counter=1))

    # A separate launch reopens the same file and appends, rather than overwriting it.
    again = RunIndex.load_or_create(path)
    again.add(run_entry(run_id="p_000002", status="failed", output_dir="d2", params={}, counter=2))

    doc = json.loads(path.read_text(encoding="utf-8"))
    assert [r["run_id"] for r in doc["runs"]] == ["p_000001", "p_000002"]
    assert doc["manifest"]["name"] == "m"  # preserved from the first write
    assert doc["study"]["scheme"] == "manual"
    assert again.created == first.created  # original creation time kept


def test_load_or_create_missing_file_is_empty(tmp_path: Path) -> None:
    idx = RunIndex.load_or_create(tmp_path / "absent.json", manifest={"name": "m"})
    assert idx.next_counter() == 1
    assert idx.manifest == {"name": "m"}


def test_next_counter_is_one_past_the_largest(tmp_path: Path) -> None:
    idx = RunIndex.load_or_create(tmp_path / "runs.json")
    assert idx.next_counter() == 1
    idx.add(run_entry(run_id="a", status="success", output_dir="a", params={}, counter=3))
    idx.add(run_entry(run_id="b", status="success", output_dir="b", params={}, counter=5))
    # Entries without a counter (a sweep's) do not affect it.
    idx.add(run_entry(run_id="c", status="success", output_dir="c", params={}))
    assert idx.next_counter() == 6


def test_load_or_create_survives_a_corrupt_file(tmp_path: Path) -> None:
    path = tmp_path / "runs.json"
    path.write_text("{not json", encoding="utf-8")
    idx = RunIndex.load_or_create(path, manifest={"name": "m"})
    assert idx.next_counter() == 1  # treated as a fresh index
