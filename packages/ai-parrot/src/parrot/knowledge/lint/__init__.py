"""Shared, backend-agnostic lint engine for the wiki graph (FEAT-625)."""

from __future__ import annotations

import importlib
from typing import Any

_LAZY: dict[str, str] = {
    "Finding": "parrot.knowledge.lint.models",
    "FixResult": "parrot.knowledge.lint.models",
    "LintOptions": "parrot.knowledge.lint.models",
    "LintReport": "parrot.knowledge.lint.models",
    "Severity": "parrot.knowledge.lint.models",
    "LintRule": "parrot.knowledge.lint.rule",
    "make_fingerprint": "parrot.knowledge.lint.rule",
    "LintContext": "parrot.knowledge.lint.context",
    "LintRunner": "parrot.knowledge.lint.runner",
}

__all__ = sorted(_LAZY)


def __getattr__(name: str) -> Any:
    """Resolve public names lazily."""
    if name not in _LAZY:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    return getattr(importlib.import_module(_LAZY[name]), name)
