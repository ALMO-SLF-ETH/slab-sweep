"""Probability distributions used to explore a parameter in a study.

A study assigns each swept numeric parameter a **distribution**. Two kinds are supported,
matching the requirement to explore a range with either a constant or a normal probability:

* :class:`Constant` -- a single fixed value (a degenerate, zero-variance distribution).
* :class:`Normal`   -- a Gaussian, optionally truncated to ``[min, max]`` bounds (which
  default to the parameter's manifest bounds).

Distributions are the vocabulary of the sweep config (:mod:`almo_sweep.contracts.sweep`).
They are standard-library + numpy only, so a client can build and describe them inside
QGIS's interpreter.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, ClassVar, Protocol

import numpy as np
import numpy.typing as npt

from almo_sweep.contracts.errors import ContractError

#: Cap on truncated-normal rejection resampling before falling back to a hard clip. Chosen
#: high enough that, for any sanely-configured normal whose bounds admit meaningful mass,
#: every draw lands in range; the final clip only guarantees the bound in pathological cases.
_MAX_TRUNCATION_ATTEMPTS = 100


class DistributionError(ContractError):
    """A distribution is configured with invalid parameters (e.g. a negative std)."""


class Distribution(Protocol):
    """The interface every distribution implements.

    ``sample`` draws ``size`` independent values with the given numpy generator, so that
    sampling is reproducible from a seed. ``describe`` returns a JSON-serialisable summary
    for provenance records.
    """

    kind: ClassVar[str]

    def sample(self, rng: np.random.Generator, size: int) -> npt.NDArray[np.float64]: ...

    def describe(self) -> dict[str, Any]: ...


@dataclass(frozen=True)
class Constant:
    """A fixed value; every draw is ``value``."""

    value: float
    kind: ClassVar[str] = "constant"

    def sample(self, rng: np.random.Generator, size: int) -> npt.NDArray[np.float64]:
        return np.full(int(size), float(self.value), dtype=np.float64)

    def describe(self) -> dict[str, Any]:
        return {"kind": self.kind, "value": self.value}


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

    def describe(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "mean": self.mean,
            "std": self.std,
            "min": self.min,
            "max": self.max,
        }
