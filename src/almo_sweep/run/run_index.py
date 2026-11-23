"""A project-level index of the runs a study produced.

A sweep writes one ``runs.json`` at the project root cataloguing every run: its id, outcome,
folder, the parameter values it used and the post-processing weight of that sample. It is the
hand-off to results inspection -- a client browses the index rather than crawling the folders --
and it records the study-level provenance (the manifest that drove the sweep and the selection
scheme) that no single run folder owns.

The index is written incrementally: each run is appended as it finishes and the file is rewritten,
so a sweep interrupted half-way still leaves a valid index of the runs that did complete. Writes
are serialised by a lock because a sweep runs its runs concurrently.

:meth:`RunIndex.load_or_create` reopens an index that already exists on disk so further runs are
*appended* to it rather than overwriting it. This lets a client that executes runs one at a time
over several launches -- e.g. a GUI user making manual runs into one project folder, each a new
run -- build the same catalogue a sweep writes in one go, so the results can be inspected the same
way. :meth:`RunIndex.next_counter` then gives the next free incremental run number for that project.
"""

from __future__ import annotations

import contextlib
import json
import threading
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

#: Version of the run-index *format*. Bumped when the on-disk JSON shape changes.
RUN_INDEX_SCHEMA_VERSION = "1.0"

#: Default file name for the index at the project root.
RUN_INDEX_FILENAME = "runs.json"


@dataclass
class RunIndex:
    """An incrementally-written catalogue of a study's runs (see the module docstring)."""

    path: Path
    manifest: dict[str, Any] = field(default_factory=dict)
    study: dict[str, Any] = field(default_factory=dict)
    created: str = field(default_factory=lambda: _now())
    _runs: list[dict[str, Any]] = field(default_factory=list, init=False)
    _lock: threading.Lock = field(default_factory=threading.Lock, init=False, repr=False)

    def __post_init__(self) -> None:
        self.path = Path(self.path)

    @classmethod
    def load_or_create(
        cls,
        path: str | Path,
        *,
        manifest: Mapping[str, Any] | None = None,
        study: Mapping[str, Any] | None = None,
    ) -> RunIndex:
        """Open the index at ``path`` if it exists, else create a fresh one.

        When the file is present and valid its existing runs (and its original ``created``, and its
        stored ``manifest``/``study`` unless overridden here) are loaded, so :meth:`add` *appends*
        to the catalogue instead of replacing it. A missing or unreadable file yields a new, empty
        index -- what :class:`RunIndex` would construct -- so this never fails on a first run.
        ``manifest`` / ``study`` seed a new index and fill in any the file omits.
        """
        index = cls(path=Path(path), manifest=dict(manifest or {}), study=dict(study or {}))
        with contextlib.suppress(OSError, json.JSONDecodeError):
            data = json.loads(index.path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                if isinstance(data.get("created"), str):
                    index.created = data["created"]
                if isinstance(data.get("manifest"), dict) and data["manifest"]:
                    index.manifest = dict(data["manifest"])
                if isinstance(data.get("study"), dict) and data["study"]:
                    index.study = dict(data["study"])
                if isinstance(data.get("runs"), list):
                    index._runs = [dict(r) for r in data["runs"] if isinstance(r, dict)]
        return index

    def next_counter(self) -> int:
        """The next free incremental run number: one past the largest ``counter`` already recorded.

        Entries written without a ``counter`` (e.g. a sweep's) are ignored here; the result is 1 for
        an index that has none. Callers that must also avoid reusing an existing run *folder* should
        still check the folder exists (names can be templated and not end in the counter)."""
        best = 0
        for run in self._runs:
            counter = run.get("counter")
            if isinstance(counter, int) and not isinstance(counter, bool):
                best = max(best, counter)
        return best + 1

    def add(self, entry: Mapping[str, Any]) -> None:
        """Append one run's entry and rewrite the index on disk (thread-safe)."""
        with self._lock:
            self._runs.append(dict(entry))
            self._flush()

    def write(self) -> Path:
        """Write the index as it currently stands and return its path."""
        with self._lock:
            self._flush()
        return self.path

    def _flush(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self._document(), indent=2), encoding="utf-8")

    def _document(self) -> dict[str, Any]:
        return {
            "schema": RUN_INDEX_SCHEMA_VERSION,
            "created": self.created,
            "manifest": dict(self.manifest),
            "study": dict(self.study),
            "runs": list(self._runs),
        }


def run_entry(
    *,
    run_id: str,
    status: str,
    output_dir: str,
    params: Mapping[str, Any],
    weight: float = 1.0,
    seed: int | None = None,
    duration_s: float | None = None,
    error: str | None = None,
    attempts: int = 1,
    counter: int | None = None,
) -> dict[str, Any]:
    """Build a run-index entry for one completed run.

    ``weight`` is the sample's post-processing weight (e.g. for an extent probability map); it is
    carried here, decoupled from how the sample was selected, exactly as the sweep produced it.
    ``counter`` is the run's incremental number within the project (used by clients that append runs
    one at a time, so :meth:`RunIndex.next_counter` can hand out the next one); omit it otherwise.
    """
    return {
        "run_id": run_id,
        "status": status,
        "dir": output_dir,
        "params": dict(params),
        "weight": weight,
        "seed": seed,
        "duration_s": duration_s,
        "error": error,
        "attempts": attempts,
        "counter": counter,
        "recorded": _now(),
    }


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


__all__ = [
    "RUN_INDEX_FILENAME",
    "RUN_INDEX_SCHEMA_VERSION",
    "RunIndex",
    "run_entry",
]
