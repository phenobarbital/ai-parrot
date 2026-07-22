"""``parrot.outputs.a2ui.recipes`` — recipe models + param resolution (FEAT-324, Module 1).

Recipes are pure data: an :class:`InfographicRecipe` binds datasets to a
registered transform chain and a catalog-component layout (spec G1). This
subpackage MUST NEVER import ``parrot.tools.dataset_manager``, ``parrot.bots``,
or ``parrot.clients`` (spec G8 one-way import rule) — the runner that performs
dataset I/O lives in ``parrot.tools.infographic_recipes`` instead.
"""

from parrot.outputs.a2ui.recipes.models import (
    DataSourceSpec,
    InfographicRecipe,
    LayoutSpec,
    RecipeParam,
    RecipeRunError,
    RenderSpec,
    ScheduleSpec,
    TransformerManifest,
    TransformStep,
)
from parrot.outputs.a2ui.recipes.params import (
    DATE_RESOLVERS,
    resolve_date,
    resolve_params,
    substitute,
)
from parrot.outputs.a2ui.recipes.transformers import (
    RegisteredTransformer,
    TransformerRegistry,
    infographic_transformer,
    transformer_registry,
    validate_inputs,
)

__all__ = [
    "RecipeParam",
    "DataSourceSpec",
    "TransformStep",
    "LayoutSpec",
    "RenderSpec",
    "ScheduleSpec",
    "InfographicRecipe",
    "TransformerManifest",
    "RecipeRunError",
    "DATE_RESOLVERS",
    "resolve_date",
    "resolve_params",
    "substitute",
    "RegisteredTransformer",
    "TransformerRegistry",
    "infographic_transformer",
    "transformer_registry",
    "validate_inputs",
]
