"""Fire-path coverage for the target-agnostic scheduler manager."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from apscheduler.jobstores.memory import MemoryJobStore

from parrot.scheduler import jobs
from parrot.scheduler.base import (
    SchedulerManager,
    SchedulerUnavailableError,
    TargetMissingError,
)
from parrot.scheduler.coordination import FireCoordinationError
from parrot.scheduler.models import FireContext, JobDefinition, RunState
from parrot.scheduler.runstate import MemoryRunState


class Target:
    """Target used by the fire-path tests."""

    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    async def run(self, value: str = "ok", **kwargs: object) -> str:
        """Record the call and return its value."""
        self.calls.append({"value": value, **kwargs})
        return value


def definition(schedule_id: str, *, backend: str = "code", metadata: dict[str, object] | None = None) -> JobDefinition:
    """Build a minimal valid definition."""
    return JobDefinition(
        schedule_id=schedule_id,
        backend=backend,  # type: ignore[arg-type]
        target_kind="service",
        target_name="target",
        method_name="run",
        schedule_type="interval",
        schedule_config={"minutes": 5},
        metadata=metadata or {},
    )


@pytest.fixture
def manager() -> SchedulerManager:
    """Return a manager with an isolated in-memory run-state store."""
    instance = SchedulerManager(registered_name=f"fire-{uuid.uuid4().hex}")
    instance._memory_state = MemoryRunState()
    instance._run_state_for = lambda _backend: instance._memory_state  # type: ignore[method-assign]
    return instance


@pytest.mark.asyncio
async def test_target_missing_raises_not_skipped(manager: SchedulerManager) -> None:
    """A missing resolver target is a stamped target-missing failure."""
    job_id = str(uuid.uuid4())
    job = definition(job_id, backend="db")
    manager.register_target("other", Target())
    with pytest.raises(TargetMissingError):
        await manager._execute_with_failure(job, FireContext.for_fire(job_id, datetime.now(timezone.utc)))
    state = await manager._memory_state.read(job_id)
    assert state is not None and state.last_status == "target_missing"


@pytest.mark.asyncio
async def test_resolver_exception_is_target_missing(manager: SchedulerManager) -> None:
    """Resolver exceptions are translated to target-missing errors."""

    class BrokenResolver:
        kind = "broken"

        async def resolve(self, name: str, *, target_id: str | None = None) -> object:
            raise RuntimeError("registry down")

        def build_call(
            self, target: object, definition: JobDefinition, fire: FireContext
        ) -> tuple[list[object], dict[str, object]]:
            raise AssertionError("unreachable")

        def derive_target_id(self, target: object) -> str | None:
            return None

    job = definition(str(uuid.uuid4())).model_copy(update={"target_kind": "broken"})
    manager.register_resolver(BrokenResolver())
    with pytest.raises(TargetMissingError):
        await manager._execute_job(job, FireContext.for_fire(job.schedule_id, datetime.now(timezone.utc)))


@pytest.mark.asyncio
async def test_auto_disable_after_threshold_and_single_alert(
    manager: SchedulerManager, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The threshold crossing disables once and sends one alert."""
    manager._max_failures = 3
    target = Target()
    manager.register_target("target", target)
    record = SimpleNamespace(
        method=target.run,
        to_definition=lambda: definition("auto_target_run"),
        success_callback=None,
        enabled=True,
    )
    manager._code_jobs["auto_target_run"] = record
    alert = AsyncMock()
    monkeypatch.setattr(manager, "_alert_disabled", alert)
    target.run = AsyncMock(side_effect=RuntimeError("boom"))
    record.method = target.run
    for _ in range(3):
        with pytest.raises(RuntimeError):
            await manager._run_auto_task("auto_target_run")
    assert alert.await_count == 1
    assert record.enabled is False


@pytest.mark.asyncio
async def test_alert_failure_never_raises(manager: SchedulerManager, monkeypatch: pytest.MonkeyPatch) -> None:
    """Notification errors are swallowed by the alert helper."""
    notification = AsyncMock(side_effect=RuntimeError("mail unavailable"))
    monkeypatch.setattr("parrot.scheduler.base._SchedulerNotification.send_notification", notification)
    await manager._alert_disabled(
        definition("job").model_copy(update={"send_result": {"recipients": ["ops@example.com"]}}),
        RunState(schedule_id="job", backend="code", enabled=False, consecutive_failures=3),
    )
    notification.assert_awaited_once()


@pytest.mark.asyncio
async def test_success_callback_raise_does_not_skip_delivery(
    manager: SchedulerManager, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A user callback failure is recorded while result delivery continues."""
    sent = AsyncMock(return_value={"status": "sent"})
    monkeypatch.setattr(manager, "_send_result_email", sent)
    callback = AsyncMock(side_effect=RuntimeError("callback failed"))
    job = definition("job").model_copy(update={"send_result": {"recipients": ["ops@example.com"]}})
    outcomes = await manager._handle_job_success(job, "result", callback)
    assert outcomes[0]["callback"] == "success_callback"
    assert outcomes[0]["status"] == "failed"
    sent.assert_awaited_once()


@pytest.mark.asyncio
async def test_run_now_coordination_outage_is_unavailable_error(manager: SchedulerManager) -> None:
    """A run-now coordination outage is typed for the API layer."""
    manager._fire_coordinator.try_acquire_running = AsyncMock(side_effect=FireCoordinationError("down"))
    with pytest.raises(SchedulerUnavailableError):
        await manager.run_schedule_now("job")


@pytest.mark.asyncio
async def test_unavailable_hook_skips_non_uuid_ids(manager: SchedulerManager) -> None:
    """Non-DB identifiers never reach the DB run-state store."""
    store = AsyncMock()
    manager._run_state_for = store  # type: ignore[method-assign]
    await manager._on_coordination_unavailable("auto_target_run", FireCoordinationError("down"))
    store.assert_not_called()


@pytest.mark.asyncio
async def test_redis_job_incompatible_version_pauses(manager: SchedulerManager) -> None:
    """Redis definitions with an unknown version are paused and skipped."""
    manager.scheduler.add_jobstore(MemoryJobStore(), alias="redis")
    manager._redis_client = SimpleNamespace()
    job_id = "redis-job"
    manager.scheduler.add_job(
        jobs.run_redis_job,
        "interval",
        minutes=5,
        id=job_id,
        jobstore="redis",
        kwargs={
            "manager_name": manager.registered_name,
            "schedule_id": job_id,
            "definition_version": 1,
            "definition": {},
        },
    )
    result = await manager._run_redis_job(
        job_id,
        definition_version=99,
        definition=definition(job_id, backend="redis").model_dump(mode="json"),
    )
    assert result is jobs.SKIPPED
    assert manager.scheduler.get_job(job_id, jobstore="redis").next_run_time is None
    state = await manager._memory_state.read(job_id)
    assert state is not None and state.last_status == "incompatible"


@pytest.mark.asyncio
async def test_fire_context_injected_into_target(manager: SchedulerManager) -> None:
    """Declared fire parameters receive the coordinator timestamp."""

    class ContextTarget:
        async def run(self, fire_id: str, scheduled_at: object) -> tuple[str, object]:
            return fire_id, scheduled_at

    target = ContextTarget()
    manager.register_target("target", target)
    job = definition("job", backend="db")
    result = await manager._execute_job(job, FireContext.for_fire("job", datetime.now(timezone.utc)))
    assert result[0] == "job:" + result[1].isoformat()


@pytest.mark.asyncio
async def test_metadata_never_contains_run_state(manager: SchedulerManager) -> None:
    """Execution passes the original metadata without scheduler state fields."""
    target = Target()
    manager.register_target("target", target)
    job = definition("job", backend="db", metadata={"value": "input"})
    await manager._execute_job(job, FireContext.for_fire("job", datetime.now(timezone.utc)))
    assert target.calls[0]["value"] == "input"
    assert "last_status" not in target.calls[0]


@pytest.mark.asyncio
async def test_get_last_result_per_backend(manager: SchedulerManager) -> None:
    """Code jobs expose the common RunState shape before their first fire."""

    async def automatic() -> str:
        return "ok"

    automatic._schedule_config = {"schedule_type": "interval", "schedule_config": {"minutes": 5}}  # type: ignore[attr-defined]
    target = type("Scheduled", (), {"automatic": automatic})()
    manager.register_object_schedules(target, "target")
    state = await manager.get_last_result("auto_target_automatic")
    assert state.backend == "code"
    assert state.schedule_id == "auto_target_automatic"
