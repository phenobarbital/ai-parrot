"""Unit tests for A2A v1.0 server routes & version negotiation (FEAT-272)."""
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
    # Ensure ask_stream is not present so the fallback path is used.
    if hasattr(agent, "ask_stream"):
        del agent.ask_stream
    return agent


@pytest.fixture
def a2a_app(mock_agent):
    app = web.Application()
    server = A2AServer(mock_agent, capabilities=AgentCapabilities(streaming=True))
    server.setup(app, url="https://test.example.com/a2a")
    return app


class TestVersionNegotiation:
    async def test_v1_header_returns_v1_format(self, aiohttp_client, a2a_app):
        client = await aiohttp_client(a2a_app)
        resp = await client.get("/.well-known/agent-card.json",
                                headers={"A2A-Version": "1.0"})
        assert resp.status == 200
        data = await resp.json()
        assert "supportedInterfaces" in data
        assert "url" not in data

    async def test_no_header_returns_v03(self, aiohttp_client, a2a_app):
        client = await aiohttp_client(a2a_app)
        resp = await client.get("/.well-known/agent.json")
        data = await resp.json()
        assert "url" in data
        assert "supportedInterfaces" not in data

    async def test_unsupported_version(self, aiohttp_client, a2a_app):
        client = await aiohttp_client(a2a_app)
        resp = await client.post("/a2a/message:send",
                                 headers={"A2A-Version": "2.0"},
                                 json={"message": {"role": "user", "parts": [{"text": "hi"}]}})
        assert resp.status == 400
        data = await resp.json()
        assert data["error"]["code"] == -32009

    async def test_v1_content_type(self, aiohttp_client, a2a_app):
        client = await aiohttp_client(a2a_app)
        resp = await client.get("/.well-known/agent-card.json",
                                headers={"A2A-Version": "1.0"})
        assert "application/a2a+json" in resp.content_type


class TestV1Routes:
    async def test_message_send_colon_route(self, aiohttp_client, a2a_app):
        client = await aiohttp_client(a2a_app)
        resp = await client.post(
            "/a2a/message:send",
            headers={"A2A-Version": "1.0"},
            json={"message": {"messageId": "m1", "role": "ROLE_USER",
                              "parts": [{"kind": "text", "text": "Hello"}]}},
        )
        assert resp.status == 200
        data = await resp.json()
        assert data["status"]["state"] == "TASK_STATE_COMPLETED"

    async def test_message_send_v03_route(self, aiohttp_client, a2a_app):
        client = await aiohttp_client(a2a_app)
        resp = await client.post(
            "/a2a/message/send",
            json={"message": {"messageId": "m1", "role": "user",
                              "parts": [{"kind": "text", "text": "Hello"}]}},
        )
        assert resp.status == 200
        data = await resp.json()
        assert data["status"]["state"] == "completed"

    async def test_cancel_colon_route(self, aiohttp_client, a2a_app):
        client = await aiohttp_client(a2a_app)
        # Create a task first
        send = await client.post(
            "/a2a/message:send",
            headers={"A2A-Version": "1.0"},
            json={"message": {"messageId": "m1", "role": "ROLE_USER",
                              "parts": [{"kind": "text", "text": "Hi"}]}},
        )
        task_id = (await send.json())["id"]
        # Completed tasks are not cancelable -> TaskNotCancelableError
        resp = await client.post(f"/a2a/tasks/{task_id}:cancel",
                                 headers={"A2A-Version": "1.0"})
        assert resp.status == 400

    async def test_history_length_config(self, aiohttp_client, a2a_app):
        client = await aiohttp_client(a2a_app)
        resp = await client.post(
            "/a2a/message:send",
            headers={"A2A-Version": "1.0"},
            json={
                "message": {"messageId": "m1", "role": "ROLE_USER",
                            "parts": [{"kind": "text", "text": "Hi"}]},
                "configuration": {"historyLength": 0},
            },
        )
        data = await resp.json()
        assert data["history"] == []

    async def test_streaming_v1(self, aiohttp_client, a2a_app):
        client = await aiohttp_client(a2a_app)
        resp = await client.post(
            "/a2a/message:stream",
            headers={"A2A-Version": "1.0"},
            json={"message": {"messageId": "m1", "role": "ROLE_USER",
                              "parts": [{"kind": "text", "text": "Hi"}]}},
        )
        assert resp.status == 200
        assert "text/event-stream" in resp.content_type
        body = await resp.text()
        assert "TASK_STATE_COMPLETED" in body
