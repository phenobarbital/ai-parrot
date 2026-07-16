"""Unit tests for BusCore (FEAT-310, TASK-1784)."""
import asyncio
import time

import pytest

from parrot.core.events.bus import (
    BackpressureError,
    BusClosedError,
    BusCore,
    EventEnvelope,
    Severity,
)
from parrot.core.events.evb import EventPriority


def make_envelope(
    topic: str = "test.topic",
    *,
    severity: Severity = Severity.INFO,
    priority: EventPriority = EventPriority.NORMAL,
) -> EventEnvelope:
    return EventEnvelope(
        topic=topic, payload={}, severity=severity, priority=priority
    )


async def wait_until(condition, timeout: float = 2.0) -> None:
    """Poll *condition* until truthy or fail the test."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if condition():
            return
        await asyncio.sleep(0.01)
    pytest.fail("condition not met within timeout")


@pytest.fixture
async def bus_core():
    core = BusCore(workers=2, queue_size=8)  # small queue for tests
    await core.start()
    yield core
    await core.close()


async def test_publish_is_o1_enqueue(bus_core):
    started = asyncio.Event()
    done = asyncio.Event()

    async def slow_handler(env):
        started.set()
        await asyncio.sleep(0.3)
        done.set()

    bus_core.subscribe("slow.topic", slow_handler)

    t0 = time.monotonic()
    await bus_core.publish(make_envelope("slow.topic"))
    elapsed = time.monotonic() - t0

    # publish returned before the handler even started
    assert elapsed < 0.1
    assert not started.is_set()
    await wait_until(done.is_set)


async def test_priority_queues_scheduling():
    core = BusCore(workers=1, queue_size=16)
    order: list[str] = []

    async def handler(env):
        order.append(env.priority.name)

    core.subscribe("*", handler)
    # Enqueue BEFORE starting the worker so all levels compete.
    for _ in range(3):
        await core.publish(make_envelope(priority=EventPriority.LOW))
    await core.publish(make_envelope(priority=EventPriority.CRITICAL))
    await core.publish(make_envelope(priority=EventPriority.HIGH))

    await core.start()
    await wait_until(lambda: len(order) == 5)
    await core.close()

    assert order[0] == "CRITICAL"
    assert order[1] == "HIGH"
    assert order[2:] == ["LOW", "LOW", "LOW"]


async def test_severity_filter_subscription(bus_core):
    received: list[Severity] = []

    async def handler(env):
        received.append(env.severity)

    marker = asyncio.Event()

    async def marker_handler(env):
        marker.set()

    bus_core.subscribe("sev.*", handler, min_severity=Severity.WARNING)
    bus_core.subscribe("sev.done", marker_handler)

    await bus_core.publish(make_envelope("sev.a", severity=Severity.INFO))
    await bus_core.publish(make_envelope("sev.a", severity=Severity.DEBUG))
    await bus_core.publish(make_envelope("sev.a", severity=Severity.WARNING))
    await bus_core.publish(make_envelope("sev.a", severity=Severity.ERROR))
    await bus_core.publish(make_envelope("sev.done", severity=Severity.INFO))

    await wait_until(marker.is_set)
    await wait_until(lambda: len(received) == 2)
    assert Severity.INFO not in received
    assert Severity.DEBUG not in received
    assert received == [Severity.WARNING, Severity.ERROR]


async def test_handler_error_isolation_model_b():
    core = BusCore(workers=2, queue_size=8, retry_attempts=1)
    await core.start()

    sibling_calls: list[str] = []
    errors: list[EventEnvelope] = []

    async def raising_handler(env):
        raise RuntimeError("boom")

    async def sibling_handler(env):
        sibling_calls.append(env.topic)

    async def error_observer(env):
        errors.append(env)

    core.subscribe("iso.topic", raising_handler)
    core.subscribe("iso.topic", sibling_handler)
    core.subscribe("bus.subscriber_error", error_observer)

    # Emitter unaffected: publish does not raise.
    await core.publish(make_envelope("iso.topic"))

    await wait_until(lambda: len(sibling_calls) == 1)
    await wait_until(lambda: len(errors) == 1)
    meta = errors[0]
    assert meta.topic == "bus.subscriber_error"
    assert meta.payload["original_topic"] == "iso.topic"
    assert meta.payload["error_type"] == "RuntimeError"
    assert meta.severity == Severity.INFO  # capped below alert thresholds
    await core.close()


async def test_meta_event_recursion_guard():
    core = BusCore(workers=1, queue_size=16, retry_attempts=1)
    await core.start()

    meta_handler_calls: list[str] = []
    observer_calls: list[str] = []

    async def raising_handler(env):
        raise RuntimeError("boom")

    async def raising_meta_handler(env):
        meta_handler_calls.append(env.topic)
        raise RuntimeError("meta boom")

    async def observer(env):
        observer_calls.append(env.topic)

    core.subscribe("guard.topic", raising_handler)
    core.subscribe("bus.subscriber_error", raising_meta_handler)
    core.subscribe("bus.subscriber_error", observer)

    await core.publish(make_envelope("guard.topic"))

    await wait_until(lambda: len(meta_handler_calls) == 1)
    # Give any (buggy) recursion a chance to manifest.
    await asyncio.sleep(0.2)
    assert meta_handler_calls == ["bus.subscriber_error"]
    assert observer_calls == ["bus.subscriber_error"]  # no loop
    await core.close()


async def test_backpressure_reject():
    core = BusCore(
        workers=1, queue_size=1, default_backpressure="reject"
    )
    # Not started — the queue cannot drain.
    await core.publish(make_envelope("r.a"))
    with pytest.raises(BackpressureError):
        await core.publish(make_envelope("r.b"))
    core._stopping = True  # allow clean close without a start
    await core.close(drain_timeout=0.1)


async def test_backpressure_drop_oldest():
    core = BusCore(
        workers=1, queue_size=1, default_backpressure="drop_oldest"
    )
    received: list[str] = []

    async def handler(env):
        received.append(env.topic)

    core.subscribe("d.*", handler)
    await core.publish(make_envelope("d.first"))
    await core.publish(make_envelope("d.second"))  # drops d.first

    await core.start()
    await wait_until(lambda: len(received) == 1)
    await asyncio.sleep(0.05)
    assert received == ["d.second"]
    await core.close()


async def test_backpressure_block_emits_meta():
    core = BusCore(workers=1, queue_size=1)  # default policy: block
    backpressure_events: list[EventEnvelope] = []

    async def bp_observer(env):
        backpressure_events.append(env)

    received: list[str] = []

    async def handler(env):
        received.append(env.topic)

    core.subscribe("bus.backpressure", bp_observer)
    core.subscribe("b.*", handler)

    await core.publish(make_envelope("b.one"))
    publish_task = asyncio.create_task(
        core.publish(make_envelope("b.two"))
    )
    await asyncio.sleep(0.05)
    assert not publish_task.done()  # blocked on the full queue

    await core.start()  # workers drain → blocked publish completes
    await asyncio.wait_for(publish_task, timeout=2.0)
    await wait_until(lambda: len(received) == 2)
    await wait_until(lambda: len(backpressure_events) >= 1)
    assert backpressure_events[0].payload["policy"] == "block"
    await core.close()


async def test_retry_backoff_then_dlq_callback():
    dlq_calls: list[dict] = []

    def on_dlq(envelope, *, attempts, error, subscriber_id):
        dlq_calls.append(
            {
                "envelope": envelope,
                "attempts": attempts,
                "error": error,
                "subscriber_id": subscriber_id,
            }
        )

    core = BusCore(
        workers=1,
        queue_size=8,
        retry_attempts=2,
        retry_base_delay=0.01,
        on_dlq=on_dlq,
    )
    await core.start()

    handler_calls: list[str] = []

    async def always_fails(env):
        handler_calls.append(env.event_id)
        raise ValueError("permanent failure")

    core.subscribe("dlq.topic", always_fails)
    env = make_envelope("dlq.topic")
    await core.publish(env)

    await wait_until(lambda: len(dlq_calls) == 1)
    assert len(handler_calls) == 2  # retried
    call = dlq_calls[0]
    assert call["envelope"] is env
    assert call["attempts"] == 2
    assert isinstance(call["error"], ValueError)
    await core.close()


async def test_graceful_shutdown_drain():
    core = BusCore(workers=2, queue_size=32)
    await core.start()

    handled: list[str] = []

    async def handler(env):
        await asyncio.sleep(0.01)
        handled.append(env.event_id)

    core.subscribe("drain.*", handler)
    for i in range(10):
        await core.publish(make_envelope(f"drain.{i}"))

    await core.close()
    assert len(handled) == 10  # everything drained before shutdown

    with pytest.raises(BusClosedError):
        await core.publish(make_envelope("drain.after"))
