# ALMO Sweep — implementation roadmap

The single source of truth for *what we build, in what order*. Each phase is a shippable
increment. `[x]` done · `[~]` in progress · `[ ]` to do. We do not skip ahead: a later
phase starts only when the one before it is green (tests passing under every interpreter).

Two code bases move together:
- **engine** = `almo-sweep` (pure Python, tested on CPython + inside QGIS's Python).
- **plugin** = `qgis_sweep` / `almo_sweep_qgis` in `QGIS_Simulation_GUI` (tested under QGIS).
- **dampm** = reference model, implemented by colleagues against `docs/manifest-spec.md`.

---

## Phase 0 — Foundations  ✅

- [x] Contracts: manifest (`model.toml`)
- [x] Contracts: distributions + sweep config (constant/normal, seeded sampling)
- [x] Contracts: run-spec (`runspec.json`), result (`result.json`), process (spawn/progress/exit)
- [x] Manifest specification for model authors (`docs/manifest-spec.md`)
- [x] Plugin shell: loadable on QGIS 4.2 / Qt 6, dockable panel, five-section navigator
- [x] Tooling: ruff + mypy (strict, engine) + pytest, pinned via pre-commit, CI

## Phase 1 — Deterministic single run, end-to-end  ✅

Prove the whole pipeline with the manifest's **default** parameters (no parameter editing yet).

- [x] [plugin] Inputs page — one native layer-picker per declared input
- [x] [engine] Run-spec resolver — manifest + input paths + default params → validated `RunSpec`
- [x] [engine] Executor — spawn the model process, stream progress, enforce timeout, read result
- [x] [engine] Toy reference model — exercises the process contract in tests (stands in for dampm)
- [x] [plugin] Run page — run name, output folder, launch (defaults), progress, load result layers
- [x] [both] End-to-end test — toy model spawned via RunTask → RunResult → output raster loaded
      (engine executor tests + plugin `test_run_page`, verified live on QGIS 4.2.2 and 3.44)

## Phase 2 — Parameter UI from manifest  ✅

- [x] [plugin] Parameters page — a control per parameter (float/int spinboxes with units &
      bounds, choice combos, bool checkboxes), seeded with defaults, written to `StudyState`
- [x] [plugin] Output selection — Run page group of per-output checkboxes; non-optional
      outputs always stored, optional ones toggleable; selection passed to `resolve_runspec`

## Phase 3 — Probabilistic sweeps  ☐

- [ ] [plugin] Study page — assign each swept parameter a constant/normal distribution, set
      sample count and seed
- [ ] [engine] Scheduler / process pool — run many samples, with cancellation and retries
- [ ] [engine] Run index + provenance — manifest hash, input checksums, tool versions per run

## Phase 4 — Results inspection  ☐

- [ ] [plugin] Results page — browse the run index, load/compare output rasters, aggregate
      statistics across a sweep

---

## Working agreement

- Every change lands on `dev`, green under all relevant interpreters, before the next step.
- The engine never imports `qgis`; all QGIS code lives in the plugin.
- New engine behaviour ships with tests; new QGIS API use is verified against a live QGIS
  first (per the pyqgis workflow) and covered by a headless smoke test.
