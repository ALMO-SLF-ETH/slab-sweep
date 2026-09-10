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

Phase 0 — foundations. Frozen so far:

- **Manifest contract** (`almo_sweep.contracts.manifest`): the `model.toml` schema a model
  publishes to declare its identity, invocation, inputs, parameters and outputs.

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
