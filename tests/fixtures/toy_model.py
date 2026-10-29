"""A minimal model that honours the process contract, for executor tests.

Behaviour is driven by the run-spec's ``mode`` parameter:

* ``"success"`` (default) -- emit progress, write the requested outputs and a success result.
* ``"fail"``              -- exit non-zero without writing a result.
* ``"flaky"``             -- fail the first ``fail_times`` attempts (counted on disk), then succeed
                             (to exercise the scheduler's retries).
* ``"sleep"``             -- sleep far longer than any test timeout (to exercise timeouts).
* ``"spawn_sleep"``       -- spawn a grandchild that sleeps then writes a marker, and wait on it
                             (mirrors the real adapter->binary chain, to exercise tree-kill).
* ``"coop_sleep"``        -- sleep, but poll the cancel sentinel and exit cleanly when it appears
                             (a model that honours cooperative cancellation).

It uses the engine's own SDK helpers, so running it also verifies the contract round-trips
through a real subprocess.
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

from almo_sweep.contracts import CANCEL_ENV, RESULT_FILENAME, RunResult, RunSpec, emit_progress


def main() -> int:
    runspec_path = sys.argv[sys.argv.index("--runspec") + 1]
    spec = RunSpec.read(runspec_path)
    mode = spec.params.get("mode", "success")

    out_dir = Path(spec.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    if mode == "sleep":
        time.sleep(30)
        return 0
    if mode == "nap":
        # Sleep a short, param-controlled time then succeed -- lets a test prove that several runs
        # overlapped (wall time well under the serial sum) without a long or flaky sleep.
        time.sleep(float(spec.params.get("seconds", 0.4)))
        outputs = {name: str(out_dir / f"{name}.txt") for name in (spec.store_outputs or ("out",))}
        for path in outputs.values():
            Path(path).write_text("dummy output", encoding="utf-8")
        RunResult.success(spec.run_id, outputs, message="nap complete").write(
            out_dir / RESULT_FILENAME
        )
        return 0
    if mode == "coop_sleep":
        # Honour cooperative cancellation: stop as soon as the engine raises the sentinel.
        sentinel = os.environ.get(CANCEL_ENV)
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            if sentinel and Path(sentinel).exists():
                return 0
            time.sleep(0.05)
        return 0
    if mode == "spawn_sleep":
        # Launch a grandchild that writes a "started" marker at once, sleeps, then writes a "done"
        # marker; wait on it. A cancel that kills only this process (not the whole tree) leaves the
        # grandchild alive to write "done" -- which the tree-kill test asserts must NOT happen. The
        # "started" marker lets the test cancel only once the grandchild is provably running, so the
        # test does not depend on a race between the cancel and the grandchild's own start-up.
        started = out_dir / "grandchild_started.txt"
        done = out_dir / "grandchild_done.txt"
        code = (
            f"open(r'{started}', 'w').close()\n"
            f"import time; time.sleep(3)\n"
            f"open(r'{done}', 'w').close()\n"
        )
        child = subprocess.Popen([sys.executable, "-c", code])
        return child.wait()
    if mode == "fail":
        print("toy model failing on purpose")
        return 1
    if mode == "flaky":
        # Fail the first ``fail_times`` attempts, then succeed. The attempt count is kept in a file
        # in the run dir, which retries reuse -- so this exercises retry-until-success.
        counter = out_dir / "attempts.txt"
        n = (int(counter.read_text(encoding="utf-8")) if counter.exists() else 0) + 1
        counter.write_text(str(n), encoding="utf-8")
        if n <= int(spec.params.get("fail_times", 1)):
            print(f"toy model flaky attempt {n} failing on purpose")
            return 1
        # otherwise fall through to the success path below

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
