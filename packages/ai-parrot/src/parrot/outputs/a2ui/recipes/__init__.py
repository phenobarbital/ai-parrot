"""``parrot.outputs.a2ui.recipes`` — recipe models + param resolution (FEAT-324, Module 1).

Recipes are pure data: an :class:`InfographicRecipe` binds datasets to a
registered transform chain and a catalog-component layout (spec G1). This
subpackage MUST NEVER import ``parrot.tools.dataset_manager``, ``parrot.bots``,
or ``parrot.clients`` (spec G8 one-way import rule) — the runner that performs
dataset I/O lives in ``parrot.tools.infographic_recipes`` instead.
"""

# Built-in transformers (recipes.library) register lazily on the first
# transformer_registry access — not at package import (FEAT-668).
from parrot.outputs.a2ui.recipes.migrate import (
    MigrationReport,
    migrate_layout,
    migrate_store,
)
from parrot.outputs.a2ui.recipes.models import (
    DataSourceSpec,
    InfographicRecipe,
    LayoutSpec,
    NarrativeSpec,
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
from parrot.outputs.a2ui.recipes.store import (
    SUPPORTED_SCHEMA_VERSION,
    AbstractRecipeStore,
    DBRecipeStore,
    FileRecipeStore,
    RecipeNotFoundError,
    RecipeSchemaVersionError,
)
from parrot.outputs.a2ui.recipes.transformers import (
    RegisteredTransformer,
    TransformerRegistry,
    infographic_transformer,
    transformer_registry,
    validate_inputs,
)

__all__ = [
    "DATE_RESOLVERS",
    "SUPPORTED_SCHEMA_VERSION",
    "AbstractRecipeStore",
    "DBRecipeStore",
    "DataSourceSpec",
    "FileRecipeStore",
    "InfographicRecipe",
    "LayoutSpec",
    "MigrationReport",
    "NarrativeSpec",
    "RecipeNotFoundError",
    "RecipeParam",
    "RecipeRunError",
    "RecipeSchemaVersionError",
    "RegisteredTransformer",
    "RenderSpec",
    "ScheduleSpec",
    "TransformStep",
    "TransformerManifest",
    "TransformerRegistry",
    "infographic_transformer",
    "migrate_layout",
    "migrate_store",
    "resolve_date",
    "resolve_params",
    "substitute",
    "transformer_registry",
    "validate_inputs",
]
