"""A2AServer <-> A2UIRuntime dispatch tests (FEAT-469 TASK-2572)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from aiohttp import web
from parrot.a2a.models import A2UI_MEDIA_TYPE
from parrot.a2a.server import A2AServer
from parrot.memory.file import FileConversationMemory
from parrot.outputs.a2ui.catalog.base import DEFAULT_CATALOG_ID
from parrot.tools import tool
from parrot.tools.manager import ToolManager


@tool
def echo(value: str) -> str:
    """Echo back the given value."""
    return value


def _make_agent(tmp_path):
    tm = ToolManager()
    tm.register_tool(echo)
    agent = MagicMock()
    agent.name = "TestAgent"
    agent.tool_manager = tm
    agent.conversation_memory = FileConversationMemory(base_path=str(tmp_path))
    agent.ask = AsyncMock(return_value="hi there")
    return agent


@pytest.fixture
async def a2a_client(aiohttp_client, tmp_path):
    agent = _make_agent(tmp_path)
    server = A2AServer(agent)
    app = web.Application()
    server.setup(app, register_well_known=False)
    client = await aiohttp_client(app)
    return client, server


def _call_agent_function_payload(session_id="sess-1", function_call_id="fc-1", user_id="user-1"):
    envelope = {
        "version": "v1.0",
        "callAgentFunction": {
            "surfaceId": "s-1",
            "functionCallId": function_call_id,
            "callFunction": {"call": "echo", "args": {"value": "hi"}, "catalogId": DEFAULT_CATALOG_ID},
        },
    }
    message = {
        "messageId": "m-1",
        "role": "user",
        "contextId": session_id,
        "parts": [{"data": envelope, "metadata": {"mimeType": A2UI_MEDIA_TYPE}}],
    }
    if user_id is not None:
        message["metadata"] = {"user_id": user_id}
    return {"message": message}


class TestInboundDataPart:
    async def test_dispatches_a2ui_part(self, a2a_client):
        client, _server = a2a_client
        resp = await client.post("/a2a/message:send", json=_call_agent_function_payload())
        assert resp.status == 200
        body = await resp.json()
        artifacts = body["artifacts"]
        assert len(artifacts) == 1
        part = artifacts[0]["parts"][0]
        assert part["data"]["data"]["agentFunctionResponse"]["functionCallId"] == "fc-1"
        assert part["data"]["data"]["agentFunctionResponse"]["value"] == "hi"

    async def test_response_artifact_uses_same_mimetype(self, a2a_client):
        client, _server = a2a_client
        resp = await client.post("/a2a/message:send", json=_call_agent_function_payload())
        body = await resp.json()
        part = body["artifacts"][0]["parts"][0]
        assert part["metadata"]["mimeType"] == A2UI_MEDIA_TYPE

    async def test_non_a2ui_message_unchanged(self, a2a_client):
        client, _server = a2a_client
        payload = {
            "message": {
                "messageId": "m-2",
                "role": "user",
                "contextId": "sess-2",
                "parts": [{"text": "hello"}],
            }
        }
        resp = await client.post("/a2a/message:send", json=payload)
        assert resp.status == 200
        body = await resp.json()
        # Normal conversational path: text response, not an A2UI envelope.
        assert body["artifacts"][0]["parts"][0].get("text") == "hi there"

    async def test_a2ui_rpc_not_spawned_as_background_task(self, a2a_client):
        """returnImmediately must not apply to an A2UI RPC — response is synchronous."""
        client, _server = a2a_client
        payload = _call_agent_function_payload()
        payload["configuration"] = {"returnImmediately": True}
        resp = await client.post("/a2a/message:send", json=payload)
        body = await resp.json()
        # A SUBMITTED task (background path) would have no artifacts yet;
        # the A2UI RPC always returns COMPLETED with its artifact attached.
        assert body["status"]["state"] in ("TASK_STATE_COMPLETED", "completed")
        assert body["artifacts"]

    async def test_dispatch_fails_closed_without_identity(self, a2a_client):
        """No verifiable identity => FAILED task, dispatch never reaches the tool.

        Security fix (code review CRITICAL finding on FEAT-469): the A2A
        transport must gate on identity the same way ``A2UIHandler``'s HTTP
        transport returns 401 — never build a ``PermissionContext`` and
        dispatch anyway when ``user_id`` is unresolvable.
        """
        client, _server = a2a_client
        resp = await client.post("/a2a/message:send", json=_call_agent_function_payload(user_id=None))
        assert resp.status == 200
        body = await resp.json()
        assert body["status"]["state"] in ("TASK_STATE_FAILED", "failed")
        assert not body.get("artifacts")


class TestQueuedRendererCalls:
    async def test_stream_emits_call_renderer_function(self, a2a_client):
        client, server = a2a_client
        session_id = "sess-stream"
        runtime, _store = server._build_a2ui_runtime(user_id="user-1")
        function_call_id, _ = await runtime.call_renderer(session_id, "s-1", "openUrl", {"url": "https://x"})

        # A response to an unrelated rendererFunctionResponse over the SAME
        # session should drain and deliver the queued call.
        payload = {
            "message": {
                "messageId": "m-3",
                "role": "user",
                "contextId": session_id,
                "metadata": {"user_id": "user-1"},
                "parts": [
                    {
                        "data": {
                            "version": "v1.0",
                            "rendererFunctionResponse": {"functionCallId": "unrelated", "value": {}},
                        },
                        "metadata": {"mimeType": A2UI_MEDIA_TYPE},
                    }
                ],
            }
        }
        resp = await client.post("/a2a/message:send", json=payload)
        body = await resp.json()
        parts = body["artifacts"][0]["parts"]
        call_parts = [p for p in parts if "callRendererFunction" in p.get("data", {}).get("data", {})]
        assert len(call_parts) == 1
        assert call_parts[0]["data"]["data"]["callRendererFunction"]["functionCallId"] == function_call_id

    async def test_next_send_drains_queued_call(self, a2a_client):
        client, server = a2a_client
        session_id = "sess-drain"
        runtime, _store = server._build_a2ui_runtime(user_id="user-1")
        await runtime.call_renderer(session_id, "s-1", "openUrl", {"url": "https://x"})

        payload = _call_agent_function_payload(session_id=session_id, function_call_id="fc-2")
        resp = await client.post("/a2a/message:send", json=payload)
        body = await resp.json()
        parts = body["artifacts"][0]["parts"]
        assert any("callRendererFunction" in p.get("data", {}).get("data", {}) for p in parts)
        assert any("agentFunctionResponse" in p.get("data", {}).get("data", {}) for p in parts)

    async def test_call_never_delivered_twice(self, a2a_client):
        client, server = a2a_client
        session_id = "sess-once"
        runtime, _store = server._build_a2ui_runtime(user_id="user-1")
        await runtime.call_renderer(session_id, "s-1", "openUrl", {"url": "https://x"})

        payload = _call_agent_function_payload(session_id=session_id, function_call_id="fc-3")
        resp1 = await client.post("/a2a/message:send", json=payload)
        body1 = await resp1.json()
        first_call_parts = [p for p in body1["artifacts"][0]["parts"] if "callRendererFunction" in p.get("data", {}).get("data", {})]
        assert len(first_call_parts) == 1

        payload2 = _call_agent_function_payload(session_id=session_id, function_call_id="fc-4")
        resp2 = await client.post("/a2a/message:send", json=payload2)
        body2 = await resp2.json()
        second_call_parts = [p for p in body2["artifacts"][0]["parts"] if "callRendererFunction" in p.get("data", {}).get("data", {})]
        assert len(second_call_parts) == 0
