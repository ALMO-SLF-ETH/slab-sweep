"""The sweep-config contract: a user-authored study, validated against a manifest.

Where the manifest (:mod:`almo_sweep.contracts.manifest`) declares *what a model accepts*,
a **sweep config** declares *what a study explores*: which parameters vary, under which
distribution, how many samples to draw, and with what seed. A deterministic single run is
just the degenerate case -- every parameter :class:`~almo_sweep.contracts.distributions.Constant`
and ``n_samples = 1``.

The public entry point is :func:`build_sweep`, which validates the requested assignments
against a manifest and *normalises* them so that, in the resulting :class:`SweepConfig`,
every numeric parameter lives in ``distributions`` (as a Constant or Normal) and every
non-numeric parameter lives in ``fixed``. :meth:`SweepConfig.samples` then expands the
config into concrete ``{param: value}`` dictionaries, one per sample, reproducibly.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np

from almo_sweep.contracts.distributions import Constant, Distribution, Normal
from almo_sweep.contracts.errors import ContractError
from almo_sweep.contracts.manifest import ModelManifest, ParamSpec, ParamType


class SweepError(ContractError):
    """A sweep config is inconsistent with the manifest it is built against."""


@dataclass(frozen=True)
class SweepConfig:
    """A normalised, manifest-validated study definition.

    Invariant (guaranteed by :func:`build_sweep`): ``distributions`` holds exactly the
    manifest's numeric parameters and ``fixed`` holds exactly its non-numeric ones; together
    they cover every parameter exactly once.
    """

    model_name: str
    distributions: dict[str, Distribution]
    fixed: dict[str, Any]
    n_samples: int = 1
    seed: int | None = None
    model_version: str | None = None

    @property
    def is_deterministic(self) -> bool:
        """True if no parameter actually varies (every distribution is a Constant)."""
        return all(isinstance(d, Constant) for d in self.distributions.values())

    def samples(self, manifest: ModelManifest) -> list[dict[str, Any]]:
        """Expand the config into ``n_samples`` concrete parameter dictionaries.

        Each swept parameter is drawn from its own independent, seed-derived generator, so
        adding or removing one parameter does not change the draws of the others. Integer
        parameters are rounded to ``int``; everything else is returned as authored.
        """
        names = list(manifest.params)
        varying = [n for n in names if n in self.distributions]
        seeds = dict(
            zip(varying, np.random.SeedSequence(self.seed).spawn(len(varying)), strict=True)
        )

        rows: list[dict[str, Any]] = [{} for _ in range(self.n_samples)]
        for name in names:
            spec = manifest.params[name]
            if name in self.distributions:
                rng = np.random.default_rng(seeds[name])
                draws = self.distributions[name].sample(rng, self.n_samples)
                values: list[Any] = _coerce_numeric(draws, spec)
            else:
                values = [self.fixed[name]] * self.n_samples
            for row, value in zip(rows, values, strict=True):
                row[name] = value
        return rows


def build_sweep(
    manifest: ModelManifest,
    *,
    distributions: dict[str, Distribution] | None = None,
    fixed: dict[str, Any] | None = None,
    n_samples: int = 1,
    seed: int | None = None,
) -> SweepConfig:
    """Validate requested assignments against ``manifest`` and normalise them.

    :param distributions: distribution per numeric parameter to vary or pin. Keys must be
        numeric, sweepable manifest parameters.
    :param fixed: a single concrete value per parameter. A numeric value here is normalised
        into a :class:`~almo_sweep.contracts.distributions.Constant`; a non-numeric value is
        kept as-is. A parameter may not appear in both ``distributions`` and ``fixed``.
    :param n_samples: number of samples to draw (>= 1).
    :param seed: seed for reproducible sampling (``None`` = nondeterministic).
    :raises SweepError: on any inconsistency with the manifest.
    """
    dists = dict(distributions or {})
    fixes = dict(fixed or {})
    if n_samples < 1:
        raise SweepError(f"n_samples must be >= 1, got {n_samples}")

    unknown = (set(dists) | set(fixes)) - set(manifest.params)
    if unknown:
        raise SweepError(f"unknown parameter(s): {sorted(unknown)}")
    both = set(dists) & set(fixes)
    if both:
        raise SweepError(
            f"parameter(s) assigned both a distribution and a fixed value: {sorted(both)}"
        )

    out_dists: dict[str, Distribution] = {}
    out_fixed: dict[str, Any] = {}
    for name, spec in manifest.params.items():
        if name in dists:
            out_dists[name] = _validate_distribution(name, spec, dists[name])
        elif name in fixes:
            _place_fixed(name, spec, fixes[name], out_dists, out_fixed)
        else:
            _place_default(spec, out_dists, out_fixed)

    return SweepConfig(
        model_name=manifest.name,
        model_version=manifest.version,
        distributions=out_dists,
        fixed=out_fixed,
        n_samples=n_samples,
        seed=seed,
    )


# ---------------------------------------------------------------------------
# Validation / normalisation helpers
# ---------------------------------------------------------------------------
def _validate_distribution(name: str, spec: ParamSpec, dist: Distribution) -> Distribution:
    if not spec.is_numeric:
        raise SweepError(f"{name}: only numeric parameters can take a distribution")
    if not spec.sweepable:
        raise SweepError(f"{name}: parameter is not marked sweepable in the manifest")
    if isinstance(dist, Normal):
        return _fill_normal_bounds(name, spec, dist)
    if isinstance(dist, Constant):
        _check_in_bounds(name, spec, dist.value)
        return dist
    raise SweepError(f"{name}: unsupported distribution {type(dist).__name__!r}")


def _fill_normal_bounds(name: str, spec: ParamSpec, dist: Normal) -> Normal:
    """Default a Normal's truncation bounds to the parameter's manifest bounds."""
    lo = dist.min if dist.min is not None else spec.min
    hi = dist.max if dist.max is not None else spec.max
    # Any explicit bound must not fall outside the manifest's own bounds.
    if spec.min is not None and lo is not None and lo < spec.min:
        raise SweepError(f"{name}: distribution min ({lo}) is below the manifest min ({spec.min})")
    if spec.max is not None and hi is not None and hi > spec.max:
        raise SweepError(f"{name}: distribution max ({hi}) is above the manifest max ({spec.max})")
    return Normal(mean=dist.mean, std=dist.std, min=lo, max=hi)


def _place_fixed(
    name: str,
    spec: ParamSpec,
    value: Any,
    out_dists: dict[str, Distribution],
    out_fixed: dict[str, Any],
) -> None:
    _check_fixed_value(name, spec, value)
    if spec.is_numeric:
        out_dists[name] = Constant(float(value))
    else:
        out_fixed[name] = value


def _place_default(
    spec: ParamSpec,
    out_dists: dict[str, Distribution],
    out_fixed: dict[str, Any],
) -> None:
    if spec.is_numeric:
        out_dists[spec.name] = Constant(float(spec.default))
    else:
        out_fixed[spec.name] = spec.default


def _check_fixed_value(name: str, spec: ParamSpec, value: Any) -> None:
    if spec.type is ParamType.CHOICE:
        if value not in spec.choices:
            raise SweepError(f"{name}: {value!r} is not one of {list(spec.choices)}")
    elif spec.type is ParamType.BOOL:
        if not isinstance(value, bool):
            raise SweepError(f"{name}: expected a boolean, got {value!r}")
    else:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise SweepError(f"{name}: expected a number, got {value!r}")
        _check_in_bounds(name, spec, float(value))


def _check_in_bounds(name: str, spec: ParamSpec, value: float) -> None:
    if spec.min is not None and value < spec.min:
        raise SweepError(f"{name}: value {value} is below the manifest min ({spec.min})")
    if spec.max is not None and value > spec.max:
        raise SweepError(f"{name}: value {value} is above the manifest max ({spec.max})")


def _coerce_numeric(draws: Any, spec: ParamSpec) -> list[Any]:
    if spec.type is ParamType.INT:
        return [round(float(x)) for x in draws]
    return [float(x) for x in draws]


__all__ = ["SweepConfig", "SweepError", "build_sweep"]
