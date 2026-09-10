"""Shared test fixtures for the almo-sweep core suite."""

from __future__ import annotations

from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def dampm_manifest_path() -> Path:
    """Path to the reference dampm manifest."""
    return FIXTURES / "dampm.model.toml"
