"""Tests for the model manifest contract."""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

import pytest

from almo_sweep.contracts import (
    InputKind,
    ManifestError,
    ModelManifest,
    OutputKind,
    ParamType,
    load_manifest,
    parse_manifest,
)


@pytest.fixture
def valid_data() -> dict[str, Any]:
    """A minimal-but-complete manifest mapping, mutated by the invalid-case tests."""
    return {
        "model": {"name": "dampm", "version": "0.1.0", "schema": "1.0"},
        "invocation": {"command": ["python", "-m", "dampm.run"]},
        "inputs": {"dem": {"kind": "raster", "band": 1}},
        "params": {
            "friction_angle": {
                "type": "float",
                "default": 30.0,
                "min": 0.0,
                "max": 60.0,
                "sweepable": True,
            }
        },
        "outputs": {"max_depth": {"kind": "raster", "format": "GTiff"}},
    }


# --- happy path against the shipped fixture -------------------------------------------
def test_load_reference_manifest(dampm_manifest_path: Path) -> None:
    m = load_manifest(dampm_manifest_path)

    assert isinstance(m, ModelManifest)
    assert (m.name, m.version, m.schema) == ("dampm", "0.1.0", "1.0")
    assert m.invocation.command == ("python", "-m", "dampm.run")
    assert m.invocation.args_template == ("--runspec", "{runspec}")
    assert m.invocation.timeout_s == 3600.0

    assert m.inputs["dem"].kind is InputKind.RASTER
    assert m.inputs["dem"].band == 1
    assert m.inputs["release_zones"].geometry == "polygon"

    assert m.params["friction_angle"].type is ParamType.FLOAT
    assert m.params["friction_angle"].unit == "deg"
    assert m.params["integrator"].type is ParamType.CHOICE
    assert m.params["integrator"].choices == ("euler", "rk4")

    assert m.outputs["max_depth"].kind is OutputKind.RASTER
    assert m.outputs["max_pressure"].optional is True


def test_sweepable_params_selects_only_flagged_numeric(dampm_manifest_path: Path) -> None:
    m = load_manifest(dampm_manifest_path)
    assert set(m.sweepable_params) == {"friction_angle", "release_depth", "density"}
    assert "integrator" not in m.sweepable_params


def test_from_toml_classmethod_matches_load(dampm_manifest_path: Path) -> None:
    assert ModelManifest.from_toml(dampm_manifest_path) == load_manifest(dampm_manifest_path)


# --- structural requirements ----------------------------------------------------------
def test_missing_model_table_is_rejected(valid_data: dict[str, Any]) -> None:
    del valid_data["model"]
    with pytest.raises(ManifestError, match=r"\[model\] table is required"):
        parse_manifest(valid_data)


def test_missing_model_name_is_rejected(valid_data: dict[str, Any]) -> None:
    del valid_data["model"]["name"]
    with pytest.raises(ManifestError, match=r"model\.name"):
        parse_manifest(valid_data)


def test_empty_command_is_rejected(valid_data: dict[str, Any]) -> None:
    valid_data["invocation"]["command"] = []
    with pytest.raises(ManifestError, match="command must contain at least one"):
        parse_manifest(valid_data)


def test_incompatible_schema_major_is_rejected(valid_data: dict[str, Any]) -> None:
    valid_data["model"]["schema"] = "2.0"
    with pytest.raises(ManifestError, match="incompatible"):
        parse_manifest(valid_data)


# --- parameter validation -------------------------------------------------------------
def test_default_outside_bounds_is_rejected(valid_data: dict[str, Any]) -> None:
    valid_data["params"]["friction_angle"]["default"] = 90.0
    with pytest.raises(ManifestError, match="above max"):
        parse_manifest(valid_data)


def test_min_greater_than_max_is_rejected(valid_data: dict[str, Any]) -> None:
    valid_data["params"]["friction_angle"]["min"] = 70.0
    valid_data["params"]["friction_angle"]["default"] = 65.0
    with pytest.raises(ManifestError, match="greater than max"):
        parse_manifest(valid_data)


def test_unknown_param_type_is_rejected(valid_data: dict[str, Any]) -> None:
    valid_data["params"]["friction_angle"]["type"] = "complex"
    with pytest.raises(ManifestError, match=r"params\.friction_angle\.type"):
        parse_manifest(valid_data)


def test_choice_without_choices_is_rejected(valid_data: dict[str, Any]) -> None:
    valid_data["params"]["scheme"] = {"type": "choice", "default": "a"}
    with pytest.raises(ManifestError, match="choices is required"):
        parse_manifest(valid_data)


def test_choice_default_not_in_choices_is_rejected(valid_data: dict[str, Any]) -> None:
    valid_data["params"]["scheme"] = {
        "type": "choice",
        "default": "z",
        "choices": ["a", "b"],
    }
    with pytest.raises(ManifestError, match="must be one of"):
        parse_manifest(valid_data)


def test_choice_cannot_be_swept(valid_data: dict[str, Any]) -> None:
    valid_data["params"]["scheme"] = {
        "type": "choice",
        "default": "a",
        "choices": ["a", "b"],
        "sweepable": True,
    }
    with pytest.raises(ManifestError, match="cannot be swept"):
        parse_manifest(valid_data)


def test_bool_default_must_be_boolean(valid_data: dict[str, Any]) -> None:
    valid_data["params"]["verbose"] = {"type": "bool", "default": "yes"}
    with pytest.raises(ManifestError, match="must be a boolean"):
        parse_manifest(valid_data)


def test_numeric_default_rejects_bool(valid_data: dict[str, Any]) -> None:
    # In Python, ``True`` is an int; the contract must not silently accept it as a number.
    valid_data["params"]["friction_angle"]["default"] = True
    with pytest.raises(ManifestError, match="must be a number"):
        parse_manifest(valid_data)


# --- input / invocation edge cases ----------------------------------------------------
def test_bad_band_is_rejected(valid_data: dict[str, Any]) -> None:
    valid_data["inputs"]["dem"]["band"] = 0
    with pytest.raises(ManifestError, match="band must be a positive integer"):
        parse_manifest(valid_data)


def test_bad_timeout_is_rejected(valid_data: dict[str, Any]) -> None:
    valid_data["invocation"]["timeout_s"] = -1
    with pytest.raises(ManifestError, match="timeout_s must be a positive"):
        parse_manifest(valid_data)


def test_invalid_toml_file_is_rejected(tmp_path: Path) -> None:
    bad = tmp_path / "broken.toml"
    bad.write_text("this is = = not toml", encoding="utf-8")
    with pytest.raises(ManifestError, match="not valid TOML"):
        load_manifest(bad)


def test_defaults_do_not_leak_between_instances(valid_data: dict[str, Any]) -> None:
    a = parse_manifest(copy.deepcopy(valid_data))
    b = parse_manifest(copy.deepcopy(valid_data))
    assert a.params is not b.params
