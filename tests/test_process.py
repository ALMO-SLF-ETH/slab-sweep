"""Tests for the process contract: argv construction and the progress protocol."""

from __future__ import annotations

import io

import pytest

from slab_sweep.contracts import (
    Invocation,
    ProcessError,
    ProgressEvent,
    build_argv,
    emit_progress,
    parse_progress_line,
)


# --- build_argv -----------------------------------------------------------------------
def test_build_argv_substitutes_placeholders() -> None:
    inv = Invocation(
        command=("python", "-m", "slab_pro_interface", "run"),
        args_template=("--runspec", "{runspec}"),
    )
    argv = build_argv(inv, {"runspec": "/runs/r1/runspec.json"})
    assert argv == [
        "python",
        "-m",
        "slab_pro_interface",
        "run",
        "--runspec",
        "/runs/r1/runspec.json",
    ]


def test_build_argv_without_placeholders() -> None:
    inv = Invocation(command=("./model",))
    assert build_argv(inv, {}) == ["./model"]


def test_build_argv_unresolved_placeholder_raises() -> None:
    inv = Invocation(command=("run",), args_template=("--in", "{missing}"))
    with pytest.raises(ProcessError, match="unresolved placeholder"):
        build_argv(inv, {"runspec": "x"})


def test_build_argv_substitutes_in_command_too() -> None:
    inv = Invocation(command=("{python}", "-m", "model"))
    assert build_argv(inv, {"python": "/usr/bin/python3"})[0] == "/usr/bin/python3"


# --- parse_progress_line --------------------------------------------------------------
def test_parse_valid_progress() -> None:
    ev = parse_progress_line('{"progress": 0.5, "message": "halfway"}')
    assert ev == ProgressEvent(progress=0.5, message="halfway")


def test_parse_progress_without_message() -> None:
    ev = parse_progress_line('{"progress": 1}')
    assert ev == ProgressEvent(progress=1.0, message="")


def test_parse_clamps_out_of_range() -> None:
    assert parse_progress_line('{"progress": 1.5}') == ProgressEvent(1.0, "")
    assert parse_progress_line('{"progress": -0.2}') == ProgressEvent(0.0, "")


@pytest.mark.parametrize(
    "line",
    [
        "",
        "   ",
        "just a log line",
        "loading dem.tif ...",
        '{"message": "no progress key"}',
        '{"progress": "soon"}',
        '{"progress": true}',
        "{not valid json",
        "[1, 2, 3]",
    ],
)
def test_non_progress_lines_return_none(line: str) -> None:
    assert parse_progress_line(line) is None


# --- emit_progress round-trips through parse_progress_line -----------------------------
def test_emit_and_parse_roundtrip() -> None:
    buf = io.StringIO()
    emit_progress(0.25, "quarter", stream=buf)
    line = buf.getvalue()
    assert line.endswith("\n")
    assert parse_progress_line(line) == ProgressEvent(0.25, "quarter")


def test_emit_clamps() -> None:
    buf = io.StringIO()
    emit_progress(2.0, stream=buf)
    assert parse_progress_line(buf.getvalue()) == ProgressEvent(1.0, "")
