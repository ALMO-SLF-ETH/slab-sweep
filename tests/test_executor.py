"""Tests for the executor: it spawns a real subprocess (the toy model)."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from almo_sweep.contracts import ModelManifest, ProgressEvent, RunSpec, RunStatus, parse_manifest
from almo_sweep.run import run_one

TOY_MODEL = Path(__file__).parent / "fixtures" / "toy_model.py"


def _toy_manifest(timeout_s: float | None = None) -> ModelManifest:
    invocation: dict[str, object] = {
        "command": [sys.executable, str(TOY_MODEL)],
        "args_template": ["--runspec", "{runspec}"],
    }
    if timeout_s is not None:
        invocation["timeout_s"] = timeout_s
    return parse_manifest({"model": {"name": "toy", "version": "0.1.0"}, "invocation": invocation})


def _runspec(out_dir: Path, mode: str = "success") -> RunSpec:
    return RunSpec(
        run_id="run-1",
        model_name="toy",
        params={"mode": mode},
        inputs={"a": "/x", "b": "/y"},
        output_dir=str(out_dir),
        store_outputs=("alpha", "beta"),
    )


def test_successful_run(tmp_path: Path) -> None:
    events: list[ProgressEvent] = []
    result = run_one(_toy_manifest(), _runspec(tmp_path / "run"), on_progress=events.append)

    assert result.ok
    assert result.status is RunStatus.SUCCESS
    assert set(result.outputs) == {"alpha", "beta"}
    assert Path(result.outputs["alpha"]).read_text(encoding="utf-8") == "dummy output"
    assert result.metrics["n_inputs"] == 2.0
    assert result.duration_s is None or result.duration_s >= 0  # from the model's own result
    # progress was streamed and ends at completion
    assert events and events[-1] == ProgressEvent(1.0, "done")


def test_runspec_and_result_written_to_run_dir(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    run_one(_toy_manifest(), _runspec(run_dir))
    assert (run_dir / "runspec.json").exists()
    assert (run_dir / "result.json").exists()


def test_failing_model_yields_failure_result(tmp_path: Path) -> None:
    result = run_one(_toy_manifest(), _runspec(tmp_path / "run", mode="fail"))
    assert not result.ok
    assert result.status is RunStatus.FAILED
    assert "without writing result.json" in (result.error or "")
    assert "failing on purpose" in result.message  # captured stdout tail


def test_timeout_yields_failure(tmp_path: Path) -> None:
    result = run_one(_toy_manifest(timeout_s=0.5), _runspec(tmp_path / "run", mode="sleep"))
    assert not result.ok
    assert "timed out" in (result.error or "")
    assert result.duration_s is not None and result.duration_s < 5.0


def test_precancelled_run_does_not_spawn(tmp_path: Path) -> None:
    # Cancelled before it starts (as a queued sweep run would be): run_one must return a cancelled
    # failure without ever spawning the model. duration_s == 0.0 marks the no-spawn short-circuit.
    run_dir = tmp_path / "run"
    result = run_one(_toy_manifest(), _runspec(run_dir, mode="sleep"), cancel_check=lambda: True)
    assert not result.ok
    assert result.status is RunStatus.FAILED
    assert "cancelled" in (result.error or "")
    assert result.duration_s == 0.0
    assert not (run_dir / "runspec.json").exists()  # nothing was launched


def test_cancel_kills_whole_process_tree(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # A model that does NOT honour the sentinel must still be hard-killed as a whole tree after
    # the grace period. The toy spawns a grandchild (like the real adapter->binary chain); after
    # the hard kill the grandchild never writes its "done" marker. Short grace keeps the test fast.
    import time

    from almo_sweep.run import executor

    monkeypatch.setattr(executor, "_CANCEL_GRACE_S", 0.5)

    run_dir = tmp_path / "run"
    started_marker = run_dir / "grandchild_started.txt"
    done_marker = run_dir / "grandchild_done.txt"

    def cancel() -> bool:
        return started_marker.exists()  # cancel only once the grandchild is provably running

    result = run_one(_toy_manifest(), _runspec(run_dir, mode="spawn_sleep"), cancel_check=cancel)
    assert not result.ok and "cancelled" in (result.error or "")
    assert started_marker.exists()  # the grandchild really did start (test is meaningful)

    time.sleep(4.0)  # it would write "done" at ~3s if the tree-kill had missed it
    assert not done_marker.exists(), "grandchild survived the cancel (tree not killed)"


def test_cooperative_cancel_lets_model_stop_before_hard_kill(tmp_path: Path) -> None:
    # A model that polls the sentinel exits cleanly as soon as it is raised, so run_one returns
    # well within the (default, multi-second) grace period rather than waiting it out and
    # hard-killing. The engine must create the sentinel on cancel for this to work.
    import time

    run_dir = tmp_path / "run"
    started = {"at": 0.0}

    def cancel() -> bool:
        if started["at"] == 0.0:
            started["at"] = time.monotonic()  # first (pre-spawn) check: let it start
            return False
        return True

    t0 = time.monotonic()
    result = run_one(_toy_manifest(), _runspec(run_dir, mode="coop_sleep"), cancel_check=cancel)
    elapsed = time.monotonic() - t0
    assert not result.ok and "cancelled" in (result.error or "")
    assert elapsed < 3.0, f"model did not stop cooperatively (took {elapsed:.1f}s)"


def test_uncancelled_run_completes_normally(tmp_path: Path) -> None:
    # A cancel_check that never trips must not interfere with a normal successful run.
    result = run_one(_toy_manifest(), _runspec(tmp_path / "run"), cancel_check=lambda: False)
    assert result.ok


def test_unresolved_placeholder_is_reported(tmp_path: Path) -> None:
    # A manifest whose args reference an unknown token must fail argv construction.
    bad = parse_manifest(
        {
            "model": {"name": "toy", "version": "0"},
            "invocation": {
                "command": [sys.executable, str(TOY_MODEL)],
                "args_template": ["{bogus}"],
            },
        }
    )
    from almo_sweep.contracts import ProcessError

    with pytest.raises(ProcessError, match="unresolved placeholder"):
        run_one(bad, _runspec(tmp_path / "run"))


def test_python_placeholder_resolves_to_interpreter(tmp_path: Path) -> None:
    # A manifest may invoke {python} instead of a hard-coded interpreter.
    manifest = parse_manifest(
        {
            "model": {"name": "toy", "version": "0"},
            "invocation": {
                "command": ["{python}", str(TOY_MODEL)],
                "args_template": ["--runspec", "{runspec}"],
            },
        }
    )
    result = run_one(manifest, _runspec(tmp_path / "run"))
    assert result.ok


def test_substitutions_override_python(tmp_path: Path) -> None:
    manifest = parse_manifest(
        {
            "model": {"name": "toy", "version": "0"},
            "invocation": {
                "command": ["{python}", str(TOY_MODEL)],
                "args_template": ["--runspec", "{runspec}"],
            },
        }
    )
    result = run_one(manifest, _runspec(tmp_path / "run"), substitutions={"python": sys.executable})
    assert result.ok
