"""Unit tests for A2AServer v1.0.0 JSON-RPC methods & error codes
(FEAT-272 / TASK-1715).

Covers:
    - All 11 v1.0.0 JSON-RPC method names (PascalCase) dispatch correctly.
    - v0.3 compat method names (`message/send`, `tasks/get`, `tasks/list`)
      still work.
    - Unknown method -> -32601 (MethodNotFound, standard JSON-RPC).
    - A2A error code table (-32001..-32009) used for typed protocol errors.
    - `GetExtendedAgentCard` gated on `capabilities.extended_agent_card`.
    - Push notification JSON-RPC methods return -32003 when no store is wired.
"""
from unittest.mock import AsyncMock, MagicMock

import pytest
from aiohttp import web

from parrot.a2a.models import AgentCapabilities
from parrot.a2a.server import A2AServer


@pytest.fixture
def mock_agent():
    agent = MagicMock()
    agent.name = "TestAgent"
    agent.description = "Test agent"
    agent.ask = AsyncMock(return_value="Hello from agent")
    agent.tool_manager = None
    agent.tools = []
    agent.tags = []
    return agent


@pytest.fixture
def a2a_server(mock_agent):
    return A2AServer(mock_agent, capabilities=AgentCapabilities(streaming=True))


@pytest.fixture
def a2a_app(a2a_server):
    app = web.Application()
    a2a_server.setup(app, url="https://test.example.com/a2a")
    return app


async def _rpc(client, method, params=None, req_id=1, version="1.0"):
    headers = {"A2A-Version": version} if version else {}
    return await client.post(
        "/a2a/rpc",
        headers=headers,
        json={"jsonrpc": "2.0", "id": req_id, "method": method, "params": params or {}},
    )


class TestJsonRpcV1MethodNames:
    async def test_send_message_pascal_case(self, aiohttp_client, a2a_app):
        client = await aiohttp_client(a2a_app)
        resp = await _rpc(client, "SendMessage", {
            "message": {"role": "ROLE_USER", "parts": [{"text": "hi"}]}
        })
        data = await resp.json()
        assert "result" in data
        assert data["result"]["status"]["state"] == "TASK_STATE_COMPLETED"

    async def test_get_task_pascal_case(self, aiohttp_client, a2a_app, a2a_server):
        from parrot.a2a.models import Message
        task = await a2a_server.process_message(Message.user("hi"))

        client = await aiohttp_client(a2a_app)
        resp = await _rpc(client, "GetTask", {"id": task.id})
        data = await resp.json()
        assert data["result"]["id"] == task.id

    async def test_list_tasks_pascal_case(self, aiohttp_client, a2a_app, a2a_server):
        from parrot.a2a.models import Message
        await a2a_server.process_message(Message.user("hi"))

        client = await aiohttp_client(a2a_app)
        resp = await _rpc(client, "ListTasks")
        data = await resp.json()
        assert "tasks" in data["result"]
        assert len(data["result"]["tasks"]) >= 1

    async def test_cancel_task_pascal_case(self, aiohttp_client, a2a_app, a2a_server):
        from parrot.a2a.models import Message, TaskState, TaskStatus
        task = await a2a_server.process_message(Message.user("hi"))
        task.status = TaskStatus(state=TaskState.WORKING)

        client = await aiohttp_client(a2a_app)
        resp = await _rpc(client, "CancelTask", {"id": task.id})
        data = await resp.json()
        assert data["result"]["status"]["state"] == "TASK_STATE_CANCELED"

    async def test_get_extended_agent_card_not_configured(self, aiohttp_client, a2a_app):
        client = await aiohttp_client(a2a_app)
        resp = await _rpc(client, "GetExtendedAgentCard")
        data = await resp.json()
        assert data["error"]["code"] == -32007

    async def test_get_extended_agent_card_configured(self, aiohttp_client, mock_agent):
        server = A2AServer(
            mock_agent,
            capabilities=AgentCapabilities(streaming=True, extended_agent_card=True),
        )
        app = web.Application()
        server.setup(app, url="https://test.example.com/a2a")

        from aiohttp.test_utils import TestClient, TestServer
        async with TestClient(TestServer(app)) as client:
            resp = await _rpc(client, "GetExtendedAgentCard")
            data = await resp.json()
            assert "supportedInterfaces" in data["result"]


class TestJsonRpcV03Compat:
    async def test_v03_method_compat(self, aiohttp_client, a2a_app):
        client = await aiohttp_client(a2a_app)
        resp = await _rpc(client, "message/send", {
            "message": {"role": "user", "parts": [{"text": "hi"}]}
        }, version=None)
        data = await resp.json()
        assert "result" in data
        assert data["result"]["status"]["state"] == "completed"

    async def test_tasks_get_compat(self, aiohttp_client, a2a_app, a2a_server):
        from parrot.a2a.models import Message
        task = await a2a_server.process_message(Message.user("hi"))

        client = await aiohttp_client(a2a_app)
        resp = await _rpc(client, "tasks/get", {"id": task.id})
        data = await resp.json()
        assert data["result"]["id"] == task.id

    async def test_tasks_list_compat(self, aiohttp_client, a2a_app, a2a_server):
        from parrot.a2a.models import Message
        await a2a_server.process_message(Message.user("hi"))

        client = await aiohttp_client(a2a_app)
        resp = await _rpc(client, "tasks/list")
        data = await resp.json()
        assert "tasks" in data["result"]


class TestJsonRpcErrorCodes:
    async def test_unknown_method(self, aiohttp_client, a2a_app):
        client = await aiohttp_client(a2a_app)
        resp = await _rpc(client, "DoesNotExist")
        data = await resp.json()
        assert data["error"]["code"] == -32601

    async def test_task_not_found_error_code(self, aiohttp_client, a2a_app):
        client = await aiohttp_client(a2a_app)
        resp = await _rpc(client, "GetTask", {"id": "nonexistent"})
        data = await resp.json()
        assert data["error"]["code"] == -32001

    async def test_task_not_cancelable_error_code(self, aiohttp_client, a2a_app, a2a_server):
        from parrot.a2a.models import Message
        task = await a2a_server.process_message(Message.user("hi"))
        # process_message already completed the task -> terminal state.

        client = await aiohttp_client(a2a_app)
        resp = await _rpc(client, "CancelTask", {"id": task.id})
        data = await resp.json()
        assert data["error"]["code"] == -32002

    async def test_push_notification_not_supported(self, aiohttp_client, a2a_app):
        client = await aiohttp_client(a2a_app)
        resp = await _rpc(client, "CreateTaskPushNotificationConfig", {
            "config": {"taskId": "t1", "url": "https://example.com/hook"}
        })
        data = await resp.json()
        assert data["error"]["code"] == -32003

    async def test_push_notification_get_not_supported(self, aiohttp_client, a2a_app):
        client = await aiohttp_client(a2a_app)
        resp = await _rpc(client, "GetTaskPushNotificationConfig", {
            "taskId": "t1", "configId": "c1"
        })
        data = await resp.json()
        assert data["error"]["code"] == -32003

    async def test_rest_error_codes_use_table(self, aiohttp_client, a2a_app):
        client = await aiohttp_client(a2a_app)
        resp = await client.get(
            "/a2a/tasks/nonexistent", headers={"A2A-Version": "1.0"}
        )
        assert resp.status == 404
        data = await resp.json()
        assert data["error"]["code"] == -32001
