# Contributing to slab-sweep

## Branches and pull requests

- `main` is the released code. It only changes through reviewed pull requests.
- `dev` collects the work in progress. Work on a topic branch off `dev` named `feature/…`,
  `bugfix/…`, `chore/…`, `test/…`, `ci/…` or `docs/…`, and open the pull request against `main`.
  Large changes can be split into **stacked** pull requests; say in each description which PR it
  depends on.
- Merge with **"Create a merge commit"**, not squash or rebase, so commit hashes stay the same on
  `dev`, the topic branches and `main` (the same rule as Slab-Pro and slab-qgis).
- Keep commits focused, with an imperative subject line ("Retry failed runs", not "retried…").
  If a change alters a contract (manifest, run spec, result, process), say so in the commit
  message and the pull request, and update `docs/manifest-spec.md`.
- Note user-visible changes under *Unreleased* in [CHANGELOG.md](CHANGELOG.md).

## The two interpreters

This project deliberately runs on **two separate Python interpreters**. Keeping them
straight avoids most setup confusion.

| | **slab-sweep core** (this repo) | **QGIS plugin** (`slab-qgis`) |
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
conda create -n slab-sweep python=3.12
conda activate slab-sweep
cd path/to/slab-sweep
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

## Using the core from QGIS's Python

The plugin `import`s `slab_sweep` to read manifests and drive runs. That import runs in
**QGIS's** interpreter, not conda, so install the core there once, editable. Use QGIS's own
Python (find it via QGIS ▸ Plugins ▸ Python Console → `import sys; print(sys.executable)`):

```bash
# Windows
"C:/Program Files/QGIS 4.2.2/bin/python-qgis.bat" -m pip install -e path/to/slab-sweep
# macOS  (prefix with sudo if the app bundle isn't writable)
/Applications/QGIS-<version>.app/Contents/MacOS/python -m pip install -e path/to/slab-sweep
# Linux
python3 -m pip install -e path/to/slab-sweep
```

Because the core is standard-library + numpy only (and QGIS already ships numpy), this
install is essentially free — which is exactly why the core avoids heavy dependencies such
as pydantic. The full plugin install (engine + a model adapter + the plugin folder) is in
slab-qgis's [docs/development.md](https://github.com/ALMO-SLF-ETH/slab-qgis/blob/main/docs/development.md).

## Architectural rules

- **The core never imports `qgis`.** It is the model-agnostic engine; all QGIS-specific code
  lives in the plugin. The guard test enforces this.
- **The manifest declares the parameter space; a sweep config declares the study.** Keep
  "what a model accepts" (`model.toml`) separate from "what a study explores" (distributions,
  sample counts).
- **Standard library first.** Add a third-party dependency to the core only when it is
  unavoidable and lightweight, because every core dependency must also be installable into
  QGIS's interpreter.
