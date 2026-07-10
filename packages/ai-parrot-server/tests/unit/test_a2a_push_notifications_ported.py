"""Supplementary push-notification coverage ported from the parallel
``feat-272`` implementation (FEAT-272 / TASK-1716).

These A-only cases widen ``feat-FEAT-272``'s coverage of the
``PushNotificationStore`` SSRF guard and CRUD edge cases, plus the
``A2AServer`` push-store wiring. They exercise only the public store /
server API and pass unchanged against this implementation. (A's REST-route
push tests were intentionally NOT ported — this implementation has its own
REST push binding and end-to-end coverage in ``test_a2a_v1_roundtrip.py``.)
"""
from unittest.mock import AsyncMock, MagicMock

import pytest

from parrot.a2a.models import AgentCapabilities, TaskPushNotificationConfig
from parrot.a2a.push_notifications import PushNotificationStore
from parrot.a2a.server import A2AServer


@pytest.fixture
def store():
    return PushNotificationStore()


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


class TestPushStoreEdgeCases:
    async def test_get_missing_returns_none(self, store):
        assert await store.get("task-1", "nonexistent") is None

    async def test_delete_missing_returns_false(self, store):
        assert await store.delete("task-1", "nonexistent") is False

    async def test_list_for_task_scoped_by_task(self, store):
        await store.create(
            TaskPushNotificationConfig(id="a", task_id="task-1", url="https://x.com/a")
        )
        await store.create(
            TaskPushNotificationConfig(id="b", task_id="task-2", url="https://x.com/b")
        )
        assert len(await store.list_for_task("task-1")) == 1
        assert len(await store.list_for_task("task-2")) == 1


class TestPushStoreSSRFGuard:
    async def test_allow_public_hostname(self, store):
        config = TaskPushNotificationConfig(
            id="cfg-1", task_id="task-1", url="https://webhook.example.com/hook"
        )
        result = await store.create(config)
        assert result.url == "https://webhook.example.com/hook"

    async def test_reject_10_x_private_range(self, store):
        config = TaskPushNotificationConfig(
            id="cfg-1", task_id="task-1", url="http://10.0.0.5/hook"
        )
        with pytest.raises(ValueError, match="Private/loopback"):
            await store.create(config)

    async def test_reject_invalid_scheme(self, store):
        config = TaskPushNotificationConfig(
            id="cfg-1", task_id="task-1", url="ftp://example.com/hook"
        )
        with pytest.raises(ValueError, match="Invalid scheme"):
            await store.create(config)


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
