"""Unit tests for DLQHandler (FEAT-310, TASK-1788) — asyncdb mocked."""
import asyncio
import time

import pytest

from parrot.core.events.bus import BusCore, DLQHandler, EventEnvelope, Severity
from parrot.core.events.bus import dlq as dlq_module


def make_envelope(topic: str = "app.task", **kwargs) -> EventEnvelope:
    return EventEnvelope(topic=topic, payload=kwargs.pop("payload", {"k": 1}), **kwargs)


async def wait_until(condition, timeout: float = 2.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if condition():
            return
        await asyncio.sleep(0.01)
    pytest.fail("condition not met within timeout")


# ---------------------------------------------------------------------------
# Fake asyncdb
# ---------------------------------------------------------------------------


class FakeConn:
    def __init__(self, store: "FakeStore") -> None:
        self._store = store

    async def execute(self, sql, *args):
        if self._store.fail_execute:
            raise RuntimeError("pg down")
        self._store.executed.append((sql, args))
        return None

    async def query(self, sql, *args):
        self._store.queried.append((sql, args))
        return self._store.query_result, self._store.query_error


class FakeCtx:
    def __init__(self, store: "FakeStore") -> None:
        self._store = store

    async def __aenter__(self):
        return FakeConn(self._store)

    async def __aexit__(self, *exc):
        return False


class FakeStore:
    """Shared state across FakeDB instances."""

    def __init__(self) -> None:
        self.executed: list[tuple] = []
        self.queried: list[tuple] = []
        self.query_result = []
        self.query_error = None
        self.fail_execute = False
        self.constructed: list[tuple] = []


@pytest.fixture
def mock_asyncdb(monkeypatch):
    store = FakeStore()

    class FakeDB:
        def __init__(self, driver, dsn=None, **kwargs):
            store.constructed.append((driver, dsn))

        async def connection(self):
            return FakeCtx(store)

    monkeypatch.setattr(dlq_module, "AsyncDB", FakeDB)
    return store


def inserts(store):
    return [
        (sql, args) for sql, args in store.executed if "INSERT INTO" in sql
    ]


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


async def test_retry_exhaustion_persists_to_dlq(mock_asyncdb):
    core = BusCore(workers=1, queue_size=16, retry_attempts=1)
    handler = DLQHandler(core, dsn="postgres://fake/db")
    core._on_dlq = handler.on_dlq  # wire post-construction for the test
    await core.start()

    dlq_events: list[EventEnvelope] = []

    async def dlq_observer(env):
        dlq_events.append(env)

    async def always_fails(env):
        raise ValueError("kaput")

    core.subscribe("app.*", always_fails)
    core.subscribe("bus.dlq", dlq_observer)

    env = make_envelope("app.task")
    await core.publish(env)

    # bus.dlq republication with failure metadata
    await wait_until(lambda: len(dlq_events) == 1)
    dlq_env = dlq_events[0]
    assert dlq_env.topic == "bus.dlq"
    assert dlq_env.severity == Severity.WARNING  # capped below alerts
    assert dlq_env.payload["failure"]["error_type"] == "ValueError"
    assert dlq_env.payload["failure"]["attempts"] == 1
    assert dlq_env.payload["envelope"]["event_id"] == env.event_id

    # exactly one persisted row (mock asserts SQL + params)
    await wait_until(lambda: len(inserts(mock_asyncdb)) == 1)
    sql, args = inserts(mock_asyncdb)[0]
    assert "navigator.evb_dlq" in sql
    assert args[0] == env.event_id
    assert args[1] == "app.task"
    assert "ValueError: kaput" in args[9]
    assert args[10] == 1  # attempts
    assert mock_asyncdb.constructed[0] == ("pg", "postgres://fake/db")
    await core.close()


async def test_ddl_targets_navigator_evb_dlq(mock_asyncdb):
    core = BusCore(workers=1)
    handler = DLQHandler(core, dsn="postgres://fake/db")
    await handler.ensure_table()
    ddl = [sql for sql, _ in mock_asyncdb.executed if "CREATE TABLE" in sql]
    assert len(ddl) == 1
    assert "navigator.evb_dlq" in ddl[0]
    # idempotent — second call is a no-op
    await handler.ensure_table()
    assert len(
        [sql for sql, _ in mock_asyncdb.executed if "CREATE TABLE" in sql]
    ) == 1


async def test_dlq_duplicate_event_id_noop(mock_asyncdb):
    core = BusCore(workers=1)
    await core.start()
    handler = DLQHandler(core, dsn="postgres://fake/db")
    env = make_envelope("app.dup")
    err = RuntimeError("x")
    await handler.on_dlq(env, attempts=2, error=err, subscriber_id="s1")
    await handler.on_dlq(env, attempts=2, error=err, subscriber_id="s1")
    await wait_until(lambda: len(inserts(mock_asyncdb)) == 2)
    for sql, args in inserts(mock_asyncdb):
        assert "ON CONFLICT (event_id) DO NOTHING" in sql
        assert args[0] == env.event_id  # DB-side dedup on the unique key
    await core.close()


async def test_dlq_persistence_failure_is_isolated(mock_asyncdb):
    mock_asyncdb.fail_execute = True
    core = BusCore(workers=1, queue_size=16)
    await core.start()
    handler = DLQHandler(core, dsn="postgres://fake/db")

    meta_events: list[EventEnvelope] = []
    core.subscribe("bus.dlq_error", lambda e: meta_events.append(e))

    # Must not raise into the dispatch path.
    await handler.on_dlq(
        make_envelope("app.iso"),
        attempts=1,
        error=RuntimeError("boom"),
        subscriber_id="s1",
    )
    await wait_until(lambda: len(meta_events) == 1)
    assert meta_events[0].severity == Severity.WARNING
    await core.close()


async def test_dlq_replay_republishes(mock_asyncdb):
    core = BusCore(workers=1, queue_size=16)
    await core.start()
    handler = DLQHandler(core, dsn="postgres://fake/db")

    stored = make_envelope("orders.sync")
    mock_asyncdb.query_result = [
        {
            "event_id": stored.event_id,
            "topic": stored.topic,
            "payload": '{"k": 1}',
            "severity": Severity.ERROR.value,
            "priority": 5,
            "source": "worker-1",
            "correlation_id": None,
            "trace_context": None,
            "metadata": "{}",
            "failure_reason": "ValueError: kaput",
            "attempts": 3,
            "failed_at": "2026-07-16T10:00:00+00:00",
        }
    ]

    received: list[EventEnvelope] = []
    core.subscribe("orders.*", lambda e: received.append(e))

    count = await handler.replay(event_id=stored.event_id)
    assert count == 1
    await wait_until(lambda: len(received) == 1)
    assert received[0].topic == "orders.sync"  # ORIGINAL topic
    assert received[0].event_id == stored.event_id
    assert received[0].severity == Severity.ERROR

    marked = [
        (sql, args)
        for sql, args in mock_asyncdb.executed
        if "replayed_at = now()" in sql
    ]
    assert len(marked) == 1
    assert marked[0][1] == (stored.event_id,)
    await core.close()


async def test_replay_selector_validation(mock_asyncdb):
    core = BusCore(workers=1)
    handler = DLQHandler(core, dsn="postgres://fake/db")
    with pytest.raises(ValueError):
        await handler.replay()


async def test_missing_dsn_disables_persistence(mock_asyncdb, monkeypatch):
    core = BusCore(workers=1)
    await core.start()
    # Force the parrot.conf fallback to fail so dsn stays None.
    import builtins
    real_import = builtins.__import__

    def failing_import(name, *args, **kwargs):
        if name == "parrot.conf":
            raise ImportError("no conf")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", failing_import)
    handler = DLQHandler(core)
    monkeypatch.setattr(builtins, "__import__", real_import)

    await handler.on_dlq(
        make_envelope("app.nodsn"),
        attempts=1,
        error=RuntimeError("x"),
        subscriber_id="s1",
    )
    await asyncio.sleep(0.05)
    assert inserts(mock_asyncdb) == []  # persistence disabled, no crash
    with pytest.raises(ValueError):
        await handler.replay(event_id="whatever")
    await core.close()
