"""Two-worker behaviour of the agent scheduler (FEAT-631 TASK-4066, issue #1573)."""

import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from asyncdb.exceptions import NoDataFound

from parrot.scheduler import jobs
from parrot.scheduler import base as base_module
from parrot.scheduler.coordination import RedisFireCoordinator
from parrot.scheduler.manager import AgentSchedulerManager, ScheduleType, schedule
from parrot.scheduler.models import JobDefinition
from parrot.scheduler.runstate import MemoryRunState


class FakeRedis:
    """Dict-backed async double for Redis SET NX EX and DELETE."""

    def __init__(self, raise_on: bool = False) -> None:
        self.store: dict[str, str] = {}
        self.raise_on = raise_on

    async def set(self, key, value, nx=False, ex=None):
        """Store a value unless an existing NX key prevents it."""
        if self.raise_on:
            raise ConnectionError("redis down")
        if nx and key in self.store:
            return None
        self.store[key] = value
        return True

    async def delete(self, key):
        """Delete a stored key."""
        self.store.pop(key, None)

    async def aclose(self) -> None:
        """Match the Redis client's async shutdown interface."""
        return None


class _FakeBot:
    """Agent double that records prompt execution."""

    def __init__(self) -> None:
        self.chat_calls: list[str] = []

    async def chat(self, prompt: str) -> str:
        """Record the prompt and produce a deterministic result."""
        self.chat_calls.append(prompt)
        return "ok-result"


class _FakeBotManager:
    """Minimal bot manager used by scheduler execution."""

    def __init__(self, bot: _FakeBot) -> None:
        self._bots = {"test_agent": bot}
        self.registry = MagicMock()

    def get_bots(self):
        """Expose the public bot lookup used by the agent resolver."""
        return self._bots

    def get_crew(self, name: str):
        """This test fixture contains no crews."""
        return None


class _FakePoolAcquireCtx:
    """Async context manager returned by the fake pool."""

    def __init__(self, conn) -> None:
        self._conn = conn

    async def __aenter__(self):
        """Return the fake connection."""
        return self._conn

    async def __aexit__(self, *_args) -> bool:
        """Do not suppress exceptions."""
        return False


class _FakePool:
    """Shared row-store pool with the query shape used by schedule loading."""

    def __init__(self, rows: list[dict]) -> None:
        self.rows = rows
        self.conn = SimpleNamespace(query=self.query)

    async def acquire(self) -> _FakePoolAcquireCtx:
        """Return a context manager around the shared fake connection."""
        return _FakePoolAcquireCtx(self.conn)

    async def query(self, _query: str):
        """Return enabled rows in asyncdb's ``(rows, error)`` shape."""
        return ([row for row in self.rows if row["enabled"]], None)


class _FakeServiceSchedule:
    """Schedule model double backed by a shared row map."""

    Meta = SimpleNamespace(connection=None)
    records: dict[str, "_FakeServiceSchedule"] = {}

    def __init__(self, **record) -> None:
        self.__dict__.update(record)

    @classmethod
    async def get(cls, *, schedule_id: str):
        """Fetch a shared row or reproduce the database missing-row signal."""
        try:
            return cls.records[str(schedule_id)]
        except KeyError as error:
            raise NoDataFound() from error

    async def update(self) -> None:
        """Persist in place; the object already belongs to the shared store."""
        return None

    async def delete(self) -> None:
        """Remove this row from the shared store."""
        self.records.pop(str(self.schedule_id), None)

    def to_definition(self) -> JobDefinition:
        """Return the backend-neutral definition consumed by the manager."""
        return JobDefinition(
            schedule_id=str(self.schedule_id),
            backend="db",
            target_kind=self.target_kind,
            target_name=self.target_name,
            target_id=self.target_id,
            prompt=self.prompt,
            method_name=self.method_name,
            schedule_type=self.schedule_type,
            schedule_config=self.schedule_config,
            metadata=self.metadata,
            send_result=self.send_result,
            callbacks=self.callbacks,
            misfire_grace_time=300,
        )


def _row(schedule_id: str = "00000000-0000-0000-0000-000000000001") -> dict:
    """Build one enabled interval schedule row for both workers to load."""
    return {
        "schedule_id": schedule_id,
        "target_kind": "agent",
        "target_name": "test_agent",
        "target_id": "agent-1",
        "prompt": "do the thing",
        "method_name": None,
        "metadata": {},
        "send_result": {},
        "callbacks": [],
        "schedule_type": "interval",
        "schedule_config": {"seconds": 60},
        "enabled": True,
    }


async def _fire_once(manager: AgentSchedulerManager, job_id: str, run_time: datetime) -> None:
    """Submit one deterministic scheduler fire and await its executor work."""
    executor = manager.scheduler._lookup_executor("default")
    job = manager.scheduler.get_job(job_id)
    assert job is not None
    executor._do_submit_job(job, [run_time])
    await asyncio.gather(*executor._pending_futures)
    await asyncio.gather(*manager._pending_success_tasks)


async def _start_managers(monkeypatch, redis: FakeRedis):
    """Start two schedulers over a shared fake Redis, row store, and bot."""
    rows = [_row()]
    shared = _FakeServiceSchedule(**rows[0])
    _FakeServiceSchedule.records = {str(shared.schedule_id): shared}
    monkeypatch.setattr(base_module, "ServiceSchedule", _FakeServiceSchedule)
    bot = _FakeBot()
    pool = _FakePool(rows)
    store = MemoryRunState(backend="db")
    managers = []
    for worker_id in ("w1", "w2"):
        manager = AgentSchedulerManager(bot_manager=_FakeBotManager(bot), registered_name=f"multiworker_{worker_id}")
        manager._pool = pool
        manager._run_state_for = lambda _backend: store  # type: ignore[method-assign]
        await manager.start_headless(coordination="none")
        coordinator = RedisFireCoordinator(redis, worker_id=worker_id)
        manager._fire_coordinator = coordinator
        manager.scheduler._lookup_executor("default").set_coordinator(coordinator)
        managers.append(manager)
    return managers, shared, bot


@pytest.fixture
async def two_managers(monkeypatch):
    """Yield two real schedulers over one fake Redis and one fake row store."""
    managers, row, bot = await _start_managers(monkeypatch, FakeRedis())
    try:
        yield (*managers, row, bot)
    finally:
        for manager in managers:
            await manager.stop_headless(wait=False)


async def test_two_workers_one_fire(two_managers):
    """One DB schedule fire executes once across two scheduler managers."""
    first, second, row, bot = two_managers
    callbacks: list[str] = []
    first._local_callbacks[str(row.schedule_id)] = lambda result, **_kwargs: callbacks.append(result)
    second._local_callbacks[str(row.schedule_id)] = lambda result, **_kwargs: callbacks.append(result)
    run_time = datetime.now(timezone.utc)

    await _fire_once(first, str(row.schedule_id), run_time)
    await _fire_once(second, str(row.schedule_id), run_time)

    assert bot.chat_calls == ["do the thing"]
    state = await first.get_last_result(str(row.schedule_id))
    assert state.run_count == 1
    assert callbacks == ["ok-result"]


async def test_auto_job_one_fire(two_managers):
    """One decorator schedule fire executes once across two scheduler managers."""
    first, second, _row_data, _bot = two_managers
    calls: list[str] = []

    class Bot:
        name = "test_agent"

        @schedule(ScheduleType.INTERVAL, seconds=60)
        async def tick(self) -> str:
            """Record the decorator job execution."""
            calls.append("tick")
            return "tick-result"

    first.register_bot_schedules(Bot())
    second.register_bot_schedules(Bot())
    run_time = datetime.now(timezone.utc)

    await _fire_once(first, "auto_test_agent_tick", run_time)
    await _fire_once(second, "auto_test_agent_tick", run_time)

    assert calls == ["tick"]


async def test_delete_in_one_worker_stops_other(two_managers):
    """Deleting the shared row makes another worker skip and remove its job."""
    first, second, row, _bot = two_managers

    await first.delete_schedule(str(row.schedule_id))
    await _fire_once(second, str(row.schedule_id), datetime.now(timezone.utc))

    assert second.scheduler.get_job(str(row.schedule_id)) is None


async def test_redis_down_fails_closed(monkeypatch):
    """Unavailable Redis prevents execution and marks the DB row unavailable."""
    managers, row, bot = await _start_managers(monkeypatch, FakeRedis(raise_on=True))
    try:
        run_time = datetime.now(timezone.utc)
        await _fire_once(managers[0], str(row.schedule_id), run_time)
        await _fire_once(managers[1], str(row.schedule_id), run_time)

        assert bot.chat_calls == []
        state = await managers[0].get_last_result(str(row.schedule_id))
        assert state.run_count == 0
        assert state.last_status == "lock_unavailable"
    finally:
        for manager in managers:
            await manager.stop_headless(wait=False)
