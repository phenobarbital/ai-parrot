"""Turn a chat turn into a refreshable linked widget without an LLM round-trip (FEAT-757)."""

from __future__ import annotations

from typing import Any

from pydantic import Field

from parrot.outputs.a2ui.linked import has_data_sources
from parrot.outputs.a2ui.linked.materialize import (
    REASON_BUILD_FAILED,
    REASON_MULTI_SOURCE_TURN,
    REASON_NO_ENVELOPE,
    REASON_NO_PUBLISH_SURFACE,
    REASON_NO_QUERYSOURCE_TOOLKIT,
    REASON_NO_SLUG_ORIGIN,
    REASON_PIN_FAILED,
    REASON_TURN_NOT_FOUND,
    REASON_UNSUPPORTED_COMPONENT,
    MaterializeWidgetResult,
    component_from_envelope,
    extract_slug_origin,
)
from parrot.tools.abstract import AbstractTool, AbstractToolArgsSchema

__all__ = ["MaterializeWidgetArgs", "MaterializeWidgetTool"]

BUILD_TOOL = "qs_build_linked_surface"
PUBLISH_TOOL = "publish_surface"


class MaterializeWidgetArgs(AbstractToolArgsSchema):
    """Arguments for materializing a chat turn as a linked widget."""

    turn_id: str = Field(description="The chat turn whose answer should become a refreshable widget.")
    envelope: dict[str, Any] | None = Field(
        default=None, description="The a2ui_envelope that turn displayed (the chat bubble already holds it)."
    )
    session_id: str | None = Field(default=None, description="Session of the turn; defaults to the bound session.")
    title: str | None = Field(default=None, description="Title for the pinned widget; defaults to the turn question.")
    pin: bool = Field(default=False, description="Also persist the linked widget as a refreshable pinned surface.")
    snapshot: bool = Field(
        default=False, description="Embed current rows (share links / offline export only); default definition-only."
    )


class MaterializeWidgetTool(AbstractTool):
    """Turn a previous chat answer (a chart, table or KPI) into a refreshable linked widget.

    Use it when the user asks to keep, pin or save an answer "so it stays up to date". Pass the ``turn_id`` of
    that answer and the envelope it displayed. The tool replays nothing through the model: it reads which query
    produced the data and rebuilds the same widget bound to that query. Set ``pin`` to also save it.
    """

    name = "materialize_widget"
    description = (
        "Turn a previous chat answer (chart, table or KPI) into a refreshable linked widget, optionally pinned. "
        "Pass turn_id and the envelope it displayed; no new query is invented."
    )
    args_schema = MaterializeWidgetArgs

    def __init__(
        self,
        bot: Any = None,
        user_id: str | None = None,
        session_id: str | None = None,
        **kwargs: Any,
    ) -> None:
        """Bind the tool to the agent whose turns and sibling tools it uses.

        Args:
            bot: The agent (provides ``conversation_memory``, ``memory_key_id`` and ``tool_manager``).
            user_id: Fallback identity when no permission context is present (direct Python use).
            session_id: Fallback session when the call does not pass one.
        """
        super().__init__(**kwargs)
        self._bot = bot
        self._user_id = user_id
        self._session_id = session_id

    async def _execute(
        self,
        *,
        turn_id: str,
        envelope: dict[str, Any] | None = None,
        session_id: str | None = None,
        title: str | None = None,
        pin: bool = False,
        snapshot: bool = False,
        **kwargs: Any,
    ) -> dict[str, Any]:
        # Snapshot once: ``_current_pctx`` is shared, unlocked per-instance state and is cleared by
        # ``execute``'s ``finally``; never re-read it after an await (concurrent users share this tool).
        pctx = self._current_pctx
        result = await self._materialize(pctx, turn_id, envelope, session_id, title, pin, snapshot)
        self.logger.info("materialize_widget turn=%s status=%s reason=%s", turn_id, result.status, result.reason)
        return result.model_dump(mode="json")

    async def _materialize(
        self,
        pctx: Any,
        turn_id: str,
        envelope: dict[str, Any] | None,
        session_id: str | None,
        title: str | None,
        pin: bool,
        snapshot: bool,
    ) -> MaterializeWidgetResult:
        """Run the spec pipeline; every early exit is a typed result except authorization errors."""
        turn = await self._find_turn(pctx, turn_id, session_id or self._session_id)
        if turn is None:
            return MaterializeWidgetResult(status="not_materializable", reason=REASON_TURN_NOT_FOUND)
        if not envelope:
            return MaterializeWidgetResult(status="not_materializable", reason=REASON_NO_ENVELOPE)

        origin_outcome = extract_slug_origin(turn.tool_invocations)
        if origin_outcome.kind == "already_linked":
            return MaterializeWidgetResult(
                status="already_linked",
                a2ui_envelope=envelope,
                refreshable=has_data_sources(envelope),
            )
        if origin_outcome.kind == "multi_source":
            return MaterializeWidgetResult(status="not_materializable", reason=REASON_MULTI_SOURCE_TURN)
        if origin_outcome.kind == "none" or origin_outcome.origin is None:
            return MaterializeWidgetResult(status="snapshot_only", reason=REASON_NO_SLUG_ORIGIN)

        component = component_from_envelope(envelope)
        if component is None:
            return MaterializeWidgetResult(status="snapshot_only", reason=REASON_UNSUPPORTED_COMPONENT)

        origin = origin_outcome.origin
        builder = self._sibling(BUILD_TOOL)
        if builder is None:
            return MaterializeWidgetResult(status="not_materializable", reason=REASON_NO_QUERYSOURCE_TOOLKIT)
        build_result = await builder.execute(
            slug=origin.slug,
            component=component,
            request=origin.request or None,
            tenant=origin.tenant,
            snapshot=snapshot,
            _permission_context=pctx,
        )
        build_payload = getattr(build_result, "result", None)
        built_envelope = build_payload.get("a2ui_envelope") if isinstance(build_payload, dict) else None
        if not getattr(build_result, "success", False) or not isinstance(built_envelope, dict):
            return MaterializeWidgetResult(
                status="not_materializable",
                reason=REASON_BUILD_FAILED,
                message=getattr(build_result, "error", None),
                origin=origin,
            )

        artifacts = build_payload.get("artifacts", [])
        if not isinstance(artifacts, list):
            artifacts = []
        surface_id: str | None = None
        pinned = False
        reason: str | None = None
        message: str | None = None
        if pin:
            publisher = self._sibling(PUBLISH_TOOL)
            if publisher is None:
                reason = REASON_NO_PUBLISH_SURFACE
            else:
                publish_result = await publisher.execute(
                    kind="widget",
                    title=title or turn.user_message[:80],
                    envelope=built_envelope,
                    _permission_context=pctx,
                )
                publish_payload = getattr(publish_result, "result", None)
                candidate_surface_id = publish_payload.get("surface_id") if isinstance(publish_payload, dict) else None
                if getattr(publish_result, "success", False) and isinstance(candidate_surface_id, str):
                    surface_id = candidate_surface_id
                    pinned = True
                else:
                    reason = REASON_PIN_FAILED
                    message = getattr(publish_result, "error", None)

        return MaterializeWidgetResult(
            status="materialized",
            reason=reason,
            message=message,
            a2ui_envelope=built_envelope,
            artifacts=artifacts,
            surface_id=surface_id,
            pinned=pinned,
            refreshable=has_data_sources(built_envelope),
            origin=origin,
        )

    async def _find_turn(self, pctx: Any, turn_id: str, session_id: str | None) -> Any:
        """Return the caller's conversation turn, or None when it cannot be resolved safely."""
        user_id = getattr(pctx, "user_id", None) if pctx is not None else None
        user_id = user_id or self._user_id
        memory = getattr(self._bot, "conversation_memory", None)
        if not user_id or not session_id or memory is None:
            return None
        history = await memory.get_history(
            user_id,
            session_id,
            chatbot_id=getattr(self._bot, "memory_key_id", None),
        )
        if history is None:
            return None
        return next((turn for turn in history.turns if turn.turn_id == turn_id), None)

    def _sibling(self, name: str) -> Any:
        """Look up a sibling tool on the bot's ToolManager without importing its toolkit."""
        manager = getattr(self._bot, "tool_manager", None)
        return manager.get_tool(name) if manager is not None else None
