"""almo-sweep: headless, manifest-driven orchestration core for simulation sweeps.

This package must never import ``qgis``; it is the model-agnostic engine that the
QGIS plugin and any other client build upon. See ``tests/test_no_qgis_import.py``.
"""

from __future__ import annotations

__version__ = "0.0.1"

__all__ = ["__version__"]
