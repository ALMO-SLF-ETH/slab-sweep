# almo-sweep

Headless, **manifest-driven** orchestration core for mass-movement simulation studies.

`almo-sweep` is a pure-Python library (no GUI, **no `qgis` import**) that turns a
declarative model **manifest** (`model.toml`) plus a user-authored **sweep config** into
concrete, reproducible **run specs**, executes them as isolated subprocesses, and collects
the results with full provenance.

It is one component of the ALMO simulation stack:

```
 almo-sweep (this repo)     the engine: manifests, sampling, scheduling, execution, collection
 qgis_sweep_plugin          a thin QGIS 4 / Qt 6 client that drives almo-sweep from the map canvas
 dampm                      a reference model that ships a manifest and obeys the process contract
```

The core deliberately depends only on the **Python standard library** plus **numpy**, so it
can be imported inside QGIS's own Python interpreter without extra installation friction.

## Status

The contract layer and single-run execution are implemented and tested; probabilistic
sweeps are next (see [docs/roadmap.md](docs/roadmap.md)).

**Contracts** (`almo_sweep.contracts`):
- **Manifest** (`manifest`) — the `model.toml` a model publishes (identity, invocation,
  inputs, params, outputs, and optional host `runtime` settings). Params carry presentation
  metadata — a human `label`, a `group` for layout, and `visible_when` conditions that let a
  dependent control appear only when it applies — so a client can build a well-structured
  form and generate documentation from the manifest alone.
- **Distributions + selection + sweep** (`distributions`, `selection`, `sweep`) — studies.
  A **distribution** per swept parameter (`Constant`, `Uniform`, `Normal`) is its *weight
  profile* over a range; a **selection strategy** decides which combinations are simulated:
  `MonteCarloSelection` (random draws, count fixed by `n_samples`), `LatinHypercubeSelection`
  (stratified, space-filling), or `GridSelection` (full-factorial, linear/log steps). Each
  sample carries a post-processing **weight** (equal for the samplers; the normalised per-node
  probability for the grid) used to weight *results* — e.g. an extent probability map — never
  to choose which runs happen. A new scheme is one class implementing `SelectionStrategy`.
- **Run-spec** (`runspec`) — `runspec.json`, one resolved job into a model.
- **Result** (`result`) — `result.json`, the outcome a model writes back.
- **Process** (`process`) — the spawn / progress / exit protocol.

**Execution** (`almo_sweep.run`):
- **`resolve_runspec`** — manifest + input paths + parameters → a validated run-spec.
- **`run_one`** — spawn the model process, stream progress, enforce the timeout, collect the
  result, and write a `provenance.json` (below) into the run folder.
- **`run_sweep`** — run the many samples of a study, with configurable concurrency
  (`max_workers`), per-run `retries` and shared cancellation, reporting progress through
  callbacks. It writes a project **run index** (`runs.json`) cataloguing each run's outcome,
  parameters and post-processing weight — incrementally, so an interrupted sweep still leaves a
  valid index. Models run here are single-threaded, so one run per logical CPU is the natural
  setting; `run_sweep` itself defaults to serial, and the QGIS plugin defaults its Parallel-runs
  control to the processor count. For a model that is itself multi-threaded (OpenMP), the opt-in
  `cap_model_threads` divides the CPU among the workers (`OMP_NUM_THREADS = cpu_count //
  max_workers`) so parallel runs do not oversubscribe.

**Provenance** (`almo_sweep.provenance` + `run_one`): each run's `provenance.json` records the
code, model definition and data that produced it — version + git commit/dirty/date for the engine,
the model's Python adapter and (via the model's own report, e.g. dampm's `--version`) its binary;
any client tool (the QGIS plugin) passed as `tool_versions`; the **manifest** (name/version +
SHA-256 of the `model.toml`); and the **input content digests** (SHA-256 + size, surfaced from the
run-spec). `git_info` / `package_provenance` are best-effort and stdlib-only.

### For model authors

See **[docs/manifest-spec.md](docs/manifest-spec.md)** — the authoritative specification for
writing a `model.toml`, plus the runtime contract your executable must honour.

## Development

```bash
python -m pip install -e ".[dev]"
pytest
ruff check .
mypy
```

The core test suite runs on plain CPython (>= 3.11); it never requires a QGIS install.

See [CONTRIBUTING.md](CONTRIBUTING.md) for the two-interpreter setup (a fresh conda env for
the core vs. QGIS's own Qt 6 Python for the plugin), the quality gates, and the
architectural rules.

## License

Copyright © 2026 ALMO. slab-sweep is free software, licensed under the **GNU General Public
License v3.0** (GPL-3.0-only) — see [LICENSE](LICENSE).
