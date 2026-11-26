"""Tests for the provenance helpers (version + git commit/dirty/date)."""

from __future__ import annotations

from pathlib import Path

from slab_sweep import provenance


def test_git_info_for_this_checkout() -> None:
    # The engine source lives in a git checkout, so git_info resolves commit/dirty/date.
    info = provenance.git_info(Path(provenance.__file__).parent)
    assert info is not None
    assert isinstance(info["commit"], str) and len(info["commit"]) >= 7
    assert isinstance(info["dirty"], bool)
    assert info["date"] is None or "T" in info["date"]  # ISO-8601 commit date


def test_git_info_none_outside_a_repo(tmp_path: Path) -> None:
    assert provenance.git_info(tmp_path) is None


def test_package_provenance_has_the_expected_fields() -> None:
    rec = provenance.package_provenance("slab-sweep", Path(provenance.__file__).parent)
    assert rec["name"] == "slab-sweep"
    assert set(rec) >= {"name", "version", "commit", "dirty", "date"}
    assert isinstance(rec["commit"], str)  # this checkout -> a real commit


def test_package_provenance_accepts_explicit_version(tmp_path: Path) -> None:
    rec = provenance.package_provenance("slab_qgis", tmp_path, version="1.4.0")
    assert rec["version"] == "1.4.0"  # e.g. a plugin's metadata.txt version
    assert rec["commit"] is None  # tmp_path is not a checkout


def test_engine_provenance_names_itself() -> None:
    assert provenance.engine_provenance()["name"] == "slab-sweep"
