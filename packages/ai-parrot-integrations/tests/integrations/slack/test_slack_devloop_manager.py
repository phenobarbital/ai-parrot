"""Manager wiring tests for the Slack dev-loop service (TASK-3208)."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from parrot.integrations.manager import IntegrationBotManager  # verified: manager.py:63


def _config(devloop=None, connection_mode: str = "webhook") -> SimpleNamespace:
    return SimpleNamespace(
        chatbot_id="bot1",
        name="bot1",
        jira_client_id=None,
        connection_mode=connection_mode,
        devloop=devloop,
        bot_token="xoxb-x",
        signing_secret="sig",
    )


def _manager() -> IntegrationBotManager:
    app = MagicMock()
    app.get = MagicMock(return_value=None)
    bot_manager = MagicMock()
    bot_manager.get_app = MagicMock(return_value=app)
    manager = IntegrationBotManager(bot_manager=bot_manager)
    manager._get_agent = AsyncMock(return_value=MagicMock())
    return manager


def _fake_wrapper() -> MagicMock:
    wrapper = MagicMock()
    wrapper.start = AsyncMock()
    wrapper.stop = AsyncMock()
    wrapper._socket_handler = None
    return wrapper


@pytest.mark.asyncio
async def test_manager_wires_service_when_enabled():
    """A config with devloop.enabled=True builds DevLoopDispatchService, calls register_devloop and service.start()."""
    manager = _manager()
    wrapper = _fake_wrapper()
    devloop_cfg = SimpleNamespace(enabled=True, redis_url="")
    config = _config(devloop=devloop_cfg)

    fake_service = MagicMock()
    fake_service.start = AsyncMock()

    with (
        patch("parrot.integrations.slack.wrapper.SlackAgentWrapper", return_value=wrapper),
        patch("redis.asyncio.from_url", return_value=MagicMock()) as from_url,
        patch("parrot.integrations.devloop.service.DevLoopDispatchService", return_value=fake_service) as service_cls,
        patch("parrot.integrations.slack.devloop.register_devloop") as register_devloop,
        patch("parrot.integrations.slack.devloop.actions.SlackIdentityResolver"),
        patch("parrot.integrations.slack.devloop.transport.SlackDevLoopTransport"),
    ):
        await manager._start_slack_bot("bot1", config)

    from_url.assert_called_once()
    service_cls.assert_called_once()
    register_devloop.assert_called_once_with(wrapper, fake_service)
    fake_service.start.assert_awaited_once()
    assert manager._devloop_services["bot1"] is fake_service


@pytest.mark.asyncio
async def test_manager_skips_service_when_disabled_or_absent():
    """devloop=None or enabled=False ⇒ no service, bot still starts."""
    manager = _manager()
    wrapper = _fake_wrapper()

    with patch("parrot.integrations.slack.wrapper.SlackAgentWrapper", return_value=wrapper):
        await manager._start_slack_bot("bot1", _config(devloop=None))
        assert manager._devloop_services == {}
        wrapper.start.assert_awaited()

    manager2 = _manager()
    wrapper2 = _fake_wrapper()
    with patch("parrot.integrations.slack.wrapper.SlackAgentWrapper", return_value=wrapper2):
        await manager2._start_slack_bot("bot1", _config(devloop=SimpleNamespace(enabled=False, redis_url="")))
        assert manager2._devloop_services == {}
        wrapper2.start.assert_awaited()


@pytest.mark.asyncio
async def test_manager_devloop_failure_never_blocks_bot_startup():
    """A construction failure in the dev-loop wiring is caught and logged; the Slack bot still starts."""
    manager = _manager()
    wrapper = _fake_wrapper()
    devloop_cfg = SimpleNamespace(enabled=True, redis_url="")
    config = _config(devloop=devloop_cfg)

    with (
        patch("parrot.integrations.slack.wrapper.SlackAgentWrapper", return_value=wrapper),
        patch("redis.asyncio.from_url", side_effect=RuntimeError("no redis")),
    ):
        await manager._start_slack_bot("bot1", config)

    assert manager._devloop_services == {}
    wrapper.start.assert_awaited_once()


@pytest.mark.asyncio
async def test_shutdown_stops_service_before_wrapper():
    """shutdown() awaits service.stop() before wrapper.stop() and clears the registries."""
    manager = _manager()
    call_order: list[str] = []

    fake_service = MagicMock()

    async def _service_stop():
        call_order.append("service.stop")

    fake_service.stop = _service_stop

    wrapper = _fake_wrapper()

    async def _wrapper_stop():
        call_order.append("wrapper.stop")

    wrapper.stop = _wrapper_stop

    fake_redis = MagicMock()
    fake_redis.aclose = AsyncMock()

    manager._devloop_services["bot1"] = fake_service
    manager._devloop_redis["bot1"] = fake_redis
    manager.slack_bots["bot1"] = wrapper

    await manager.shutdown()

    assert call_order.index("service.stop") < call_order.index("wrapper.stop")
    assert manager._devloop_services == {}
    assert manager._devloop_redis == {}
    fake_redis.aclose.assert_awaited_once()
