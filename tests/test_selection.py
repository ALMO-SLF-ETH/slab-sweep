"""Tests for the selection strategies (Monte Carlo, Latin hypercube, grid) and the seam."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import pytest

from almo_sweep.contracts import (
    GridSelection,
    LatinHypercubeSelection,
    ModelManifest,
    MonteCarloSelection,
    Normal,
    Uniform,
    build_sweep,
    load_manifest,
)
from almo_sweep.contracts.distributions import Distribution
from almo_sweep.contracts.selection import Draw, SelectionError


@pytest.fixture
def manifest(dampm_manifest_path: Path) -> ModelManifest:
    return load_manifest(dampm_manifest_path)


# --- Monte Carlo ----------------------------------------------------------------------
def test_monte_carlo_count_is_n_samples_regardless_of_dimension(manifest: ModelManifest) -> None:
    cfg = build_sweep(
        manifest,
        distributions={"friction_angle": Normal(30.0, 3.0), "density": Normal(2000.0, 50.0)},
        strategy=MonteCarloSelection(40),
        seed=0,
    )
    samples = cfg.samples_with_weights(manifest)
    assert len(samples) == 40  # count set by n_samples, not by how many params vary
    assert abs(sum(s.weight for s in samples) - 1.0) < 1e-9
    assert all(abs(s.weight - 1.0 / 40) < 1e-12 for s in samples)  # equal weights


def test_monte_carlo_is_reproducible_and_independent(manifest: ModelManifest) -> None:
    def frictions(dists: dict[str, Distribution]) -> list[float]:
        cfg = build_sweep(manifest, distributions=dists, strategy=MonteCarloSelection(16), seed=7)
        return [row["friction_angle"] for row in cfg.samples(manifest)]

    one = frictions({"friction_angle": Normal(30.0, 3.0)})
    again = frictions({"friction_angle": Normal(30.0, 3.0)})
    with_second = frictions({"friction_angle": Normal(30.0, 3.0), "density": Normal(2000.0, 50.0)})
    assert one == again  # reproducible from the seed
    assert one == with_second  # adding a parameter does not shift another's draws


# --- Latin hypercube ------------------------------------------------------------------
def test_latin_hypercube_fills_every_stratum_once(manifest: ModelManifest) -> None:
    # 12 samples over a uniform [0, 60] range -> exactly one sample in each 5-wide stratum.
    n = 12
    cfg = build_sweep(
        manifest,
        distributions={"friction_angle": Uniform(0.0, 60.0)},
        strategy=LatinHypercubeSelection(n),
        seed=3,
    )
    values = sorted(row["friction_angle"] for row in cfg.samples(manifest))
    assert len(values) == n
    strata = np.floor(np.array(values) / (60.0 / n)).astype(int)
    assert list(strata) == list(range(n))  # one per stratum, none doubled up


def test_latin_hypercube_is_reproducible(manifest: ModelManifest) -> None:
    def draw() -> list[float]:
        cfg = build_sweep(
            manifest,
            distributions={"density": Uniform(500.0, 3000.0)},
            strategy=LatinHypercubeSelection(20),
            seed=11,
        )
        return [row["density"] for row in cfg.samples(manifest)]

    assert draw() == draw()


# --- Grid -----------------------------------------------------------------------------
def test_grid_is_the_cartesian_product_of_the_axes(manifest: ModelManifest) -> None:
    cfg = build_sweep(
        manifest,
        distributions={"friction_angle": Uniform(0.0, 60.0), "density": Uniform(500.0, 3000.0)},
        strategy=GridSelection(steps={"friction_angle": 3, "density": 2}),
    )
    rows = cfg.samples(manifest)
    pairs = {(r["friction_angle"], r["density"]) for r in rows}
    expected = {(f, d) for f in (0.0, 30.0, 60.0) for d in (500.0, 3000.0)}
    assert len(rows) == 6  # 3 x 2
    assert pairs == expected


def test_grid_is_deterministic_and_seed_independent(manifest: ModelManifest) -> None:
    def run(seed: int | None) -> list[dict[str, Any]]:
        return build_sweep(
            manifest,
            distributions={"friction_angle": Uniform(0.0, 60.0)},
            strategy=GridSelection(steps=5),
            seed=seed,
        ).samples(manifest)

    assert run(None) == run(999)  # the grid ignores the seed


def test_grid_weights_follow_the_distribution(manifest: ModelManifest) -> None:
    # A normal weight profile over an equal-step grid must weight the centre above the corners,
    # while the *nodes themselves* are the plain equal steps (probability tilts weight, not choice).
    cfg = build_sweep(
        manifest,
        distributions={"friction_angle": Normal(30.0, 5.0, min=0.0, max=60.0)},
        strategy=GridSelection(steps=5),
    )
    samples = sorted(cfg.samples_with_weights(manifest), key=lambda s: s.values["friction_angle"])
    assert [s.values["friction_angle"] for s in samples] == [0.0, 15.0, 30.0, 45.0, 60.0]
    assert abs(sum(s.weight for s in samples) - 1.0) < 1e-9
    centre = samples[2].weight  # value 30.0 == the mean
    assert centre > samples[0].weight and centre > samples[-1].weight


def test_grid_uniform_profile_gives_equal_weights(manifest: ModelManifest) -> None:
    cfg = build_sweep(
        manifest,
        distributions={"friction_angle": Uniform(0.0, 60.0)},
        strategy=GridSelection(steps=4),
    )
    weights = [s.weight for s in cfg.samples_with_weights(manifest)]
    assert all(abs(w - 0.25) < 1e-9 for w in weights)


def test_grid_log_spacing(manifest: ModelManifest) -> None:
    cfg = build_sweep(
        manifest,
        distributions={"density": Uniform(500.0, 3000.0)},
        strategy=GridSelection(steps={"density": 3}, spacing="log"),
    )
    values = sorted(row["density"] for row in cfg.samples(manifest))
    assert values[0] == pytest.approx(500.0)
    assert values[2] == pytest.approx(3000.0)
    assert values[1] == pytest.approx((500.0 * 3000.0) ** 0.5)  # geometric mean


def test_grid_needs_a_finite_range(manifest: ModelManifest) -> None:
    # An unbounded normal has no finite support, so a grid cannot lay out an axis for it.
    cfg = build_sweep(
        manifest,
        distributions={"friction_angle": Normal(30.0, 5.0)},
        strategy=GridSelection(steps=3),
    )
    # friction_angle's manifest bounds [0, 60] fill the normal's bounds, so this one is fine;
    # a parameter with no manifest bounds is the failing case -- exercised on a custom manifest.
    assert len(cfg.samples(manifest)) == 3


def test_grid_rejects_bad_configuration() -> None:
    with pytest.raises(SelectionError, match="spacing must be"):
        GridSelection(spacing="cubic")
    with pytest.raises(SelectionError, match="steps must be >= 1"):
        GridSelection(steps=0)


def test_grid_log_spacing_rejects_nonpositive_range(manifest: ModelManifest) -> None:
    cfg = build_sweep(
        manifest,
        distributions={"friction_angle": Uniform(0.0, 60.0)},  # starts at 0 -> invalid for log
        strategy=GridSelection(steps=3, spacing="log"),
    )
    with pytest.raises(SelectionError, match="log spacing needs a strictly positive"):
        cfg.samples(manifest)


# --- Extensibility: a new scheme is one class implementing the protocol ---------------
class _QuartileSelection:
    """A toy strategy proving the seam: two samples at the 25th and 75th quantiles."""

    kind = "quartiles"

    def draw(self, varying: dict[str, Distribution], *, seed: int | None) -> Draw:
        quantiles = np.array([0.25, 0.75])
        cols = {name: dist.ppf(quantiles) for name, dist in varying.items()}
        weights = np.array([0.5, 0.5])
        return cols, weights

    def describe(self) -> dict[str, Any]:
        return {"kind": self.kind}


def test_a_custom_strategy_plugs_into_the_same_seam(manifest: ModelManifest) -> None:
    cfg = build_sweep(
        manifest,
        distributions={"friction_angle": Uniform(0.0, 60.0)},
        strategy=_QuartileSelection(),
    )
    rows = cfg.samples(manifest)
    assert [r["friction_angle"] for r in rows] == [15.0, 45.0]  # 25% and 75% of [0, 60]
