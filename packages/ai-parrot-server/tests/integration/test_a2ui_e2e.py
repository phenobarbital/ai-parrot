"""FEAT-469 TASK-2576 — the five A2UI Agent Functions end-to-end tests
(spec §4 Integration Tests table).

Each test wires REAL components (a real `ToolManager` + `@tool`, a real
`FileConversationMemory`, a real `A2UIHandler`/`AgentTalk`/`A2AServer`/
`DeepLinkService`) — no fakes/mocks of the runtime itself. Per the task's
own instruction, a failing assertion here means a defect in the layer that
owns it (recorded in the Completion Note), never weakened to pass.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from aiohttp import web
from parrot.a2a.models import A2UI_MEDIA_TYPE, Message
from parrot.a2a.server import A2AServer
from parrot.handlers.a2ui import A2UIHandler
from parrot.handlers.deeplink import DeepLinkResumeHandler
from parrot.memory.file import FileConversationMemory
from parrot.outputs.a2ui.catalog.base import DEFAULT_CATALOG_ID
from parrot.outputs.a2ui.deeplink import DeepLinkService
from parrot.outputs.a2ui.runtime.adapters import (
    ConversationMemorySurfaceStore,
    ToolManagerExecutor,
)
from parrot.outputs.a2ui.runtime.dispatch import A2UIRuntime
from parrot.tools import tool
from parrot.tools.manager import ToolManager

pytestmark = pytest.mark.asyncio


@tool
def get_weather(location: str) -> str:
    """Return a canned weather report for the given location."""
    return f"Weather in {location}: Sunny, 25C"


class _FakeRedis:
    def __init__(self):
        self.store = {}

    async def set(self, key, value, ex=None):
        self.store[key] = value

    async def get(self, key):
        return self.store.get(key)

    async def delete(self, key):
        self.store.pop(key, None)


class _FakeAgent:
    """A minimal, explicit stand-in for `AbstractBot` — avoids MagicMock's
    auto-attribute surprises (e.g. `agent.tags`/`agent.description` silently
    resolving to a non-JSON-serializable Mock inside `A2AServer.get_agent_card()`)."""

    def __init__(self, name: str, tool_manager: ToolManager, conversation_memory):
        self.name = name
        self.description = None
        self.role = None
        self.goal = None
        self.tags: list = []
        self.tool_manager = tool_manager
        self.conversation_memory = conversation_memory
        self.ask_calls: list = []

    async def ask(self, *, question, session_id=None, user_id=None, a2ui_surface_state=None, **kwargs):
        self.ask_calls.append(
            {"question": question, "session_id": session_id, "user_id": user_id, "a2ui_surface_state": a2ui_surface_state}
        )
        reply = MagicMock()
        reply.a2ui_envelope = None
        reply.content = "ok"
        return reply


def _make_agent(tmp_path, name="demo"):
    tm = ToolManager()
    tm.register_tool(get_weather)
    return _FakeAgent(name, tm, FileConversationMemory(base_path=str(tmp_path)))


def _bot_manager(agent):
    manager = MagicMock()
    manager.get_user_bot = AsyncMock(return_value=None)
    manager.get_bot = AsyncMock(return_value=agent)
    return manager


def _call_agent_function_envelope(function_call_id="fc-1", call="get_weather", args=None):
    return {
        "version": "v1.0",
        "callAgentFunction": {
            "surfaceId": "s-1",
            "functionCallId": function_call_id,
            "callFunction": {"call": call, "args": args or {}, "catalogId": DEFAULT_CATALOG_ID},
        },
    }


class TestE2E:
    async def test_e2e_http_call_agent_function(self, aiohttp_client, tmp_path):
        """A real @tool-decorated function, invoked via POST, returns its real result."""
        agent = _make_agent(tmp_path)
        app = web.Application()
        app["bot_manager"] = _bot_manager(agent)
        app.router.add_view("/api/v1/agents/{agent_id}/a2ui", A2UIHandler)
        client = await aiohttp_client(app)

        resp = await client.post(
            "/api/v1/agents/demo/a2ui",
            json=_call_agent_function_envelope(args={"location": "Caracas"}),
            params={"user_id": "u-1", "session_id": "sess-1"},
        )

        assert resp.status == 200
        body = await resp.json()
        assert body["agentFunctionResponse"]["functionCallId"] == "fc-1"
        assert body["agentFunctionResponse"]["value"] == "Weather in Caracas: Sunny, 25C"

    async def test_e2e_http_action_with_send_data_model(self, aiohttp_client, tmp_path):
        """`action` + `dataModel` persists to memory, and the NEXT turn sees it via `_a2ui_surface_state`."""
        agent = _make_agent(tmp_path)
        received_surface_state = {}

        async def capture_ask(*, question, session_id, user_id, a2ui_surface_state=None, **kwargs):
            received_surface_state["value"] = a2ui_surface_state
            reply = MagicMock()
            reply.a2ui_envelope = None
            return reply

        agent.ask = AsyncMock(side_effect=capture_ask)

        app = web.Application()
        app["bot_manager"] = _bot_manager(agent)
        app.router.add_view("/api/v1/agents/{agent_id}/a2ui", A2UIHandler)
        client = await aiohttp_client(app)

        action_env = {
            "version": "v1.0",
            "action": {
                "name": "submit",
                "surfaceId": "main",
                "sourceComponentId": "btn-1",
                "timestamp": "2026-08-29T10:00:00Z",
                "context": {},
                "userMessage": "clicked",
                "dataModel": {"count": 42},
            },
        }
        resp = await client.post(
            "/api/v1/agents/demo/a2ui", json=action_env, params={"user_id": "u-1", "session_id": "sess-2"}
        )
        assert resp.status == 200

        # The bot turn triggered by dispatch() received the surface state.
        surface_state = received_surface_state["value"]
        assert surface_state is not None
        assert surface_state.data_model == {"count": 42}

        # And it is independently persisted for a later read (e.g. a tool
        # invoked on a SUBSEQUENT turn, not just this one).
        store = ConversationMemorySurfaceStore(agent.conversation_memory, user_id="u-1")
        persisted = await store.get("sess-2", "main")
        assert persisted is not None
        assert persisted.data_model == {"count": 42}

    async def test_e2e_a2a_round_trip(self, aiohttp_client, tmp_path):
        """The card advertises the extension; message/send with a DataPart returns an Artifact."""
        from parrot.a2a.models import A2UI_EXTENSION_URI

        agent = _make_agent(tmp_path, name="a2a-demo")
        server = A2AServer(agent)
        app = web.Application()
        server.setup(app, register_well_known=False)
        client = await aiohttp_client(app)

        card_resp = await client.get(f"{server.base_path}/.well-known/agent-card.json")
        assert card_resp.status == 200
        card = await card_resp.json()
        ext_uris = {e["uri"] for e in card["capabilities"].get("extensions", [])}
        assert A2UI_EXTENSION_URI in ext_uris

        from parrot.a2a.models import Part

        a2ui_part = Part(
            data=_call_agent_function_envelope(args={"location": "Caracas"}),
            metadata={"mimeType": A2UI_MEDIA_TYPE},
        )
        message = Message.user([a2ui_part])
        # A2A fails closed without a verifiable identity (security fix, code
        # review CRITICAL finding on this feature) — mirror the identity
        # claim shape `_extract_identity` reads from `message.metadata`.
        message.metadata = {"user_id": "u-1"}
        payload = {"message": message.to_dict()}
        resp = await client.post(f"{server.base_path}/message:send", json=payload)
        assert resp.status == 200
        body = await resp.json()
        assert len(body["artifacts"]) == 1
        part = body["artifacts"][0]["parts"][0]
        assert part["metadata"]["mimeType"] == A2UI_MEDIA_TYPE
        assert part["data"]["data"]["agentFunctionResponse"]["functionCallId"] == "fc-1"

    async def test_e2e_call_renderer_function_correlation(self, aiohttp_client, tmp_path):
        """A tool calls `runtime.call_renderer()`; the stream delivers it; `rendererFunctionResponse` resolves the pending."""
        import asyncio
        import json

        agent = _make_agent(tmp_path)
        app = web.Application()
        app["bot_manager"] = _bot_manager(agent)
        app.router.add_view("/api/v1/agents/{agent_id}/a2ui", A2UIHandler)
        client = await aiohttp_client(app)

        # Simulate a tool that decided to call the renderer mid-turn — it
        # would receive the runtime by injection in a full production
        # wiring; here we build the SAME runtime the HTTP handler itself
        # would build for this (agent_id, user_id) pair.
        store = ConversationMemorySurfaceStore(agent.conversation_memory, user_id="u-1")
        runtime = A2UIRuntime(executor=ToolManagerExecutor(agent.tool_manager), surfaces=store, pending=store)
        function_call_id, _envelope = await runtime.call_renderer("sess-3", "s-1", "openUrl", {"url": "https://x"})

        # Stream delivers the queued call.
        resp = await client.get("/api/v1/agents/demo/a2ui", params={"user_id": "u-1", "session_id": "sess-3"})
        try:
            assert resp.status == 200
            line = await asyncio.wait_for(resp.content.readline(), timeout=5)
            payload = json.loads(line[len(b"data: "):])
            assert payload["callRendererFunction"]["functionCallId"] == function_call_id
        finally:
            resp.close()

        # rendererFunctionResponse resolves the pending record.
        response_env = {
            "version": "v1.0",
            "rendererFunctionResponse": {"functionCallId": function_call_id, "value": {"ok": True}},
        }
        resp2 = await client.post(
            "/api/v1/agents/demo/a2ui", json=response_env, params={"user_id": "u-1", "session_id": "sess-3"}
        )
        assert resp2.status == 200

        # Resolving again (replay) is now unknown -> NOT_FOUND.
        resp3 = await client.post(
            "/api/v1/agents/demo/a2ui", json=response_env, params={"user_id": "u-1", "session_id": "sess-3"}
        )
        body3 = await resp3.json()
        assert body3["error"]["code"] == "NOT_FOUND"

    async def test_e2e_deeplink_to_action(self, tmp_path):
        """A deep-link click produces a v1.0 `action` -> a bot turn."""

        def _action_envelope() -> dict:
            return {
                "version": "v1.0",
                "action": {
                    "name": "approve",
                    "surfaceId": "main",
                    "sourceComponentId": "btn1",
                    "timestamp": "2026-01-01T00:00:00+00:00",
                    "context": {"row": 7},
                },
            }

        service = DeepLinkService(_FakeRedis(), base_url="https://app.example")
        injected = {}

        async def invoker(*, agent_name, query, session_id, user_id):
            injected.update(agent_name=agent_name, query=query, session_id=session_id, user_id=user_id)
            return {"ok": True}

        agent = _make_agent(tmp_path)

        async def runtime_factory(agent_id, user_id):
            store = ConversationMemorySurfaceStore(agent.conversation_memory, user_id=user_id)
            return A2UIRuntime(executor=ToolManagerExecutor(agent.tool_manager), surfaces=store, pending=store)

        handler = DeepLinkResumeHandler(service, invoker, runtime_factory=runtime_factory)
        dl = await service.mint(
            session_id="sess-4",
            user_id="u-1",
            agent_id="demo",
            channel="web",
            action_payload=_action_envelope(),
        )

        body, status = await handler.handle(dl.token_id)

        assert status == 200
        assert body["status"] == "resumed"
        import json

        decoded = json.loads(injected["query"])
        assert decoded["type"] == "a2ui_action"
        assert decoded["action"]["action"]["name"] == "approve"
