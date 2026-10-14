"""``parrot.tools.infographic_recipes`` — RecipeRunner (FEAT-324, Module 5).

Lives OUTSIDE ``parrot.outputs.a2ui`` so it may import ``DatasetManager``
(spec G8 one-way import rule — the a2ui core package itself never imports
DatasetManager/agents/LLM clients; this package is where dataset I/O happens).

``load_transformer_module`` (FEAT-528) belongs here for the same one-way-
import reason: it is the host-side contract for registering a recipe's
transformers without importing the agent that ships them.
"""

from __future__ import annotations

import importlib
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from parrot.tools.infographic_recipes.freeze import (
        FreezeProvenanceError,
        FreezeValidationError,
        freeze_session_envelope,
    )
    from parrot.tools.infographic_recipes.loader import load_transformer_module
    from parrot.tools.infographic_recipes.runner import RecipeRunException, RecipeRunner

# Public name -> defining submodule. Resolved on first attribute access (PEP 562)
# so importing a leaf submodule (figure_guard, loader) does not import runner/freeze
# and, through them, the A2UI builders and catalog registrations (FEAT-668).
_LAZY: dict[str, str] = {
    "FreezeProvenanceError": "freeze",
    "FreezeValidationError": "freeze",
    "freeze_session_envelope": "freeze",
    "load_transformer_module": "loader",
    "RecipeRunException": "runner",
    "RecipeRunner": "runner",
}

__all__ = [
    "RecipeRunException",
    "RecipeRunner",
    "FreezeProvenanceError",
    "FreezeValidationError",
    "freeze_session_envelope",
    "load_transformer_module",
]


def __getattr__(name: str) -> Any:
    """Resolve a public name from its submodule on first access (PEP 562).

    Raises:
        AttributeError: for names not in ``_LAZY``.
    """
    submodule = _LAZY.get(name)
    if submodule is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    value = getattr(importlib.import_module(f"{__name__}.{submodule}"), name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    """Include the lazily resolved public names."""
    return sorted(set(globals()) | set(__all__))
