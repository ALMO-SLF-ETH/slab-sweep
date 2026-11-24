"""Resolve a manifest + concrete choices into a validated run-spec."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from slab_sweep.contracts.errors import ContractError
from slab_sweep.contracts.manifest import ModelManifest
from slab_sweep.contracts.runspec import RunSpec


class RunError(ContractError):
    """A run could not be resolved from the given inputs, parameters, or outputs."""


def resolve_runspec(
    manifest: ModelManifest,
    *,
    run_id: str,
    inputs: Mapping[str, str | Path | None],
    params: Mapping[str, Any],
    output_dir: str | Path,
    store_outputs: list[str] | tuple[str, ...] | None = None,
    seed: int | None = None,
    input_crs: Mapping[str, str] | None = None,
) -> RunSpec:
    """Build a :class:`RunSpec` for one run, validating everything against ``manifest``.

    * Every ``required`` input must be provided with a non-empty path; optional inputs may be
      omitted (they are simply absent from the spec).
    * ``params`` may be partial: any parameter the manifest declares but the caller omits is
      filled with the manifest default. Unknown parameters are rejected.
    * ``store_outputs`` defaults to every non-optional output; if given, it must name only
      declared outputs.

    :raises RunError: on any inconsistency with the manifest.
    """
    _reject_unknown("input", inputs, manifest.inputs)
    _reject_unknown("parameter", params, manifest.params)

    missing = [
        name for name, spec in manifest.inputs.items() if spec.required and not inputs.get(name)
    ]
    if missing:
        raise RunError(f"missing required input(s): {sorted(missing)}")

    resolved_inputs = {name: str(path) for name, path in inputs.items() if path}
    # Keep CRS only for inputs that are actually present in this run.
    resolved_crs = {
        name: str(crs) for name, crs in (input_crs or {}).items() if crs and name in resolved_inputs
    }
    resolved_params = {
        name: params.get(name, spec.default) for name, spec in manifest.params.items()
    }

    if store_outputs is None:
        store = tuple(name for name, spec in manifest.outputs.items() if not spec.optional)
    else:
        _reject_unknown("output", dict.fromkeys(store_outputs), manifest.outputs)
        store = tuple(store_outputs)

    return RunSpec(
        run_id=run_id,
        model_name=manifest.name,
        model_version=manifest.version,
        params=resolved_params,
        inputs=resolved_inputs,
        input_crs=resolved_crs,
        output_dir=str(output_dir),
        store_outputs=store,
        seed=seed,
    )


def _reject_unknown(kind: str, given: Mapping[str, Any], declared: Mapping[str, Any]) -> None:
    unknown = set(given) - set(declared)
    if unknown:
        raise RunError(f"unknown {kind}(s): {sorted(unknown)}")
