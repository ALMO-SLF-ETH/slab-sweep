"""Tests for run-spec resolution."""

from __future__ import annotations

from pathlib import Path

import pytest

from slab_sweep.contracts import ModelManifest, load_manifest
from slab_sweep.run import RunError, resolve_runspec


@pytest.fixture
def manifest(slab_pro_manifest_path: Path) -> ModelManifest:
    return load_manifest(slab_pro_manifest_path)


def _inputs() -> dict[str, str]:
    return {"dem": "/data/dem.tif", "release_zones": "/data/release.shp"}


def test_resolve_fills_param_defaults(manifest: ModelManifest) -> None:
    spec = resolve_runspec(
        manifest,
        run_id="r1",
        inputs=_inputs(),
        params={"friction_angle": 25.0},  # partial: the rest come from manifest defaults
        output_dir="/runs/r1",
    )
    assert spec.params["friction_angle"] == 25.0
    assert spec.params["density"] == 2000.0
    assert spec.params["integrator"] == "rk4"
    assert spec.model_name == "slab-pro"
    assert spec.output_dir == "/runs/r1"


def test_default_store_is_non_optional_outputs(manifest: ModelManifest) -> None:
    spec = resolve_runspec(manifest, run_id="r1", inputs=_inputs(), params={}, output_dir="/o")
    # max_depth is required-to-store; max_pressure and summary are optional.
    assert spec.store_outputs == ("max_depth",)


def test_explicit_store_outputs(manifest: ModelManifest) -> None:
    spec = resolve_runspec(
        manifest,
        run_id="r1",
        inputs=_inputs(),
        params={},
        output_dir="/o",
        store_outputs=["max_depth", "max_pressure"],
    )
    assert spec.store_outputs == ("max_depth", "max_pressure")


def test_optional_input_may_be_omitted(manifest: ModelManifest) -> None:
    # release_zones is required in the Slab-Pro manifest, dem is required too; provide both but
    # drop a hypothetical optional via a None value to prove None-paths are dropped.
    spec = resolve_runspec(
        manifest,
        run_id="r1",
        inputs={"dem": "/d.tif", "release_zones": "/r.shp"},
        params={},
        output_dir="/o",
    )
    assert set(spec.inputs) == {"dem", "release_zones"}


# --- validation -----------------------------------------------------------------------
def test_missing_required_input_is_rejected(manifest: ModelManifest) -> None:
    with pytest.raises(RunError, match="missing required input"):
        resolve_runspec(manifest, run_id="r1", inputs={"dem": "/d.tif"}, params={}, output_dir="/o")


def test_none_path_counts_as_missing(manifest: ModelManifest) -> None:
    with pytest.raises(RunError, match="missing required input"):
        resolve_runspec(
            manifest,
            run_id="r1",
            inputs={"dem": "/d.tif", "release_zones": None},
            params={},
            output_dir="/o",
        )


def test_unknown_input_is_rejected(manifest: ModelManifest) -> None:
    with pytest.raises(RunError, match="unknown input"):
        resolve_runspec(
            manifest,
            run_id="r1",
            inputs={**_inputs(), "extra": "/x"},
            params={},
            output_dir="/o",
        )


def test_unknown_param_is_rejected(manifest: ModelManifest) -> None:
    with pytest.raises(RunError, match="unknown parameter"):
        resolve_runspec(
            manifest, run_id="r1", inputs=_inputs(), params={"nope": 1}, output_dir="/o"
        )


def test_unknown_output_is_rejected(manifest: ModelManifest) -> None:
    with pytest.raises(RunError, match="unknown output"):
        resolve_runspec(
            manifest,
            run_id="r1",
            inputs=_inputs(),
            params={},
            output_dir="/o",
            store_outputs=["nope"],
        )
