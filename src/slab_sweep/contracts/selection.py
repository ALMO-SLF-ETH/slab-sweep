"""Selection strategies: *how* a study turns parameter ranges into concrete sample points.

Where a :mod:`distribution <slab_sweep.contracts.distributions>` says what a single parameter
looks like, a **selection strategy** decides which combinations across all the varying
parameters are actually simulated, and what weight each carries for post-processing. The three
schemes cover the spectrum used in runout/hazard practice:

* :class:`MonteCarloSelection` -- independent random draws per parameter. Run count is fixed
  (``n_samples``), independent of how many parameters vary; probability is expressed through the
  density of the draws (so every run carries equal weight).
* :class:`LatinHypercubeSelection` -- stratified sampling: each parameter's quantile range is
  split into ``n_samples`` equal strata with one jittered draw each, then shuffled across
  parameters. Far better space-filling than plain Monte Carlo for the same budget; again equal
  weights.
* :class:`GridSelection` -- a full-factorial grid: each parameter's range is cut into equal
  (linear or log) steps and the Cartesian product is simulated. Deterministic (no seed), with
  the corners the samplers tend to miss; each node carries the decoupled probability weight
  ``prod(pdf(value))`` so probability drives the *map*, never the *selection*.

Adding a future scheme (Sobol, one-factor-at-a-time, ...) is one new class implementing
:class:`SelectionStrategy` -- nothing in :mod:`~slab_sweep.contracts.sweep` or its callers
changes. All strategies are standard-library + numpy only.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, ClassVar, Protocol

import numpy as np
import numpy.typing as npt

from slab_sweep.contracts.distributions import Distribution
from slab_sweep.contracts.errors import ContractError

#: A column bundle: one value array per varying parameter plus a per-sample weight array. All
#: arrays share the same length (the number of samples the strategy produced). The weights sum
#: to 1 so a client can read each run's share of the study's total probability mass directly.
Draw = tuple[dict[str, npt.NDArray[np.float64]], npt.NDArray[np.float64]]

_VALID_SPACINGS = ("linear", "log")


class SelectionError(ContractError):
    """A selection strategy is misconfigured or cannot place points for the given ranges."""


class SelectionStrategy(Protocol):
    """Turns the varying parameters' distributions into concrete sample columns + weights.

    ``varying`` maps each varying parameter's name to its distribution, in a stable order (the
    manifest's parameter order); ``seed`` seeds any randomness (ignored by deterministic
    strategies). ``describe`` returns a JSON-serialisable summary for provenance.
    """

    kind: ClassVar[str]

    def draw(self, varying: dict[str, Distribution], *, seed: int | None) -> Draw: ...

    def describe(self) -> dict[str, Any]: ...


def _spawn_seeds(seed: int | None, names: list[str]) -> dict[str, np.random.SeedSequence]:
    """One independent, reproducible seed per parameter.

    Keying a child seed to each parameter (rather than drawing all parameters from one stream)
    means adding or removing a parameter never shifts another's draws -- a study stays
    comparable when a parameter is added.
    """
    children = np.random.SeedSequence(seed).spawn(len(names))
    return dict(zip(names, children, strict=True))


@dataclass(frozen=True)
class MonteCarloSelection:
    """Independent random draws per parameter; ``n_samples`` runs, equal weights."""

    n_samples: int
    kind: ClassVar[str] = "monte_carlo"

    def __post_init__(self) -> None:
        if self.n_samples < 1:
            raise SelectionError(f"n_samples must be >= 1, got {self.n_samples}")

    def draw(self, varying: dict[str, Distribution], *, seed: int | None) -> Draw:
        names = list(varying)
        seeds = _spawn_seeds(seed, names)
        cols = {
            name: varying[name].sample(np.random.default_rng(seeds[name]), self.n_samples)
            for name in names
        }
        weights = np.full(self.n_samples, 1.0 / self.n_samples, dtype=np.float64)
        return cols, weights

    def describe(self) -> dict[str, Any]:
        return {"kind": self.kind, "n_samples": self.n_samples}


@dataclass(frozen=True)
class LatinHypercubeSelection:
    """Stratified sampling: one jittered draw per equal-probability stratum, per parameter.

    Each parameter's quantile range ``[0, 1]`` is split into ``n_samples`` equal strata; one
    value is drawn from each (jittered within the stratum) via the distribution's inverse CDF,
    then the per-parameter columns are shuffled independently so the strata do not line up across
    parameters. Weights are equal -- the stratification already reflects each distribution's shape.
    """

    n_samples: int
    kind: ClassVar[str] = "latin_hypercube"

    def __post_init__(self) -> None:
        if self.n_samples < 1:
            raise SelectionError(f"n_samples must be >= 1, got {self.n_samples}")

    def draw(self, varying: dict[str, Distribution], *, seed: int | None) -> Draw:
        names = list(varying)
        seeds = _spawn_seeds(seed, names)
        n = self.n_samples
        cols: dict[str, npt.NDArray[np.float64]] = {}
        for name in names:
            rng = np.random.default_rng(seeds[name])
            quantiles = (np.arange(n, dtype=np.float64) + rng.random(n)) / n
            values = varying[name].ppf(quantiles)
            rng.shuffle(values)  # decorrelate the strata across parameters
            cols[name] = values
        weights = np.full(n, 1.0 / n, dtype=np.float64)
        return cols, weights

    def describe(self) -> dict[str, Any]:
        return {"kind": self.kind, "n_samples": self.n_samples}


@dataclass(frozen=True)
class GridSelection:
    """Full-factorial grid: the Cartesian product of each parameter's equal steps.

    ``steps`` is the number of grid points per parameter -- one integer for all, or a mapping of
    per-parameter counts (a parameter absent from the mapping defaults to :data:`DEFAULT_STEPS`).
    ``spacing`` is ``"linear"`` or ``"log"`` (log needs a strictly positive range). The grid is
    laid over each distribution's ``support``, so a parameter needs a finite range -- give it a
    :class:`~slab_sweep.contracts.distributions.Uniform` or a bounded
    :class:`~slab_sweep.contracts.distributions.Normal`. Each node's weight is the normalised
    product of the per-parameter densities at that node, so a non-uniform distribution tilts the
    *weights* (for the probability map) without changing *which* nodes are simulated.
    """

    #: Default grid points for a parameter not named in a per-parameter ``steps`` mapping.
    DEFAULT_STEPS: ClassVar[int] = 5

    steps: int | Mapping[str, int] = DEFAULT_STEPS
    spacing: str = "linear"
    kind: ClassVar[str] = "grid"

    def __post_init__(self) -> None:
        if self.spacing not in _VALID_SPACINGS:
            raise SelectionError(f"spacing must be one of {_VALID_SPACINGS}, got {self.spacing!r}")
        counts = self.steps.values() if isinstance(self.steps, Mapping) else [self.steps]
        if any(int(c) < 1 for c in counts):
            raise SelectionError("grid steps must be >= 1")

    def _steps_for(self, name: str) -> int:
        if isinstance(self.steps, Mapping):
            return int(self.steps.get(name, self.DEFAULT_STEPS))
        return int(self.steps)

    def _axis(self, name: str, dist: Distribution) -> npt.NDArray[np.float64]:
        lo, hi = dist.support()
        k = self._steps_for(name)
        if lo == hi:  # a constant (or zero-width) parameter contributes a single node
            return np.array([lo], dtype=np.float64)
        if not (np.isfinite(lo) and np.isfinite(hi)):
            raise SelectionError(
                f"{name}: a grid needs a finite range; give it a Uniform(low, high) "
                f"or a bounded Normal"
            )
        if k == 1:
            return np.array([(lo + hi) / 2.0], dtype=np.float64)
        if self.spacing == "log":
            if lo <= 0.0:
                raise SelectionError(f"{name}: log spacing needs a strictly positive range")
            return np.geomspace(lo, hi, k, dtype=np.float64)
        return np.linspace(lo, hi, k, dtype=np.float64)

    def draw(self, varying: dict[str, Distribution], *, seed: int | None) -> Draw:
        names = list(varying)
        if not names:
            return {}, np.array([1.0], dtype=np.float64)

        axes = [self._axis(name, varying[name]) for name in names]
        mesh = np.meshgrid(*axes, indexing="ij")
        cols: dict[str, npt.NDArray[np.float64]] = {
            name: np.reshape(grid, -1) for name, grid in zip(names, mesh, strict=True)
        }

        weight: npt.NDArray[np.float64] = np.ones(cols[names[0]].shape, dtype=np.float64)
        for name in names:
            weight = weight * varying[name].pdf(cols[name])
        total = float(weight.sum())
        n = int(weight.size)
        weights = weight / total if total > 0.0 else np.full(n, 1.0 / n, dtype=np.float64)
        return cols, weights

    def describe(self) -> dict[str, Any]:
        steps = dict(self.steps) if isinstance(self.steps, Mapping) else self.steps
        return {"kind": self.kind, "steps": steps, "spacing": self.spacing}


@dataclass(frozen=True)
class Sample:
    """One concrete parameter combination to simulate, with its post-processing weight.

    ``weight`` is this run's share of the study's total probability mass (the weights across a
    study sum to 1). It never influenced whether this run was selected -- it is for weighting
    results afterwards, e.g. a probability-weighted extent map.
    """

    values: dict[str, Any]
    weight: float = 1.0
    #: Reserved for future per-sample provenance; kept so the dataclass can grow compatibly.
    _extra: dict[str, Any] = field(default_factory=dict, repr=False, compare=False)


__all__ = [
    "Draw",
    "GridSelection",
    "LatinHypercubeSelection",
    "MonteCarloSelection",
    "Sample",
    "SelectionError",
    "SelectionStrategy",
]
