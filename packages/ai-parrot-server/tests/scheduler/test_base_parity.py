"""Backend parity integration tests for ``SchedulerManager`` (FEAT-644)."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from apscheduler.jobstores.memory import MemoryJobStore

from parrot.scheduler import JobDefinition, SchedulerManager
from parrot.scheduler import base as base_module
from parrot.scheduler.models import FireContext
from parrot.scheduler.runstate import MemoryRunState


class Service:
    """Small registered target used by each backend test."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    async def run(self, value: str = "ok") -> str:
        """Record a call and return its value."""
        self.calls.append(value)
        return value


class _Acquire:
    """Async context manager returned by the fake database pool."""

    async def __aenter__(self) -> SimpleNamespace:
        """Return the inert fake connection."""
        return SimpleNamespace()

    async def __aexit__(self, *_args: object) -> bool:
        """Never suppress exceptions from the managed operation."""
        return False


class _Pool:
    """Minimal pool surface used by database schedule CRUD."""

    async def acquire(self) -> _Acquire:
        """Return a connection context manager."""
        return _Acquire()


class _ServiceSchedule:
    """In-memory stand-in for the database model used by this test module."""

    Meta = SimpleNamespace(connection=None)
    records: dict[str, "_ServiceSchedule"] = {}

    def __init__(self, **values: object) -> None:
        """Store the supplied model fields."""
        self.__dict__.update(values)

    @classmethod
    def from_definition(cls, definition: JobDefinition) -> "_ServiceSchedule":
        """Build a row without carrying run-state fields."""
        return cls(definition=definition, schedule_id=definition.schedule_id, enabled=True)

    @classmethod
    async def all(cls) -> list["_ServiceSchedule"]:
        """Return all persisted fake rows."""
        return list(cls.records.values())

    @classmethod
    async def get(cls, *, schedule_id: object) -> "_ServiceSchedule":
        """Return one stored row."""
        return cls.records[str(schedule_id)]

    async def save(self) -> None:
        """Persist this fake row."""
        self.records[str(self.schedule_id)] = self

    async def update(self) -> None:
        """Persist in-place updates."""
        self.records[str(self.schedule_id)] = self

    async def delete(self) -> None:
        """Delete this fake row."""
        self.records.pop(str(self.schedule_id), None)

    def to_definition(self) -> JobDefinition:
        """Return the stored backend-neutral definition."""
        return self.definition


@pytest.fixture
async def parity_manager(monkeypatch: pytest.MonkeyPatch, scheduler_namespace: str):
    """Create a manager with fake database persistence and memory Redis storage."""
    _ServiceSchedule.records = {}
    monkeypatch.setattr(base_module, "ServiceSchedule", _ServiceSchedule)
    manager = SchedulerManager(registered_name=scheduler_namespace)
    await manager.start_headless(register_listeners=False)
    manager._pool = _Pool()
    states = {backend: MemoryRunState(backend) for backend in ("db", "redis", "code")}
    manager._memory_state = states["code"]
    manager._run_state_for = lambda backend: states[backend]  # type: ignore[method-assign]
    manager.scheduler.add_jobstore(MemoryJobStore(), alias="redis")
    manager._redis_client = SimpleNamespace()
    manager.register_target("service", Service(), methods=["run"])
    yield manager
    await manager.stop_headless(wait=False)


async def test_three_backends_same_list_payload(parity_manager: SchedulerManager) -> None:
    """Database, Redis and code definitions share the same list payload shape."""
    database = await parity_manager.add_schedule(
        "service", "service", "interval", {"minutes": 5}, backend="db", method_name="run"
    )
    redis = await parity_manager.add_schedule(
        "service", "service", "interval", {"minutes": 5}, backend="redis", method_name="run"
    )

    class Automatic:
        """Object with one code-declared schedule."""

        async def tick(self) -> str:
            """Return a deterministic code-job result."""
            return "code"

    Automatic.tick._schedule_config = {"schedule_type": "interval", "schedule_config": {"minutes": 5}}  # type: ignore[attr-defined]
    assert parity_manager.register_object_schedules(Automatic(), "automatic") == 1

    definitions = {item.schedule_id: item for item in await parity_manager.list_schedules()}
    assert {definitions[database.schedule_id].backend, definitions[redis.schedule_id].backend} == {"db", "redis"}
    code = definitions["auto_automatic_tick"]
    for definition in (definitions[database.schedule_id], definitions[redis.schedule_id], code):
        assert set(definition.model_dump()) == set(JobDefinition.model_fields)
        assert definition.target_kind == "service"


async def test_db_schedule_end_to_end(parity_manager: SchedulerManager) -> None:
    """A database schedule persists, resolves its target, and executes through the manager."""
    definition = await parity_manager.add_schedule(
        "service", "service", "interval", {"minutes": 5}, backend="db", method_name="run", metadata={"value": "db"}
    )

    result = await parity_manager._run_db_schedule(definition.schedule_id, None)

    assert result == "db"
    assert (await parity_manager.get_schedule(definition.schedule_id)).backend == "db"
    assert definition.schedule_id in _ServiceSchedule.records


async def test_runstate_parity_matrix(parity_manager: SchedulerManager) -> None:
    """Manager-facing run state has the same readable shape for all backends."""
    definitions = [
        await parity_manager.add_schedule(
            "service", "service", "interval", {"minutes": 5}, backend=backend, method_name="run"
        )
        for backend in ("db", "redis")
    ]

    class Automatic:
        """Object with one code schedule for state parity."""

        async def tick(self) -> str:
            """Return a deterministic result."""
            return "code"

    Automatic.tick._schedule_config = {"schedule_type": "interval", "schedule_config": {"minutes": 5}}  # type: ignore[attr-defined]
    parity_manager.register_object_schedules(Automatic(), "state")
    definitions.append(await parity_manager.get_schedule("auto_state_tick"))

    for definition in definitions:
        await parity_manager._process_job_success(
            definition,
            FireContext.for_fire(definition.schedule_id, definition.created_at),
            "ok",
            None,
        )
        state = await parity_manager.get_last_result(definition.schedule_id)
        assert state.schedule_id == definition.schedule_id
        assert state.backend == definition.backend
        assert state.run_count == 1
