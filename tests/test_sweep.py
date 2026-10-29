"""Tests for the sweep-config contract."""

from __future__ import annotations

from pathlib import Path

import pytest

from almo_sweep.contracts import (
    Constant,
    GridSelection,
    ModelManifest,
    Normal,
    SweepError,
    Uniform,
    build_sweep,
    load_manifest,
    parse_manifest,
)


@pytest.fixture
def manifest(dampm_manifest_path: Path) -> ModelManifest:
    return load_manifest(dampm_manifest_path)


# --- normalisation --------------------------------------------------------------------
def test_defaults_cover_every_parameter(manifest: ModelManifest) -> None:
    sweep = build_sweep(manifest)
    # Every numeric param becomes a Constant distribution; the choice param becomes fixed.
    assert set(sweep.distributions) == {
        "friction_angle",
        "release_depth",
        "density",
        "rk4_stages",
    }
    assert set(sweep.fixed) == {"integrator"}
    assert sweep.is_deterministic
    assert sweep.model_name == "dampm"
    assert sweep.model_version == "0.1.0"


def test_default_values_match_manifest(manifest: ModelManifest) -> None:
    sweep = build_sweep(manifest)
    assert sweep.distributions["friction_angle"] == Constant(30.0)
    assert sweep.fixed["integrator"] == "rk4"


def test_deterministic_single_run(manifest: ModelManifest) -> None:
    rows = build_sweep(manifest, n_samples=1).samples(manifest)
    assert rows == [
        {
            "friction_angle": 30.0,
            "release_depth": 1.5,
            "density": 2000.0,
            "rk4_stages": 4,
            "integrator": "rk4",
        }
    ]


# --- sampling -------------------------------------------------------------------------
def test_sampling_is_reproducible_with_seed(manifest: ModelManifest) -> None:
    cfg = build_sweep(
        manifest,
        distributions={"friction_angle": Normal(30.0, 3.0)},
        n_samples=64,
        seed=42,
    )
    first = cfg.samples(manifest)
    second = cfg.samples(manifest)
    assert first == second
    assert len(first) == 64
    assert not cfg.is_deterministic


def test_independent_params_do_not_shift_each_others_draws(manifest: ModelManifest) -> None:
    # Adding a second varying parameter must not change the draws of the first.
    one = build_sweep(
        manifest, distributions={"friction_angle": Normal(30.0, 3.0)}, n_samples=32, seed=1
    ).samples(manifest)
    two = build_sweep(
        manifest,
        distributions={"friction_angle": Normal(30.0, 3.0), "density": Normal(2000.0, 50.0)},
        n_samples=32,
        seed=1,
    ).samples(manifest)
    assert [r["friction_angle"] for r in one] == [r["friction_angle"] for r in two]


def test_normal_bounds_default_to_manifest_bounds(manifest: ModelManifest) -> None:
    # friction_angle is bounded [0, 60]; a wide normal must still respect that.
    cfg = build_sweep(
        manifest, distributions={"friction_angle": Normal(30.0, 100.0)}, n_samples=5000, seed=3
    )
    values = [r["friction_angle"] for r in cfg.samples(manifest)]
    assert min(values) >= 0.0
    assert max(values) <= 60.0


def _manifest_with_param(param: dict[str, object]) -> ModelManifest:
    """A tiny valid manifest carrying a single custom parameter."""
    return parse_manifest(
        {
            "model": {"name": "toy", "version": "0.0.0"},
            "invocation": {"command": ["true"]},
            "params": {"p": param},
        }
    )


def test_int_param_is_rounded() -> None:
    mm = _manifest_with_param(
        {"type": "int", "default": 100, "min": 1, "max": 1000, "sweepable": True}
    )
    rows = build_sweep(mm, distributions={"p": Normal(100.0, 5.0)}, n_samples=20, seed=0).samples(
        mm
    )
    assert all(isinstance(r["p"], int) for r in rows)


# --- validation -----------------------------------------------------------------------
def test_unknown_parameter_is_rejected(manifest: ModelManifest) -> None:
    with pytest.raises(SweepError, match="unknown parameter"):
        build_sweep(manifest, fixed={"nope": 1.0})


def test_distribution_on_non_numeric_is_rejected(manifest: ModelManifest) -> None:
    with pytest.raises(SweepError, match="only numeric"):
        build_sweep(manifest, distributions={"integrator": Constant(1.0)})


def test_distribution_on_numeric_non_sweepable_is_rejected() -> None:
    mm = _manifest_with_param({"type": "float", "default": 1.0, "sweepable": False})
    with pytest.raises(SweepError, match="not marked sweepable"):
        build_sweep(mm, distributions={"p": Constant(1.0)})


def test_distribution_and_fixed_conflict_is_rejected(manifest: ModelManifest) -> None:
    with pytest.raises(SweepError, match="both a distribution and a fixed"):
        build_sweep(
            manifest,
            distributions={"friction_angle": Constant(30.0)},
            fixed={"friction_angle": 30.0},
        )


def test_fixed_choice_out_of_domain_is_rejected(manifest: ModelManifest) -> None:
    with pytest.raises(SweepError, match="not one of"):
        build_sweep(manifest, fixed={"integrator": "leapfrog"})


def test_fixed_numeric_out_of_bounds_is_rejected(manifest: ModelManifest) -> None:
    with pytest.raises(SweepError, match="above the manifest max"):
        build_sweep(manifest, fixed={"friction_angle": 90.0})


def test_normal_bound_outside_manifest_is_rejected(manifest: ModelManifest) -> None:
    with pytest.raises(SweepError, match="below the manifest min"):
        build_sweep(manifest, distributions={"friction_angle": Normal(30.0, 1.0, min=-5.0)})


def test_zero_samples_is_rejected(manifest: ModelManifest) -> None:
    with pytest.raises(SweepError, match="n_samples must be >= 1"):
        build_sweep(manifest, n_samples=0)


def test_fixed_numeric_becomes_constant(manifest: ModelManifest) -> None:
    cfg = build_sweep(manifest, fixed={"friction_angle": 25.0})
    assert cfg.distributions["friction_angle"] == Constant(25.0)


# --- strategy selection & weights -----------------------------------------------------
def test_default_strategy_is_a_single_monte_carlo_sample(manifest: ModelManifest) -> None:
    # The degenerate study: one run, every sample carries the whole probability mass.
    samples = build_sweep(manifest).samples_with_weights(manifest)
    assert len(samples) == 1
    assert samples[0].weight == 1.0


def test_an_explicit_strategy_overrides_n_samples(manifest: ModelManifest) -> None:
    cfg = build_sweep(
        manifest,
        distributions={"friction_angle": Uniform(0.0, 60.0)},
        n_samples=99,  # ignored because an explicit strategy is given
        strategy=GridSelection(steps=4),
    )
    assert len(cfg.samples(manifest)) == 4


def test_uniform_out_of_manifest_bounds_is_rejected(manifest: ModelManifest) -> None:
    with pytest.raises(SweepError, match="above the manifest max"):
        build_sweep(manifest, distributions={"friction_angle": Uniform(0.0, 90.0)})


def test_uniform_on_non_sweepable_is_rejected() -> None:
    mm = _manifest_with_param({"type": "float", "default": 1.0, "sweepable": False})
    with pytest.raises(SweepError, match="not marked sweepable"):
        build_sweep(mm, distributions={"p": Uniform(0.0, 1.0)})


def test_grid_over_an_unbounded_param_is_rejected() -> None:
    # A sweepable param with no manifest bounds cannot fill a Normal's range, so a grid over it
    # has no finite axis -- this is the failing case the finite-range guard exists for.
    from almo_sweep.contracts.selection import SelectionError

    mm = _manifest_with_param({"type": "float", "default": 1.0, "sweepable": True})
    cfg = build_sweep(mm, distributions={"p": Normal(1.0, 1.0)}, strategy=GridSelection(steps=3))
    with pytest.raises(SelectionError, match="needs a finite range"):
        cfg.samples(mm)
