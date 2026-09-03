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

**Auth inheritance caveat**: ``navigator_auth``'s ``@is_authenticated()``
applies via ``setattr`` on the decorated class's own methods.  When a
subclass overrides ``post``/``get``, the wrapped version on the parent is
shadowed and the auth check is silently lost.  Therefore this class
**re-applies** ``@is_authenticated()`` and ``@user_session()`` — matching
every other ``AgentTalk`` subclass (``AgentVoiceTalk``,
``InfographicTalk``, ``AgentTranscribeOnly``).  The internal
``_authenticate()`` helper is a *secondary* gate (agent resolution + 401
on missing ``user_id``); it is **not** a substitute for the decorator,
which performs real credential verification against the auth backends.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
from typing import Any

from aiohttp import web
from navconfig.logging import logging
from parrot.a2a.models import A2UI_MEDIA_TYPE
from navigator_auth.decorators import is_authenticated, user_session
from parrot.auth.permission import build_principal_context
from parrot.handlers.agent import AgentTalk
from parrot.handlers.models.ui_surfaces import PgUISurfaceStore
from parrot.handlers.ui_surfaces import (
    SurfaceNegotiationService,
    resolve_surface_access,
)
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


@is_authenticated()
@user_session()
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

        # `_get_user_session` returns the identity verbatim from the auth
        # backend, which may be non-string (navigator_auth stores an int
        # primary key). Everything downstream — the surface store key, the
        # `A2UICallContext`, the permission principal — expects a string, so
        # normalize once here rather than at each use site.
        return agent, str(user_id), session_id, None

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
                # FEAT-469 TASK-2575 (spec §3 Module 8, G3): thread the
                # surface state into this turn so tools invoked during it
                # receive it via the reserved `_a2ui_surface_state` kwarg.
                response = await agent.ask(
                    question=result.user_turn,
                    session_id=session_id,
                    user_id=user_id,
                    a2ui_surface_state=result.surface_state,
                )
                turn_envelope = getattr(response, "a2ui_envelope", None)
                if turn_envelope is not None:
                    messages.append(turn_envelope)

        if len(messages) == 1:
            return web.json_response(messages[0], status=200, content_type=A2UI_MEDIA_TYPE)
        return self.json_response({"messages": messages}, status=200)

    async def get(self) -> web.StreamResponse:
        """GET — SSE stream (default), the capabilities document (``/capabilities``),
        or the FEAT-492 surfaces mirror (``/surfaces/{surface_id}``).

        Path dispatch happens BEFORE any ``StreamResponse`` preparation —
        ``/capabilities`` and ``/surfaces/{surface_id}`` both return a plain
        ``web.Response``; only the default branch prepares an SSE stream.
        """
        if self.request.path.rstrip("/").endswith("/capabilities"):
            return await self._get_capabilities()
        if "surface_id" in self.request.match_info:
            return await self._get_surface()
        return await self._get_stream()

    async def _get_capabilities(self) -> web.Response:
        """GET .../a2ui/capabilities — the same document published on the Agent Card."""
        return self.json_response(agent_capabilities([DEFAULT_CATALOG_ID, BASIC_CATALOG_ID]), status=200)

    def _ui_surfaces_store(self) -> PgUISurfaceStore:
        """Reuse (or lazily create) the app-wide ``PgUISurfaceStore`` — shared
        with ``UISurfacesHandler`` via ``app["ui_surfaces_store"]`` so both
        routes hit the same store instance when mounted on the same app.
        """
        store = self.request.app.get("ui_surfaces_store")
        if store is None:
            store = PgUISurfaceStore()
            self.request.app["ui_surfaces_store"] = store
        return store

    def _ui_surfaces_negotiation(self) -> SurfaceNegotiationService:
        """Reuse (or lazily create) the app-wide ``SurfaceNegotiationService``
        — the SAME service ``UISurfacesHandler`` uses, so negotiation cannot
        drift between the REST lane and this mirror route.
        """
        service = self.request.app.get("ui_surfaces_negotiation")
        if service is None:
            service = SurfaceNegotiationService()
            self.request.app["ui_surfaces_negotiation"] = service
        return service

    async def _get_surface(self) -> web.Response:
        """GET .../a2ui/surfaces/{surface_id} — mirror of the ui_surfaces REST
        lane's negotiated GET (FEAT-492 TASK-2703, spec §3 Module 4, G6).

        Not protocol-strict: negotiates JSON/HTML exactly like
        ``UISurfacesHandler`` via the SAME ``SurfaceNegotiationService``
        instance (resolved decision — spec §2). ``agent_id`` is resolved via
        the existing ``_authenticate()`` for auth/consistency with every
        other route on this handler, but the surface lookup itself is by
        ``surface_id`` alone (same as the REST lane).
        """
        _agent, user_id, _session_id, err = await self._authenticate(self._resolution_data())
        if err is not None:
            return err

        surface_id = self.request.match_info["surface_id"]
        qs = self.query_parameters(self.request)
        token = qs.get("share")

        record, error = await resolve_surface_access(self._ui_surfaces_store(), surface_id, user_id, token)
        if error is not None:
            message, status = error
            return self.json_response({"status": "error", "message": message}, status=status)

        negotiation = self._ui_surfaces_negotiation()
        accept = negotiation.negotiate(self.request)
        return await negotiation.respond(record, accept)

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
