"""Guard: the core must never pull in QGIS.

Importing the whole package must not, directly or transitively, import ``qgis``. This is
the invariant that keeps the engine testable on plain CPython and portable to any client.
"""

from __future__ import annotations

import sys


def test_importing_core_does_not_import_qgis() -> None:
    # Import inside the test so the assertion reflects this package's own imports.
    import slab_sweep
    import slab_sweep.contracts

    # Reference the modules so the imports are unambiguously used.
    assert slab_sweep.__version__
    assert slab_sweep.contracts.__all__

    offenders = [name for name in sys.modules if name == "qgis" or name.startswith("qgis.")]
    assert not offenders, f"core imported QGIS modules: {offenders}"
