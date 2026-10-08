"""CRUD coverage for the target-agnostic scheduler backends."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from apscheduler.jobstores.memory import MemoryJobStore

from parrot.scheduler import jobs
from parrot.scheduler.base import NotEditableError, SchedulerManager
from parrot.scheduler.runstate import MemoryRunState
from parrot.scheduler.sanitize import SchedulerConfigError


class Service:
    """Small target used to prove registry-backed validation."""

    async def run(self, prompt: str | None = None) -> str:
        """Return the provided prompt."""
        return prompt or "ok"


@pytest.fixture
async def memory_manager(scheduler_namespace: str):
    """Create a manager with isolated in-memory default and Redis stores."""
    manager = SchedulerManager(registered_name=scheduler_namespace)
    manager.scheduler.add_jobstore(MemoryJobStore(), alias="redis")
    manager._redis_client = SimpleNamespace()
    manager._memory_state = MemoryRunState()
    manager._run_state_for = lambda backend: manager._memory_state  # type: ignore[method-assign]
    manager.register_target("service", Service(), methods=["run"])
    yield manager
    await manager.stop_headless(wait=False)


async def test_add_redis_schedule_has_data_only_kwargs(memory_manager: SchedulerManager) -> None:
    """Redis definitions are stored entirely in the versioned job kwargs."""
    definition = await memory_manager.add_schedule(
        "service", "service", "interval", {"minutes": 5}, backend="redis", method_name="run"
    )

    job = memory_manager.scheduler.get_job(definition.schedule_id, jobstore="redis")
    assert job is not None
    assert set(job.kwargs) == {"manager_name", "schedule_id", "definition_version", "definition"}
    assert job.kwargs["definition"]["backend"] == "redis"


async def test_add_redis_rejects_success_callback(memory_manager: SchedulerManager) -> None:
    """Redis jobs cannot persist arbitrary callbacks."""
    with pytest.raises(ValueError, match="success_callback"):
        await memory_manager.add_schedule(
            "service",
            "service",
            "interval",
            {"minutes": 5},
            backend="redis",
            method_name="run",
            success_callback=lambda: None,
        )


async def test_add_redis_without_jobstore_fails_closed(scheduler_namespace: str) -> None:
    """Explicit Redis requests never silently fall back to the DB backend."""
    manager = SchedulerManager(registered_name=scheduler_namespace)
    manager.register_target("service", Service(), methods=["run"])
    try:
        with pytest.raises(SchedulerConfigError, match="Redis backend"):
            await manager.add_schedule("service", "service", "interval", {"minutes": 5}, backend="redis")
    finally:
        await manager.stop_headless(wait=False)


async def test_crud_matrix_for_redis_and_code(memory_manager: SchedulerManager) -> None:
    """Redis schedules are editable; code schedules are pause-only."""
    definition = await memory_manager.add_schedule(
        "service", "service", "interval", {"minutes": 5}, backend="redis", method_name="run"
    )
    updated = await memory_manager.update_schedule(definition.schedule_id, {"prompt": "new"})
    assert updated.prompt == "new"
    paused = await memory_manager.pause_schedule(definition.schedule_id)
    assert paused.schedule_id == definition.schedule_id
    await memory_manager.delete_schedule(definition.schedule_id)

    async def automatic() -> None:
        """Scheduled code target."""

    automatic._schedule_config = {"schedule_type": "interval", "schedule_config": {"minutes": 5}}  # type: ignore[attr-defined]
    target = SimpleNamespace(automatic=automatic)
    # ``inspect.ismethod`` intentionally scans bound methods, matching production objects.
    target = type("Scheduled", (), {"automatic": automatic})()
    assert memory_manager.register_object_schedules(target, "a.b") == 1
    code_id = "auto_a.b_automatic"
    assert (await memory_manager.get_schedule(code_id)).target_name == "a.b"
    with pytest.raises(NotEditableError):
        await memory_manager.update_schedule(code_id, {"prompt": "no"})


async def test_external_job_is_listed_readonly(memory_manager: SchedulerManager) -> None:
    """Foreign APScheduler jobs are never exposed with their private kwargs."""
    memory_manager.scheduler.add_job(
        jobs.run_auto_schedule,
        "interval",
        minutes=5,
        id="foreign",
        kwargs={"manager_name": memory_manager.registered_name, "job_id": "secret"},
        jobstore="redis",
    )
    payload = next(item for item in await memory_manager.list_jobs() if item["schedule_id"] == "foreign")
    assert payload["source"] == "external"
    assert payload["schedule_id"] == "foreign"
    assert payload["enabled"] is False
    assert "kwargs" not in payload
    with pytest.raises(NotEditableError):
        await memory_manager.pause_schedule("foreign")
