"""Unit tests for the A2A push notification config store (FEAT-272 / TASK-1716).

Covers:
    - `PushNotificationStore` CRUD (create/get/list_for_task/delete).
    - SSRF validation stub (rejects private/loopback IP webhook URLs).
    - Wiring into `A2AServer` (auto-created when `capabilities.
      push_notifications` is true; REST CRUD routes; -32003 when disabled).
"""
from unittest.mock import AsyncMock, MagicMock

import pytest
from aiohttp import web

from parrot.a2a.models import AgentCapabilities, TaskPushNotificationConfig
from parrot.a2a.push_notifications import PushNotificationStore
from parrot.a2a.server import A2AServer


@pytest.fixture
def store():
    return PushNotificationStore()


class TestPushNotificationStore:
    async def test_create_assigns_id(self, store):
        config = TaskPushNotificationConfig(
            id="", task_id="task-1", url="https://example.com/hook"
        )
        result = await store.create(config)
        assert result.id != ""

    async def test_get_returns_config(self, store):
        config = TaskPushNotificationConfig(
            id="cfg-1", task_id="task-1", url="https://example.com/hook"
        )
        await store.create(config)
        found = await store.get("task-1", "cfg-1")
        assert found is not None
        assert found.url == "https://example.com/hook"

    async def test_get_missing_returns_none(self, store):
        assert await store.get("task-1", "nonexistent") is None

    async def test_list_for_task(self, store):
        for i in range(3):
            await store.create(TaskPushNotificationConfig(
                id=f"cfg-{i}", task_id="task-1", url=f"https://example.com/hook{i}"
            ))
        configs = await store.list_for_task("task-1")
        assert len(configs) == 3

    async def test_list_for_task_scoped_by_task(self, store):
        await store.create(TaskPushNotificationConfig(id="a", task_id="task-1", url="https://x.com/a"))
        await store.create(TaskPushNotificationConfig(id="b", task_id="task-2", url="https://x.com/b"))
        assert len(await store.list_for_task("task-1")) == 1
        assert len(await store.list_for_task("task-2")) == 1

    async def test_delete(self, store):
        await store.create(TaskPushNotificationConfig(
            id="cfg-1", task_id="task-1", url="https://example.com/hook"
        ))
        assert await store.delete("task-1", "cfg-1") is True
        assert await store.get("task-1", "cfg-1") is None

    async def test_delete_missing_returns_false(self, store):
        assert await store.delete("task-1", "nonexistent") is False

    async def test_reject_private_ip(self, store):
        config = TaskPushNotificationConfig(
            id="cfg-1", task_id="task-1", url="http://127.0.0.1/hook"
        )
        with pytest.raises(ValueError, match="Private/loopback"):
            await store.create(config)

    async def test_reject_10_x_private_range(self, store):
        config = TaskPushNotificationConfig(
            id="cfg-1", task_id="task-1", url="http://10.0.0.5/hook"
        )
        with pytest.raises(ValueError, match="Private/loopback"):
            await store.create(config)

    async def test_allow_public_hostname(self, store):
        config = TaskPushNotificationConfig(
            id="cfg-1", task_id="task-1", url="https://webhook.example.com/hook"
        )
        result = await store.create(config)
        assert result.url == "https://webhook.example.com/hook"

    async def test_reject_invalid_scheme(self, store):
        config = TaskPushNotificationConfig(
            id="cfg-1", task_id="task-1", url="ftp://example.com/hook"
        )
        with pytest.raises(ValueError, match="Invalid scheme"):
            await store.create(config)


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


class TestA2AServerPushStoreWiring:
    def test_auto_created_when_capability_enabled(self, mock_agent):
        server = A2AServer(
            mock_agent, capabilities=AgentCapabilities(push_notifications=True)
        )
        assert server._push_store is not None
        assert isinstance(server._push_store, PushNotificationStore)

    def test_not_created_when_capability_disabled(self, mock_agent):
        server = A2AServer(
            mock_agent, capabilities=AgentCapabilities(push_notifications=False)
        )
        assert server._push_store is None

    def test_explicit_store_takes_precedence(self, mock_agent):
        custom_store = PushNotificationStore()
        server = A2AServer(
            mock_agent,
            capabilities=AgentCapabilities(push_notifications=True),
            push_store=custom_store,
        )
        assert server._push_store is custom_store


@pytest.fixture
def a2a_server_with_push(mock_agent):
    return A2AServer(mock_agent, capabilities=AgentCapabilities(push_notifications=True))


@pytest.fixture
def a2a_app_with_push(a2a_server_with_push):
    app = web.Application()
    a2a_server_with_push.setup(app, url="https://test.example.com/a2a")
    return app


@pytest.fixture
def a2a_server_no_push(mock_agent):
    return A2AServer(mock_agent, capabilities=AgentCapabilities(push_notifications=False))


@pytest.fixture
def a2a_app_no_push(a2a_server_no_push):
    app = web.Application()
    a2a_server_no_push.setup(app, url="https://test.example.com/a2a")
    return app


class TestPushConfigRestRoutes:
    async def test_crud_roundtrip(self, aiohttp_client, a2a_app_with_push):
        client = await aiohttp_client(a2a_app_with_push)

        create_resp = await client.post(
            "/a2a/tasks/task-1/pushNotificationConfigs",
            json={"url": "https://example.com/hook"},
        )
        assert create_resp.status == 201
        created = await create_resp.json()
        config_id = created["id"]
        assert created["url"] == "https://example.com/hook"

        get_resp = await client.get(
            f"/a2a/tasks/task-1/pushNotificationConfigs/{config_id}"
        )
        assert get_resp.status == 200
        fetched = await get_resp.json()
        assert fetched["id"] == config_id

        list_resp = await client.get("/a2a/tasks/task-1/pushNotificationConfigs")
        assert list_resp.status == 200
        listed = await list_resp.json()
        assert len(listed["configs"]) == 1

        delete_resp = await client.delete(
            f"/a2a/tasks/task-1/pushNotificationConfigs/{config_id}"
        )
        assert delete_resp.status == 200
        assert (await delete_resp.json())["deleted"] is True

        get_after_delete = await client.get(
            f"/a2a/tasks/task-1/pushNotificationConfigs/{config_id}"
        )
        assert get_after_delete.status == 404

    async def test_disabled_returns_push_not_supported(self, aiohttp_client, a2a_app_no_push):
        client = await aiohttp_client(a2a_app_no_push)
        resp = await client.post(
            "/a2a/tasks/task-1/pushNotificationConfigs",
            json={"url": "https://example.com/hook"},
        )
        assert resp.status == 400
        data = await resp.json()
        assert data["error"]["code"] == -32003
