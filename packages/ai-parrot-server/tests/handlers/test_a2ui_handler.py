"""``A2UIHandler`` tests (FEAT-469 TASK-2573)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from aiohttp import web
from navigator_session.data import SessionData
from parrot.a2a.models import A2UI_MEDIA_TYPE
from parrot.handlers.a2ui import A2UIHandler
from parrot.handlers.agent import AgentTalk
from parrot.memory.file import FileConversationMemory
from parrot.outputs.a2ui.catalog.base import DEFAULT_CATALOG_ID
from parrot.tools import tool
from parrot.tools.manager import ToolManager


@web.middleware
async def _stub_auth_middleware(request, handler):
    """Mark every test request as pre-authenticated and attach a minimal
    session so ``@is_authenticated()``/``@user_session()`` pass through."""
    request["authenticated"] = True
    request["NAV_SESSION"] = SessionData(data={"user_id": "u-test"})
    return await handler(request)


@tool
def get_weather(location: str) -> str:
    """Get the weather for a location."""
    return f"Weather in {location}: Sunny"


def _make_agent(tmp_path):
    tm = ToolManager()
    tm.register_tool(get_weather)
    agent = MagicMock()
    agent.name = "demo"
    agent.tool_manager = tm
    agent.conversation_memory = FileConversationMemory(base_path=str(tmp_path))
    reply = MagicMock()
    reply.a2ui_envelope = None
    agent.ask = AsyncMock(return_value=reply)
    return agent


def _bot_manager(agent):
    manager = MagicMock()
    manager.get_user_bot = AsyncMock(return_value=None)
    manager.get_bot = AsyncMock(return_value=agent)
    return manager


@pytest.fixture
async def client(aiohttp_client, tmp_path):
    agent = _make_agent(tmp_path)
    app = web.Application(middlewares=[_stub_auth_middleware])
    app["bot_manager"] = _bot_manager(agent)
    app["_test_agent"] = agent
    router = app.router
    router.add_view("/api/v1/agents/chat/{agent_id}", AgentTalk)
    router.add_view("/api/v1/agents/{agent_id}/a2ui/capabilities", A2UIHandler)
    router.add_view("/api/v1/agents/{agent_id}/a2ui", A2UIHandler)
    return await aiohttp_client(app)


def _auth_params(user_id="u-1", session_id="sess-1"):
    return {"user_id": user_id, "session_id": session_id}


def _call_agent_function(function_call_id="fc-1"):
    return {
        "version": "v1.0",
        "callAgentFunction": {
            "surfaceId": "s-1",
            "functionCallId": function_call_id,
            "callFunction": {"call": "get_weather", "args": {"location": "Caracas"}, "catalogId": DEFAULT_CATALOG_ID},
        },
    }


class TestPost:
    async def test_call_agent_function(self, client):
        r = await client.post("/api/v1/agents/demo/a2ui", json=_call_agent_function(), params=_auth_params())
        assert r.status == 200
        body = await r.json()
        assert body["agentFunctionResponse"]["functionCallId"] == "fc-1"

    async def test_invalid_envelope_returns_error_envelope(self, client):
        payload = {"version": "v1.0"}
        r = await client.post("/api/v1/agents/demo/a2ui", json=payload, params=_auth_params())
        assert r.status == 400
        body = await r.json()
        assert body["error"]["code"] == "INVALID_FUNCTION_CALL"

    async def test_secondary_gate_rejects_missing_user_id(self, aiohttp_client, tmp_path):
        """Even when ``@is_authenticated()`` passes, the secondary
        ``_authenticate()`` gate returns 401 if no ``user_id`` can be resolved
        from query params OR the session."""

        @web.middleware
        async def _auth_no_user(request, handler):
            request["authenticated"] = True
            request["NAV_SESSION"] = SessionData(data={})  # no user_id
            return await handler(request)

        agent = _make_agent(tmp_path)
        app = web.Application(middlewares=[_auth_no_user])
        app["bot_manager"] = _bot_manager(agent)
        app.router.add_view("/api/v1/agents/{agent_id}/a2ui", A2UIHandler)
        raw = await aiohttp_client(app)
        r = await raw.post("/api/v1/agents/demo/a2ui", json=_call_agent_function())
        assert r.status == 401

    async def test_int_user_id_from_session_is_coerced(self, aiohttp_client, tmp_path):
        """An auth backend storing an integer primary key must not 500.

        ``navigator_auth`` puts the DB ``user_id`` on the session as an
        ``int``; ``A2UICallContext.user_id`` is a ``str``, so the unconverted
        value used to raise a Pydantic ``string_type`` error out of ``post()``.
        """

        @web.middleware
        async def _auth_int_user(request, handler):
            request["authenticated"] = True
            request["NAV_SESSION"] = SessionData(data={"user_id": 35})
            return await handler(request)

        agent = _make_agent(tmp_path)
        app = web.Application(middlewares=[_auth_int_user])
        app["bot_manager"] = _bot_manager(agent)
        app.router.add_view("/api/v1/agents/{agent_id}/a2ui", A2UIHandler)
        raw = await aiohttp_client(app)
        r = await raw.post(
            "/api/v1/agents/demo/a2ui",
            json=_call_agent_function(),
            params={"session_id": "sess-1"},
        )
        assert r.status == 200
        body = await r.json()
        assert body["agentFunctionResponse"]["functionCallId"] == "fc-1"

    async def test_decorator_rejects_unauthenticated(self, aiohttp_client, tmp_path):
        """Without authentication, ``@is_authenticated()`` rejects before the
        handler code runs — the fix for the auth-bypass CVE.

        The exact status depends on ``navigator_auth``'s backend configuration
        (401 when backends are configured but reject; 400 when no backend is
        installed at all) — either way the request must not succeed.
        """
        agent = _make_agent(tmp_path)
        app = web.Application()  # no auth middleware
        app["bot_manager"] = _bot_manager(agent)
        app.router.add_view("/api/v1/agents/{agent_id}/a2ui", A2UIHandler)
        raw = await aiohttp_client(app)
        r = await raw.post(
            "/api/v1/agents/demo/a2ui",
            json=_call_agent_function(),
            params=_auth_params(),
        )
        assert r.status in (400, 401), f"Expected 400/401, got {r.status}"

    async def test_action_injects_turn(self, client):
        action_env = {
            "version": "v1.0",
            "action": {
                "name": "submit",
                "surfaceId": "s-1",
                "sourceComponentId": "btn-1",
                "timestamp": "2026-08-29T10:00:00Z",
                "context": {},
                "userMessage": "clicked",
            },
        }
        r = await client.post("/api/v1/agents/demo/a2ui", json=action_env, params=_auth_params(session_id="sess-2"))
        assert r.status == 200

    async def test_single_envelope_content_type(self, client):
        r = await client.post("/api/v1/agents/demo/a2ui", json=_call_agent_function(), params=_auth_params())
        assert r.headers["Content-Type"].startswith(A2UI_MEDIA_TYPE)


class TestStream:
    async def test_delivers_pending_call_renderer_function(self, client):
        import asyncio
        import json as _json

        from parrot.outputs.a2ui.runtime.adapters import (
            ConversationMemorySurfaceStore,
            ToolManagerExecutor,
        )
        from parrot.outputs.a2ui.runtime.dispatch import A2UIRuntime

        agent = client.app["_test_agent"]
        store = ConversationMemorySurfaceStore(agent.conversation_memory, user_id="u-1")
        runtime = A2UIRuntime(executor=ToolManagerExecutor(agent.tool_manager), surfaces=store, pending=store)
        function_call_id, _ = await runtime.call_renderer("sess-stream", "s-1", "openUrl", {"url": "https://x"})

        resp = await client.get("/api/v1/agents/demo/a2ui", params=_auth_params(session_id="sess-stream"))
        try:
            assert resp.status == 200
            assert resp.headers["Content-Type"].startswith("text/event-stream")
            line = await asyncio.wait_for(resp.content.readline(), timeout=5)
            assert line.startswith(b"data: ")
            payload = _json.loads(line[len(b"data: ") :])
            assert payload["callRendererFunction"]["functionCallId"] == function_call_id
        finally:
            resp.close()

    async def test_does_not_use_agenttalk_separator(self, client):
        import asyncio

        resp = await client.get("/api/v1/agents/demo/a2ui", params=_auth_params(session_id="sess-empty"))
        try:
            chunk = await asyncio.wait_for(resp.content.read(20), timeout=5)
            assert b"\n\x00" not in chunk
        finally:
            resp.close()


class TestCapabilities:
    async def test_matches_agent_card_document(self, client):
        from parrot.outputs.a2ui.catalog.basic import BASIC_CATALOG_ID
        from parrot.outputs.a2ui.catalog.export import agent_capabilities

        r = await client.get("/api/v1/agents/demo/a2ui/capabilities")
        assert r.status == 200
        body = await r.json()
        assert body == agent_capabilities([DEFAULT_CATALOG_ID, BASIC_CATALOG_ID])


class TestRouting:
    async def test_agenttalk_route_still_resolves(self, client):
        """{agent_id}/a2ui must not shadow chat/{agent_id}."""
        r = await client.post(
            "/api/v1/agents/chat/demo",
            json={"query": "hi", "user_id": "u-1", "session_id": "sess-3"},
        )
        assert r.status != 404
