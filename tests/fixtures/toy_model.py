"""A minimal model that honours the process contract, for executor tests.

Behaviour is driven by the run-spec's ``mode`` parameter:

* ``"success"`` (default) -- emit progress, write the requested outputs and a success result.
* ``"fail"``              -- exit non-zero without writing a result.
* ``"sleep"``             -- sleep far longer than any test timeout (to exercise timeouts).

It uses the engine's own SDK helpers, so running it also verifies the contract round-trips
through a real subprocess.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

from almo_sweep.contracts import RESULT_FILENAME, RunResult, RunSpec, emit_progress


def main() -> int:
    runspec_path = sys.argv[sys.argv.index("--runspec") + 1]
    spec = RunSpec.read(runspec_path)
    mode = spec.params.get("mode", "success")

    out_dir = Path(spec.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    if mode == "sleep":
        time.sleep(30)
        return 0
    if mode == "fail":
        print("toy model failing on purpose")
        return 1

    emit_progress(0.0, "starting")
    outputs: dict[str, str] = {}
    for name in spec.store_outputs or ("out",):
        path = out_dir / f"{name}.txt"
        path.write_text("dummy output", encoding="utf-8")
        outputs[name] = str(path)
    emit_progress(1.0, "done")

    RunResult.success(
        spec.run_id,
        outputs,
        metrics={"n_inputs": float(len(spec.inputs))},
        message="toy run complete",
    ).write(out_dir / RESULT_FILENAME)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
