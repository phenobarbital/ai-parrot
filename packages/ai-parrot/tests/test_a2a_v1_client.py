"""Unit tests for A2AClient v1.0.0 upgrade (FEAT-272 / TASK-1717).

Covers:
    - Client sends `A2A-Version: 1.0` by default.
    - `discover()` tries `/.well-known/agent-card.json` first, falls back
      to `/.well-known/agent.json`.
    - `_server_version` detection from the AgentCard shape returned.
    - Compat deserialization of both v1.0 and v0.3 task/status responses.
    - `rpc_call()` method-name downgrade for v0.3 servers.
    - Push notification config CRUD client methods.
"""
from unittest.mock import AsyncMock, MagicMock

from parrot.a2a.client import A2AClient
from parrot.a2a.models import TaskState


class TestA2AClientDefaults:
    def test_sends_version_header(self):
        client = A2AClient("http://localhost:8080")
        assert client._default_headers.get("A2A-Version") == "1.0"
        assert client.headers.get("A2A-Version") == "1.0"

    def test_default_server_version_optimistic(self):
        client = A2AClient("http://localhost:8080")
        assert client._server_version == "1.0"


def _mock_get_response(status=200, json_data=None):
    """Build an async-context-manager mock for `session.get(...)`."""
    resp = MagicMock()
    resp.status = status
    resp.json = AsyncMock(return_value=json_data or {})
    resp.raise_for_status = MagicMock()
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=resp)
    cm.__aexit__ = AsyncMock(return_value=False)
    return cm


class TestA2AClientDiscover:
    async def test_discover_tries_v1_endpoint_first(self):
        client = A2AClient("http://localhost:8080")
        v1_card = {
            "name": "TestAgent", "description": "T", "version": "1.0",
            "supportedInterfaces": [
                {"url": "http://localhost:8080/a2a", "protocolBinding": "JSONRPC", "protocolVersion": "1.0"}
            ],
            "capabilities": {"streaming": True},
            "defaultInputModes": ["text/plain"],
            "defaultOutputModes": ["text/plain"],
            "skills": [],
        }
        client._session = MagicMock()
        client._session.get = MagicMock(return_value=_mock_get_response(200, v1_card))

        card = await client.discover()

        called_url = client._session.get.call_args[0][0]
        assert called_url.endswith("/.well-known/agent-card.json")
        assert client._server_version == "1.0"
        assert card.url == "http://localhost:8080/a2a"

    async def test_discover_falls_back_to_v03(self):
        client = A2AClient("http://localhost:8080")
        v03_card = {
            "name": "TestAgent", "description": "T", "version": "1.0",
            "url": "http://localhost:8080/a2a", "preferredTransport": "JSONRPC",
            "protocolVersion": "0.3.0",
            "capabilities": {"streaming": True},
            "defaultInputModes": ["text/plain"],
            "defaultOutputModes": ["text/plain"],
            "skills": [],
        }

        calls = []

        def fake_get(url, *args, **kwargs):
            calls.append(url)
            if url.endswith("agent-card.json"):
                return _mock_get_response(404)
            return _mock_get_response(200, v03_card)

        client._session = MagicMock()
        client._session.get = MagicMock(side_effect=fake_get)
        client._session.headers = {}

        card = await client.discover()

        assert calls[0].endswith("/.well-known/agent-card.json")
        assert calls[1].endswith("/.well-known/agent.json")
        assert client._server_version == "0.3"
        assert card.url == "http://localhost:8080/a2a"

    async def test_v03_server_detection_drops_version_header(self):
        client = A2AClient("http://localhost:8080")
        v03_card = {
            "name": "TestAgent", "description": "T", "version": "1.0",
            "url": "http://localhost:8080/a2a", "preferredTransport": "JSONRPC",
            "capabilities": {"streaming": True},
            "defaultInputModes": ["text/plain"],
            "defaultOutputModes": ["text/plain"],
            "skills": [],
        }

        def fake_get(url, *args, **kwargs):
            if url.endswith("agent-card.json"):
                return _mock_get_response(404)
            return _mock_get_response(200, v03_card)

        client._session = MagicMock()
        client._session.get = MagicMock(side_effect=fake_get)
        client._session.headers = {"A2A-Version": "1.0"}

        await client.discover()

        assert client._server_version == "0.3"
        assert "A2A-Version" not in client._session.headers


class TestA2AClientParseTask:
    def test_parse_task_v1_format(self):
        client = A2AClient("http://localhost:8080")
        data = {
            "id": "t1", "contextId": "c1",
            "status": {"state": "TASK_STATE_COMPLETED"},
            "artifacts": [], "history": [],
        }
        task = client._parse_task(data)
        assert task.status.state == TaskState.COMPLETED

    def test_parse_task_v03_format(self):
        client = A2AClient("http://localhost:8080")
        data = {
            "id": "t1", "contextId": "c1",
            "status": {"state": "completed"},
            "artifacts": [], "history": [],
        }
        task = client._parse_task(data)
        assert task.status.state == TaskState.COMPLETED

    def test_parse_task_v03_cancelled(self):
        client = A2AClient("http://localhost:8080")
        data = {
            "id": "t1", "contextId": "c1",
            "status": {"state": "cancelled"},
            "artifacts": [], "history": [],
        }
        task = client._parse_task(data)
        assert task.status.state == TaskState.CANCELED


class TestA2AClientRpcCallCompat:
    async def test_rpc_call_uses_pascal_case_for_v1(self):
        client = A2AClient("http://localhost:8080")
        client._server_version = "1.0"

        resp = MagicMock()
        resp.raise_for_status = MagicMock()
        resp.json = AsyncMock(return_value={"jsonrpc": "2.0", "id": "1", "result": {}})
        cm = MagicMock()
        cm.__aenter__ = AsyncMock(return_value=resp)
        cm.__aexit__ = AsyncMock(return_value=False)

        client._session = MagicMock()
        client._session.post = MagicMock(return_value=cm)

        await client.rpc_call("SendMessage", {"message": {}})

        sent_payload = client._session.post.call_args.kwargs["json"]
        assert sent_payload["method"] == "SendMessage"

    async def test_rpc_call_downgrades_for_v03(self):
        client = A2AClient("http://localhost:8080")
        client._server_version = "0.3"

        resp = MagicMock()
        resp.raise_for_status = MagicMock()
        resp.json = AsyncMock(return_value={"jsonrpc": "2.0", "id": "1", "result": {}})
        cm = MagicMock()
        cm.__aenter__ = AsyncMock(return_value=resp)
        cm.__aexit__ = AsyncMock(return_value=False)

        client._session = MagicMock()
        client._session.post = MagicMock(return_value=cm)

        await client.rpc_call("SendMessage", {"message": {}})

        sent_payload = client._session.post.call_args.kwargs["json"]
        assert sent_payload["method"] == "message/send"


class TestA2AClientPushConfigMethods:
    async def test_create_push_config(self):
        client = A2AClient("http://localhost:8080")

        resp = MagicMock()
        resp.raise_for_status = MagicMock()
        resp.json = AsyncMock(return_value={
            "id": "cfg-1", "taskId": "task-1", "url": "https://example.com/hook",
        })
        cm = MagicMock()
        cm.__aenter__ = AsyncMock(return_value=resp)
        cm.__aexit__ = AsyncMock(return_value=False)

        client._session = MagicMock()
        client._session.post = MagicMock(return_value=cm)

        config = await client.create_push_config("task-1", "https://example.com/hook")
        assert config.id == "cfg-1"
        assert config.url == "https://example.com/hook"
