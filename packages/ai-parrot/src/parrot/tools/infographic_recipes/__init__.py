"""``parrot.tools.infographic_recipes`` — RecipeRunner (FEAT-324, Module 5).

Lives OUTSIDE ``parrot.outputs.a2ui`` so it may import ``DatasetManager``
(spec G8 one-way import rule — the a2ui core package itself never imports
DatasetManager/agents/LLM clients; this package is where dataset I/O happens).
"""

from parrot.tools.infographic_recipes.runner import RecipeRunException, RecipeRunner

__all__ = ["RecipeRunException", "RecipeRunner"]
