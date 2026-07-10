"""Unit tests for A2A v1.0 JSON-RPC methods & error codes (FEAT-272 TASK-1715)."""
import pytest
from unittest.mock import AsyncMock, MagicMock
from aiohttp import web

from parrot.a2a.server import A2AServer
from parrot.a2a.models import AgentCapabilities, A2A_ERROR_CODES


@pytest.fixture
def mock_agent():
    agent = MagicMock()
    agent.name = "RpcAgent"
    agent.description = "Test"
    agent.tags = []
    agent.ask = AsyncMock(return_value="Hello")
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


def _msg():
    return {"message": {"messageId": "m1", "role": "ROLE_USER",
                        "parts": [{"kind": "text", "text": "hi"}]}}


class TestJsonRpcV1Methods:
    async def test_send_message_pascal_case(self, aiohttp_client, a2a_app):
        client = await aiohttp_client(a2a_app)
        resp = await client.post("/a2a/rpc", headers={"A2A-Version": "1.0"}, json={
            "jsonrpc": "2.0", "id": 1, "method": "SendMessage", "params": _msg()})
        data = await resp.json()
        assert "result" in data
        assert data["result"]["status"]["state"] == "TASK_STATE_COMPLETED"

    async def test_v03_method_compat(self, aiohttp_client, a2a_app):
        client = await aiohttp_client(a2a_app)
        resp = await client.post("/a2a/rpc", json={
            "jsonrpc": "2.0", "id": 1, "method": "message/send", "params": _msg()})
        data = await resp.json()
        assert "result" in data
        assert data["result"]["status"]["state"] == "completed"

    async def test_unknown_method(self, aiohttp_client, a2a_app):
        client = await aiohttp_client(a2a_app)
        resp = await client.post("/a2a/rpc", json={
            "jsonrpc": "2.0", "id": 1, "method": "DoesNotExist", "params": {}})
        data = await resp.json()
        assert data["error"]["code"] == -32601

    async def test_invalid_request(self, aiohttp_client, a2a_app):
        client = await aiohttp_client(a2a_app)
        resp = await client.post("/a2a/rpc", json={"id": 1})
        data = await resp.json()
        assert data["error"]["code"] == -32600

    async def test_task_not_found_error_code(self, aiohttp_client, a2a_app):
        client = await aiohttp_client(a2a_app)
        resp = await client.post("/a2a/rpc", json={
            "jsonrpc": "2.0", "id": 1, "method": "GetTask", "params": {"id": "nope"}})
        data = await resp.json()
        assert data["error"]["code"] == -32001

    async def test_cancel_not_cancelable(self, aiohttp_client, a2a_app):
        client = await aiohttp_client(a2a_app)
        send = await client.post("/a2a/rpc", headers={"A2A-Version": "1.0"}, json={
            "jsonrpc": "2.0", "id": 1, "method": "SendMessage", "params": _msg()})
        task_id = (await send.json())["result"]["id"]
        resp = await client.post("/a2a/rpc", json={
            "jsonrpc": "2.0", "id": 2, "method": "CancelTask", "params": {"id": task_id}})
        data = await resp.json()
        assert data["error"]["code"] == -32002

    async def test_extended_card_not_configured(self, aiohttp_client, a2a_app):
        client = await aiohttp_client(a2a_app)
        resp = await client.post("/a2a/rpc", json={
            "jsonrpc": "2.0", "id": 1, "method": "GetExtendedAgentCard", "params": {}})
        data = await resp.json()
        assert data["error"]["code"] == -32007

    async def test_push_config_via_rpc(self, aiohttp_client, a2a_app):
        client = await aiohttp_client(a2a_app)
        # Create
        create = await client.post("/a2a/rpc", json={
            "jsonrpc": "2.0", "id": 1, "method": "CreateTaskPushNotificationConfig",
            "params": {"taskId": "t1", "pushNotificationConfig": {"url": "https://ex.com/h"}}})
        cfg = (await create.json())["result"]
        assert cfg["taskId"] == "t1"
        cfg_id = cfg["id"]
        # List
        lst = await client.post("/a2a/rpc", json={
            "jsonrpc": "2.0", "id": 2, "method": "ListTaskPushNotificationConfigs",
            "params": {"taskId": "t1"}})
        assert len((await lst.json())["result"]["configs"]) == 1
        # Delete
        dele = await client.post("/a2a/rpc", json={
            "jsonrpc": "2.0", "id": 3, "method": "DeleteTaskPushNotificationConfig",
            "params": {"taskId": "t1", "pushNotificationConfigId": cfg_id}})
        assert (await dele.json())["result"]["deleted"] is True


class TestErrorTable:
    def test_all_codes_present(self):
        assert A2A_ERROR_CODES["TaskNotFoundError"] == (-32001, 404)
        assert A2A_ERROR_CODES["VersionNotSupportedError"] == (-32009, 400)


class TestPushDisabled:
    async def test_push_not_supported_error(self, aiohttp_client, mock_agent):
        app = web.Application()
        server = A2AServer(mock_agent, capabilities=AgentCapabilities())  # no push
        server.setup(app, url="https://x.example.com/a2a")
        client = await aiohttp_client(app)
        resp = await client.post("/a2a/rpc", json={
            "jsonrpc": "2.0", "id": 1, "method": "CreateTaskPushNotificationConfig",
            "params": {"taskId": "t1", "pushNotificationConfig": {"url": "https://ex.com/h"}}})
        data = await resp.json()
        assert data["error"]["code"] == -32003
