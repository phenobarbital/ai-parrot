"""Unit tests for the A2A v1.0 PushNotificationStore (FEAT-272 TASK-1716)."""
import pytest
from unittest.mock import AsyncMock, MagicMock
from aiohttp import web

from parrot.a2a.push_notifications import PushNotificationStore
from parrot.a2a.models import TaskPushNotificationConfig, AgentCapabilities
from parrot.a2a.server import A2AServer


@pytest.fixture
def store():
    return PushNotificationStore()


class TestPushNotificationStore:
    async def test_create_assigns_id(self, store):
        config = TaskPushNotificationConfig(id="", task_id="task-1", url="https://example.com/hook")
        result = await store.create(config)
        assert result.id != ""

    async def test_get_returns_config(self, store):
        config = TaskPushNotificationConfig(id="cfg-1", task_id="task-1", url="https://example.com/hook")
        await store.create(config)
        found = await store.get("task-1", "cfg-1")
        assert found is not None
        assert found.url == "https://example.com/hook"

    async def test_list_for_task(self, store):
        for i in range(3):
            await store.create(TaskPushNotificationConfig(
                id=f"cfg-{i}", task_id="task-1", url=f"https://example.com/hook{i}"))
        configs = await store.list_for_task("task-1")
        assert len(configs) == 3

    async def test_delete(self, store):
        await store.create(TaskPushNotificationConfig(
            id="cfg-1", task_id="task-1", url="https://example.com/hook"))
        assert await store.delete("task-1", "cfg-1") is True
        assert await store.get("task-1", "cfg-1") is None

    async def test_delete_missing(self, store):
        assert await store.delete("task-x", "cfg-x") is False

    async def test_reject_private_ip(self, store):
        config = TaskPushNotificationConfig(id="cfg-1", task_id="task-1", url="http://127.0.0.1/hook")
        with pytest.raises(ValueError, match="Private/loopback"):
            await store.create(config)

    async def test_reject_bad_scheme(self, store):
        config = TaskPushNotificationConfig(id="cfg-1", task_id="task-1", url="ftp://example.com/hook")
        with pytest.raises(ValueError, match="Invalid scheme"):
            await store.create(config)

    @pytest.mark.parametrize("host", [
        "0.0.0.0",                 # unspecified
        "169.254.169.254",         # cloud metadata endpoint (link-local)
        "10.0.0.5",                # RFC1918 private
        "[::1]",                   # IPv6 loopback
        "224.0.0.1",               # multicast
    ])
    async def test_reject_ssrf_ranges(self, store, host):
        config = TaskPushNotificationConfig(
            id="", task_id="task-1", url=f"http://{host}/hook")
        with pytest.raises(ValueError):
            await store.create(config)

    async def test_allow_public_ip(self, store):
        config = TaskPushNotificationConfig(
            id="", task_id="task-1", url="https://8.8.8.8/hook")
        result = await store.create(config)
        assert result.id != ""


@pytest.fixture
def mock_agent():
    agent = MagicMock()
    agent.name = "PushAgent"
    agent.description = "Test"
    agent.tags = []
    agent.ask = AsyncMock(return_value="ok")
    agent.tool_manager = None
    agent.tools = []
    if hasattr(agent, "ask_stream"):
        del agent.ask_stream
    return agent


@pytest.fixture
def push_app(mock_agent):
    app = web.Application()
    server = A2AServer(
        mock_agent,
        capabilities=AgentCapabilities(streaming=True, push_notifications=True),
    )
    server.setup(app, url="https://test.example.com/a2a")
    return app


class TestPushConfigRoutes:
    async def test_auto_store_created(self, mock_agent):
        server = A2AServer(
            mock_agent,
            capabilities=AgentCapabilities(push_notifications=True),
        )
        assert server._push_store is not None

    async def test_no_store_when_disabled(self, mock_agent):
        server = A2AServer(mock_agent, capabilities=AgentCapabilities())
        assert server._push_store is None

    async def test_crud_roundtrip(self, aiohttp_client, push_app):
        client = await aiohttp_client(push_app)
        # Create
        resp = await client.post(
            "/a2a/tasks/t1/pushNotificationConfigs",
            headers={"A2A-Version": "1.0"},
            json={"url": "https://example.com/hook"},
        )
        assert resp.status == 200
        created = await resp.json()
        cfg_id = created["id"]
        assert created["taskId"] == "t1"
        # List
        lst = await client.get("/a2a/tasks/t1/pushNotificationConfigs",
                               headers={"A2A-Version": "1.0"})
        assert len((await lst.json())["configs"]) == 1
        # Get
        got = await client.get(f"/a2a/tasks/t1/pushNotificationConfigs/{cfg_id}",
                               headers={"A2A-Version": "1.0"})
        assert got.status == 200
        # Delete
        dele = await client.delete(f"/a2a/tasks/t1/pushNotificationConfigs/{cfg_id}",
                                   headers={"A2A-Version": "1.0"})
        assert dele.status == 200
        assert (await dele.json())["deleted"] is True
        # Get after delete -> 404
        missing = await client.get(f"/a2a/tasks/t1/pushNotificationConfigs/{cfg_id}",
                                   headers={"A2A-Version": "1.0"})
        assert missing.status == 404
