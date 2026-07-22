"""RecipeRunner — deterministic replay pipeline (Module 5, FEAT-324).

The heart of the feature: ONE runner behind all three triggers (chat tool,
REST, scheduler — spec G6) executes the seven-step replay:

    1. load recipe + resolve params (declared defaults + overrides + date resolvers)
    2. fetch datasets (DatasetManager, invoker pctx honored)
    3. fail-fast validation gate (spec G4)
    4. execute the registered transform chain into a data_model dict
    5. cross-check every layout ``$bind`` pointer against data_model keys, then
       assemble + catalog-validate the envelope
    6. render via the resolved renderer profile
    7. optionally deliver (persistence is a caller concern — see NOTE below)

Lives OUTSIDE ``parrot.outputs.a2ui`` (in ``parrot.tools.infographic_recipes``)
precisely so it may import ``DatasetManager`` (spec G8 one-way import rule).

**pctx propagation (spec G8)**: ``DatasetManager`` reads its per-call
``PermissionContext`` from the module-level ``parrot.auth.context._pctx_var``
``ContextVar`` — set by ``DatasetManager._pre_execute`` ONLY when a tool is
invoked through the toolkit dispatch mechanism (``ToolkitTool._execute``).
This runner calls ``fetch_dataset``/``get_dataset_entry`` directly (bypassing
that dispatch path), so it sets ``_pctx_var`` itself around the data-fetch
step and resets it afterwards — mirroring what ``_pre_execute``/
``_post_execute`` do, just invoked manually. Scheduled jobs pass whatever
``PermissionContext`` they resolved for ``schedule.principal`` as ``pctx``
(constructing/resolving that principal's context is TASK-1872's concern, not
this runner's).

**Persistence NOTE**: this task's ``run()`` signature (spec §2 New Public
Interfaces) takes no ``user_id``/``agent_id``/``session_id`` — the context
``ArtifactStore.save_artifact`` requires (``parrot/storage/artifacts.py``).
Full envelope/artifact persistence therefore stays with whichever caller HAS
that session context (chat tool TASK-1870, REST/scheduler TASK-1872); this
runner's ``artifact_store`` constructor param is passed straight through to
``deliver_artifact(..., artifact_store=...)`` for its one VERIFIED use (the
Slack public-URL lookup), not re-invented as a separate persist call.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

import pandas as pd

from parrot.auth.context import _pctx_var
from parrot.outputs.a2ui.artifacts import RenderedArtifact
from parrot.outputs.a2ui.builders import build_infographic, build_surface
from parrot.outputs.a2ui.catalog.base import CatalogValidationError
from parrot.outputs.a2ui.delivery import deliver_artifact
from parrot.outputs.a2ui.models import BINDING_KEY, is_binding_expression
from parrot.outputs.a2ui.recipes.models import (
    InfographicRecipe,
    RecipeRunError,
    TransformStep,
)
from parrot.outputs.a2ui.recipes.params import resolve_params, substitute
from parrot.outputs.a2ui.recipes.store import AbstractRecipeStore
from parrot.outputs.a2ui.recipes.transformers import transformer_registry, validate_inputs
from parrot.outputs.a2ui.renderers import get_a2ui_renderer
from parrot.tools.dataset_manager.tool import DatasetManager

__all__ = ["RecipeRunException", "RecipeRunner"]


class RecipeRunException(Exception):
    """Raised on every pipeline abort; carries the structured :class:`RecipeRunError`."""

    def __init__(self, error: RecipeRunError) -> None:
        self.error = error
        super().__init__(error.detail)


def _pointer_top_key(pointer: str) -> str:
    """Return the top-level (first) segment of an RFC 6901 JSON Pointer.

    E.g. ``"/division_breakdown/Sales/rev_actual"`` -> ``"division_breakdown"``.
    """
    segment = pointer.lstrip("/").split("/", 1)[0]
    return segment.replace("~1", "/").replace("~0", "~")


def _collect_bind_pointers(value: Any) -> list[str]:
    """Recursively collect every ``{"$bind": "/pointer"}`` pointer in ``value``."""
    pointers: list[str] = []
    if is_binding_expression(value):
        pointers.append(value[BINDING_KEY])
    elif isinstance(value, dict):
        for item in value.values():
            pointers.extend(_collect_bind_pointers(item))
    elif isinstance(value, list):
        for item in value:
            pointers.extend(_collect_bind_pointers(item))
    return pointers


def _substitute_value(value: Any, resolved_params: dict[str, str]) -> Any:
    """Recursively apply ``{param}`` substitution to every string in ``value``."""
    if isinstance(value, str):
        return substitute(value, resolved_params)
    if isinstance(value, dict):
        return {k: _substitute_value(v, resolved_params) for k, v in value.items()}
    if isinstance(value, list):
        return [_substitute_value(v, resolved_params) for v in value]
    return value


def _extract_metadata_columns(metadata: Any) -> Optional[set[str]]:
    """Best-effort extraction of a column-name set from ``DatasetManager.get_metadata()``.

    That method's ``"columns"`` field is a ``dict`` (name -> per-column metadata)
    when the dataset is loaded, or a plain ``list[str]`` when it is not
    (spec Codebase Contract note — both shapes observed in ``tool.py``).
    Returns ``None`` when metadata is unavailable/errored (dry_run must not
    fail just because metadata could not be fetched).
    """
    if not isinstance(metadata, dict) or metadata.get("error"):
        return None
    columns = metadata.get("columns")
    if isinstance(columns, dict):
        return set(columns.keys())
    if isinstance(columns, list):
        return set(columns)
    return None


class RecipeRunner:
    """Executes the seven-step deterministic recipe-replay pipeline (spec §2).

    Args:
        store: Recipe store (:class:`FileRecipeStore` or :class:`DBRecipeStore`)
            recipes are loaded from.
        dataset_manager: The :class:`DatasetManager` instance used to fetch
            datasets.
        artifact_store: Optional ``ArtifactStore``-shaped object forwarded to
            ``deliver_artifact`` for its Slack public-URL lookup (see module
            docstring's Persistence NOTE).
        owner: Optional ``NotificationMixin``-bearing object (e.g. an agent)
            used as ``deliver_artifact``'s ``owner`` argument.
    """

    def __init__(
        self,
        store: AbstractRecipeStore,
        dataset_manager: DatasetManager,
        *,
        artifact_store: Any = None,
        owner: Any = None,
    ) -> None:
        self.store = store
        self.dataset_manager = dataset_manager
        self.artifact_store = artifact_store
        self.owner = owner
        self.logger = logging.getLogger(f"parrot.tools.infographic_recipes.{self.__class__.__name__}")

    async def run(
        self,
        name: str,
        *,
        params: dict[str, Any] | None = None,
        pctx: Any | None = None,
    ) -> RenderedArtifact:
        """Run the full seven-step replay pipeline for recipe ``name``.

        Args:
            name: Recipe name to load from ``self.store``.
            params: Override values for the recipe's declared params.
            pctx: Invoker's ``PermissionContext`` (chat/REST) or the resolved
                context for ``schedule.principal`` (scheduled jobs). Propagated
                to ``DatasetManager`` via its ``_pctx_var`` ContextVar for the
                duration of the data-fetch step.

        Returns:
            The rendered, persisted-if-configured :class:`RenderedArtifact`.

        Raises:
            RecipeRunException: On any pipeline abort (stage-tagged diagnostic).
            ImportError: If the recipe's render profile names an uninstalled
                renderer backend (propagated from ``get_a2ui_renderer`` unchanged
                — "degrades with the existing actionable ImportError").
        """
        recipe = await self._load_recipe(name)
        resolved_params = self._resolve_params_or_raise(recipe, params)
        frames = await self._fetch_frames(recipe, resolved_params, pctx)
        self._run_gate_or_raise(recipe, frames)
        data_model = self._run_transforms_or_raise(recipe, frames, resolved_params)
        self._check_bind_drift_or_raise(recipe, data_model)
        envelope = self._assemble_envelope_or_raise(recipe, data_model)
        artifact = await self._render_or_raise(recipe, envelope)
        await self._deliver_best_effort(recipe, artifact)
        return artifact

    async def dry_run(self, recipe: InfographicRecipe) -> list[RecipeRunError]:
        """Validate a recipe WITHOUT fetching data or rendering (freeze-path use).

        Checks (spec: steps 1/3/5 only):
            - param references resolve (declared defaults / resolver names valid)
            - every ``TransformStep.transformer`` is registered
            - gate columns against dataset METADATA when available (no fetch)
            - every layout ``$bind`` pointer's top-level key matches a declared
              ``output_key``

        Args:
            recipe: The (not-yet-persisted) recipe to validate.

        Returns:
            ALL problems found (empty list if the recipe is clean).
        """
        errors: list[RecipeRunError] = []

        try:
            resolve_params(recipe.params)
        except ValueError as exc:
            errors.append(RecipeRunError(recipe=recipe.name, stage="params", detail=str(exc)))

        known_aliases = {ds.alias: ds for ds in recipe.data_sources}
        declared_output_keys = {step.output_key for step in recipe.transforms}

        for step in recipe.transforms:
            try:
                registered = transformer_registry.get(step.transformer)
            except KeyError as exc:
                errors.append(
                    RecipeRunError(
                        recipe=recipe.name,
                        stage="gate",
                        transformer=step.transformer,
                        detail=str(exc),
                    )
                )
                continue

            for alias in step.inputs:
                if alias not in known_aliases:
                    continue  # chained prior output_key — nothing to check without data
                ds = known_aliases[alias]
                try:
                    metadata = await self.dataset_manager.get_metadata(ds.dataset)
                except Exception:  # noqa: BLE001 - metadata is best-effort in dry_run
                    metadata = None
                columns = _extract_metadata_columns(metadata)
                if columns is None:
                    continue
                required = registered.manifest.requires_columns.get(alias, [])
                missing = [c for c in required if c not in columns]
                if missing:
                    errors.append(
                        RecipeRunError(
                            recipe=recipe.name,
                            stage="gate",
                            transformer=step.transformer,
                            dataset=alias,
                            missing_columns=missing,
                            detail=(
                                f"Dataset metadata for {alias!r} is missing required "
                                f"column(s) {missing!r} for transformer {step.transformer!r}."
                            ),
                        )
                    )

        for pointer in _collect_bind_pointers(recipe.layout.properties):
            top_key = _pointer_top_key(pointer)
            if top_key not in declared_output_keys:
                errors.append(
                    RecipeRunError(
                        recipe=recipe.name,
                        stage="layout",
                        detail=(
                            f"$bind pointer {pointer!r} references undeclared output_key "
                            f"{top_key!r}; declared output_keys: {sorted(declared_output_keys)!r}"
                        ),
                    )
                )

        return errors

    # ── Pipeline steps ────────────────────────────────────────────────

    async def _load_recipe(self, name: str) -> InfographicRecipe:
        return await self.store.get(name)

    def _resolve_params_or_raise(
        self, recipe: InfographicRecipe, overrides: dict[str, Any] | None
    ) -> dict[str, str]:
        try:
            return resolve_params(recipe.params, overrides)
        except ValueError as exc:
            raise RecipeRunException(
                RecipeRunError(recipe=recipe.name, stage="params", detail=str(exc))
            ) from exc

    async def _fetch_frames(
        self,
        recipe: InfographicRecipe,
        resolved_params: dict[str, str],
        pctx: Any | None,
    ) -> dict[str, pd.DataFrame]:
        token = _pctx_var.set(pctx)
        try:
            frames: dict[str, pd.DataFrame] = {}
            for ds in recipe.data_sources:
                sql = substitute(ds.sql, resolved_params) if ds.sql else None
                conditions = (
                    _substitute_value(ds.conditions, resolved_params)
                    if ds.conditions is not None
                    else None
                )
                result = await self.dataset_manager.fetch_dataset(
                    ds.dataset, sql=sql, conditions=conditions, force_refresh=ds.force_refresh
                )
                if isinstance(result, dict) and result.get("error"):
                    raise RecipeRunException(
                        RecipeRunError(
                            recipe=recipe.name,
                            stage="data",
                            dataset=ds.dataset,
                            detail=str(result["error"]),
                        )
                    )
                entry = self.dataset_manager.get_dataset_entry(ds.dataset)
                if entry is None:
                    available = [
                        d.get("name") for d in await self.dataset_manager.list_datasets()
                    ]
                    raise RecipeRunException(
                        RecipeRunError(
                            recipe=recipe.name,
                            stage="data",
                            dataset=ds.dataset,
                            detail=(
                                f"Dataset {ds.dataset!r} is not registered; "
                                f"available datasets: {available!r}"
                            ),
                        )
                    )
                frames[ds.alias] = entry.df
            return frames
        finally:
            _pctx_var.reset(token)

    def _run_gate_or_raise(
        self, recipe: InfographicRecipe, frames: dict[str, pd.DataFrame]
    ) -> None:
        # Only DataFrame-backed (data-source alias) inputs are column-gated;
        # an input referencing a PRIOR step's dict output_key has no columns
        # to check and is validated instead at transform-execution time
        # (_run_transforms_or_raise raises stage="transform" if truly missing).
        errors: list[RecipeRunError] = []
        for step in recipe.transforms:
            frame_backed_step = TransformStep(
                transformer=step.transformer,
                inputs=[alias for alias in step.inputs if alias in frames],
                params=step.params,
                output_key=step.output_key,
            )
            errors.extend(validate_inputs(frame_backed_step, frames, recipe_name=recipe.name))
        if errors:
            raise RecipeRunException(errors[0])

    def _run_transforms_or_raise(
        self,
        recipe: InfographicRecipe,
        frames: dict[str, pd.DataFrame],
        resolved_params: dict[str, str],
    ) -> dict[str, Any]:
        data_model: dict[str, Any] = {}
        for step in recipe.transforms:
            step_inputs: dict[str, Any] = {}
            for alias in step.inputs:
                if alias in frames:
                    step_inputs[alias] = frames[alias]
                elif alias in data_model:
                    step_inputs[alias] = data_model[alias]
                else:
                    raise RecipeRunException(
                        RecipeRunError(
                            recipe=recipe.name,
                            stage="transform",
                            transformer=step.transformer,
                            detail=(
                                f"Input {alias!r} is neither a data-source alias nor a "
                                "prior step's output_key."
                            ),
                        )
                    )
            step_params = _substitute_value(step.params, resolved_params)
            try:
                registered = transformer_registry.get(step.transformer)
                result = registered(step_inputs, step_params)
            except Exception as exc:  # noqa: BLE001 - any transform failure is stage="transform"
                raise RecipeRunException(
                    RecipeRunError(
                        recipe=recipe.name,
                        stage="transform",
                        transformer=step.transformer,
                        detail=str(exc),
                    )
                ) from exc
            data_model[step.output_key] = result
        return data_model

    def _check_bind_drift_or_raise(
        self, recipe: InfographicRecipe, data_model: dict[str, Any]
    ) -> None:
        missing = sorted(
            {
                pointer
                for pointer in _collect_bind_pointers(recipe.layout.properties)
                if _pointer_top_key(pointer) not in data_model
            }
        )
        if missing:
            raise RecipeRunException(
                RecipeRunError(
                    recipe=recipe.name,
                    stage="layout",
                    detail=(
                        f"$bind pointer(s) {missing!r} reference key(s) absent from the "
                        f"assembled data_model (keys present: {sorted(data_model)!r})."
                    ),
                )
            )

    def _assemble_envelope_or_raise(self, recipe: InfographicRecipe, data_model: dict[str, Any]):
        layout = recipe.layout
        try:
            if layout.component == "Infographic":
                envelope = build_infographic(
                    title=layout.properties.get("title", recipe.title),
                    sections=layout.properties.get("sections", []),
                    subtitle=layout.properties.get("subtitle"),
                    theme=layout.properties.get("theme") or recipe.render.theme,
                    surface_id=f"{recipe.name}-infographic",
                    data_model=data_model,
                )
            else:
                envelope = build_surface(
                    layout.component,
                    layout.properties,
                    surface_id=f"{recipe.name}-{layout.component.lower()}",
                    data_model=data_model,
                )
        except CatalogValidationError as exc:
            raise RecipeRunException(
                RecipeRunError(recipe=recipe.name, stage="layout", detail=str(exc))
            ) from exc
        return envelope

    async def _render_or_raise(self, recipe: InfographicRecipe, envelope) -> RenderedArtifact:
        # Unknown/uninstalled renderer -> let ImportError propagate UNCHANGED
        # (acceptance criterion: "degrades with the existing actionable ImportError").
        renderer_cls = get_a2ui_renderer(recipe.render.profile)
        renderer = renderer_cls()
        try:
            return await renderer.render(envelope)
        except Exception as exc:  # noqa: BLE001 - any renderer failure is stage="render"
            raise RecipeRunException(
                RecipeRunError(recipe=recipe.name, stage="render", detail=str(exc))
            ) from exc

    async def _deliver_best_effort(self, recipe: InfographicRecipe, artifact: RenderedArtifact) -> None:
        # No RecipeRunError stage exists for delivery (spec's stage Literal is
        # params|data|gate|transform|layout|render) — delivery is intentionally
        # best-effort and never aborts an otherwise-successful run.
        if not recipe.render.delivery:
            return
        if self.owner is None:
            self.logger.warning(
                "Recipe %r declares render.delivery but no owner is configured on this "
                "RecipeRunner; skipping delivery.",
                recipe.name,
            )
            return
        delivery_kwargs = dict(recipe.render.delivery)
        delivery_kwargs.setdefault("artifact_store", self.artifact_store)
        try:
            await deliver_artifact(self.owner, artifact, **delivery_kwargs)
        except Exception:  # noqa: BLE001 - delivery failures are logged, not raised
            self.logger.exception("Delivery failed for recipe %r", recipe.name)
