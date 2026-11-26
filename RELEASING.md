# Releasing slab-sweep

A release is a tag `vX.Y.Z` on `main`. The [release workflow](.github/workflows/release.yml) then
builds and checks the wheel and sdist, publishes a GitHub release, optionally publishes to PyPI,
and tells [slab-qgis](https://github.com/ALMO-SLF-ETH/slab-qgis), which bundles the engine, to
update its pin:

```
tag vX.Y.Z ──> build + checks ──> GitHub release (wheel, sdist, SHA256SUMS)
                              ├─> PyPI (when enabled)
                              └─> slab-qgis: pull request "Bundle slab-sweep X.Y.Z" into its dev
```

## One-time setup

- **`SLAB_QGIS_DISPATCH_TOKEN`** (secret in this repository): a token with *Contents* write access
  to slab-qgis. Without it, slab-qgis's daily bump run picks the release up within a day.
- **PyPI** (optional): add a trusted publisher for this repository on PyPI (workflow
  `release.yml`, environment `pypi`), create the `pypi` environment under *Settings ▸
  Environments*, and set the repository variable `PUBLISH_TO_PYPI` to `true`. Until then, releases
  are on GitHub only.

## 1. Prepare the release on `dev`

1. Set the version in **both** [`pyproject.toml`](pyproject.toml) (`version = "X.Y.Z"`) and
   [`src/slab_sweep/__init__.py`](src/slab_sweep/__init__.py) (`__version__ = "X.Y.Z"`); CI checks
   that they agree.
2. Move the *Unreleased* entries in [`CHANGELOG.md`](CHANGELOG.md) under `## [X.Y.Z] - YYYY-MM-DD`.
   If a contract changed (manifest, run spec, result, process), say so, and check that
   [`docs/manifest-spec.md`](docs/manifest-spec.md) describes it.
3. Open a pull request from `dev` into `main` and merge it with **Create a merge commit** when CI
   is green.

## 2. Tag

```bash
git fetch origin
git tag -a vX.Y.Z -m "slab-sweep X.Y.Z" origin/main
git push origin vX.Y.Z
```

The workflow checks that the tag matches the version, builds the wheel and sdist (`twine check`,
an import test of the wheel), and creates the GitHub release with both and a `SHA256SUMS` file.
If a job fails, fix the cause on `dev`, merge into `main` again, delete the tag
(`git push origin :vX.Y.Z`) and tag again.

## 3. Follow up in slab-qgis

A pull request "Bundle slab-sweep X.Y.Z" appears in slab-qgis within minutes (with the dispatch
token) or by the next day. Its CI tests the plugin with the new engine; merge it, and release the
plugin when ready (see slab-qgis's
[RELEASING.md](https://github.com/ALMO-SLF-ETH/slab-qgis/blob/main/RELEASING.md)).

Models declare the manifest schema they use; a model using a newer schema needs an engine (and a
plugin bundling it) that supports it, so release the engine before such a model.
