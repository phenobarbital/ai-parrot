"""Semantic-layer exception hierarchy (spec §3 Module 2)."""

from __future__ import annotations

from typing import Any


class SemanticError(Exception):
    """Base for all semantic-layer errors.

    Args:
        code: Stable machine-readable error code (for example, ``"no_credentials"``).
        message: Human-readable message that never contains SQL or subject values.
        details: Extra structured context such as suggestions or an audit ID.
    """

    def __init__(self, code: str, message: str = "", *, details: dict[str, Any] | None = None) -> None:
        """Initialize an error with its stable code and structured details."""
        super().__init__(message or code)
        self.code = code
        self.details: dict[str, Any] = details or {}


class SemanticValidationError(SemanticError):
    """Malformed or unsatisfiable query, including unknown members and invalid filter placement."""


class SemanticPolicyError(SemanticError):
    """Invalid model or policy definition, including invalid RLS bindings."""


class SemanticAccessError(SemanticError):
    """Denied access due to missing context, policy, grants, usage rights, or lineage."""


class SemanticExecutionError(SemanticError):
    """Database execution failure whose details may include an audit ID but never SQL."""


class SemanticResultError(SemanticError):
    """Unknown, foreign, expired, or stale result handle."""
