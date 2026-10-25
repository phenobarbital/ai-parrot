"""Semantic-layer exception hierarchy (spec §3 Module 2)."""
from __future__ import annotations

from typing import Any


class SemanticError(Exception):
    """Base for all semantic-layer errors.

    Args:
        code: Stable machine-readable error code.
        message: Human-readable message without SQL or subject values.
        details: Extra structured context such as suggestions or an audit ID.
    """

    def __init__(self, code: str, message: str = "", *, details: dict[str, Any] | None = None) -> None:
        super().__init__(message or code)
        self.code = code
        self.details: dict[str, Any] = details or {}


class SemanticValidationError(SemanticError):
    """Malformed or unsatisfiable semantic query."""


class SemanticPolicyError(SemanticError):
    """Invalid model or policy definition."""


class SemanticAccessError(SemanticError):
    """Denied access to a semantic model, member, or resource."""


class SemanticExecutionError(SemanticError):
    """Database execution failure whose details identify an audit entry."""


class SemanticResultError(SemanticError):
    """Unknown, foreign, expired, or stale result handle."""
