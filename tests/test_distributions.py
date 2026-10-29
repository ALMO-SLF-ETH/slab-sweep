"""Tests for the distribution primitives."""

from __future__ import annotations

import numpy as np
import pytest

from almo_sweep.contracts import Constant, DistributionError, Normal, Uniform


def test_constant_always_returns_value() -> None:
    rng = np.random.default_rng(0)
    draws = Constant(4.2).sample(rng, 1000)
    assert draws.shape == (1000,)
    assert np.all(draws == 4.2)


def test_constant_describe_is_serialisable() -> None:
    assert Constant(1.0).describe() == {"kind": "constant", "value": 1.0}


def test_normal_is_reproducible_from_seed() -> None:
    a = Normal(10.0, 2.0).sample(np.random.default_rng(123), 500)
    b = Normal(10.0, 2.0).sample(np.random.default_rng(123), 500)
    np.testing.assert_array_equal(a, b)


def test_normal_statistics_are_roughly_right() -> None:
    draws = Normal(10.0, 2.0).sample(np.random.default_rng(7), 50_000)
    assert abs(float(draws.mean()) - 10.0) < 0.1
    assert abs(float(draws.std()) - 2.0) < 0.1


def test_normal_truncation_respects_bounds() -> None:
    # Bounds that cut off a large fraction of the mass still never leak.
    draws = Normal(0.0, 5.0, min=-1.0, max=1.0).sample(np.random.default_rng(1), 20_000)
    assert float(draws.min()) >= -1.0
    assert float(draws.max()) <= 1.0


def test_normal_zero_std_is_a_spike() -> None:
    draws = Normal(3.0, 0.0).sample(np.random.default_rng(0), 10)
    assert np.all(draws == 3.0)


def test_normal_rejects_negative_std() -> None:
    with pytest.raises(DistributionError, match="std must be >= 0"):
        Normal(0.0, -1.0)


def test_normal_rejects_inverted_bounds() -> None:
    with pytest.raises(DistributionError, match="greater than max"):
        Normal(0.0, 1.0, min=5.0, max=1.0)


def test_normal_describe_reports_bounds() -> None:
    assert Normal(1.0, 0.5, min=0.0, max=2.0).describe() == {
        "kind": "normal",
        "mean": 1.0,
        "std": 0.5,
        "min": 0.0,
        "max": 2.0,
    }


# --- ppf / pdf (used by Latin-hypercube and grid strategies) --------------------------
def test_normal_ppf_inverts_the_cdf() -> None:
    # ppf(0.5) is the median (== mean for an untruncated normal); the quantiles are monotone.
    dist = Normal(10.0, 2.0)
    q = np.array([0.1, 0.25, 0.5, 0.75, 0.9])
    v = dist.ppf(q)
    assert abs(float(v[2]) - 10.0) < 1e-6
    assert np.all(np.diff(v) > 0)
    # 1-sigma below/above the mean sits at the ~15.9/84.1 percentiles.
    assert float(dist.ppf(np.array([0.1586]))[0]) == pytest.approx(8.0, abs=1e-2)


def test_truncated_normal_ppf_stays_in_bounds() -> None:
    dist = Normal(0.0, 5.0, min=-1.0, max=1.0)
    v = dist.ppf(np.linspace(0.0, 1.0, 50))
    assert float(v.min()) >= -1.0
    assert float(v.max()) <= 1.0


def test_normal_pdf_peaks_at_the_mean() -> None:
    dist = Normal(0.0, 1.0)
    dens = dist.pdf(np.array([-2.0, 0.0, 2.0]))
    assert dens[1] > dens[0] and dens[1] > dens[2]
    assert float(dens[1]) == pytest.approx(1.0 / np.sqrt(2.0 * np.pi), rel=1e-6)


def test_uniform_samples_within_range() -> None:
    draws = Uniform(2.0, 5.0).sample(np.random.default_rng(0), 10_000)
    assert float(draws.min()) >= 2.0
    assert float(draws.max()) <= 5.0
    assert abs(float(draws.mean()) - 3.5) < 0.1


def test_uniform_ppf_is_linear() -> None:
    v = Uniform(0.0, 10.0).ppf(np.array([0.0, 0.5, 1.0]))
    np.testing.assert_allclose(v, [0.0, 5.0, 10.0])


def test_uniform_pdf_is_flat_inside_and_zero_outside() -> None:
    dist = Uniform(0.0, 4.0)
    dens = dist.pdf(np.array([-1.0, 1.0, 2.0, 5.0]))
    np.testing.assert_allclose(dens, [0.0, 0.25, 0.25, 0.0])


def test_uniform_support_is_the_range() -> None:
    assert Uniform(1.0, 9.0).support() == (1.0, 9.0)


def test_uniform_rejects_inverted_range() -> None:
    with pytest.raises(DistributionError, match="greater than high"):
        Uniform(5.0, 1.0)


def test_uniform_describe_is_serialisable() -> None:
    assert Uniform(1.0, 2.0).describe() == {"kind": "uniform", "low": 1.0, "high": 2.0}


def test_constant_ppf_and_support_are_the_point() -> None:
    assert Constant(3.0).support() == (3.0, 3.0)
    np.testing.assert_array_equal(Constant(3.0).ppf(np.array([0.1, 0.9])), [3.0, 3.0])
