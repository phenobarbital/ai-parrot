"""Regression tests for the EventBus Redis consumer lifecycle.

The orchestrator historically constructed a Redis-backed EventBus and called
connect(), but never consumed inbound distributed events. It was then fixed by
spawning ``start_redis_listener()`` as a background task — which navigator-
eventbus >= 0.4.0 turned into a deprecated no-op alias: ``connect()``
(``BusCore.start()``) now starts the backend consumer itself, so the extra task
only emitted a DeprecationWarning log line and finished immediately while
pretending to be a live receive loop. These tests pin the current behaviour:

- start() connects the bus and does NOT call the deprecated alias.
- stop() closes the bus (which drains and stops the consumer it owns).
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from parrot.autonomous.orchestrator import AutonomousOrchestrator


def _make_fake_eventbus(*, use_redis: bool) -> MagicMock:
    """Build a MagicMock EventBus with the navigator-eventbus 0.4 surface."""
    bus = MagicMock()
    bus.use_redis = use_redis
    bus.connect = AsyncMock()
    bus.close = AsyncMock()
    bus.subscribe = MagicMock()
    bus.on = MagicMock(return_value=lambda fn: fn)
    bus.start_redis_listener = AsyncMock()
    return bus


@pytest.mark.asyncio
async def test_start_connects_bus_without_deprecated_listener_when_redis_backed():
    fake_bus = _make_fake_eventbus(use_redis=True)

    with patch(
        "parrot.autonomous.orchestrator.EventBus", return_value=fake_bus
    ), patch(
        "parrot.autonomous.orchestrator.RedisJobInjector"
    ) as MockInjector:
        MockInjector.return_value.connect = AsyncMock()
        MockInjector.return_value.start_listening = AsyncMock()
        MockInjector.return_value.close = AsyncMock()

        orch = AutonomousOrchestrator(redis_url="redis://localhost:6379/0", use_webhooks=False)
        await orch.start()

        # connect() starts the Redis consumer; the deprecated alias must not be used.
        fake_bus.connect.assert_awaited_once()
        fake_bus.start_redis_listener.assert_not_called()
        assert not hasattr(orch, "_evb_listener_task")

        await orch.stop()

        fake_bus.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_start_skips_deprecated_listener_for_in_memory_bus():
    fake_bus = _make_fake_eventbus(use_redis=False)

    with patch("parrot.autonomous.orchestrator.EventBus", return_value=fake_bus):
        orch = AutonomousOrchestrator(redis_url=None, use_webhooks=False)
        await orch.start()

        fake_bus.connect.assert_awaited_once()
        fake_bus.start_redis_listener.assert_not_called()

        await orch.stop()

        fake_bus.close.assert_awaited_once()
