"""Tests for the run-spec contract."""

from __future__ import annotations

from pathlib import Path

import pytest

from slab_sweep.contracts import RunSpec, RunSpecError


def _spec() -> RunSpec:
    return RunSpec(
        run_id="run-0001",
        model_name="slab-pro",
        model_version="0.1.0",
        params={"friction_angle": 30.0, "integrator": "rk4"},
        inputs={"dem": "/data/dem.tif", "release_zones": "/data/release.shp"},
        output_dir="/runs/run-0001",
        store_outputs=("max_depth", "summary"),
        seed=7,
    )


def test_roundtrip_through_dict() -> None:
    spec = _spec()
    assert RunSpec.from_dict(spec.to_dict()) == spec


def test_roundtrip_through_file(tmp_path: Path) -> None:
    spec = _spec()
    path = spec.write(tmp_path / "runspec.json")
    assert path.exists()
    assert RunSpec.read(path) == spec


def test_input_digests_record_path_filename_and_hash(tmp_path: Path) -> None:
    good = tmp_path / "dem.tif"
    good.write_bytes(b"abc")
    missing = tmp_path / "gone.shp"  # never created
    spec = RunSpec(
        run_id="run-0001",
        model_name="slab-pro",
        params={},
        inputs={"dem": str(good), "release_zones": str(missing)},
        output_dir=str(tmp_path / "out"),
        store_outputs=(),
    )
    import json

    data = json.loads(spec.write(tmp_path / "runspec.json").read_text(encoding="utf-8"))
    digests = data["input_digests"]
    # A readable input: path, filename and content hash + size.
    assert digests["dem"]["path"] == str(good)
    assert digests["dem"]["filename"] == "dem.tif"
    assert digests["dem"]["bytes"] == 3 and "sha256" in digests["dem"]
    # A missing input still records which file it was, with an error instead of a hash.
    assert digests["release_zones"]["filename"] == "gone.shp"
    assert "error" in digests["release_zones"] and "sha256" not in digests["release_zones"]


def test_to_dict_shape_is_nested() -> None:
    d = _spec().to_dict()
    assert d["model"] == {"name": "slab-pro", "version": "0.1.0"}
    assert d["outputs"] == {"dir": "/runs/run-0001", "store": ["max_depth", "summary"]}
    assert d["schema"] == "1.0"


def test_defaults_are_permissible() -> None:
    spec = RunSpec(
        run_id="r1",
        model_name="m",
        params={},
        inputs={},
        output_dir="/out",
    )
    assert RunSpec.from_dict(spec.to_dict()) == spec
    assert spec.store_outputs == ()
    assert spec.seed is None
    assert spec.model_version is None


# --- validation -----------------------------------------------------------------------
def test_missing_run_id_is_rejected() -> None:
    data = _spec().to_dict()
    del data["run_id"]
    with pytest.raises(RunSpecError, match="run_id is required"):
        RunSpec.from_dict(data)


def test_empty_run_id_is_rejected() -> None:
    data = _spec().to_dict()
    data["run_id"] = "  "
    with pytest.raises(RunSpecError, match="non-empty"):
        RunSpec.from_dict(data)


def test_missing_model_name_is_rejected() -> None:
    data = _spec().to_dict()
    del data["model"]["name"]
    with pytest.raises(RunSpecError, match=r"model\.name is required"):
        RunSpec.from_dict(data)


def test_inputs_must_be_string_paths() -> None:
    data = _spec().to_dict()
    data["inputs"]["dem"] = 123
    with pytest.raises(RunSpecError, match="inputs must map strings to strings"):
        RunSpec.from_dict(data)


def test_incompatible_schema_is_rejected() -> None:
    data = _spec().to_dict()
    data["schema"] = "2.0"
    with pytest.raises(RunSpecError, match="incompatible"):
        RunSpec.from_dict(data)


def test_bad_seed_is_rejected() -> None:
    data = _spec().to_dict()
    data["seed"] = "later"
    with pytest.raises(RunSpecError, match="seed must be an integer"):
        RunSpec.from_dict(data)


def test_read_rejects_non_object_json(tmp_path: Path) -> None:
    p = tmp_path / "bad.json"
    p.write_text("[1, 2, 3]", encoding="utf-8")
    with pytest.raises(RunSpecError, match="must contain a JSON object"):
        RunSpec.read(p)


def test_read_rejects_invalid_json(tmp_path: Path) -> None:
    p = tmp_path / "bad.json"
    p.write_text("{not json", encoding="utf-8")
    with pytest.raises(RunSpecError, match="not valid JSON"):
        RunSpec.read(p)
