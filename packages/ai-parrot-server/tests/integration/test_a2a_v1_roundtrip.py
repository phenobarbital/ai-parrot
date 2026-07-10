"""End-to-end A2A v1.0 protocol integration tests (FEAT-272 TASK-1719).

Exercises the full v1.0 stack over the wire (aiohttp test client → A2AServer):
version negotiation, REST routes, JSON-RPC, SSE streaming, push-notification
CRUD, error codes, and v0.3 backward compatibility.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock
from aiohttp import web

from parrot.a2a.server import A2AServer
from parrot.a2a.models import AgentCapabilities


@pytest.fixture
def mock_agent():
    agent = MagicMock()
    agent.name = "TestAgent"
    agent.description = "Test"
    agent.tags = []
    agent.ask = AsyncMock(return_value="Hello from agent")
    agent.tool_manager = None
    agent.tools = []
    if hasattr(agent, "ask_stream"):
        del agent.ask_stream
    return agent


@pytest.fixture
def a2a_app(mock_agent):
    app = web.Application()
    server = A2AServer(
        mock_agent,
        capabilities=AgentCapabilities(streaming=True, push_notifications=True),
    )
    server.setup(app, url="https://test.example.com/a2a")
    return app


def _v1_msg():
    return {"message": {"messageId": "m1", "role": "ROLE_USER",
                        "parts": [{"kind": "text", "text": "Hello"}]}}


class TestV1Roundtrip:
    async def test_send_message_v1(self, aiohttp_client, a2a_app):
        client = await aiohttp_client(a2a_app)
        resp = await client.post("/a2a/message:send",
                                 headers={"A2A-Version": "1.0"}, json=_v1_msg())
        assert resp.status == 200
        data = await resp.json()
        assert data["status"]["state"] == "TASK_STATE_COMPLETED"
        assert "application/a2a+json" in resp.content_type

    async def test_v03_compat(self, aiohttp_client, a2a_app):
        client = await aiohttp_client(a2a_app)
        resp = await client.post("/a2a/message/send", json={
            "message": {"messageId": "m1", "role": "user",
                        "parts": [{"kind": "text", "text": "Hello"}]}})
        assert resp.status == 200
        data = await resp.json()
        assert data["status"]["state"] == "completed"

    async def test_full_lifecycle_get_task(self, aiohttp_client, a2a_app):
        client = await aiohttp_client(a2a_app)
        send = await client.post("/a2a/message:send",
                                 headers={"A2A-Version": "1.0"}, json=_v1_msg())
        task_id = (await send.json())["id"]
        got = await client.get(f"/a2a/tasks/{task_id}", headers={"A2A-Version": "1.0"})
        assert got.status == 200
        assert (await got.json())["status"]["state"] == "TASK_STATE_COMPLETED"

    async def test_streaming_v1(self, aiohttp_client, a2a_app):
        client = await aiohttp_client(a2a_app)
        resp = await client.post("/a2a/message:stream",
                                 headers={"A2A-Version": "1.0"}, json=_v1_msg())
        assert resp.status == 200
        assert "text/event-stream" in resp.content_type
        body = await resp.text()
        assert "TASK_STATE_COMPLETED" in body

    async def test_jsonrpc_v1(self, aiohttp_client, a2a_app):
        client = await aiohttp_client(a2a_app)
        resp = await client.post("/a2a/rpc", headers={"A2A-Version": "1.0"}, json={
            "jsonrpc": "2.0", "id": 1, "method": "SendMessage", "params": _v1_msg()})
        data = await resp.json()
        assert data["result"]["status"]["state"] == "TASK_STATE_COMPLETED"

    async def test_jsonrpc_streaming_v1(self, aiohttp_client, a2a_app):
        """SendStreamingMessage over JSON-RPC streams SSE (ported from feat-272)."""
        client = await aiohttp_client(a2a_app)
        resp = await client.post("/a2a/rpc", headers={"A2A-Version": "1.0"}, json={
            "jsonrpc": "2.0", "id": 1, "method": "SendStreamingMessage",
            "params": _v1_msg()})
        assert resp.status == 200
        # Must be an SSE stream, NOT a unary JSON-RPC envelope.
        assert "text/event-stream" in resp.content_type
        body = await resp.text()
        assert "TASK_STATE_COMPLETED" in body

    async def test_jsonrpc_streaming_v03_alias(self, aiohttp_client, a2a_app):
        """The v0.3 message/stream JSON-RPC alias streams SSE too."""
        client = await aiohttp_client(a2a_app)
        resp = await client.post("/a2a/rpc", json={
            "jsonrpc": "2.0", "id": 2, "method": "message/stream",
            "params": {"message": {"messageId": "m1", "role": "user",
                                   "parts": [{"kind": "text", "text": "Hi"}]}}})
        assert resp.status == 200
        assert "text/event-stream" in resp.content_type
        body = await resp.text()
        assert "completed" in body

    async def test_well_known_v1(self, aiohttp_client, a2a_app):
        client = await aiohttp_client(a2a_app)
        resp = await client.get("/.well-known/agent-card.json",
                                headers={"A2A-Version": "1.0"})
        assert "supportedInterfaces" in (await resp.json())


class TestPushRoundtrip:
    async def test_push_crud(self, aiohttp_client, a2a_app):
        client = await aiohttp_client(a2a_app)
        create = await client.post("/a2a/tasks/t1/pushNotificationConfigs",
                                   headers={"A2A-Version": "1.0"},
                                   json={"url": "https://example.com/hook"})
        cfg_id = (await create.json())["id"]
        lst = await client.get("/a2a/tasks/t1/pushNotificationConfigs",
                               headers={"A2A-Version": "1.0"})
        assert len((await lst.json())["configs"]) == 1
        dele = await client.delete(f"/a2a/tasks/t1/pushNotificationConfigs/{cfg_id}",
                                   headers={"A2A-Version": "1.0"})
        assert (await dele.json())["deleted"] is True


class TestErrorCodes:
    async def test_task_not_found(self, aiohttp_client, a2a_app):
        client = await aiohttp_client(a2a_app)
        resp = await client.get("/a2a/tasks/nonexistent", headers={"A2A-Version": "1.0"})
        assert resp.status == 404
        assert (await resp.json())["error"]["code"] == -32001

    async def test_version_not_supported(self, aiohttp_client, a2a_app):
        client = await aiohttp_client(a2a_app)
        resp = await client.post("/a2a/message:send",
                                 headers={"A2A-Version": "99.0"}, json=_v1_msg())
        assert resp.status == 400
        assert (await resp.json())["error"]["code"] == -32009

    async def test_rpc_unknown_method(self, aiohttp_client, a2a_app):
        client = await aiohttp_client(a2a_app)
        resp = await client.post("/a2a/rpc", json={
            "jsonrpc": "2.0", "id": 1, "method": "Nope", "params": {}})
        assert (await resp.json())["error"]["code"] == -32601

    async def test_rpc_extended_card_not_configured(self, aiohttp_client, a2a_app):
        client = await aiohttp_client(a2a_app)
        resp = await client.post("/a2a/rpc", json={
            "jsonrpc": "2.0", "id": 1, "method": "GetExtendedAgentCard", "params": {}})
        assert (await resp.json())["error"]["code"] == -32007
