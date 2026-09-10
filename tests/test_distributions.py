"""Tests for the distribution primitives."""

from __future__ import annotations

import numpy as np
import pytest

from almo_sweep.contracts import Constant, DistributionError, Normal


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
