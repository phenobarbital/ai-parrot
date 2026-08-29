"""Concrete adapters over ``ToolManager``/``ConversationMemory`` (spec §3 Module 3).

``ToolManagerExecutor`` and ``ConversationMemorySurfaceStore`` are the real
implementations of the ``FunctionExecutor``/``SurfaceStateStore``/
``PendingCallRegistry`` ``Protocol``s declared in
:mod:`parrot.outputs.a2ui.runtime`. They live under ``runtime/`` but DO touch
``parrot.tools``/``parrot.memory`` — the G8 one-way import rule is preserved
by importing those modules **lazily, inside method bodies** (never at module
level). :data:`typing.TYPE_CHECKING` is used only for type-hint purposes,
which is erased at runtime.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

from parrot.outputs.a2ui.catalog import DEFAULT_CATALOG_ID
from parrot.outputs.a2ui.catalog.base import FunctionDefinition
from parrot.outputs.a2ui.runtime.models import (
    A2UICallContext,
    FunctionCallRecord,
    SurfaceState,
)

if TYPE_CHECKING:  # pragma: no cover - import-rule guard (G8)
    from parrot.memory.abstract import ConversationHistory, ConversationMemory
    from parrot.tools.abstract import ToolResult
    from parrot.tools.manager import ToolManager

__all__ = ["ConversationMemorySurfaceStore", "ToolManagerExecutor"]

logger = logging.getLogger(__name__)

#: Metadata key holding ``{surface_id: SurfaceState.model_dump(mode="json")}``.
_SURFACES_KEY = "a2ui_surfaces"

#: Metadata key holding ``{function_call_id: FunctionCallRecord.model_dump(mode="json")}``.
_PENDING_KEY = "a2ui_pending_calls"


class ToolManagerExecutor:
    """``FunctionExecutor`` over a ``ToolManager`` (spec G1/G7).

    Args:
        tool_manager: The agent's tool registry.
    """

    def __init__(self, tool_manager: ToolManager) -> None:
        self._tool_manager = tool_manager
        self.logger = logging.getLogger(__name__)

    async def call(self, name: str, args: dict[str, Any], ctx: A2UICallContext) -> ToolResult:
        """Execute ``name`` via ``ToolManager.execute_tool``, always passing ``permission_context``.

        Args:
            name: The tool/function name to invoke.
            args: Arguments for the call.
            ctx: The A2UI call context; ``ctx.permission_context`` is the
                *only* authorization barrier (spec G7 — every ToolManager
                tool is invocable, opt-out only via ``a2ui_hidden``).

        Returns:
            A normalized :class:`~parrot.tools.abstract.ToolResult` — even
            when ``ToolManager.execute_tool`` returned a raw, unwrapped value
            (the ``ToolDefinition``/``@tool`` path).
        """
        from parrot.tools.manager import ToolDefinition

        tool = self._tool_manager.get_tool(name)
        if isinstance(tool, ToolDefinition):
            self.logger.warning(
                "A2UI callAgentFunction %r targets a ToolDefinition (@tool-decorated) "
                "function: ToolManager.execute_tool() does not enforce permission_context "
                "on this path (manager.py ~1530-1535). This is a known G7 gap, not fixed "
                "by this adapter — see FEAT-469 TASK-2570 completion note.",
                name,
            )

        raw = await self._tool_manager.execute_tool(name, args, permission_context=ctx.permission_context)
        result = self._normalize(raw)

        # Audit log — the only forensic record that a renderer invoked a tool
        # (spec §7 "Superficie de ataque").
        self.logger.info(
            "a2ui_audit agent_id=%s user_id=%s call=%s status=%s",
            ctx.agent_id,
            ctx.user_id,
            name,
            result.status,
        )
        return result

    def _normalize(self, raw: Any) -> ToolResult:
        """Normalize ``ToolManager.execute_tool``'s ``Any`` return into a ``ToolResult``.

        The ``ToolDefinition``/``@tool`` path returns the function's raw
        return value rather than a ``ToolResult`` (``manager.py`` ~1554-1557).
        """
        from parrot.tools.abstract import ToolResult

        if isinstance(raw, ToolResult):
            return raw
        return ToolResult(success=True, status="success", result=raw)

    def list_functions(self) -> list[FunctionDefinition]:
        """Return catalog-shaped :class:`FunctionDefinition`\\ s for every registered tool.

        Mechanical derivation only — UAX #31 name sanitization, cross-source
        collision detection, and the final ``export_functions()`` merge with
        the Basic Catalog's own functions are TASK-2571's job
        (``catalog/export.py``). ``a2ui_hidden``/``a2ui_requires_user_activation``
        are read defensively via ``getattr`` (default ``False``) since
        TASK-2571 is what actually adds those ``AbstractTool`` attributes —
        until then this is a no-op, and no tool is ever excluded here.
        """
        definitions: list[FunctionDefinition] = []
        for schema in self._tool_manager.get_tool_schemas():
            tool_instance = schema.get("_tool_instance")
            if getattr(tool_instance, "a2ui_hidden", False):
                continue
            definitions.append(
                FunctionDefinition(
                    name=schema.get("name", ""),
                    catalog_id=DEFAULT_CATALOG_ID,
                    args_schema=schema.get("parameters", {}),
                    return_type="any",
                    allowed_callers="rendererOrAgent",
                    requires_user_activation=getattr(tool_instance, "a2ui_requires_user_activation", False),
                )
            )
        return definitions


class ConversationMemorySurfaceStore:
    """``SurfaceStateStore`` + ``PendingCallRegistry`` over ``ConversationHistory.metadata``.

    One class implements both Protocols because both pieces of state are
    session-scoped and there is no dedicated metadata API on
    ``ConversationMemory`` — everything goes through
    ``get_history()``/``update_history()`` (read-modify-write).

    Concurrency (spec §7 "Concurrencia en memoria"): ``RedisConversation``
    exposes no atomic compare-and-set/pipeline primitive for a partial
    metadata update (verified: no ``pipeline``/``WATCH``/transaction method
    on ``parrot/memory/redis.py``). This adapter therefore serializes
    read-modify-write with a per-``session_id`` ``asyncio.Lock``. This is a
    **process-local** mitigation only — it does not protect a multi-worker
    deployment where two processes race the same session concurrently. See
    the completion note for the escalation.

    Args:
        memory: The conversation memory backend.
        user_id: The user id — required to resolve a ``ConversationHistory``
            (``ConversationMemory.get_history`` takes ``user_id`` positionally;
            the ``SurfaceStateStore``/``PendingCallRegistry`` Protocols only
            carry ``session_id``, so ``user_id`` is bound at construction
            time. Construct one instance per request/user.).
        chatbot_id: Optional chatbot id, passed through to ``get_history``.
    """

    def __init__(self, memory: ConversationMemory, user_id: str, chatbot_id: str | None = None) -> None:
        self._memory = memory
        self._user_id = user_id
        self._chatbot_id = chatbot_id
        self._locks: dict[str, asyncio.Lock] = {}
        self.logger = logging.getLogger(__name__)

    def _lock_for(self, session_id: str) -> asyncio.Lock:
        return self._locks.setdefault(session_id, asyncio.Lock())

    async def _load_history(self, session_id: str) -> ConversationHistory:
        history = await self._memory.get_history(self._user_id, session_id, self._chatbot_id)
        if history is None:
            history = await self._memory.create_history(self._user_id, session_id, chatbot_id=self._chatbot_id)
        return history

    # -- SurfaceStateStore ------------------------------------------------

    async def get(self, session_id: str, surface_id: str) -> SurfaceState | None:
        history = await self._load_history(session_id)
        raw = history.metadata.get(_SURFACES_KEY, {}).get(surface_id)
        if raw is None:
            return None
        return SurfaceState.model_validate(raw)

    async def put(self, session_id: str, state: SurfaceState) -> None:
        async with self._lock_for(session_id):
            history = await self._load_history(session_id)
            surfaces = dict(history.metadata.get(_SURFACES_KEY, {}))
            surfaces[state.surface_id] = state.model_dump(mode="json")
            history.metadata[_SURFACES_KEY] = surfaces
            await self._memory.update_history(history)

    async def delete(self, session_id: str, surface_id: str) -> None:
        async with self._lock_for(session_id):
            history = await self._load_history(session_id)
            surfaces = dict(history.metadata.get(_SURFACES_KEY, {}))
            surfaces.pop(surface_id, None)
            history.metadata[_SURFACES_KEY] = surfaces
            await self._memory.update_history(history)

    # -- PendingCallRegistry ------------------------------------------------

    @staticmethod
    def _sweep_expired(pending: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
        """Drop pending-call entries whose TTL has elapsed (lazy expiry, spec §7)."""
        now = datetime.now(UTC)
        alive: dict[str, dict[str, Any]] = {}
        for function_call_id, raw in pending.items():
            record = FunctionCallRecord.model_validate(raw)
            expires_at = record.created_at + timedelta(seconds=record.ttl_seconds)
            if now <= expires_at:
                alive[function_call_id] = raw
        return alive

    async def add(self, session_id: str, record: FunctionCallRecord) -> None:
        async with self._lock_for(session_id):
            history = await self._load_history(session_id)
            pending = self._sweep_expired(dict(history.metadata.get(_PENDING_KEY, {})))
            pending[record.function_call_id] = record.model_dump(mode="json")
            history.metadata[_PENDING_KEY] = pending
            await self._memory.update_history(history)

    async def resolve(
        self,
        session_id: str,
        function_call_id: str,
        value: Any,
        error: dict | None,
    ) -> FunctionCallRecord | None:
        async with self._lock_for(session_id):
            history = await self._load_history(session_id)
            pending = self._sweep_expired(dict(history.metadata.get(_PENDING_KEY, {})))
            raw = pending.pop(function_call_id, None)
            history.metadata[_PENDING_KEY] = pending
            await self._memory.update_history(history)

        if raw is None:
            return None

        self.logger.info(
            "a2ui_audit resolve session_id=%s function_call_id=%s ok=%s",
            session_id,
            function_call_id,
            error is None,
        )
        return FunctionCallRecord.model_validate(raw)
