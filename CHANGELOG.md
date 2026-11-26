# Changelog

All notable changes to slab-sweep are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.1.0] - 2026-11-26

The first public release.

### Added

- Contracts: the model manifest (`model.toml`, schema 1.2), the run spec (`runspec.json`), the
  result (`result.json`) and the process protocol (spawn, progress lines, exit, cooperative
  cancel through `SLAB_SWEEP_CANCEL_FILE`), specified in `docs/manifest-spec.md`.
- Manifest presentation metadata (labels, groups, `visible_when`) and host runtime settings with
  defaults; schema 1.2 adds the `{model_dir}` and `{exe}` placeholders and
  `[invocation].pythonpath`, so a model package finds its own binary and adapter.
- Studies: distributions (constant, uniform, normal) and selection strategies (grid, Latin
  hypercube, Monte Carlo), with a post-processing weight per sample.
- Execution: `resolve_runspec`, `run_one` (subprocess, progress, timeout, cancellation) and
  `run_sweep` (parallel runs, retries, shared cancellation, a `runs.json` run index written as
  runs finish).
- Provenance for every run (`provenance.json`): versions and git state of the engine, the model
  adapter and binary and the client, the manifest digest and input digests.
- Releases from a tag: GitHub release with wheel, sdist and checksums; optional PyPI publishing;
  slab-qgis is notified to bundle the new release.

### Fixed

- A relative run folder or input path no longer breaks a run: `run_one` makes them absolute
  before starting the model in the run folder.
