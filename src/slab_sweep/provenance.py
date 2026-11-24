"""Capture the provenance of the code that produced a run: version + git commit/dirty/date.

For reproducibility every result records *which code made it*. Each component contributes a small
record ``{name, version, commit, dirty, date}``:

* Python packages (this engine, the GUI plugin, a model's Python adapter) are read at run time --
  the package version plus the git state of its source directory (editable installs are git
  checkouts, which is how the stack is deployed).
* A compiled model binary reports its own version (fixed at its build) through its own channel
  (e.g. Slab-Pro's ``--version``); the model adapter captures that.

The git lookups are best-effort and standard-library only: a missing ``git``, a non-checkout, or
a detached/odd state yields ``None`` fields rather than an error, so provenance never breaks a run.
"""

from __future__ import annotations

import functools
import os
import shutil
import subprocess
import sys
from importlib import metadata
from pathlib import Path
from typing import Any

#: git calls are quick, but guard against a hung/odd environment so provenance never stalls a run.
_GIT_TIMEOUT_S = 5.0

#: On Windows, keep git's console window hidden when launched from a GUI host (QGIS).
_CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def _no_window_kwargs() -> dict[str, Any]:
    """``subprocess`` kwargs that keep git's console window hidden on Windows (no-op elsewhere)."""
    kwargs: dict[str, Any] = {"creationflags": _CREATE_NO_WINDOW}
    if os.name == "nt":
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startupinfo.wShowWindow = subprocess.SW_HIDE
        kwargs["startupinfo"] = startupinfo
    return kwargs


@functools.lru_cache(maxsize=1)
def _git_exe() -> str | None:
    """Locate the ``git`` executable, even when it is not on ``PATH``.

    QGIS launches Python with a trimmed ``PATH`` that omits Git, so a bare ``git`` subprocess
    raises ``FileNotFoundError`` and every git field comes back ``None``. Honour an explicit
    override, then search ``PATH``, then the usual install locations before giving up."""
    override = os.environ.get("GIT_EXECUTABLE") or os.environ.get("GIT")
    if override and Path(override).exists():
        return override
    found = shutil.which("git")
    if found:
        return found
    candidates: list[Path] = []
    if sys.platform.startswith("win"):
        from_registry = _git_from_registry()  # authoritative for any Git-for-Windows install
        if from_registry:
            return from_registry
        for var in ("ProgramFiles", "ProgramFiles(x86)", "ProgramW6432", "LOCALAPPDATA"):
            base = os.environ.get(var)
            if base:
                candidates.append(Path(base) / "Git" / "cmd" / "git.exe")
                candidates.append(Path(base) / "Programs" / "Git" / "cmd" / "git.exe")
    else:
        candidates = [
            Path(p) for p in ("/usr/bin/git", "/usr/local/bin/git", "/opt/homebrew/bin/git")
        ]
    return next((str(c) for c in candidates if c.exists()), None)


def _git_from_registry() -> str | None:
    """The ``git.exe`` of a Git-for-Windows install, read from its registry key.

    Git for Windows records its install path under ``SOFTWARE\\GitForWindows`` regardless of where
    it was installed (scoop, winget, a custom folder, ...), so this covers installs the fixed-path
    guesses miss. Returns ``None`` off Windows or when no such install is registered."""
    try:
        import winreg
    except ImportError:
        return None
    views = (winreg.KEY_WOW64_64KEY, winreg.KEY_WOW64_32KEY)
    for root in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
        for view in views:
            try:
                with winreg.OpenKey(
                    root, r"SOFTWARE\GitForWindows", 0, winreg.KEY_READ | view
                ) as key:
                    install = winreg.QueryValueEx(key, "InstallPath")[0]
            except OSError:
                continue
            exe = Path(install) / "cmd" / "git.exe"
            if exe.exists():
                return str(exe)
    return None


def git_info(source_dir: str | Path) -> dict[str, Any] | None:
    """``{commit, dirty, date}`` for the git repo containing ``source_dir``; ``None`` if there is
    none (not a checkout, or ``git`` unavailable)."""
    cwd = str(source_dir)
    commit = _git(cwd, "rev-parse", "HEAD")
    if commit is None:
        return None
    status = _git(cwd, "status", "--porcelain")
    date = _git(cwd, "show", "-s", "--format=%cI", "HEAD")
    return {
        "commit": commit,
        "dirty": None if status is None else bool(status),  # any tracked/untracked change => dirty
        "date": date,
    }


def package_provenance(
    name: str, source_dir: str | Path, *, version: str | None = None
) -> dict[str, Any]:
    """Provenance for a Python package: its ``version`` plus the git state of ``source_dir``.

    ``version`` may be given explicitly (e.g. a QGIS plugin's ``metadata.txt`` version); otherwise
    the installed distribution version of ``name`` is used when available."""
    record: dict[str, Any] = {
        "name": name,
        "version": version if version is not None else _dist_version(name),
        "commit": None,
        "dirty": None,
        "date": None,
    }
    git = git_info(source_dir)
    if git is not None:
        record.update(git)
    return record


def engine_provenance() -> dict[str, Any]:
    """Provenance of this engine (``slab-sweep``)."""
    import slab_sweep

    return package_provenance("slab-sweep", Path(slab_sweep.__file__).resolve().parent)


def _dist_version(name: str) -> str | None:
    try:
        return metadata.version(name)
    except metadata.PackageNotFoundError:
        return None


def _git(cwd: str, *args: str) -> str | None:
    exe = _git_exe()
    if exe is None:
        return None
    try:
        result = subprocess.run(
            [exe, "-C", cwd, *args],
            capture_output=True,
            text=True,
            timeout=_GIT_TIMEOUT_S,
            check=False,
            **_no_window_kwargs(),
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    out: str = result.stdout
    return out.strip()


__all__ = ["engine_provenance", "git_info", "package_provenance"]
