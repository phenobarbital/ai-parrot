"""Unit tests for AuditSubscriber + MetricsSubscriber (FEAT-310, TASK-1792)."""
import asyncio
import time
from datetime import datetime, timedelta, timezone

import pytest

from parrot.core.events.bus import BusCore, EventEnvelope, Severity
from parrot.core.events.bus.subscribers import AuditSubscriber, MetricsSubscriber
from parrot.core.events.bus.subscribers import audit as audit_module


def make_envelope(topic: str = "app.evt", **kwargs) -> EventEnvelope:
    return EventEnvelope(topic=topic, payload=kwargs.pop("payload", {"k": 1}), **kwargs)


async def wait_until(condition, timeout: float = 2.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if condition():
            return
        await asyncio.sleep(0.01)
    pytest.fail("condition not met within timeout")


# ---------------------------------------------------------------------------
# Fake asyncdb (same shape as test_dlq.py)
# ---------------------------------------------------------------------------


class FakeConn:
    def __init__(self, store):
        self._store = store

    async def execute(self, sql, *args):
        if self._store.fail_execute:
            raise RuntimeError("pg down")
        self._store.executed.append((sql, args))


class FakeCtx:
    def __init__(self, store):
        self._store = store

    async def __aenter__(self):
        self._store.connections += 1
        return FakeConn(self._store)

    async def __aexit__(self, *exc):
        return False


class FakeStore:
    def __init__(self):
        self.executed = []
        self.connections = 0
        self.fail_execute = False


@pytest.fixture
def mock_asyncdb(monkeypatch):
    store = FakeStore()

    class FakeDB:
        def __init__(self, driver, dsn=None, **kwargs):
            store.driver = driver
            store.dsn = dsn

        async def connection(self):
            return FakeCtx(store)

    monkeypatch.setattr(audit_module, "AsyncDB", FakeDB)
    return store


def inserts(store):
    return [(sql, args) for sql, args in store.executed if "INSERT INTO" in sql]


# ---------------------------------------------------------------------------
# AuditSubscriber
# ---------------------------------------------------------------------------


async def test_audit_batched_append_only(mock_asyncdb):
    core = BusCore(workers=2, queue_size=64)
    await core.start()
    audit = AuditSubscriber(
        dsn="postgres://fake/db", batch_size=3, flush_interval=60.0
    )
    assert audit.attach(core) is not None

    for i in range(3):
        await core.publish(make_envelope(f"app.evt{i}"))

    # Size-triggered flush: 3 rows in ONE connection round.
    await wait_until(lambda: len(inserts(mock_asyncdb)) == 3)
    assert mock_asyncdb.connections >= 1
    ddl = [sql for sql, _ in mock_asyncdb.executed if "CREATE TABLE" in sql]
    assert len(ddl) == 1 and "navigator.evb_audit" in ddl[0]
    sql, args = inserts(mock_asyncdb)[0]
    assert "navigator.evb_audit" in sql
    assert "ON CONFLICT" not in sql  # append-only, duplicates allowed
    assert args[1] == "app.evt0"
    assert audit.stats["persisted"] == 3
    await audit.close()
    await core.close()


async def test_audit_flush_on_interval(mock_asyncdb):
    core = BusCore(workers=1, queue_size=16)
    await core.start()
    audit = AuditSubscriber(
        dsn="postgres://fake/db", batch_size=100, flush_interval=0.05
    )
    audit.attach(core)
    await core.publish(make_envelope("app.slow"))
    # Below batch size — the INTERVAL flush must pick it up.
    await wait_until(lambda: len(inserts(mock_asyncdb)) == 1)
    await audit.close()
    await core.close()


async def test_audit_flush_on_close(mock_asyncdb):
    core = BusCore(workers=1, queue_size=16)
    await core.start()
    audit = AuditSubscriber(
        dsn="postgres://fake/db", batch_size=100, flush_interval=600.0
    )
    audit.attach(core)
    await core.publish(make_envelope("app.pending"))
    await wait_until(lambda: audit.stats["buffered"] == 1)
    assert inserts(mock_asyncdb) == []  # nothing flushed yet

    await audit.close()  # close() flushes the remainder
    assert len(inserts(mock_asyncdb)) == 1
    await core.close()


async def test_audit_overload_drop_oldest(mock_asyncdb):
    audit = AuditSubscriber(
        dsn="postgres://fake/db",
        batch_size=1000,
        flush_interval=600.0,
        queue_size=5,
    )
    for i in range(8):
        await audit._on_envelope(make_envelope(f"app.e{i}"))
    assert audit.stats["buffered"] == 5
    assert audit.stats["dropped"] == 3
    # Oldest were dropped — newest survive.
    topics = [row[1] for row in audit._buffer]
    assert topics == ["app.e3", "app.e4", "app.e5", "app.e6", "app.e7"]


async def test_audit_persistence_failure_isolated(mock_asyncdb):
    mock_asyncdb.fail_execute = True
    audit = AuditSubscriber(
        dsn="postgres://fake/db", batch_size=1, flush_interval=600.0
    )
    await audit._on_envelope(make_envelope("app.x"))
    await audit._flush()  # must not raise
    assert audit.stats["persisted"] == 0


async def test_bus_meta_topics_excluded(mock_asyncdb):
    audit = AuditSubscriber(dsn="postgres://fake/db")
    await audit._on_envelope(make_envelope("bus.subscriber_error"))
    await audit._on_envelope(make_envelope("bus.dlq"))
    assert audit.stats["buffered"] == 0

    inclusive = AuditSubscriber(
        dsn="postgres://fake/db", include_bus_internal=True
    )
    await inclusive._on_envelope(make_envelope("bus.dlq"))
    assert inclusive.stats["buffered"] == 1


async def test_audit_missing_dsn_disabled(mock_asyncdb, monkeypatch):
    import builtins
    real_import = builtins.__import__

    def failing_import(name, *args, **kwargs):
        if name == "parrot.conf":
            raise ImportError("no conf")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", failing_import)
    audit = AuditSubscriber()
    monkeypatch.setattr(builtins, "__import__", real_import)

    core = BusCore(workers=1)
    assert audit.attach(core) is None  # disabled, no crash


# ---------------------------------------------------------------------------
# MetricsSubscriber
# ---------------------------------------------------------------------------


async def test_metrics_counters_and_latency():
    core = BusCore(workers=2, queue_size=64, retry_attempts=1)
    await core.start()
    metrics = MetricsSubscriber()
    assert len(metrics.attach(core)) == 2

    async def failing_handler(env):
        raise RuntimeError("boom")

    core.subscribe("orders.fail", failing_handler)

    await core.publish(make_envelope("orders.created"))
    await core.publish(make_envelope("orders.updated", severity=Severity.WARNING))
    await core.publish(make_envelope("billing.charged", severity=Severity.ERROR))
    await core.publish(make_envelope("orders.fail"))

    await wait_until(
        lambda: metrics.snapshot()["failed"].get("orders", 0) == 1
    )
    snap = metrics.snapshot()
    assert snap["delivered"]["orders"] == 3
    assert snap["delivered"]["billing"] == 1
    assert snap["by_severity"]["INFO"] == 2
    assert snap["by_severity"]["WARNING"] == 1
    assert snap["by_severity"]["ERROR"] == 1
    assert snap["failed"] == {"orders": 1}

    lat = snap["latency"]
    assert lat["count"] == 4
    assert lat["sum_seconds"] >= 0
    assert lat["max_seconds"] >= 0
    assert sum(lat["buckets"].values()) == 4
    assert lat["bucket_bounds_seconds"] == [
        0.001, 0.005, 0.01, 0.05, 0.1, 0.5, 1.0, 5.0,
    ]
    await core.close()


async def test_metrics_latency_bucketing_and_reset():
    metrics = MetricsSubscriber()
    old = EventEnvelope(
        topic="slow.evt",
        payload={},
        timestamp=datetime.now(timezone.utc) - timedelta(seconds=2),
    )
    await metrics._on_envelope(old)
    snap = metrics.snapshot()
    assert snap["latency"]["buckets"].get("le_5.0") == 1  # 2s → (1.0, 5.0]
    assert snap["latency"]["max_seconds"] >= 2.0

    metrics.reset()
    empty = metrics.snapshot()
    assert empty["delivered"] == {}
    assert empty["latency"]["count"] == 0


async def test_metrics_detach():
    core = BusCore(workers=1, queue_size=16)
    await core.start()
    metrics = MetricsSubscriber()
    metrics.attach(core)
    assert metrics.detach(core) == 2

    await core.publish(make_envelope("app.after"))
    await asyncio.sleep(0.05)
    assert metrics.snapshot()["delivered"] == {}
    await core.close()
