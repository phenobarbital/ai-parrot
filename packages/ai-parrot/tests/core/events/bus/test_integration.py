"""End-to-end integration tests for FEAT-310 (spec §4, TASK-1793)."""
import asyncio
import json
import time
from dataclasses import dataclass

import pytest

from parrot.core.events import Event, EventBus
from parrot.core.events.bus import BusCore, DLQHandler, EventEnvelope, Severity
from parrot.core.events.bus import dlq as dlq_module
from parrot.core.events.bus.backends.redis_streams import RedisStreamsBackend
from parrot.core.events.bus.subscribers import AlertRule, NotificationSubscriber
from parrot.core.events.lifecycle.base import LifecycleEvent
from parrot.core.events.lifecycle.registry import EventRegistry
from parrot.core.events.lifecycle.trace import TraceContext

from .test_redis_streams import FakeResponseError, FakeStreamsRedis


async def wait_until(condition, timeout: float = 3.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if condition():
            return
        await asyncio.sleep(0.01)
    pytest.fail("condition not met within timeout")


class MockNotify:
    """async-notify stand-in recording deliveries."""

    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def send_notification(
        self, message, recipients, provider="email", subject=None, **kwargs
    ):
        self.calls.append(
            {"message": message, "recipients": recipients, "provider": provider}
        )
        return {"status": "sent"}


@pytest.fixture
def mock_notify():
    return MockNotify()


# ---------------------------------------------------------------------------
# spec §4: test_end_to_end_memory_mode
# ---------------------------------------------------------------------------


async def test_end_to_end_memory_mode(mock_notify):
    """emit → workers → severity-filtered subscriber → notification fires."""
    bus = EventBus()  # MemoryBackend default

    filtered: list[Event] = []
    bus.subscribe("orders.*", lambda e: filtered.append(e),
                  min_severity=Severity.WARNING)

    alerter = NotificationSubscriber(
        mock_notify,
        rules=[
            AlertRule(
                rule_id="order-errors",
                pattern="orders.*",
                min_severity=Severity.ERROR,
                provider="slack",
                recipients=["#ops"],
            )
        ],
    )
    alerter.attach(bus._core)

    await bus.emit("orders.created", {"id": 1})                          # INFO
    await bus.emit("orders.delayed", {"id": 2}, severity=Severity.WARNING)
    await bus.emit("orders.failed", {"id": 3}, severity=Severity.ERROR)

    await wait_until(lambda: len(filtered) == 2)  # WARNING + ERROR only
    assert {e.event_type for e in filtered} == {
        "orders.delayed", "orders.failed",
    }
    await wait_until(lambda: len(mock_notify.calls) == 1)  # rule fired once
    assert "orders.failed" in mock_notify.calls[0]["message"]
    assert mock_notify.calls[0]["provider"] == "slack"
    await bus.close()


# ---------------------------------------------------------------------------
# spec §4: test_end_to_end_streams_mode (fake Redis; real-Redis variant is
# integration-marked in test_redis_streams.py)
# ---------------------------------------------------------------------------


async def test_end_to_end_streams_mode(monkeypatch):
    """Two consumers in one group: at-least-once, no double-processing."""
    import parrot.core.events.bus.backends.redis_streams as streams_mod
    monkeypatch.setattr(
        streams_mod.aioredis, "ResponseError", FakeResponseError, raising=False
    )

    shared_redis = FakeStreamsRedis()  # one "server" for both instances

    def make_backend(name: str) -> RedisStreamsBackend:
        return RedisStreamsBackend(
            client=shared_redis,
            consumer_name=name,
            block_ms=20,
            autoclaim_interval=999,
            stream_refresh_interval=0.01,
        )

    backend_a, backend_b = make_backend("inst-a"), make_backend("inst-b")
    received_a: list[str] = []
    received_b: list[str] = []

    async def consumer_a(env: EventEnvelope) -> None:
        received_a.append(env.event_id)

    async def consumer_b(env: EventEnvelope) -> None:
        received_b.append(env.event_id)

    envelopes = [
        EventEnvelope(topic=f"jobs.task{i}", payload={"i": i})
        for i in range(12)
    ]
    for env in envelopes:
        await backend_a.publish(env)

    await backend_a.start_consumer(consumer_a)
    await backend_b.start_consumer(consumer_b)
    await wait_until(lambda: len(received_a) + len(received_b) == 12)
    await asyncio.sleep(0.1)

    processed = received_a + received_b
    assert sorted(processed) == sorted(e.event_id for e in envelopes)
    assert len(set(processed)) == 12          # dedup: no double-processing
    assert len(shared_redis.acked) == 12      # every entry ACKed
    await backend_a.close()
    await backend_b.close()


# ---------------------------------------------------------------------------
# spec §4: test_lifecycle_dual_emit_through_facade
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _IntegrationLifecycleEvent(LifecycleEvent):
    """Concrete lifecycle event for the dual-emit path."""
    step: str = "done"


async def test_lifecycle_dual_emit_through_facade():
    """EventRegistry.forward_to_bus → envelope arrives; FEAT-177
    fire-and-forget preserved (registry emit never waits on the bus)."""
    bus = EventBus()
    arrived: list[Event] = []
    bus.subscribe("lifecycle.*", lambda e: arrived.append(e))

    # Slow bus subscriber must NOT delay the typed hot path.
    async def slow_bus_subscriber(event):
        await asyncio.sleep(0.3)

    bus.subscribe("lifecycle.*", slow_bus_subscriber)

    registry = EventRegistry(event_bus=bus, forward_to_global=False)
    typed_calls: list[LifecycleEvent] = []

    async def typed_callback(event):
        typed_calls.append(event)

    registry.subscribe(
        _IntegrationLifecycleEvent, typed_callback, forward_to_bus=True
    )

    evt = _IntegrationLifecycleEvent(
        trace_context=TraceContext.new_root(),
        source_type="agent",
        source_name="itest-agent",
    )
    t0 = time.monotonic()
    await registry.emit(evt)
    hot_path = time.monotonic() - t0

    assert typed_calls == [evt]      # typed hot path delivered synchronously
    assert hot_path < 0.1            # fire-and-forget: no bus wait
    await wait_until(lambda: len(arrived) == 1)
    assert arrived[0].event_type == "lifecycle._IntegrationLifecycleEvent"
    assert arrived[0].payload["event_id"] == evt.event_id
    await bus.close()


# ---------------------------------------------------------------------------
# spec §4: test_graceful_shutdown_drain (no lost DLQ writes)
# ---------------------------------------------------------------------------


class _FakeDLQConn:
    def __init__(self, store):
        self._store = store

    async def execute(self, sql, *args):
        self._store.append((sql, args))


class _FakeDLQCtx:
    def __init__(self, store):
        self._store = store

    async def __aenter__(self):
        return _FakeDLQConn(self._store)

    async def __aexit__(self, *exc):
        return False


@pytest.fixture
def mock_asyncdb(monkeypatch):
    store: list = []

    class FakeDB:
        def __init__(self, driver, dsn=None, **kwargs):
            pass

        async def connection(self):
            return _FakeDLQCtx(store)

    monkeypatch.setattr(dlq_module, "AsyncDB", FakeDB)
    return store


async def test_graceful_shutdown_drain(mock_asyncdb):
    """Pending queue drained within deadline; no lost DLQ writes."""
    core = BusCore(
        workers=2, queue_size=64, retry_attempts=1, drain_timeout=5.0
    )
    handler = DLQHandler(core, dsn="postgres://fake/db")
    core._on_dlq = handler.on_dlq
    await core.start()

    handled: list[str] = []

    async def slowish(env):
        await asyncio.sleep(0.01)
        handled.append(env.event_id)

    async def always_fails(env):
        raise ValueError("dlq me")

    core.subscribe("work.*", slowish)
    core.subscribe("doomed.*", always_fails)

    for i in range(10):
        await core.publish(EventEnvelope(topic=f"work.{i}", payload={}))
    doomed = EventEnvelope(topic="doomed.one", payload={})
    await core.publish(doomed)

    await core.close()  # graceful drain
    assert len(handled) == 10  # everything drained before shutdown

    # The DLQ write survived the shutdown (fire-and-forget not lost).
    await asyncio.sleep(0.05)
    dlq_inserts = [
        (sql, args) for sql, args in mock_asyncdb if "INSERT INTO" in sql
    ]
    assert len(dlq_inserts) == 1
    assert dlq_inserts[0][1][0] == doomed.event_id
    assert json.loads(dlq_inserts[0][1][2]) == {}

    from parrot.core.events.bus import BusClosedError
    with pytest.raises(BusClosedError):
        await core.publish(EventEnvelope(topic="work.late", payload={}))
