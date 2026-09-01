"""``PublishSurfaceTool`` — LLM-invocable wrapper over
``InfographicAuthoringMixin.publish_surface()`` (FEAT-492, TASK-2704).

A thin tool: when bound to a mixin-composed bot (via the ``bot=`` constructor
kwarg), delegates straight to ``bot.publish_surface(...)`` — the SAME
injection seam (explicit ``surface_store`` > bound attribute > lazy-import
``PgUISurfaceStore``) the mixin itself resolves. When no such bot is bound
(headless/standalone use), falls back to persisting directly against a store
using the identical row shape, so both lanes stay in lockstep.

Reachable via the legacy import path too — ``parrot.tools`` redirects any
non-core submodule name to ``parrot_tools`` (see ``parrot/tools/__init__.py``
meta_path finder): ``from parrot.tools.ui_surfaces import PublishSurfaceTool``
resolves to this module.
"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from parrot.outputs.a2ui.models import CreateSurface
from parrot.tools.abstract import AbstractTool, AbstractToolArgsSchema
from pydantic import Field

__all__ = ["PublishSurfaceArgs", "PublishSurfaceTool"]


class PublishSurfaceArgs(AbstractToolArgsSchema):
    """Arguments for persisting a rehydratable A2UI surface."""

    kind: str = Field(
        description="Surface kind: 'dashboard', 'infographic', or 'widget'."
    )
    title: str = Field(description="Human-readable surface title.")
    envelope: dict[str, Any] = Field(
        description=(
            "The CreateSurface envelope to persist (surfaceId/components/"
            "dataModel/... — the same dump shape produced by baking.py's "
            "persist_envelope)."
        )
    )
    recipe_name: str | None = Field(
        default=None,
        description=(
            "When set, the surface becomes refreshable: this recipe is "
            "replayed on POST .../refresh."
        ),
    )
    recipe_owner: str | None = Field(
        default=None,
        description="Owner scope the recipe was saved under (must match publish_recipe's owner).",
    )
    recipe_params: dict[str, Any] | None = Field(
        default=None,
        description="Params snapshot used to produce this envelope — the refresh lane's stored precedence tier.",
    )
    overwrite: bool = Field(
        default=False,
        description="Replace an existing surface_id row instead of raising on collision.",
    )


class PublishSurfaceTool(AbstractTool):
    """Persist a rehydratable A2UI surface so it can be fetched later at a
    bookmarkable URL (``GET /api/v1/ui/surfaces/{surface_id}``), outside the
    conversation that produced it.

    Pass ``kind``, ``title``, and the ``envelope`` to save. Optionally pass
    ``recipe_name``/``recipe_owner``/``recipe_params`` to make the surface
    *refreshable* — a later ``POST .../refresh`` re-runs that recipe and
    updates this same row in place, rather than replaying nothing at all.
    """

    name = "publish_surface"
    description = (
        "Persist a rehydratable A2UI surface (dashboard, infographic, or "
        "widget) so it can be fetched later at a bookmarkable URL, outside "
        "the current conversation. Pass kind, title, and envelope; "
        "optionally recipe_name/recipe_owner/recipe_params to make it "
        "refreshable."
    )
    args_schema = PublishSurfaceArgs

    def __init__(
        self,
        bot: Any = None,
        surface_store: Any = None,
        agent_id: str | None = None,
        user_id: str | None = None,
        session_id: str | None = None,
        **kwargs: Any,
    ) -> None:
        """Construct the tool.

        Args:
            bot: The mixin-composed bot to delegate to (preferred lane).
                When it exposes ``publish_surface`` (i.e., composed with
                ``InfographicAuthoringMixin``), every call is forwarded there.
            surface_store: Injection seam forwarded to the bot's
                ``publish_surface(surface_store=...)`` — or used directly by
                the standalone fallback lane when no ``bot`` is bound.
            agent_id: Attribution for the standalone fallback lane only (the
                bot lane derives this from ``bot.name`` itself).
            user_id: Attribution for the standalone fallback lane only.
            session_id: Attribution for the standalone fallback lane only.
        """
        super().__init__(**kwargs)
        self._bot = bot
        self._surface_store = surface_store
        self._agent_id = agent_id
        self._user_id = user_id
        self._session_id = session_id

    async def _execute(
        self,
        *,
        kind: str,
        title: str,
        envelope: dict[str, Any],
        recipe_name: str | None = None,
        recipe_owner: str | None = None,
        recipe_params: dict | None = None,
        overwrite: bool = False,
        **kwargs: Any,
    ) -> dict[str, Any]:
        if self._bot is not None and hasattr(self._bot, "publish_surface"):
            surface_id = await self._bot.publish_surface(
                kind=kind,
                title=title,
                envelope=envelope,
                recipe_name=recipe_name,
                recipe_owner=recipe_owner,
                recipe_params=recipe_params,
                overwrite=overwrite,
                surface_store=self._surface_store,
                user_id=self._user_id,
                session_id=self._session_id,
            )
        else:
            surface_id = await self._publish_directly(
                kind=kind,
                title=title,
                envelope=envelope,
                recipe_name=recipe_name,
                recipe_owner=recipe_owner,
                recipe_params=recipe_params,
                overwrite=overwrite,
            )
        return {
            "surface_id": surface_id,
            "kind": kind,
            "refreshable": recipe_name is not None,
        }

    async def _publish_directly(
        self,
        *,
        kind: str,
        title: str,
        envelope: dict[str, Any],
        recipe_name: str | None,
        recipe_owner: str | None,
        recipe_params: dict | None,
        overwrite: bool,
    ) -> str:
        """Standalone fallback when no mixin-composed bot is bound.

        Same injection seam as ``InfographicAuthoringMixin.publish_surface``
        (TASK-2704): explicit ``surface_store`` > lazy-import
        ``PgUISurfaceStore``. Raises an actionable ``RuntimeError`` — never a
        bare ``ModuleNotFoundError`` — when ai-parrot-server is unavailable
        and no store was injected.
        """
        try:
            from parrot.handlers.models.ui_surfaces import (
                PgUISurfaceStore,
                UISurfaceKind,
                UISurfaceRecord,
            )
        except ImportError as exc:
            raise RuntimeError(
                "publish_surface requires the ai-parrot-server package (for "
                "PgUISurfaceStore/UISurfaceRecord/UISurfaceKind) when no "
                "mixin-composed bot is bound. Install/enable ai-parrot-server, "
                "or pass surface_store= to the tool constructor."
            ) from exc

        envelope_model = CreateSurface.model_validate(envelope)
        surface_id = envelope_model.surface_id or uuid.uuid4().hex
        store = self._surface_store if self._surface_store is not None else PgUISurfaceStore()
        agent_id = self._agent_id or "publish_surface_tool"
        user_id = self._user_id or agent_id

        now = datetime.now(UTC)
        record = UISurfaceRecord(
            surface_id=surface_id,
            kind=UISurfaceKind(kind),
            title=title,
            envelope=envelope_model.model_dump(by_alias=True, mode="json"),
            catalog_id=envelope_model.catalog_id,
            agent_id=agent_id,
            user_id=user_id,
            session_id=self._session_id,
            recipe_name=recipe_name,
            recipe_owner=recipe_owner,
            recipe_params=recipe_params or {},
            created_at=now,
            updated_at=now,
        )
        return await store.save(record, overwrite=overwrite)
