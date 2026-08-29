"""``A2UIHandler`` — dedicated HTTP transport for A2UI R->A envelopes (FEAT-469
TASK-2573, spec §3 Module 6, goal G6).

A renderer talking directly to an agent (not through A2A) posts renderer->agent
envelopes here, at ``/api/v1/agents/{agent_id}/a2ui``. This is a **separate**
endpoint from ``AgentTalk`` (spec §8 explicitly rejected routing A2UI envelopes
through the AgentTalk POST) — it inherits ``AgentTalk`` ONLY to reuse its
``_resolve_bot``/``_get_user_session`` agent/user/session resolution methods
(spec §7: "reutiliza la resolución de agente/usuario/sesión de
AgentTalk._get_user_session"); ``post``/``get`` are fully overridden with A2UI's
own request/response shape — nothing else of AgentTalk's behavior is inherited
in practice.

Security note (spec §8 resolved OQ): ``AgentTalk`` never builds a
``PermissionContext`` at all (``grep -rn "PermissionContext(" packages/*/src``
proves it). Since G7 makes ``permission_context`` the *only* barrier before a
renderer can invoke ANY ToolManager tool, this handler builds one via
:func:`~parrot.auth.permission.build_principal_context`. ``roles`` defaults to
an empty ``frozenset()`` there, so role-gated PBAC policies **deny by
default** — the safe direction for a renderer-invocable surface, at the cost
of requiring real role claims to be threaded in before a role-gated tool will
work here.

Transport stays thin (spec §7): authenticate -> build context -> ``dispatch``
-> serialize. All protocol decisions live in :class:`A2UIRuntime`.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
from typing import Any

from aiohttp import web
from navconfig.logging import logging
from parrot.a2a.models import A2UI_MEDIA_TYPE
from parrot.auth.permission import build_principal_context
from parrot.handlers.agent import AgentTalk
from parrot.outputs.a2ui.catalog.base import DEFAULT_CATALOG_ID
from parrot.outputs.a2ui.catalog.basic import BASIC_CATALOG_ID
from parrot.outputs.a2ui.catalog.export import agent_capabilities
from parrot.outputs.a2ui.models import CallRendererFunction, FunctionCall
from parrot.outputs.a2ui.runtime.adapters import (
    ConversationMemorySurfaceStore,
    ToolManagerExecutor,
)
from parrot.outputs.a2ui.runtime.dispatch import A2UIRuntime
from parrot.outputs.a2ui.runtime.models import (
    A2UICallContext,
    A2UIErrorCode,
    error_envelope,
)
from parrot.outputs.a2ui.serialization import iter_jsonl, serialize

__all__ = ["A2UIHandler"]

logger = logging.getLogger(__name__)

#: How often to send an SSE keepalive comment while streaming (seconds).
_SSE_KEEPALIVE_SECONDS = 15.0


class A2UIHandler(AgentTalk):
    """HTTP transport for A2UI Agent Functions (spec §3 Module 6).

    Inherits ``AgentTalk`` only for ``_resolve_bot``/``_get_user_session``
    (agent/user/session resolution) — ``post``/``get`` are entirely A2UI's own.

    Routes (registered in ``manager.py``):
        ``POST /api/v1/agents/{agent_id}/a2ui``: dispatch one R->A envelope
            (or a JSONL/list of envelopes) and return the A->R response(s).
        ``GET /api/v1/agents/{agent_id}/a2ui``: SSE stream of queued
            ``callRendererFunction`` envelopes for the session.
        ``GET /api/v1/agents/{agent_id}/a2ui/capabilities``: the
            :func:`~parrot.outputs.a2ui.catalog.export.agent_capabilities`
            document (same one published on the Agent Card, spec §8).
    """

    def _resolution_data(self) -> dict[str, Any]:
        """Build the ``data`` dict ``_resolve_bot``/``_get_user_session`` expect.

        Unlike AgentTalk's POST, the A2UI request body is a protocol-strict
        envelope (``extra="forbid"``) with no room for ``user_id``/
        ``session_id``/``agent_name`` keys — those are read from the query
        string instead, feeding the SAME priority-ordered resolution methods
        (``_get_agent_name`` already checks ``request.match_info`` first;
        ``_get_user_session`` falls back to the authenticated request/session
        context when neither is supplied here).
        """
        qs = self.query_parameters(self.request)
        data: dict[str, Any] = {}
        if "user_id" in qs:
            data["user_id"] = qs["user_id"]
        if "session_id" in qs:
            data["session_id"] = qs["session_id"]
        if "agent_name" in qs:
            data["agent_name"] = qs["agent_name"]
        return data

    async def _authenticate(self, data: dict[str, Any]):
        """Resolve the agent + user/session, or return an error ``web.Response``.

        Returns:
            ``(agent, user_id, session_id, error_response)`` — exactly one of
            ``agent``/``error_response`` is not ``None``. ``error_response``
            covers both "agent not found" (404, from ``_resolve_bot``) and
            "no authenticated user" (401 — spec §7: the first line of defence,
            since every ToolManager tool is exposed).
        """
        agent, _is_user_bot = await self._resolve_bot(data)
        if isinstance(agent, web.Response):
            return None, None, None, agent
        if agent is None:
            return None, None, None, self.error({"error": "Agent not found."}, status=404)

        user_id, session_id = await self._get_user_session(data)
        if not user_id:
            return None, None, None, self.error({"error": "Authentication required."}, status=401)

        return agent, user_id, session_id, None

    @staticmethod
    def _build_runtime(agent, user_id: str) -> tuple[A2UIRuntime, ConversationMemorySurfaceStore]:
        store = ConversationMemorySurfaceStore(agent.conversation_memory, user_id=user_id)
        executor = ToolManagerExecutor(agent.tool_manager)
        return A2UIRuntime(executor=executor, surfaces=store, pending=store), store

    async def post(self) -> web.Response:
        """POST /api/v1/agents/{agent_id}/a2ui — dispatch one or more R->A envelopes."""
        raw_body = await self.request.text()
        agent, user_id, session_id, err = await self._authenticate(self._resolution_data())
        if err is not None:
            return err

        try:
            envelopes = list(iter_jsonl(raw_body)) if raw_body.strip() else []
        except (ValueError, TypeError, json.JSONDecodeError):
            # Not a valid JSONL body (e.g. a genuine top-level JSON array, or a
            # single envelope that failed validation): fall back to plain JSON
            # parsing and hand raw dicts to `dispatch()`, whose own guard
            # produces a proper `error` envelope for anything invalid — never
            # hand-rolled JSON (spec §7).
            try:
                parsed = json.loads(raw_body)
            except json.JSONDecodeError:
                return self.json_response(
                    error_envelope(
                        A2UIErrorCode.INVALID_FUNCTION_CALL, "Malformed JSON body.", function_call_id="unknown"
                    ),
                    status=400,
                )
            envelopes = parsed if isinstance(parsed, list) else [parsed]

        if not envelopes:
            return self.json_response(
                error_envelope(A2UIErrorCode.INVALID_FUNCTION_CALL, "Empty request body.", function_call_id="unknown"),
                status=400,
            )

        permission_context = build_principal_context(principal=user_id, channel="a2ui")
        runtime, _store = self._build_runtime(agent, user_id)

        messages: list[dict] = []
        for envelope in envelopes:
            ctx = A2UICallContext(
                agent_id=agent.name,
                user_id=user_id,
                session_id=session_id,
                transport="http",
                streaming=False,
                permission_context=permission_context,
            )
            result = await runtime.dispatch(envelope, ctx)

            is_sole_error = len(result.messages) == 1 and "error" in result.messages[0] and result.user_turn is None
            if is_sole_error and len(envelopes) == 1:
                return self.json_response(result.messages[0], status=400)

            messages.extend(result.messages)

            if result.user_turn is not None:
                response = await agent.ask(question=result.user_turn, session_id=session_id, user_id=user_id)
                turn_envelope = getattr(response, "a2ui_envelope", None)
                if turn_envelope is not None:
                    messages.append(turn_envelope)

        if len(messages) == 1:
            return web.json_response(messages[0], status=200, content_type=A2UI_MEDIA_TYPE)
        return self.json_response({"messages": messages}, status=200)

    async def get(self) -> web.StreamResponse:
        """GET — SSE stream (default path) or the capabilities document (``/capabilities``)."""
        if self.request.path.rstrip("/").endswith("/capabilities"):
            return await self._get_capabilities()
        return await self._get_stream()

    async def _get_capabilities(self) -> web.Response:
        """GET .../a2ui/capabilities — the same document published on the Agent Card."""
        return self.json_response(agent_capabilities([DEFAULT_CATALOG_ID, BASIC_CATALOG_ID]), status=200)

    async def _get_stream(self) -> web.StreamResponse:
        """GET — SSE stream of queued ``callRendererFunction`` envelopes for the session.

        Standard ``text/event-stream`` framing — NEVER the AgentTalk
        ``b'\\n\\x00'`` chunked-AIMessage separator (spec §7: that format is
        AgentTalk's own, not a shared convention).
        """
        agent, user_id, session_id, err = await self._authenticate(self._resolution_data())
        if err is not None:
            return err

        response = web.StreamResponse(headers={"Content-Type": "text/event-stream", "Cache-Control": "no-cache"})
        await response.prepare(self.request)

        _runtime, store = self._build_runtime(agent, user_id)
        try:
            while True:
                delivered_any = False
                for record in await store.list_undelivered(session_id):
                    envelope = serialize(
                        CallRendererFunction(
                            functionCallId=record.function_call_id,
                            callFunction=FunctionCall(call=record.call, args=record.args, catalogId=record.catalog_id),
                        )
                    )
                    # `write()` raising (client disconnect) skips `mark_delivered`
                    # entirely — the record stays undelivered so a later stream
                    # can still deliver it, never consumed-but-lost. Caught by
                    # the outer try/except below.
                    await response.write(f"data: {json.dumps(envelope)}\n\n".encode())
                    await store.mark_delivered(session_id, record.function_call_id)
                    delivered_any = True

                if not delivered_any:
                    await response.write(b": keepalive\n\n")
                await asyncio.sleep(_SSE_KEEPALIVE_SECONDS)
        except (ConnectionResetError, asyncio.CancelledError):
            self.logger.info("A2UI SSE stream closed for session %s", session_id)
        finally:
            with contextlib.suppress(Exception):
                await response.write_eof()
        return response
