"""Regression coverage for ``load_schedules_from_db`` persistence (NAV-10363)."""

from __future__ import annotations

import uuid
from typing import Any

import pytest

pytest.importorskip("asyncdb")

from parrot.scheduler import SchedulerManager  # noqa: E402
from parrot.scheduler.models import ServiceSchedule, utcnow  # noqa: E402


def _record(schedule_id: uuid.UUID) -> dict[str, Any]:
    """Build a ``SELECT *`` record for one enabled interval schedule."""
    return {
        "schedule_id": schedule_id,
        "target_kind": "service",
        "target_name": "service",
        "method_name": "run",
        "schedule_type": "interval",
        "schedule_config": {"minutes": 5},
        "enabled": True,
        "created_at": utcnow(),
        "updated_at": utcnow(),
    }


class _FakeConn:
    """Record every statement the manager sends over an acquired connection."""

    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self.rows = rows
        self.queries: list[tuple[str, tuple[Any, ...]]] = []
        self.executed: list[tuple[str, tuple[Any, ...]]] = []

    async def query(self, sentence: str, *args: Any) -> tuple[list[dict[str, Any]], None]:
        """Return the canned rows for the enabled-schedules query."""
        self.queries.append((sentence, args))
        return self.rows, None

    async def execute(self, sentence: str, *args: Any) -> tuple[str, None]:
        """Record a parameterized statement and report one affected row."""
        self.executed.append((sentence, args))
        return "UPDATE 1", None


class _Acquire:
    """Async context manager returned by the fake database pool."""

    def __init__(self, conn: _FakeConn) -> None:
        self.conn = conn

    async def __aenter__(self) -> _FakeConn:
        """Yield the fake connection."""
        return self.conn

    async def __aexit__(self, *_args: object) -> bool:
        """Never suppress exceptions from the managed operation."""
        return False


class _Pool:
    """Minimal pool surface used by ``load_schedules_from_db``."""

    def __init__(self, conn: _FakeConn) -> None:
        self.conn = conn

    async def acquire(self) -> _Acquire:
        """Return a connection context manager."""
        return _Acquire(self.conn)


class Service:
    """Target registered so loaded definitions resolve."""

    async def run(self) -> str:
        """Return a deterministic result."""
        return "ok"


@pytest.fixture
async def loader_manager(scheduler_namespace: str):
    """Create a started manager with no Redis jobstore and no run-state writes."""
    manager = SchedulerManager(registered_name=scheduler_namespace)
    await manager.start_headless(register_listeners=False)
    manager.register_target("service", Service(), methods=["run"])
    yield manager
    await manager.stop_headless(wait=False)


async def test_next_run_persisted_for_every_row(loader_manager: SchedulerManager) -> None:
    """NAV-10363: each row stamps its own ``next_run`` instead of the first row's."""
    ids = [uuid.uuid4() for _ in range(3)]
    conn = _FakeConn([_record(schedule_id) for schedule_id in ids])
    loader_manager._pool = _Pool(conn)

    await loader_manager.load_schedules_from_db()

    assert len(conn.executed) == len(ids), "every loaded row must persist its next_run"
    for schedule_id, (sentence, args) in zip(ids, conn.executed, strict=True):
        assert "UPDATE navigator.service_scheduler" in sentence
        assert "next_run" in sentence and "updated_at" in sentence
        assert args[-1] == schedule_id, "the WHERE clause must target this row's primary key"
        assert args[0] is not None


async def test_loader_does_not_full_row_update(loader_manager: SchedulerManager, monkeypatch) -> None:
    """The loader never calls ``Model.update()``, whose WHERE uses the shared ``__values__``."""

    async def _fail(self: ServiceSchedule) -> None:
        """Fail the test if a full-row update is attempted."""
        raise AssertionError("load_schedules_from_db must not use ServiceSchedule.update()")

    monkeypatch.setattr(ServiceSchedule, "update", _fail, raising=False)
    conn = _FakeConn([_record(uuid.uuid4()) for _ in range(2)])
    loader_manager._pool = _Pool(conn)

    await loader_manager.load_schedules_from_db()

    assert len(conn.executed) == 2
