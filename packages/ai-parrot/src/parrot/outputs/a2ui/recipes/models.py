"""Recipe data models (Module 1, FEAT-324).

An :class:`InfographicRecipe` is the persisted, replayable "construction
instructions" for an A2UI infographic: dataset bindings, a registered
transform chain, a catalog-component layout (with ``$bind`` pointers into
``dataModel``), and a render profile. Recipes are pure data — never stored
or executed code (spec G1).

Core-side, dependency-free (spec G8): pydantic v2 + stdlib + PyYAML only.
This module MUST NEVER import ``parrot.tools.dataset_manager``,
``parrot.bots``, or ``parrot.clients``.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal, Optional

import yaml
from pydantic import BaseModel, ConfigDict, Field

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
]


class RecipeParam(BaseModel):
    """A declared recipe parameter available for ``{param}`` substitution.

    Attributes:
        name: Parameter name, referenced as ``{name}`` in templated strings.
        default: Literal default value, or the name of a built-in relative-date
            resolver (e.g. ``"current_month"``). ``None`` means no default —
            the param must be supplied as an override at run time.
        description: Human-readable description of the parameter's purpose.
    """

    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    name: str
    default: Optional[str] = None
    description: Optional[str] = None


class DataSourceSpec(BaseModel):
    """A single dataset binding consumed by the recipe's transform chain.

    Attributes:
        dataset: Registered ``DatasetManager`` dataset name.
        alias: Key transforms use to reference the fetched frame.
        sql: Optional SQL template with ``{param}`` placeholders.
        conditions: Optional conditions template (values may contain
            ``{param}`` placeholders).
        force_refresh: Whether replay must force a fresh fetch (spec G3).
    """

    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    dataset: str
    alias: str
    sql: Optional[str] = None
    conditions: Optional[dict[str, Any]] = None
    force_refresh: bool = True


class TransformStep(BaseModel):
    """A single step in the recipe's registered transform chain.

    Attributes:
        transformer: Registered transformer name (e.g. ``"division_breakdown"``).
        inputs: Data-source aliases and/or prior steps' ``output_key`` values.
        params: Transformer parameters; string values may contain ``{param}``
            placeholders.
        output_key: The ``dataModel`` key that receives this step's result.
    """

    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    transformer: str
    inputs: list[str] = Field(default_factory=list)
    params: dict[str, Any] = Field(default_factory=dict)
    output_key: str


class LayoutSpec(BaseModel):
    """The catalog-component tree for the recipe's rendered layout.

    Attributes:
        component: Catalog component name (e.g. ``"Infographic"``).
        properties: Catalog properties; data-carrying properties use
            ``{"$bind": "/pointer"}`` bindings into the assembled ``dataModel``.
    """

    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    component: str
    properties: dict[str, Any] = Field(default_factory=dict)


class RenderSpec(BaseModel):
    """Render-profile configuration for a recipe.

    Attributes:
        profile: Renderer name resolved via ``get_a2ui_renderer()``.
        theme: Optional theme name passed through to the renderer.
        delivery: Optional delivery config (provider/recipients) for
            ``deliver_artifact``.
    """

    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    profile: str = "interactive-html"
    theme: Optional[str] = None
    delivery: Optional[dict[str, Any]] = None


class ScheduleSpec(BaseModel):
    """Scheduled-replay configuration for a recipe (spec G8).

    Attributes:
        principal: Explicit run-as principal for scheduled replays. Scheduled
            jobs NEVER run under a server identity — only this principal.
    """

    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    principal: str


class InfographicRecipe(BaseModel):
    """The persisted, replayable construction instructions for an infographic.

    Serializes losslessly to/from JSON and YAML for both LLM-frozen and
    hand-authored recipes (spec G2).

    Attributes:
        schema_version: Recipe schema version (bump on breaking model changes).
        name: Unique recipe name, scoped per store/owner.
        title: Human-readable title.
        description: Optional longer description.
        owner: User/agent scope owning this recipe.
        params: Declared parameters available for ``{param}`` substitution.
        data_sources: Dataset bindings consumed by the transform chain.
        transforms: Ordered registered-transformer chain.
        layout: Catalog-component layout with ``$bind`` pointers.
        render: Render-profile configuration.
        schedule: Optional scheduled-replay configuration (spec G8).
        updated_at: Last-write timestamp; set by stores on save (overwrite
            semantics, spec G5) — not auto-populated by the model itself.
    """

    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    schema_version: int = 1
    name: str
    title: str
    description: Optional[str] = None
    owner: Optional[str] = None
    params: list[RecipeParam] = Field(default_factory=list)
    data_sources: list[DataSourceSpec] = Field(default_factory=list)
    transforms: list[TransformStep] = Field(default_factory=list)
    layout: LayoutSpec
    render: RenderSpec = Field(default_factory=RenderSpec)
    schedule: Optional[ScheduleSpec] = None
    updated_at: datetime

    def to_yaml(self) -> str:
        """Serialize this recipe to a YAML document.

        Returns:
            A YAML string, lossless round-trip via :meth:`from_yaml`.
        """
        return yaml.safe_dump(
            self.model_dump(mode="json"), sort_keys=False, allow_unicode=True
        )

    @classmethod
    def from_yaml(cls, text: str) -> "InfographicRecipe":
        """Deserialize a recipe from a YAML document produced by :meth:`to_yaml`.

        Args:
            text: YAML document text.

        Returns:
            The parsed :class:`InfographicRecipe`.
        """
        data = yaml.safe_load(text)
        return cls.model_validate(data)


class TransformerManifest(BaseModel):
    """Discoverable contract for a registered transformer (spec G4 / LLM discovery).

    Attributes:
        name: Registered transformer name.
        description: Human-readable description.
        requires_columns: Required input columns keyed by input alias.
        params_schema: JSON schema of accepted params.
    """

    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    name: str
    description: str
    requires_columns: dict[str, list[str]] = Field(default_factory=dict)
    params_schema: dict[str, Any] = Field(default_factory=dict)


class RecipeRunError(BaseModel):
    """Structured fail-fast diagnostic for a failed recipe run (spec G4).

    Attributes:
        recipe: Recipe name that failed.
        stage: The pipeline stage that raised the error.
        transformer: Offending transformer name, if applicable.
        dataset: Offending dataset name, if applicable.
        missing_columns: Required columns absent from the input frame.
        detail: Human-readable diagnostic message.
    """

    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    recipe: str
    stage: Literal["params", "data", "gate", "transform", "layout", "render"]
    transformer: Optional[str] = None
    dataset: Optional[str] = None
    missing_columns: list[str] = Field(default_factory=list)
    detail: str
