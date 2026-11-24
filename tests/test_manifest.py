"""Tests for the model manifest contract."""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

import pytest

from slab_sweep.contracts import (
    InputKind,
    ManifestError,
    ModelManifest,
    OutputKind,
    ParamType,
    RuntimeKind,
    load_manifest,
    parse_manifest,
)


@pytest.fixture
def valid_data() -> dict[str, Any]:
    """A minimal-but-complete manifest mapping, mutated by the invalid-case tests."""
    return {
        "model": {"name": "slab-pro", "version": "0.1.0", "schema": "1.0"},
        "invocation": {"command": ["python", "-m", "slab_pro_interface", "run"]},
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
def test_load_reference_manifest(slab_pro_manifest_path: Path) -> None:
    m = load_manifest(slab_pro_manifest_path)

    assert isinstance(m, ModelManifest)
    assert (m.name, m.version, m.schema) == ("slab-pro", "0.1.0", "1.0")
    assert m.invocation.command == ("python", "-m", "slab_pro_interface", "run")
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


def test_sweepable_params_selects_only_flagged_numeric(slab_pro_manifest_path: Path) -> None:
    m = load_manifest(slab_pro_manifest_path)
    assert set(m.sweepable_params) == {"friction_angle", "release_depth", "density"}
    assert "integrator" not in m.sweepable_params


def test_from_toml_classmethod_matches_load(slab_pro_manifest_path: Path) -> None:
    assert ModelManifest.from_toml(slab_pro_manifest_path) == load_manifest(slab_pro_manifest_path)


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


# --- runtime settings -----------------------------------------------------------------
def test_runtime_settings_are_parsed(valid_data: dict[str, Any]) -> None:
    valid_data["runtime"] = {
        "SLAB_PRO_BIN": {"kind": "file", "description": "the binary", "required": True},
        "SLAB_PRO_DLL_DIR": {"kind": "directory", "required": False},
    }
    m = parse_manifest(valid_data)
    assert set(m.runtime) == {"SLAB_PRO_BIN", "SLAB_PRO_DLL_DIR"}
    assert m.runtime["SLAB_PRO_BIN"].kind is RuntimeKind.FILE
    assert m.runtime["SLAB_PRO_BIN"].required is True
    assert m.runtime["SLAB_PRO_DLL_DIR"].kind is RuntimeKind.DIRECTORY
    assert m.runtime["SLAB_PRO_DLL_DIR"].required is False


def test_runtime_absent_is_empty(slab_pro_manifest_path: Path) -> None:
    assert load_manifest(slab_pro_manifest_path).runtime == {}


def test_bad_runtime_kind_is_rejected(valid_data: dict[str, Any]) -> None:
    valid_data["runtime"] = {"X": {"kind": "port"}}
    with pytest.raises(ManifestError, match=r"runtime\.X\.kind"):
        parse_manifest(valid_data)


# --- labels ---------------------------------------------------------------------------
def test_label_falls_back_to_name_when_absent(valid_data: dict[str, Any]) -> None:
    m = parse_manifest(valid_data)
    assert m.params["friction_angle"].label == ""
    assert m.params["friction_angle"].display_label == "friction_angle"


def test_label_is_parsed_on_params_inputs_and_outputs(valid_data: dict[str, Any]) -> None:
    valid_data["params"]["friction_angle"]["label"] = "Friction angle"
    valid_data["inputs"]["dem"]["label"] = "Terrain (DEM)"
    valid_data["outputs"]["max_depth"]["label"] = "Max flow depth"
    m = parse_manifest(valid_data)
    assert m.params["friction_angle"].display_label == "Friction angle"
    assert m.inputs["dem"].display_label == "Terrain (DEM)"
    assert m.outputs["max_depth"].display_label == "Max flow depth"


# --- groups ---------------------------------------------------------------------------
def test_groups_are_parsed_in_order(valid_data: dict[str, Any]) -> None:
    valid_data["groups"] = [
        {"id": "physical", "label": "Physical", "description": "material"},
        {"id": "time"},
    ]
    valid_data["params"]["friction_angle"]["group"] = "physical"
    m = parse_manifest(valid_data)
    assert [g.id for g in m.groups] == ["physical", "time"]
    assert m.groups[0].display_label == "Physical"
    assert m.groups[1].display_label == "time"  # falls back to id
    assert m.params["friction_angle"].group == "physical"


def test_grouped_params_buckets_by_declared_group(valid_data: dict[str, Any]) -> None:
    valid_data["groups"] = [{"id": "physical"}, {"id": "time"}]
    valid_data["params"]["friction_angle"]["group"] = "physical"
    valid_data["params"]["step"] = {"type": "float", "default": 1.0, "group": "time"}
    valid_data["params"]["loose"] = {"type": "float", "default": 2.0}  # ungrouped
    m = parse_manifest(valid_data)
    grouped = m.grouped_params()
    by_id = {g.id: [p.name for p in specs] for g, specs in grouped}
    assert by_id == {"physical": ["friction_angle"], "time": ["step"], "": ["loose"]}
    # every declared group appears; the trailing "" bucket holds the ungrouped param
    assert [g.id for g, _ in grouped] == ["physical", "time", ""]


def test_grouped_params_without_groups_is_single_bucket(valid_data: dict[str, Any]) -> None:
    grouped = parse_manifest(valid_data).grouped_params()
    assert len(grouped) == 1
    group, specs = grouped[0]
    assert group.id == ""
    assert [p.name for p in specs] == ["friction_angle"]


def test_unknown_group_reference_is_rejected(valid_data: dict[str, Any]) -> None:
    valid_data["params"]["friction_angle"]["group"] = "ghost"
    with pytest.raises(ManifestError, match="is not a declared group"):
        parse_manifest(valid_data)


def test_duplicate_group_id_is_rejected(valid_data: dict[str, Any]) -> None:
    valid_data["groups"] = [{"id": "a"}, {"id": "a"}]
    with pytest.raises(ManifestError, match="duplicate group id"):
        parse_manifest(valid_data)


# --- conditional visibility -----------------------------------------------------------
def test_visible_when_in_clause_gates_display(valid_data: dict[str, Any]) -> None:
    valid_data["params"]["law"] = {"type": "choice", "default": "a", "choices": ["a", "b"]}
    valid_data["params"]["friction_angle"]["visible_when"] = [{"param": "law", "in": ["b"]}]
    m = parse_manifest(valid_data)
    spec = m.params["friction_angle"]
    assert spec.is_visible({"law": "b"}) is True
    assert spec.is_visible({"law": "a"}) is False
    # no values for the controlling param -> not visible
    assert spec.is_visible({}) is False


def test_visible_when_equals_is_sugar_for_single_value(valid_data: dict[str, Any]) -> None:
    valid_data["params"]["law"] = {"type": "choice", "default": "a", "choices": ["a", "b"]}
    valid_data["params"]["friction_angle"]["visible_when"] = [{"param": "law", "equals": "a"}]
    spec = parse_manifest(valid_data).params["friction_angle"]
    assert spec.visible_when[0].values == ("a",)
    assert spec.is_visible({"law": "a"}) is True


def test_visible_when_clauses_are_anded(valid_data: dict[str, Any]) -> None:
    valid_data["params"]["law"] = {"type": "choice", "default": "a", "choices": ["a", "b"]}
    valid_data["params"]["mode"] = {"type": "choice", "default": "x", "choices": ["x", "y"]}
    valid_data["params"]["friction_angle"]["visible_when"] = [
        {"param": "law", "in": ["b"]},
        {"param": "mode", "in": ["y"]},
    ]
    spec = parse_manifest(valid_data).params["friction_angle"]
    assert spec.is_visible({"law": "b", "mode": "y"}) is True
    assert spec.is_visible({"law": "b", "mode": "x"}) is False


def test_visible_when_unknown_param_is_rejected(valid_data: dict[str, Any]) -> None:
    valid_data["params"]["friction_angle"]["visible_when"] = [{"param": "ghost", "in": ["b"]}]
    with pytest.raises(ManifestError, match="references unknown param"):
        parse_manifest(valid_data)


def test_visible_when_self_reference_is_rejected(valid_data: dict[str, Any]) -> None:
    valid_data["params"]["friction_angle"]["visible_when"] = [
        {"param": "friction_angle", "in": [1]}
    ]
    with pytest.raises(ManifestError, match="cannot depend on itself"):
        parse_manifest(valid_data)


def test_visible_when_requires_in_or_equals(valid_data: dict[str, Any]) -> None:
    valid_data["params"]["law"] = {"type": "choice", "default": "a", "choices": ["a", "b"]}
    valid_data["params"]["friction_angle"]["visible_when"] = [{"param": "law"}]
    with pytest.raises(ManifestError, match="needs 'in' or 'equals'"):
        parse_manifest(valid_data)


def test_visible_when_rejects_both_in_and_equals(valid_data: dict[str, Any]) -> None:
    valid_data["params"]["law"] = {"type": "choice", "default": "a", "choices": ["a", "b"]}
    valid_data["params"]["friction_angle"]["visible_when"] = [
        {"param": "law", "in": ["b"], "equals": "b"}
    ]
    with pytest.raises(ManifestError, match="not both"):
        parse_manifest(valid_data)


# --- inputs share the presentation vocabulary -----------------------------------------
def test_inputs_carry_group_and_visible_when(valid_data: dict[str, Any]) -> None:
    valid_data["groups"] = [{"id": "release"}]
    valid_data["params"]["release_type"] = {
        "type": "choice",
        "default": "POLYGON",
        "choices": ["POLYGON", "RECTANGLE"],
    }
    valid_data["inputs"]["release_zones"] = {
        "kind": "vector",
        "geometry": "polygon",
        "required": False,
        "group": "release",
        "visible_when": [{"param": "release_type", "in": ["POLYGON"]}],
    }
    m = parse_manifest(valid_data)
    rz = m.inputs["release_zones"]
    assert rz.group == "release"
    assert rz.is_visible({"release_type": "POLYGON"}) is True
    assert rz.is_visible({"release_type": "RECTANGLE"}) is False


def test_input_unknown_group_is_rejected(valid_data: dict[str, Any]) -> None:
    valid_data["inputs"]["dem"]["group"] = "ghost"
    with pytest.raises(ManifestError, match=r"inputs\.dem\.group"):
        parse_manifest(valid_data)


def test_input_visible_when_unknown_param_is_rejected(valid_data: dict[str, Any]) -> None:
    valid_data["inputs"]["dem"]["visible_when"] = [{"param": "ghost", "in": ["x"]}]
    with pytest.raises(ManifestError, match=r"inputs\.dem\.visible_when references unknown param"):
        parse_manifest(valid_data)


def test_grouped_items_buckets_params_and_inputs(valid_data: dict[str, Any]) -> None:
    valid_data["groups"] = [{"id": "terrain"}, {"id": "numerics"}]
    valid_data["inputs"]["dem"]["group"] = "terrain"
    valid_data["params"]["friction_angle"]["group"] = "numerics"
    m = parse_manifest(valid_data)
    items = {
        g.id: ([p.name for p in ps], [i.name for i in ins]) for g, ps, ins in m.grouped_items()
    }
    assert items["terrain"] == ([], ["dem"])
    assert items["numerics"] == (["friction_angle"], [])
