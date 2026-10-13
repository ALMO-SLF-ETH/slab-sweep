# Model manifest specification (`model.toml`)

**Audience:** authors of simulation models (dampm and future models) that plug into the
ALMO sweep engine and its QGIS front-end.
**Status:** manifest schema **1.1** — enforced by
[`almo_sweep.contracts.manifest`](../src/almo_sweep/contracts/manifest.py). 1.1 adds the
optional presentation vocabulary (`label`, `[[groups]]`, `visible_when`); manifests that
declare `schema = "1.0"` remain valid because every new field is optional.

A **manifest** is a single TOML file (conventionally `model.toml`) that a model publishes to
describe itself. It is the *only* thing the engine and the QGIS UI need in order to build a
parameter form, wire up spatial inputs and outputs, and invoke your model. If your manifest
is correct, your model appears in the UI with the right controls and runs — no UI code, no
engine code, is model-specific.

The manifest declares the **parameter space** (what your model accepts). It does **not**
declare distributions, sample counts, file paths, or output folders — those are chosen by
the user at study time and delivered to your model in a `runspec.json` (see
[Runtime contract](#runtime-contract-what-your-executable-must-do) below).

---

## 1. Structure at a glance

```toml
[model]                     # identity (required)
name = "dampm"
version = "0.1.0"
schema = "1.0"
description = "Depth-averaged mass-movement runout model."

[invocation]                # how the engine spawns your model (required)
command = ["python", "-m", "dampm.run"]
args_template = ["--runspec", "{runspec}"]
timeout_s = 3600

[inputs.dem]                # one table per spatial input (zero or more)
kind = "raster"
required = true
band = 1
description = "Digital elevation model (metres)."

[[groups]]                  # ordered UI sections (zero or more)
id = "physical"
label = "Physical parameters"

[params.friction_angle]     # one table per scalar parameter (zero or more)
type = "float"
label = "Basal friction angle"   # human name; the table key stays the code identifier
group = "physical"               # lays this param out under the "physical" group
unit = "deg"
default = 30.0
min = 0.0
max = 60.0
sweepable = true
description = "Bulk basal friction angle."

[outputs.max_depth]         # one table per produced artefact (zero or more)
kind = "raster"
format = "GTiff"
description = "Maximum flow depth over the simulation."
```

Tables use the dotted-key form `[inputs.<name>]`, `[params.<name>]`, `[outputs.<name>]`. The
`<name>` is the key your model receives in the run-spec (e.g. `inputs["dem"]`,
`params["friction_angle"]`), so choose stable, code-friendly names.

---

## 2. `[model]` — identity (required)

| Field | Type | Required | Default | Notes |
|---|---|---|---|---|
| `name` | string | **yes** | — | Non-empty. The model's stable identifier. |
| `version` | string | **yes** | — | Non-empty. Your model's version; recorded in every run's provenance. |
| `schema` | string | no | `"1.0"` | Manifest-format version. The **major** must match the engine's (currently `1`) or the manifest is rejected. |
| `description` | string | no | `""` | One-line human description, shown in the UI. |

---

## 3. `[invocation]` — how the engine runs your model (required)

The engine spawns your model as a **subprocess**. `command` is the base argv;
`args_template` is appended to it. Both may contain `{placeholder}` tokens that the engine
substitutes with concrete values at launch.

| Field | Type | Required | Default | Notes |
|---|---|---|---|---|
| `command` | list of strings | **yes** | — | At least one element. The executable and its fixed arguments. |
| `args_template` | list of strings | no | `[]` | Appended to `command`; the place for `{placeholder}` tokens. |
| `timeout_s` | number | no | none | Positive. Per-run wall-clock limit; the engine kills a run that exceeds it. |

### Placeholders

| Token | Substituted with |
|---|---|
| `{runspec}` | Absolute path to this run's `runspec.json`. **Guaranteed** — this is the canonical contract. |

**Recommended pattern:** take only `--runspec {runspec}` and read *everything else*
(parameters, input paths, output directory, seed) from that file. This keeps your invocation
stable no matter how many inputs or parameters you add later. An unresolved placeholder (a
token with no known substitution) is a launch error.

---

## 4. `[inputs.<name>]` — spatial data your model consumes

One table per input. In the run-spec, each `<name>` maps to an absolute file path.

| Field | Type | Required | Default | Applies to | Notes |
|---|---|---|---|---|---|
| `kind` | string | **yes** | — | all | One of `"raster"`, `"vector"`. |
| `required` | bool | no | `true` | all | If `false`, the user may leave it unset (the key is then absent from the run-spec). |
| `label` | string | no | name | all | Human-readable name shown in the UI; defaults to the table key. |
| `description` | string | no | `""` | all | Shown in the UI. |
| `band` | int | no | none | raster | 1-based band index your model reads; positive. Omit to let the model decide. |
| `geometry` | string | no | none | vector | Required geometry type, e.g. `"polygon"`. Omit to accept any. |
| `group` | string | no | none | all | A declared `[[groups]]` id to lay this input out under, alongside params (see §6). |
| `visible_when` | array of tables | no | `[]` | all | Conditions gating the input's display on param values — same form as for params (see §6). A client renders inputs and params together, so an input (e.g. a release-zone layer) can appear only when a param selects it. |

*(Example: the release-zone polygons.)*

```toml
[inputs.release_zones]
kind = "vector"
geometry = "polygon"
required = true
description = "One or more independent release-zone polygons."
```

---

## 5. `[params.<name>]` — scalar knobs

One table per parameter. These become the controls in the UI's parameter form; numeric ones
flagged `sweepable` can additionally be given a probability distribution in a study.

| Field | Type | Required | Default | Notes |
|---|---|---|---|---|
| `type` | string | **yes** | — | One of `"float"`, `"int"`, `"bool"`, `"choice"`. |
| `default` | matches `type` | **yes** | — | The value used when the user does not override it. Must satisfy every rule below. |
| `label` | string | no | name | Human-readable name shown as the control's caption and the doc heading; defaults to the table key. |
| `description` | string | no | `""` | Help text, shown as a tooltip and in the docs. |
| `unit` | string | no | none | Display unit, e.g. `"deg"`, `"m"`, `"kg/m3"`. |
| `min` | number | no | none | float/int only. Lower bound (inclusive). |
| `max` | number | no | none | float/int only. Upper bound (inclusive). |
| `choices` | list | **for `choice`** | — | The allowed values; non-empty. |
| `sweepable` | bool | no | `false` | float/int only. Marks the parameter eligible for a distribution in a probabilistic study. |
| `group` | string | no | none | The `id` of a declared `[[groups]]` section this param is laid out under (see §6). |
| `visible_when` | array of tables | no | `[]` | Conditions that gate this param's display on other params' values (see §6). |

### Rules (all enforced; a violation rejects the manifest)

- **float / int**: `default` must be a real number (a bare `true`/`false` is *not* accepted
  as a number). If `min` and `max` are both given, `min ≤ max`. `default` must lie within any
  given bound.
- **choice**: `choices` is required and non-empty; `default` must be one of `choices`; a
  choice parameter **cannot** be `sweepable`.
- **bool**: `default` must be a real boolean; a bool parameter **cannot** be `sweepable`.
- **sweepable** is meaningful only for `float`/`int`.

### What `sweepable` enables

In a probabilistic study the user may assign a swept parameter a **constant** or **normal**
distribution. A normal distribution is automatically truncated to the parameter's `[min,
max]` bounds, so your model always receives values inside the range you declared. Parameters
that are not swept are held at a single value for every run.

```toml
[params.integrator]
type = "choice"
default = "rk4"
choices = ["euler", "rk4"]
description = "Time-integration scheme."     # non-numeric -> never swept
```

---

## 6. Presentation: labels, groups, and conditional visibility

The engine can run a model from `name`/`type`/`default` alone, but a good UI (and good
generated documentation) needs more: a readable name for each knob, a way to arrange knobs
into sections, and a way to hide knobs that do not apply to the current choices. These three
things are declared in the manifest and live entirely in presentation — they never change
the values your model receives.

`label` applies to inputs, params, and outputs; `group` and `visible_when` apply to both
**params and inputs** — a client lays them out together, so a spatial input (say a
release-zone layer) can sit in the same group as the param it relates to and appear only when
that param selects it. `visible_when` on an input is evaluated against the current *param*
values, exactly as for a param.

### Labels

Every `[inputs.*]`, `[params.*]`, and `[outputs.*]` table may carry a `label` — the
human-readable name shown in the UI and used as the heading in generated docs. The table key
(e.g. `friction_angle`) stays the stable code identifier your model receives; the `label`
(e.g. `"Basal friction angle"`) is free to read well and change without breaking anything.
When `label` is omitted, the table key is used.

### Groups

Declare an **ordered** list of sections with `[[groups]]` (a TOML array of tables), then point
each parameter at one with `group = "<id>"`:

```toml
[[groups]]
id = "physical"
label = "Physical parameters"
description = "Material properties and gravity."

[[groups]]
id = "time"
label = "Time stepping"

[params.density]
type = "float"
group = "physical"
default = 2000.0

[params.dt_max]
type = "float"
group = "time"
default = 0.06
```

| `[[groups]]` field | Type | Required | Default | Notes |
|---|---|---|---|---|
| `id` | string | **yes** | — | Non-empty, unique. The value params reference in `group`. |
| `label` | string | no | id | Section heading shown in the UI; defaults to `id`. |
| `description` | string | no | `""` | Optional one-line section description. |

A client renders groups **in declaration order**, and within each group renders its params
**in manifest order**. Every declared group is shown even if empty. A param whose `group` is
unset — or names no declared group — falls into a trailing catch-all section, so nothing is
ever hidden by omission. Referencing an undeclared group id is an error. If you declare no
groups at all, the UI simply lists every param in manifest order, as before.

### Conditional visibility (`visible_when`)

Some parameters only apply when another is set a certain way — a friction coefficient that
belongs to one friction law, a parameter a sampling scheme needs. Gate such a param's display
with one or more `visible_when` clauses (an array of tables). The param is shown **only while
every clause holds** (logical *and*); a clause holds when the named controlling param
currently equals one of the listed values:

```toml
[params.friction_type]
type = "choice"
default = "COULOMB"
choices = ["COULOMB", "VOELLMY", "MUI"]

[params.voellmy_xi]
type = "float"
default = 200.0
# shown only while friction_type == "VOELLMY"
[[params.voellmy_xi.visible_when]]
param = "friction_type"
in = ["VOELLMY"]
```

| Clause field | Type | Required | Notes |
|---|---|---|---|
| `param` | string | **yes** | The controlling param. Must be a declared param, and not this param itself. |
| `in` | array | one of `in`/`equals` | The param is visible while the controlling param's value is in this (non-empty) list. |
| `equals` | scalar | one of `in`/`equals` | Sugar for a single-value `in`. Give `in` **or** `equals`, not both. |

Use several `[[params.X.visible_when]]` blocks to require more than one condition at once.

**Visibility is presentation only.** A hidden parameter keeps its value — its default, or
whatever the user last set — and is still written into the run-spec and passed to your model.
So your model always receives a complete parameter set; `visible_when` only declutters the
form and documents which knobs are relevant together. (A client may use the same conditions
to decide which parameters a probabilistic study is allowed to sweep.)

---

## 7. `[outputs.<name>]` — artefacts your model produces

One table per output. Tells the UI what your model can emit and lets the user choose which
ones to keep.

| Field | Type | Required | Default | Notes |
|---|---|---|---|---|
| `kind` | string | **yes** | — | One of `"raster"`, `"vector"`, `"table"`, `"file"`. |
| `label` | string | no | name | Human-readable name shown in the UI; defaults to the table key. |
| `format` | string | no | none | Driver/format hint, e.g. `"GTiff"`, `"CSV"`. |
| `description` | string | no | `""` | Shown in the UI. |
| `optional` | bool | no | `false` | If `true`, the user may choose **not** to store this output. If `false`, it is always kept. |

The run-spec tells your model which outputs to store (`outputs.store`); write those into the
run's output directory and report their paths in `result.json`.

```toml
[outputs.max_pressure]
kind = "raster"
format = "GTiff"
optional = true
description = "Maximum impact pressure (optional, storage-heavy)."
```

---

## 8. `[runtime.<name>]` — host-specific settings (optional)

Declare machine-specific settings your model needs but that are **not** study parameters —
typically the path to your compiled binary, or a directory of runtime libraries. A client
(the QGIS plugin) prompts the user for each, persists it, and supplies it to your model at
run time as an **environment variable of the same name**. Omit the whole section if your
model needs none.

| Field | Type | Required | Default | Notes |
|---|---|---|---|---|
| `kind` | string | **yes** | — | One of `"file"`, `"directory"`, `"string"` (drives the UI control). |
| `description` | string | no | `""` | Shown in the UI. |
| `required` | bool | no | `true` | If `true`, the client blocks a run until it is set. |

```toml
[runtime.DAMPM_BIN]
kind = "file"
required = true
description = "Path to the compiled dampm executable."

[runtime.DAMPM_DLL_DIR]
kind = "directory"
required = false
description = "Windows only: folder with the model's runtime DLLs. Leave empty elsewhere."
```

Your executable reads these from the environment (e.g. `os.environ["DAMPM_BIN"]`). They are
host configuration, so they are **not** stored in `runspec.json`.

---

## 9. Complete reference example

This is the validated fixture the engine tests against
([`tests/fixtures/dampm.model.toml`](../tests/fixtures/dampm.model.toml)):

```toml
[model]
name = "dampm"
version = "0.1.0"
schema = "1.0"
description = "Depth-averaged mass-movement runout model."

[invocation]
command = ["python", "-m", "dampm.run"]
args_template = ["--runspec", "{runspec}"]
timeout_s = 3600

[[groups]]
id = "physical"
label = "Physical parameters"
description = "Material properties and release geometry."

[[groups]]
id = "numerics"
label = "Numerics"
description = "Time integration."

[inputs.dem]
kind = "raster"
required = true
label = "Terrain (DEM)"
band = 1
description = "Digital elevation model (metres)."

[inputs.release_zones]
kind = "vector"
geometry = "polygon"
required = true
label = "Release zones"
description = "One or more independent release-zone polygons."

[params.friction_angle]
type = "float"
label = "Basal friction angle"
group = "physical"
unit = "deg"
default = 30.0
min = 0.0
max = 60.0
sweepable = true
description = "Bulk basal friction angle."

[params.release_depth]
type = "float"
label = "Release depth"
group = "physical"
unit = "m"
default = 1.5
min = 0.0
max = 50.0
sweepable = true
description = "Uniform initial release depth over the release zones."

[params.density]
type = "float"
label = "Material density"
group = "physical"
unit = "kg/m3"
default = 2000.0
min = 500.0
max = 3000.0
sweepable = true
description = "Bulk material density."

[params.integrator]
type = "choice"
label = "Integrator"
group = "numerics"
default = "rk4"
choices = ["euler", "rk4"]
description = "Time-integration scheme."

[params.rk4_stages]
type = "int"
label = "RK4 stages"
group = "numerics"
default = 4
min = 1
max = 8
description = "Number of Runge-Kutta stages (RK4 integrator only)."
# Shown only when the Runge-Kutta integrator is selected.
[[params.rk4_stages.visible_when]]
param = "integrator"
in = ["rk4"]

[outputs.max_depth]
kind = "raster"
label = "Maximum flow depth"
format = "GTiff"
description = "Maximum flow depth over the simulation."

[outputs.max_pressure]
kind = "raster"
format = "GTiff"
optional = true
description = "Maximum impact pressure (optional, storage-heavy)."

[outputs.summary]
kind = "table"
format = "CSV"
optional = true
description = "Per-run scalar summary statistics."
```

You can validate a manifest before shipping it:

```python
from almo_sweep.contracts import load_manifest
load_manifest("model.toml")   # raises ManifestError with a field-named message if invalid
```

---

## 10. Runtime contract (what your executable must do)

The manifest declares what your model *accepts*; at run time your executable must honour the
**process contract** ([`almo_sweep.contracts.process`](../src/almo_sweep/contracts/process.py),
[`runspec`](../src/almo_sweep/contracts/runspec.py),
[`result`](../src/almo_sweep/contracts/result.py)):

1. **Read** the run-spec at the path given by `{runspec}`. It contains, for this single run:
   `run_id`, `model` (name/version), `params` (concrete values), `inputs` (name → absolute
   path), `outputs.dir` (where to write), `outputs.store` (which outputs to keep), and an
   optional `seed`.
2. **Run** the simulation.
3. **Report progress** (optional) by writing JSON-object lines to **stdout**, each with a
   `progress` field in `[0, 1]` and an optional `message`. Any other stdout line is treated
   as ordinary log output.
4. **Write** each requested output into `outputs.dir`.
5. **Write** `result.json` into `outputs.dir` — on success *and* on failure — recording
   `status`, the produced `outputs` (name → path), any scalar `metrics`, and, on failure, an
   `error`.
6. **Exit** `0` when the run completed (success or a cleanly-reported failure); a non-zero
   exit code means the run failed to complete.

### Python skeleton (the engine ships helpers for all of this)

```python
import sys
from almo_sweep.contracts import RunSpec, RunResult, emit_progress

def main() -> int:
    spec = RunSpec.read(sys.argv[sys.argv.index("--runspec") + 1])
    try:
        dem_path = spec.inputs["dem"]
        friction = spec.params["friction_angle"]

        emit_progress(0.0, "starting")
        # ... run the model, writing outputs into spec.output_dir ...
        emit_progress(1.0, "done")

        out_dir = spec.output_dir
        outputs = {"max_depth": f"{out_dir}/max_depth.tif"}   # only those in spec.store_outputs
        RunResult.success(spec.run_id, outputs, metrics={"max_depth_m": 3.2}).write(
            f"{out_dir}/result.json"
        )
        return 0
    except Exception as exc:  # noqa: BLE001 -- report, don't crash silently
        RunResult.failure(spec.run_id, error=repr(exc)).write(f"{spec.output_dir}/result.json")
        return 1

if __name__ == "__main__":
    raise SystemExit(main())
```

A model written in another language conforms the same way: read the run-spec JSON, emit
`{"progress": …}` lines, write a `result.json` with the documented fields.

---

## 11. Versioning

`schema` is the version of the **manifest format**, independent of your model's `version`.
The engine accepts any manifest whose `schema` **major** matches the version it supports
(currently `1`). Additive, backward-compatible changes bump the minor; breaking changes bump
the major and are rejected by older engines. The current format is **1.1** (1.1 added the
optional `label`, `[[groups]]`/`group`, and `visible_when` presentation vocabulary). Because
those fields are optional, a manifest may safely declare `schema = "1.0"` or `"1.1"`; use
`"1.1"` if you rely on the presentation vocabulary.
