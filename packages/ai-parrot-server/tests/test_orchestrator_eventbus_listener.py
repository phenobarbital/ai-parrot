"""Regression tests for the EventBus Redis listener lifecycle.

The orchestrator historically constructed a Redis-backed EventBus and called
connect(), but never started start_redis_listener() — so it published events to
Redis while never consuming inbound distributed events. These tests pin the
fixed behaviour:

- start() spawns the receive loop as a background task when the bus is
  Redis-backed, and NOT when it is in-memory.
- stop() cancels the listener task cleanly.
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from parrot.autonomous.orchestrator import AutonomousOrchestrator


def _make_fake_eventbus(*, use_redis: bool) -> MagicMock:
    """Build a MagicMock EventBus whose listener blocks until cancelled."""
    bus = MagicMock()
    bus.use_redis = use_redis
    bus.connect = AsyncMock()
    bus.close = AsyncMock()
    bus.subscribe = MagicMock()
    bus.on = MagicMock(return_value=lambda fn: fn)

    async def _blocking_listener():
        # Mimic pubsub.listen(): block forever until the task is cancelled.
        await asyncio.Event().wait()

    bus.start_redis_listener = MagicMock(side_effect=_blocking_listener)
    return bus


@pytest.mark.asyncio
async def test_start_spawns_redis_listener_when_redis_backed():
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

        assert orch._evb_listener_task is not None
        assert not orch._evb_listener_task.done()
        fake_bus.start_redis_listener.assert_called_once()

        await orch.stop()

        assert orch._evb_listener_task is None
        fake_bus.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_start_skips_listener_for_in_memory_bus():
    fake_bus = _make_fake_eventbus(use_redis=False)

    with patch("parrot.autonomous.orchestrator.EventBus", return_value=fake_bus):
        orch = AutonomousOrchestrator(redis_url=None, use_webhooks=False)
        await orch.start()

        assert orch._evb_listener_task is None
        fake_bus.start_redis_listener.assert_not_called()

        await orch.stop()
