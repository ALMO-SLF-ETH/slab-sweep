"""The process contract: how the engine and a model process talk.

A model runs as a spawned subprocess. This module defines the thin protocol that both sides
agree on, independent of any language the model is written in:

**Invocation.** The engine builds the argv from the manifest's :class:`Invocation` by
substituting ``{placeholder}`` tokens (for example ``{runspec}``) with concrete paths via
:func:`build_argv`.

**Filenames.** The engine writes :data:`RUNSPEC_FILENAME` into the run directory and, after
the process exits, reads :data:`RESULT_FILENAME` from it.

**Progress.** While running, a model may report progress by writing JSON-object lines to
stdout, each with a ``progress`` field in ``[0, 1]`` and an optional ``message`` -- see
:func:`emit_progress` (model side) and :func:`parse_progress_line` (engine side). Any stdout
line that is not such an object is treated as ordinary log output and ignored by the parser.

**Exit.** Exit code ``0`` means the run finished; the authoritative outcome is the
``status`` in ``result.json``. A non-zero exit code means the run failed to complete.
"""

from __future__ import annotations

import json
import re
import sys
from dataclasses import dataclass
from typing import IO

from almo_sweep.contracts.errors import ContractError
from almo_sweep.contracts.manifest import Invocation

#: Name of the run-spec file the engine writes into each run directory.
RUNSPEC_FILENAME = "runspec.json"

#: Name of the result file the engine reads back from each run directory.
RESULT_FILENAME = "result.json"

_PLACEHOLDER = re.compile(r"\{(\w+)\}")


class ProcessError(ContractError):
    """The process invocation could not be constructed (e.g. an unresolved placeholder)."""


@dataclass(frozen=True)
class ProgressEvent:
    """A single progress report from a running model.

    ``progress`` is a fraction in ``[0, 1]``; the parser clamps out-of-range values.
    """

    progress: float
    message: str = ""


def build_argv(invocation: Invocation, substitutions: dict[str, str]) -> list[str]:
    """Build the concrete argv for a model process.

    Substitutes ``{name}`` tokens in the manifest's ``command`` and ``args_template`` with
    ``substitutions[name]``.

    :raises ProcessError: if a token has no matching substitution.
    """

    def resolve(token: str) -> str:
        def repl(m: re.Match[str]) -> str:
            key = m.group(1)
            if key not in substitutions:
                raise ProcessError(
                    f"unresolved placeholder {{{key}}} in invocation "
                    f"(known: {sorted(substitutions)})"
                )
            return substitutions[key]

        return _PLACEHOLDER.sub(repl, token)

    return [resolve(tok) for tok in (*invocation.command, *invocation.args_template)]


def parse_progress_line(line: str) -> ProgressEvent | None:
    """Parse one stdout line as a progress event, or return ``None`` if it is not one.

    Lenient by design: anything that is not a JSON object carrying a numeric ``progress``
    field is treated as ordinary log output and yields ``None``.
    """
    text = line.strip()
    if not text or text[0] != "{":
        return None
    try:
        obj = json.loads(text)
    except json.JSONDecodeError:
        return None
    if not isinstance(obj, dict) or "progress" not in obj:
        return None
    value = obj["progress"]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    clamped = max(0.0, min(1.0, float(value)))
    return ProgressEvent(progress=clamped, message=str(obj.get("message", "")))


def emit_progress(progress: float, message: str = "", *, stream: IO[str] | None = None) -> None:
    """Write a progress event to stdout (model side).

    Emits a single JSON object line and flushes, so the engine sees progress promptly.
    """
    out = stream if stream is not None else sys.stdout
    clamped = max(0.0, min(1.0, float(progress)))
    out.write(json.dumps({"progress": clamped, "message": message}) + "\n")
    out.flush()
