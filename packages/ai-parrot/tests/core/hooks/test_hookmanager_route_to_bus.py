"""Unit tests for HookManager route_to_bus mode (FEAT-310, TASK-1790)."""
import asyncio
import time
from unittest.mock import AsyncMock, MagicMock

import pytest

from parrot.core.events import Event, EventBus
from parrot.core.events.bus.envelope import Severity
from parrot.core.hooks.manager import HookManager
from parrot.core.hooks.models import HookEvent, HookType


def make_event(hook_type=HookType.SCHEDULER, event_type="tick") -> HookEvent:
    return HookEvent(
        hook_id="test-hook",
        hook_type=hook_type,
        event_type=event_type,
        payload={"value": 42},
        metadata={"m": 1},
        target_type="agent",
        target_id="my-agent",
    )


async def wait_until(condition, timeout: float = 2.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if condition():
            return
        await asyncio.sleep(0.01)
    pytest.fail("condition not met within timeout")


async def test_route_to_bus_publishes_envelope():
    """route_to_bus=True → first-class hooks.<type>.<event> publication."""
    bus = EventBus()
    received: list[Event] = []

    async def observer(event):
        received.append(event)

    bus.subscribe("hooks.*", observer)

    mgr = HookManager(route_to_bus=True)
    assert mgr.route_to_bus is True
    cb = AsyncMock()
    mgr.set_event_callback(cb)
    mgr.set_event_bus(bus)

    dispatch = mgr._build_dispatch()
    hook_event = make_event(HookType.JIRA_WEBHOOK, "issue_created")
    await dispatch(hook_event)

    cb.assert_awaited_once_with(hook_event)  # callback untouched
    await wait_until(lambda: len(received) == 1)
    event = received[0]
    assert event.event_type == "hooks.jira_webhook.issue_created"
    assert event.payload == {"value": 42}  # hook payload, not model_dump
    assert event.source == "test-hook"
    assert event.metadata["m"] == 1
    assert event.metadata["target_type"] == "agent"
    assert event.metadata["target_id"] == "my-agent"
    await bus.close()


async def test_route_to_bus_severity_from_metadata():
    bus = EventBus()
    envelopes = []
    bus._core.subscribe("hooks.*", lambda env: envelopes.append(env))

    mgr = HookManager(route_to_bus=True)
    mgr.set_event_bus(bus)
    dispatch = mgr._build_dispatch()

    critical = make_event()
    critical.metadata["severity"] = "critical"
    await dispatch(critical)
    plain = make_event(event_type="plain")
    await dispatch(plain)

    await wait_until(lambda: len(envelopes) == 2)
    by_topic = {env.topic: env for env in envelopes}
    assert by_topic["hooks.scheduler.tick"].severity == Severity.CRITICAL
    assert "severity" not in by_topic["hooks.scheduler.tick"].metadata
    assert by_topic["hooks.scheduler.plain"].severity == Severity.INFO
    await bus.close()


async def test_route_to_bus_default_off_legacy_dual_emit():
    """Default OFF → byte-identical legacy dual-emit wire shape."""
    mgr = HookManager()
    assert mgr.route_to_bus is False
    cb = AsyncMock()
    bus = MagicMock()
    bus.emit = AsyncMock(return_value=1)
    mgr._callback = cb
    mgr._event_bus = bus

    dispatch = mgr._build_dispatch()
    event = make_event(HookType.SCHEDULER, "tick")
    await dispatch(event)

    cb.assert_awaited_once_with(event)
    bus.emit.assert_awaited_once_with(
        "hooks.scheduler.tick",
        event.model_dump(),
    )


async def test_orchestrator_callback_still_fires():
    """Callback path is invoked in BOTH modes (never replaced)."""
    for route in (False, True):
        mgr = HookManager(route_to_bus=route)
        cb = AsyncMock()
        bus = MagicMock()
        bus.emit = AsyncMock(return_value=1)
        mgr.set_event_callback(cb)
        mgr.set_event_bus(bus)

        dispatch = mgr._build_dispatch()
        event = make_event()
        await dispatch(event)
        cb.assert_awaited_once_with(event)
        bus.emit.assert_awaited_once()


async def test_route_to_bus_setter_reinjects_hooks():
    mgr = HookManager()
    hook = MagicMock()
    hook.hook_id = "h1"
    hook.enabled = True
    mgr._hooks["h1"] = hook
    mgr._event_bus = MagicMock()

    mgr.route_to_bus = True
    assert mgr.route_to_bus is True
    hook.set_callback.assert_called()


async def test_bus_emit_failure_isolated_in_route_mode():
    mgr = HookManager(route_to_bus=True)
    cb = AsyncMock()
    bus = MagicMock()
    bus.emit = AsyncMock(side_effect=RuntimeError("bus down"))
    mgr._callback = cb
    mgr._event_bus = bus

    dispatch = mgr._build_dispatch()
    event = make_event()
    await dispatch(event)  # must not raise
    cb.assert_awaited_once_with(event)
