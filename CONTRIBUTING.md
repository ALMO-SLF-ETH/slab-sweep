# Contributing to almo-sweep

## The two interpreters

This project deliberately runs on **two separate Python interpreters**. Keeping them
straight avoids most setup confusion.

| | **almo-sweep core** (this repo) | **QGIS plugin** (`qgis_sweep_plugin`) |
|---|---|---|
| Runs on | plain CPython in a conda env | QGIS's *own* bundled Python — `python-qgis-qt6.bat` (Python 3.12 / Qt 6) |
| Needs QGIS? | **No** — must never `import qgis` | Yes, it *is* QGIS |
| How to test | `pytest` in the conda env | headless via that `.bat` + `qgis.testing.start_app` |

A conda env cannot make the standalone QGIS use its Python — QGIS drives its own
interpreter. So the plugin is never "developed in a conda env"; it is exercised through
QGIS's Qt 6 Python. The conda env is purely for the pure-Python core and any CLI/notebook
client.

## Core development environment

Use a **fresh, dedicated conda env** for the core. **Do not reuse an older QGIS 3 / Qt 5
plugin-dev env**, for three reasons:

1. **Wrong Qt generation.** This project targets QGIS 4 / Qt 6; a Qt 5 env mixes generations.
2. **It strengthens the core's key invariant.** The core must never import `qgis`. If the
   env has no qgis/PyQt installed at all, an accidental import fails loudly instead of
   silently "working." A clean env is a free guardrail (see `tests/test_no_qgis_import.py`).
3. **Reproducibility / CI parity.** A minimal env matches the GitHub Actions matrix, so
   "passes locally" means "passes in CI."

Pin to **Python 3.12** to match QGIS's Qt 6 interpreter (CI still checks 3.11 as the floor):

```bash
conda create -n almo-sweep python=3.12
conda activate almo-sweep
cd path/to/almo-sweep
python -m pip install -e ".[dev]"
pre-commit install
```

Keep this env **qgis-free** on purpose — `numpy` comes in as a core dependency, nothing else.

## Quality gates

Every change must pass all of these before it lands (CI enforces them on 3.11 and 3.12):

```bash
ruff check .            # lint
ruff format --check .   # formatting
mypy                    # strict type check of the core
pytest                  # test suite (+ --cov in CI)
```

`pre-commit install` runs ruff and mypy automatically on every commit.

## Using the core from QGIS's Python (for later, when the plugin exists)

The plugin will `import almo_sweep` to read manifests and build its parameter UI. That
import runs in **QGIS's** interpreter, not conda, so install the core there once, editable:

```bash
& "C:/Program Files/QGISQT6 3.44.4/bin/python-qgis-qt6.bat" -m pip install -e "path/to/almo-sweep"
```

Because the core is standard-library + numpy only (and QGIS already ships numpy), this
install is essentially free — which is exactly why the core avoids heavy dependencies such
as pydantic.

## Architectural rules

- **The core never imports `qgis`.** It is the model-agnostic engine; all QGIS-specific code
  lives in the plugin. The guard test enforces this.
- **The manifest declares the parameter space; a sweep config declares the study.** Keep
  "what a model accepts" (`model.toml`) separate from "what a study explores" (distributions,
  sample counts).
- **Standard library first.** Add a third-party dependency to the core only when it is
  unavoidable and lightweight, because every core dependency must also be installable into
  QGIS's interpreter.
