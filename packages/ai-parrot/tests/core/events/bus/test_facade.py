"""Unit tests for the EventBus facade (FEAT-310, TASK-1786)."""
import asyncio
import time
from dataclasses import dataclass

import pytest

from parrot.core.events import (
    Event,
    EventBus,
    EventPriority,
    EventSubscription,
)
from parrot.core.events.bus import Severity
from parrot.core.events.lifecycle.base import LifecycleEvent
from parrot.core.events.lifecycle.registry import EventRegistry
from parrot.core.events.lifecycle.trace import TraceContext


async def wait_until(condition, timeout: float = 2.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if condition():
            return
        await asyncio.sleep(0.01)
    pytest.fail("condition not met within timeout")


@pytest.fixture
async def bus():
    b = EventBus()
    yield b
    await b.close()


async def test_facade_signatures_unchanged(bus):
    received: list[Event] = []

    async def handler(event):
        received.append(event)

    sid = bus.subscribe("a.*", handler, priority=5, filter_fn=lambda e: True)
    assert isinstance(sid, str)
    n = await bus.emit("a.b", {"k": 1})
    assert isinstance(n, int)
    assert n == 1
    await wait_until(lambda: len(received) == 1)
    assert bus.unsubscribe(sid) is True
    assert bus.unsubscribe(sid) is False


async def test_handlers_receive_legacy_event_instances(bus):
    received: list[Event] = []

    async def handler(event):
        received.append(event)

    bus.subscribe("legacy.*", handler)
    await bus.emit(
        "legacy.shape",
        {"k": 1},
        source="unit",
        priority=EventPriority.HIGH,
        correlation_id="corr-9",
        metadata={"m": 1},
    )
    await wait_until(lambda: len(received) == 1)
    event = received[0]
    assert isinstance(event, Event)
    assert event.event_type == "legacy.shape"
    assert event.payload == {"k": 1}
    assert event.source == "unit"
    assert event.priority == EventPriority.HIGH
    assert event.correlation_id == "corr-9"
    assert event.metadata == {"m": 1}
    assert event.timestamp.tzinfo is not None


async def test_emit_does_not_await_handlers(bus):
    started = asyncio.Event()
    done = asyncio.Event()

    async def slow_handler(event):
        started.set()
        await asyncio.sleep(0.3)
        done.set()

    bus.subscribe("slow.*", slow_handler)
    t0 = time.monotonic()
    n = await bus.emit("slow.one", {})
    elapsed = time.monotonic() - t0
    assert n == 1
    assert elapsed < 0.1
    assert not started.is_set()
    await wait_until(done.is_set)


async def test_publish_legacy_event_object(bus):
    received: list[Event] = []

    def sync_handler(event):  # sync handlers still supported
        received.append(event)

    bus.subscribe("pub.direct", sync_handler)
    event = Event(event_type="pub.direct", payload={"x": 2})
    n = await bus.publish(event)
    assert n == 1
    await wait_until(lambda: len(received) == 1)
    assert received[0].event_id == event.event_id
    # history compat shim
    assert event in bus._event_history


async def test_severity_kwargs_additive(bus):
    received: list[Event] = []

    async def handler(event):
        received.append(event)

    bus.subscribe("sev.*", handler, min_severity=Severity.WARNING)
    done = asyncio.Event()
    bus.subscribe("sev.done", lambda e: done.set())

    await bus.emit("sev.a", {"n": 1})                            # INFO — filtered
    await bus.emit("sev.a", {"n": 2}, severity=Severity.ERROR)   # delivered
    await bus.emit("sev.done", {})

    await wait_until(done.is_set)
    await wait_until(lambda: len(received) >= 1)
    await asyncio.sleep(0.05)
    assert len(received) == 1
    assert received[0].payload == {"n": 2}


async def test_on_decorator(bus):
    received: list[Event] = []

    @bus.on("deco.*")
    async def handler(event):
        received.append(event)

    await bus.emit("deco.fired", {})
    await wait_until(lambda: len(received) == 1)


async def test_filter_fn_receives_legacy_event(bus):
    received: list[Event] = []

    async def handler(event):
        received.append(event)

    bus.subscribe(
        "filt.*", handler, filter_fn=lambda e: e.payload.get("keep") is True
    )
    marker = asyncio.Event()
    bus.subscribe("filt.done", lambda e: marker.set())

    await bus.emit("filt.a", {"keep": False})
    await bus.emit("filt.a", {"keep": True})
    await bus.emit("filt.done", {"keep": True})

    await wait_until(marker.is_set)
    await asyncio.sleep(0.05)
    assert [e.payload for e in received if e.event_type == "filt.a"] == [
        {"keep": True}
    ]


async def test_close_rejects_new_publishes():
    bus = EventBus()
    await bus.emit("pre.close", {})
    await bus.close()
    with pytest.raises(Exception):
        await bus.emit("post.close", {})


@dataclass(frozen=True)
class _DummyLifecycleEvent(LifecycleEvent):
    """Concrete lifecycle event for dual-emit testing."""
    detail: str = "x"


async def test_lifecycle_dual_emit_through_facade(bus):
    received: list[Event] = []

    async def handler(event):
        received.append(event)

    bus.subscribe("lifecycle.*", handler)

    registry = EventRegistry(event_bus=bus, forward_to_global=False)
    callback_calls: list[LifecycleEvent] = []

    async def callback(event):
        callback_calls.append(event)

    registry.subscribe(_DummyLifecycleEvent, callback, forward_to_bus=True)

    evt = _DummyLifecycleEvent(
        trace_context=TraceContext.new_root(),
        source_type="agent",
        source_name="test-agent",
    )
    await registry.emit(evt)

    assert callback_calls == [evt]  # typed hot path unaffected
    await wait_until(lambda: len(received) == 1)
    bus_event = received[0]
    assert bus_event.event_type == "lifecycle._DummyLifecycleEvent"
    assert bus_event.payload["event_id"] == evt.event_id


def test_event_subscription_export_intact():
    sub = EventSubscription(pattern="a.*", handler=lambda e: None)
    assert sub.pattern == "a.*"
    assert isinstance(sub.subscriber_id, str)


def test_legacy_event_default_timestamp_is_utc():
    event = Event(event_type="ts.check", payload={})
    assert event.timestamp.tzinfo is not None
    assert event.timestamp.utcoffset().total_seconds() == 0
