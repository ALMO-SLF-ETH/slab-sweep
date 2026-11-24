"""Shared test fixtures for the slab-sweep core suite."""

from __future__ import annotations

from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def slab_pro_manifest_path() -> Path:
    """Path to the reference Slab-Pro manifest."""
    return FIXTURES / "slab_pro.model.toml"
