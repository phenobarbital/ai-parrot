"""Freeze path — normalize a live session envelope + provenance into a persisted
:class:`InfographicRecipe` (Module 6, FEAT-324, spec G2).

The freeze path is the LLM half of dual authorship: an agent composes an
infographic interactively, then "freezes" the EXACT construction (which
registered datasets, which registered transformer calls, and the resulting
layout) into a recipe that replays identically without the LLM.

**Explicit provenance only (spec §7 documented boundary, not a bug)**: this
function does NOT attempt to reverse-engineer a session's pandas/REPL
history. It requires the caller (the toolkit tool method) to supply
``dataset_names`` and ``transform_steps`` explicitly — if a session's
dataModel values were computed by ad-hoc REPL pandas rather than registered
``@infographic_transformer`` calls, that provenance genuinely cannot be
expressed as recipe steps, and freezing must be rejected with a clear
message rather than silently producing a recipe that cannot replay.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from parrot.outputs.a2ui.models import CreateSurface
from parrot.outputs.a2ui.recipes.models import (
    DataSourceSpec,
    InfographicRecipe,
    LayoutSpec,
    RecipeParam,
    RecipeRunError,
    RenderSpec,
    TransformStep,
)
from parrot.tools.infographic_recipes.runner import RecipeRunner

__all__ = ["FreezeProvenanceError", "FreezeValidationError", "freeze_session_envelope"]


class FreezeProvenanceError(ValueError):
    """Raised when a session's data provenance cannot be expressed as recipe steps.

    This is the documented boundary of spec G2, not a bug: freeze requires
    explicit dataset + registered-transformer provenance; it never attempts
    to infer that provenance from ad-hoc REPL computation.
    """


class FreezeValidationError(ValueError):
    """Raised when the normalized recipe fails :meth:`RecipeRunner.dry_run`.

    Attributes:
        errors: ALL collected :class:`RecipeRunError` diagnostics (spec G4 —
            collect everything, not just the first problem).
    """

    def __init__(self, errors: list[RecipeRunError]) -> None:
        self.errors = errors
        super().__init__(
            "Frozen recipe failed dry_run validation: "
            f"{[e.detail for e in errors]!r}"
        )


async def freeze_session_envelope(
    envelope: CreateSurface,
    *,
    dataset_names: dict[str, str],
    transform_steps: list[dict[str, Any]] | list[TransformStep],
    name: str,
    title: str,
    runner: RecipeRunner,
    description: Optional[str] = None,
    owner: Optional[str] = None,
    params: Optional[list[RecipeParam]] = None,
    render_profile: str = "interactive-html",
    theme: Optional[str] = None,
) -> InfographicRecipe:
    """Normalize a live envelope + explicit provenance into a dry-run-clean recipe.

    Args:
        envelope: A single-component ``CreateSurface`` (e.g. from
            ``build_surface``/``build_infographic``) representing the session's
            current infographic layout.
        dataset_names: Data-source alias -> registered ``DatasetManager``
            dataset name (e.g. ``{"snapshots": "budget_ledger"}``).
        transform_steps: Ordered transform-step provenance — either
            ``TransformStep`` instances or dicts shaped like
            ``{"transformer": ..., "inputs": [...], "params": {...},
            "output_key": ...}``. Every entry MUST name a value that was
            actually produced by a registered ``@infographic_transformer``
            call in this session.
        name: Unique recipe name (storage key).
        title: Human-readable recipe title.
        runner: The :class:`RecipeRunner` used to ``dry_run`` the normalized
            recipe before returning it.
        description: Optional longer description.
        owner: Owner scope for the recipe (spec: toolkit's resolved user/agent
            scope).
        params: Declared recipe params (defaults empty — freeze captures a
            snapshot; param-ization of a frozen recipe is a follow-up
            refinement, not required for a valid freeze).
        render_profile: Renderer profile name for replay (default
            ``"interactive-html"``).
        theme: Optional theme name.

    Returns:
        The normalized, dry-run-clean :class:`InfographicRecipe` (NOT YET
        persisted — the caller persists via ``AbstractRecipeStore.save``).

    Raises:
        FreezeProvenanceError: If ``dataset_names``/``transform_steps`` is
            empty, or ``envelope`` does not carry exactly one component.
        FreezeValidationError: If the normalized recipe fails ``dry_run``
            (carries ALL collected diagnostics).
    """
    if not dataset_names:
        raise FreezeProvenanceError(
            "Cannot freeze: no dataset provenance supplied (dataset_names is empty). "
            "Every data source must be a registered DatasetManager dataset, not "
            "ad-hoc session data."
        )
    if not transform_steps:
        raise FreezeProvenanceError(
            "Cannot freeze: no transform-step provenance supplied (transform_steps "
            "is empty). Every dataModel value must be traceable to a registered "
            "@infographic_transformer call — ad-hoc REPL pandas computation cannot "
            "be expressed as a recipe (this is a documented boundary, not a bug)."
        )
    if len(envelope.components) != 1:
        raise FreezeProvenanceError(
            "Cannot freeze: expected a single-component envelope, got "
            f"{len(envelope.components)} components. Freeze one surface at a time."
        )

    normalized_steps = [
        step if isinstance(step, TransformStep) else TransformStep(**step)
        for step in transform_steps
    ]
    data_sources = [
        DataSourceSpec(dataset=dataset_name, alias=alias)
        for alias, dataset_name in dataset_names.items()
    ]
    component = envelope.components[0]
    layout = LayoutSpec(component=component.component, properties=dict(component.properties))

    recipe = InfographicRecipe(
        name=name,
        title=title,
        description=description,
        owner=owner,
        params=params or [],
        data_sources=data_sources,
        transforms=normalized_steps,
        layout=layout,
        render=RenderSpec(profile=render_profile, theme=theme),
        updated_at=datetime.now(timezone.utc),
    )

    errors = await runner.dry_run(recipe)
    if errors:
        raise FreezeValidationError(errors)

    return recipe
