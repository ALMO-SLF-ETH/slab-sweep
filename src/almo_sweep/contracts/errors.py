"""Exceptions raised when a contract document is malformed or invalid."""

from __future__ import annotations


class ContractError(Exception):
    """Base class for all contract validation failures."""


class ManifestError(ContractError):
    """A model manifest (``model.toml``) is missing required data or is inconsistent.

    The message is written to be shown directly to a user, so it names the offending
    field with a dotted path (for example ``params.friction_angle.default``).
    """
