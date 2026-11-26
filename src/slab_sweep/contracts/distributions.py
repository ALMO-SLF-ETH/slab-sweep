"""Probability distributions used to explore a parameter in a study.

A study assigns each swept numeric parameter a **distribution**, which plays two roles:

* it is the *weight profile* over the parameter's range -- its probability density, used in
  post-processing (e.g. a probability-weighted extent map), never to decide which runs happen;
* it supplies what each :mod:`selection strategy <slab_sweep.contracts.selection>` needs to
  place sample points: random draws (Monte Carlo), the inverse CDF / quantile function (Latin
  hypercube), or a finite range plus per-node density (grid).

Three kinds are supported:

* :class:`Constant` -- a single fixed value (a degenerate, zero-variance distribution).
* :class:`Uniform`  -- a flat distribution over ``[low, high]`` (equal weight across the range).
* :class:`Normal`   -- a Gaussian, optionally truncated to ``[min, max]`` bounds (which
  default to the parameter's manifest bounds).

Distributions are the vocabulary of the sweep config (:mod:`slab_sweep.contracts.sweep`).
They are standard-library + numpy only, so a client can build and describe them inside
QGIS's interpreter.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, ClassVar, Protocol

import numpy as np
import numpy.typing as npt

from slab_sweep.contracts.errors import ContractError

#: Cap on truncated-normal rejection resampling before falling back to a hard clip. Chosen
#: high enough that, for any sanely-configured normal whose bounds admit meaningful mass,
#: every draw lands in range; the final clip only guarantees the bound in pathological cases.
_MAX_TRUNCATION_ATTEMPTS = 100

#: Inverse-CDF quantiles are clamped off the open ends of ``[0, 1]`` so ``ppf`` never returns
#: an infinite z for a stratum edge that lands exactly at 0 or 1.
_PPF_EPS = 1e-12


class DistributionError(ContractError):
    """A distribution is configured with invalid parameters (e.g. a negative std)."""


class Distribution(Protocol):
    """The interface every distribution implements.

    ``sample`` draws ``size`` independent values with the given numpy generator (used by the
    Monte-Carlo strategy). ``ppf`` is the inverse CDF / quantile function, mapping quantiles in
    ``[0, 1]`` to values (used by Latin-hypercube stratification). ``pdf`` is the probability
    density at a value (used to weight grid nodes). ``support`` returns the ``(low, high)`` range
    over which a grid is laid out. ``describe`` returns a JSON-serialisable summary for provenance.
    """

    kind: ClassVar[str]

    def sample(self, rng: np.random.Generator, size: int) -> npt.NDArray[np.float64]: ...

    def ppf(self, q: npt.NDArray[np.float64]) -> npt.NDArray[np.float64]: ...

    def pdf(self, x: npt.NDArray[np.float64]) -> npt.NDArray[np.float64]: ...

    def support(self) -> tuple[float, float]: ...

    def describe(self) -> dict[str, Any]: ...


@dataclass(frozen=True)
class Constant:
    """A fixed value; every draw is ``value`` and its support is the single point."""

    value: float
    kind: ClassVar[str] = "constant"

    def sample(self, rng: np.random.Generator, size: int) -> npt.NDArray[np.float64]:
        return np.full(int(size), float(self.value), dtype=np.float64)

    def ppf(self, q: npt.NDArray[np.float64]) -> npt.NDArray[np.float64]:
        return np.full(np.asarray(q).shape, float(self.value), dtype=np.float64)

    def pdf(self, x: npt.NDArray[np.float64]) -> npt.NDArray[np.float64]:
        # A degenerate spike has no finite density; return a neutral factor of 1 so a constant
        # parameter leaves a grid node's joint weight unchanged.
        return np.ones(np.asarray(x).shape, dtype=np.float64)

    def support(self) -> tuple[float, float]:
        return (float(self.value), float(self.value))

    def describe(self) -> dict[str, Any]:
        return {"kind": self.kind, "value": self.value}


@dataclass(frozen=True)
class Uniform:
    """A uniform distribution over ``[low, high]`` -- equal weight across the whole range.

    This is the natural weight profile when a study wants to explore a plain range without
    assuming any shape (e.g. a grid with equal node weights, or an unbiased Latin hypercube).
    """

    low: float
    high: float
    kind: ClassVar[str] = "uniform"

    def __post_init__(self) -> None:
        if self.high < self.low:
            raise DistributionError(f"uniform.low ({self.low}) is greater than high ({self.high})")

    @property
    def _width(self) -> float:
        return float(self.high) - float(self.low)

    def sample(self, rng: np.random.Generator, size: int) -> npt.NDArray[np.float64]:
        if self._width == 0.0:
            return np.full(int(size), float(self.low), dtype=np.float64)
        return rng.uniform(self.low, self.high, int(size)).astype(np.float64, copy=False)

    def ppf(self, q: npt.NDArray[np.float64]) -> npt.NDArray[np.float64]:
        q = np.asarray(q, dtype=np.float64)
        return float(self.low) + q * self._width

    def pdf(self, x: npt.NDArray[np.float64]) -> npt.NDArray[np.float64]:
        x = np.asarray(x, dtype=np.float64)
        if self._width == 0.0:  # degenerate: treat as a neutral spike
            return np.ones(x.shape, dtype=np.float64)
        inside = (x >= self.low) & (x <= self.high)
        return np.where(inside, 1.0 / self._width, 0.0)

    def support(self) -> tuple[float, float]:
        return (float(self.low), float(self.high))

    def describe(self) -> dict[str, Any]:
        return {"kind": self.kind, "low": self.low, "high": self.high}


@dataclass(frozen=True)
class Normal:
    """A normal distribution, optionally truncated to ``[min, max]``.

    Truncation is done by rejection resampling (values outside the bounds are redrawn),
    which preserves the shape of the distribution inside the bounds rather than piling mass
    on the edges the way a plain clip would. A final clip guarantees the bounds even in the
    rare case that resampling does not converge within :data:`_MAX_TRUNCATION_ATTEMPTS`.
    """

    mean: float
    std: float
    min: float | None = None
    max: float | None = None
    kind: ClassVar[str] = "normal"

    def __post_init__(self) -> None:
        if self.std < 0:
            raise DistributionError("normal.std must be >= 0")
        if self.min is not None and self.max is not None and self.min > self.max:
            raise DistributionError(f"normal.min ({self.min}) is greater than max ({self.max})")

    def sample(self, rng: np.random.Generator, size: int) -> npt.NDArray[np.float64]:
        n = int(size)
        draws = rng.normal(self.mean, self.std, n).astype(np.float64, copy=False)
        if self.min is None and self.max is None:
            return draws
        lo = -np.inf if self.min is None else self.min
        hi = np.inf if self.max is None else self.max
        for _ in range(_MAX_TRUNCATION_ATTEMPTS):
            out_of_bounds = (draws < lo) | (draws > hi)
            k = int(out_of_bounds.sum())
            if k == 0:
                break
            draws[out_of_bounds] = rng.normal(self.mean, self.std, k)
        return np.clip(draws, self.min, self.max)

    def ppf(self, q: npt.NDArray[np.float64]) -> npt.NDArray[np.float64]:
        """Quantile function of the (optionally truncated) normal.

        For a truncation ``[a, b]`` the quantile is found by mapping ``q`` into the standard
        normal's CDF range ``[Phi(alpha), Phi(beta)]`` and inverting with :func:`_ndtri`, so the
        drawn values keep the normal's shape inside the bounds.
        """
        q = np.clip(np.asarray(q, dtype=np.float64), _PPF_EPS, 1.0 - _PPF_EPS)
        if self.std == 0.0:
            return np.full(q.shape, float(self.mean), dtype=np.float64)
        alpha = -math.inf if self.min is None else (self.min - self.mean) / self.std
        beta = math.inf if self.max is None else (self.max - self.mean) / self.std
        lo_p, hi_p = _phi(alpha), _phi(beta)
        p = lo_p + q * (hi_p - lo_p)
        values = self.mean + self.std * _ndtri(p)
        if self.min is None and self.max is None:
            return values
        return np.clip(values, self.min, self.max)

    def pdf(self, x: npt.NDArray[np.float64]) -> npt.NDArray[np.float64]:
        x = np.asarray(x, dtype=np.float64)
        if self.std == 0.0:  # degenerate spike: neutral factor
            return np.ones(x.shape, dtype=np.float64)
        z = (x - self.mean) / self.std
        dens = np.exp(-0.5 * z * z) / (self.std * math.sqrt(2.0 * math.pi))
        if self.min is not None or self.max is not None:
            alpha = -math.inf if self.min is None else (self.min - self.mean) / self.std
            beta = math.inf if self.max is None else (self.max - self.mean) / self.std
            dens = dens / (_phi(beta) - _phi(alpha))
            lo = -math.inf if self.min is None else self.min
            hi = math.inf if self.max is None else self.max
            dens = np.where((x >= lo) & (x <= hi), dens, 0.0)
        return dens

    def support(self) -> tuple[float, float]:
        lo = -math.inf if self.min is None else float(self.min)
        hi = math.inf if self.max is None else float(self.max)
        return (lo, hi)

    def describe(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "mean": self.mean,
            "std": self.std,
            "min": self.min,
            "max": self.max,
        }


def _phi(z: float) -> float:
    """Standard-normal CDF at a scalar ``z`` (``Phi(-inf) = 0``, ``Phi(+inf) = 1``)."""
    return 0.5 * math.erfc(-z / math.sqrt(2.0))


# Acklam's rational-approximation coefficients for the inverse standard-normal CDF.
_NDTRI_A = (
    -3.969683028665376e01,
    2.209460984245205e02,
    -2.759285104469687e02,
    1.383577518672690e02,
    -3.066479806614716e01,
    2.506628277459239e00,
)
_NDTRI_B = (
    -5.447609879822406e01,
    1.615858368580409e02,
    -1.556989798598866e02,
    6.680131188771972e01,
    -1.328068155288572e01,
)
_NDTRI_C = (
    -7.784894002430293e-03,
    -3.223964580411365e-01,
    -2.400758277161838e00,
    -2.549732539343734e00,
    4.374664141464968e00,
    2.938163982698783e00,
)
_NDTRI_D = (
    7.784695709041462e-03,
    3.224671290700398e-01,
    2.445134137142996e00,
    3.754408661907416e00,
)
_NDTRI_P_LOW = 0.02425


def _ndtri(p: npt.NDArray[np.float64]) -> npt.NDArray[np.float64]:
    """Inverse of the standard-normal CDF, vectorised (Acklam's approximation, ~1e-9 error).

    numpy ships no ``erfinv`` and the engine takes no scipy dependency, so we use Acklam's
    piecewise rational approximation, which is accurate to roughly 1.15e-9 across ``(0, 1)``.
    """
    a, b, c, d = _NDTRI_A, _NDTRI_B, _NDTRI_C, _NDTRI_D
    p = np.asarray(p, dtype=np.float64)
    out = np.empty_like(p)

    low = p < _NDTRI_P_LOW
    high = p > 1.0 - _NDTRI_P_LOW
    mid = ~(low | high)

    if low.any():
        q = np.sqrt(-2.0 * np.log(p[low]))
        out[low] = (((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / (
            (((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1.0
        )
    if high.any():
        q = np.sqrt(-2.0 * np.log(1.0 - p[high]))
        out[high] = -(((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / (
            (((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1.0
        )
    if mid.any():
        q = p[mid] - 0.5
        r = q * q
        out[mid] = ((((((a[0] * r + a[1]) * r + a[2]) * r + a[3]) * r + a[4]) * r + a[5]) * q) / (
            ((((b[0] * r + b[1]) * r + b[2]) * r + b[3]) * r + b[4]) * r + 1.0
        )
    return out


__all__ = ["Constant", "Distribution", "DistributionError", "Normal", "Uniform"]
