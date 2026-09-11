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
  inputs, params, outputs, and optional host `runtime` settings).
- **Distributions + sweep** (`distributions`, `sweep`) — studies: constant/normal
  distributions and seeded sampling into concrete parameter sets.
- **Run-spec** (`runspec`) — `runspec.json`, one resolved job into a model.
- **Result** (`result`) — `result.json`, the outcome a model writes back.
- **Process** (`process`) — the spawn / progress / exit protocol.

**Execution** (`almo_sweep.run`):
- **`resolve_runspec`** — manifest + input paths + parameters → a validated run-spec.
- **`run_one`** — spawn the model process, stream progress, enforce the timeout, collect the
  result.

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

MIT — see [LICENSE](LICENSE).
