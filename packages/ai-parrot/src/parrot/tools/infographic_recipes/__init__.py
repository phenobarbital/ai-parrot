"""``parrot.tools.infographic_recipes`` — RecipeRunner (FEAT-324, Module 5).

Lives OUTSIDE ``parrot.outputs.a2ui`` so it may import ``DatasetManager``
(spec G8 one-way import rule — the a2ui core package itself never imports
DatasetManager/agents/LLM clients; this package is where dataset I/O happens).

``load_transformer_module`` (FEAT-528) belongs here for the same one-way-
import reason: it is the host-side contract for registering a recipe's
transformers without importing the agent that ships them.
"""

from parrot.tools.infographic_recipes.freeze import (
    FreezeProvenanceError,
    FreezeValidationError,
    freeze_session_envelope,
)
from parrot.tools.infographic_recipes.loader import load_transformer_module
from parrot.tools.infographic_recipes.runner import RecipeRunException, RecipeRunner

__all__ = [
    "RecipeRunException",
    "RecipeRunner",
    "FreezeProvenanceError",
    "FreezeValidationError",
    "freeze_session_envelope",
    "load_transformer_module",
]
