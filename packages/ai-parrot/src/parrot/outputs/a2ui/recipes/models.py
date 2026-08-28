"""Recipe data models (Module 1, FEAT-324).

An :class:`InfographicRecipe` is the persisted, replayable "construction
instructions" for an A2UI infographic: dataset bindings, a registered
transform chain, a catalog-component layout (v2, FEAT-470 TASK-2542: props
top-level, ``{"path": ...}`` pointers into ``dataModel``), and a render
profile. Recipes are pure data — never stored or executed code (spec G1).

Core-side, dependency-free (spec G8): pydantic v2 + stdlib + PyYAML only.
This module MUST NEVER import ``parrot.tools.dataset_manager``,
``parrot.bots``, or ``parrot.clients``.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal, Optional

import yaml
from pydantic import BaseModel, ConfigDict, Field

# FEAT-470 TASK-2542: ``LayoutSpec`` v2 reuses the wire's ``ComponentMetadata``
# shape for its own ``metadata.extensions.parrot_optional`` (a list of
# pointers a bind may be absent for) — the exact same convention
# ``compat.normalize_legacy_component`` already hoists a legacy
# ``{"$bind": ..., "optional": true}`` binding into. ``models.py`` is a2ui
# core, dependency-free (spec G8) — importing it here does not violate the
# "recipes core stays data-plane-free" rule above (only DatasetManager/bots/
# clients are forbidden).
from parrot.outputs.a2ui.models import ComponentMetadata

# FEAT-326: additive optional descriptor field. ``infographic_sections`` is a
# pydantic-only module (it does NOT import DatasetManager/bots/clients), so this
# import respects FEAT-324's "recipes core stays data-plane-free" rule.
from parrot.tools.infographic_sections import SectionDescriptor

__all__ = [
    "DataSourceSpec",
    "InfographicRecipe",
    "LayoutSpec",
    "NarrativeSpec",
    "RecipeParam",
    "RecipeRunError",
    "RenderSpec",
    "ScheduleSpec",
    "TransformStep",
    "TransformerManifest",
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
    """The catalog-component definition for the recipe's rendered layout.

    v2 (schema_version >= 2, FEAT-470 TASK-2542): catalog properties live
    TOP-LEVEL (``extra="allow"``), mirroring the A2UI v1.0 wire
    :class:`~parrot.outputs.a2ui.models.Component` shape — NOT nested under a
    ``properties`` key. Data-model bindings use ``{"path": "/pointer"}`` (the
    wire's ``DataBinding`` shape) — never an inline sibling ``"optional"``
    key (the wire's own ``DataBinding`` is ``extra="forbid"`` and has no such
    key). A binding that may legitimately be absent at run time is instead
    listed by its pointer in THIS layout's own
    ``metadata.extensions.parrot_optional`` (spec criterion G-E), mirroring
    how :mod:`parrot.outputs.a2ui.baking` reads the same convention off a
    wire ``Component``'s own metadata — consumed by
    :class:`~parrot.tools.infographic_recipes.runner.RecipeRunner`'s
    bind-pointer bookkeeping (``runner._optional_paths``). A v1 layout
    (``{"component", "properties"}`` + legacy ``{"$bind": ...,
    "optional": ...}``) is migrated via
    :func:`parrot.outputs.a2ui.recipes.migrate.migrate_layout`, which hoists
    every promoted binding's ``optional`` marker into ``metadata`` exactly
    this way (it reuses :func:`parrot.outputs.a2ui.compat.normalize_legacy_component`,
    whose hoisting behavior this docstring describes).

    Attributes:
        component: Catalog component name (e.g. ``"Infographic"``).
        child: Optional single-child reference, mirroring the wire
            ``Component.child`` (shape parity with the wire — unused by the
            current single-node recipe layout).
        children: Optional multi-child reference, mirroring the wire
            ``Component.children`` (shape parity — unused by the current
            single-node recipe layout).
        metadata: Layout-level metadata; ``extensions.parrot_optional`` lists
            data-model pointers (anywhere in the nested tree) allowed to be
            absent at run time without aborting the replay.
    """

    model_config = ConfigDict(populate_by_name=True, extra="allow")

    component: str
    child: Optional[str] = None
    children: Optional[list[Any]] = None
    metadata: Optional[ComponentMetadata] = None

    @property
    def props(self) -> dict[str, Any]:
        """Every top-level catalog property (everything but ``component``/``child``/``children``)."""
        return dict(self.model_extra or {})


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
        tenant_id: Optional tenant/org id for the principal's resolved
            ``PermissionContext``. Defaults to ``principal`` when unset (see
            ``parrot.auth.permission.build_principal_context``) — set this
            explicitly for any multi-tenant PBAC policy keyed on a real
            tenant id rather than the bare principal string.
        roles: Optional role claims for the principal's resolved
            ``PermissionContext``. Defaults to none — role-gated PBAC
            policies will deny scheduled replays until real roles are set
            here.
    """

    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    principal: str
    tenant_id: Optional[str] = None
    roles: list[str] = Field(default_factory=list)


class NarrativeSpec(BaseModel):
    """Declarative narrative step: a REFERENCE to a skill, never code (spec G1).

    Attributes:
        skill: Registered skill name that teaches an LLM to render the facts
            as prose (e.g. ``"budget-narrative"``). Never a prompt or template
            string — resolving the skill's content is the narrator's job.
        facts_key: ``data_model`` key holding the deterministic facts to
            render (typically a transform step's ``output_key``, e.g.
            ``"narrative_facts"``).
        output_key: ``data_model`` key the generated prose is written to.
    """

    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    skill: str = Field(..., description="Skill name resolvable in the skill registry.")
    facts_key: str = Field(..., description="data_model key holding the facts to render.")
    output_key: str = Field(default="narrative", description="data_model key for the prose.")


class InfographicRecipe(BaseModel):
    """The persisted, replayable construction instructions for an infographic.

    Serializes losslessly to/from JSON and YAML for both LLM-frozen and
    hand-authored recipes (spec G2).

    Attributes:
        schema_version: Recipe schema version (bump on breaking model
            changes). Defaults to 2 (FEAT-470 TASK-2542 — v2 ``LayoutSpec``,
            top-level props, ``{"path"}`` bindings). A v1 recipe still
            constructs/validates (``schema_version=1`` is accepted, just no
            longer the default); stores auto-migrate it in memory on read
            (see ``recipes/store.py``/``recipes/migrate.py``).
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
        section_descriptor: Optional authoring descriptor (FEAT-326) recording
            the template + render mode + per-section data contract that produced
            this recipe. Additive/optional — pre-existing recipes (field absent)
            still load. NOT a schema-version bump (the store gate is a strict
            equality on ``SUPPORTED_SCHEMA_VERSION``, so a bump would refuse
            every legacy recipe).
        narrative: Optional declarative narrative step (FEAT-420) — a
            REFERENCE to a skill name, never code (spec G1). Additive/optional
            — pre-existing recipes (field absent) still load; a `None`
            narrator injected into the runner also skips the step entirely
            (spec criterion G-E). NOT a schema-version bump, same rationale
            as `section_descriptor`.
    """

    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    schema_version: int = 2
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
    section_descriptor: Optional[SectionDescriptor] = None
    narrative: Optional[NarrativeSpec] = None

    def to_yaml(self) -> str:
        """Serialize this recipe to a YAML document.

        Returns:
            A YAML string, lossless round-trip via :meth:`from_yaml`.
        """
        return yaml.safe_dump(self.model_dump(mode="json"), sort_keys=False, allow_unicode=True)

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


# FEAT-420 (Module 7): resolve SectionDescriptor's forward-referenced
# `layout`/`narrative` fields now that LayoutSpec/NarrativeSpec are defined
# in THIS module. Deferred rebuild avoids a circular import —
# `infographic_sections.py` cannot import LayoutSpec/NarrativeSpec from here
# at runtime, since this module already imports SectionDescriptor from
# there (for its own `section_descriptor` field, above). `model_rebuild()`
# resolves the string-annotated forward references using this call site's
# module globals, which now contain both classes.
SectionDescriptor.model_rebuild()
