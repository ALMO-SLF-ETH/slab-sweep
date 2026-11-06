"""Tests for the sweep scheduler: concurrency, retries, cancellation and the run index."""

from __future__ import annotations

import json
import sys
import threading
import time
from pathlib import Path

import pytest

from almo_sweep.contracts import ModelManifest, RunSpec, parse_manifest
from almo_sweep.run import (
    RunIndex,
    SweepRun,
    default_index,
    default_max_workers,
    run_sweep,
)
from almo_sweep.run.run_index import RUN_INDEX_FILENAME

TOY_MODEL = Path(__file__).parent / "fixtures" / "toy_model.py"


def _toy_manifest(timeout_s: float | None = None) -> ModelManifest:
    invocation: dict[str, object] = {
        "command": [sys.executable, str(TOY_MODEL)],
        "args_template": ["--runspec", "{runspec}"],
    }
    if timeout_s is not None:
        invocation["timeout_s"] = timeout_s
    return parse_manifest({"model": {"name": "toy", "version": "0.1.0"}, "invocation": invocation})


def _run(
    out_dir: Path, run_id: str, *, mode: str = "success", weight: float = 1.0, **params: object
) -> SweepRun:
    return SweepRun(
        runspec=RunSpec(
            run_id=run_id,
            model_name="toy",
            params={"mode": mode, **params},
            inputs={},
            output_dir=str(out_dir / run_id),
            store_outputs=("alpha",),
        ),
        weight=weight,
    )


def test_runs_every_sample_and_reports_counts(tmp_path: Path) -> None:
    runs = [_run(tmp_path, f"run-{i}") for i in range(4)]
    report = run_sweep(_toy_manifest(), runs)
    assert report.ok
    assert len(report.results) == 4
    assert report.n_succeeded == 4 and report.n_failed == 0
    for i in range(4):
        assert (tmp_path / f"run-{i}" / "result.json").exists()


def test_results_in_submission_order(tmp_path: Path) -> None:
    runs = [_run(tmp_path, f"run-{i}") for i in range(5)]
    report = run_sweep(_toy_manifest(), runs, max_workers=4)
    assert [r.run_id for r in report.results] == [f"run-{i}" for i in range(5)]


def test_parallel_runs_actually_overlap(tmp_path: Path) -> None:
    # Three runs that each nap 0.5s, run with 3 workers, must finish in well under the 1.5s serial
    # sum -- proving they ran concurrently. Generous margin keeps it robust on a noisy CI.
    runs = [_run(tmp_path, f"run-{i}", mode="nap", seconds=0.5) for i in range(3)]
    t0 = time.monotonic()
    report = run_sweep(_toy_manifest(), runs, max_workers=3)
    elapsed = time.monotonic() - t0
    assert report.ok and report.n_succeeded == 3
    assert elapsed < 1.3, f"runs did not overlap (took {elapsed:.2f}s, serial would be ~1.5s+)"


def test_failed_run_is_retried_until_success(tmp_path: Path) -> None:
    # Flaky model fails twice then succeeds; with 2 retries (3 attempts) it must end green.
    runs = [_run(tmp_path, "flaky", mode="flaky", fail_times=2)]
    report = run_sweep(_toy_manifest(), runs, retries=2)
    assert report.ok
    index_entry_attempts = 3
    assert (tmp_path / "flaky" / "result.json").exists()
    # the on-disk attempt counter proves it took 3 tries
    assert (tmp_path / "flaky" / "attempts.txt").read_text() == str(index_entry_attempts)


def test_retries_exhausted_reports_failure(tmp_path: Path) -> None:
    runs = [_run(tmp_path, "flaky", mode="flaky", fail_times=5)]
    report = run_sweep(_toy_manifest(), runs, retries=1)  # 2 attempts < 5 needed
    assert not report.ok
    assert report.n_failed == 1


def test_cancel_short_circuits_queued_runs(tmp_path: Path) -> None:
    # Cancel is set before running; every run must short-circuit without spawning (no runspec on
    # disk), and the report is marked cancelled.
    runs = [_run(tmp_path, f"run-{i}", mode="sleep") for i in range(3)]
    report = run_sweep(_toy_manifest(), runs, cancel_check=lambda: True)
    assert report.cancelled
    assert report.n_succeeded == 0
    for i in range(3):
        assert not (tmp_path / f"run-{i}" / "runspec.json").exists()


def test_cancelled_run_is_not_retried(tmp_path: Path) -> None:
    runs = [_run(tmp_path, "flaky", mode="flaky", fail_times=5)]
    report = run_sweep(_toy_manifest(), runs, retries=5, cancel_check=lambda: True)
    assert report.cancelled
    # cancelled before spawning, so the flaky counter never advanced
    assert not (tmp_path / "flaky" / "attempts.txt").exists()


def test_writes_run_index(tmp_path: Path) -> None:
    runs = [_run(tmp_path, f"run-{i}", weight=float(i)) for i in range(3)]
    index = default_index(tmp_path, _toy_manifest(), scheme="grid", count=3)
    run_sweep(_toy_manifest(), runs, index=index)

    doc = json.loads((tmp_path / RUN_INDEX_FILENAME).read_text(encoding="utf-8"))
    assert doc["manifest"]["name"] == "toy"
    assert doc["study"]["scheme"] == "grid"
    assert len(doc["runs"]) == 3
    by_id = {r["run_id"]: r for r in doc["runs"]}
    assert by_id["run-2"]["weight"] == 2.0
    assert all(r["status"] == "success" for r in doc["runs"])


def test_index_is_written_incrementally(tmp_path: Path) -> None:
    # Each finished run should be in the index immediately, so an interrupted sweep still leaves a
    # valid partial index. We observe this via the on_finished hook.
    index = RunIndex(path=tmp_path / RUN_INDEX_FILENAME)
    seen_counts: list[int] = []

    def after(_i: int, _result: object) -> None:
        doc = json.loads((tmp_path / RUN_INDEX_FILENAME).read_text(encoding="utf-8"))
        seen_counts.append(len(doc["runs"]))

    runs = [_run(tmp_path, f"run-{i}") for i in range(3)]
    run_sweep(_toy_manifest(), runs, index=index, on_finished=after)
    assert seen_counts == [1, 2, 3]


def test_progress_and_lifecycle_callbacks_fire(tmp_path: Path) -> None:
    started: list[int] = []
    finished: list[int] = []
    progress: list[tuple[int, float]] = []
    lock = threading.Lock()

    runs = [_run(tmp_path, f"run-{i}") for i in range(3)]
    run_sweep(
        _toy_manifest(),
        runs,
        max_workers=2,
        on_started=lambda i, _r: _append(lock, started, i),
        on_finished=lambda i, _r: _append(lock, finished, i),
        on_progress=lambda i, ev: _append(lock, progress, (i, ev.progress)),
    )
    assert sorted(started) == [0, 1, 2]
    assert sorted(finished) == [0, 1, 2]
    assert progress  # the toy model emits progress, forwarded per run


def test_default_max_workers_is_sane() -> None:
    assert default_max_workers() >= 1


def test_default_max_workers_prefers_physical_cores(monkeypatch: pytest.MonkeyPatch) -> None:
    from almo_sweep.run import scheduler as sched

    # Physical-core count wins over the (higher) logical count, so hyper-threaded parts aren't
    # oversubscribed.
    monkeypatch.setattr(sched, "_physical_cpu_count", lambda: 10)
    monkeypatch.setattr(sched.os, "cpu_count", lambda: 28)
    assert default_max_workers() == 10

    # When physical detection is unavailable (no psutil), fall back to the logical count.
    monkeypatch.setattr(sched, "_physical_cpu_count", lambda: None)
    assert default_max_workers() == 28


def test_thread_capped_env_divides_cpu_among_workers(monkeypatch: pytest.MonkeyPatch) -> None:
    from almo_sweep.run import scheduler as sched

    # 8 logical CPUs, 4 parallel runs -> each run limited to 2 threads.
    monkeypatch.setattr(sched.os, "cpu_count", lambda: 8)
    env = sched._thread_capped_env({}, max_workers=4)
    assert env is not None and env["OMP_NUM_THREADS"] == "2"

    # Serial runs are left untouched, and an explicit OMP_NUM_THREADS is respected.
    assert sched._thread_capped_env(None, max_workers=1) is None
    explicit = {"OMP_NUM_THREADS": "3"}
    assert sched._thread_capped_env(explicit, max_workers=4) is explicit


def _append(lock: threading.Lock, target: list, value: object) -> None:
    with lock:
        target.append(value)
