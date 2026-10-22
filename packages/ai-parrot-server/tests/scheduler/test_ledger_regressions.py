"""Regression coverage for scheduler ledger issues closed by FEAT-644."""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from parrot.scheduler import JobDefinition, SchedulerManager
from parrot.scheduler.base import SchedulerUnavailableError
from parrot.scheduler.coordination import CURRENT_RUN_TIME, FireCoordinationError, RedisFireCoordinator
from parrot.scheduler.models import FireContext
from parrot.scheduler.runstate import MemoryRunState


def _definition(schedule_id: str = "job") -> JobDefinition:
    """Build the minimal service definition used by ledger regression tests."""
    return JobDefinition(
        schedule_id=schedule_id,
        backend="code",
        target_kind="service",
        target_name="service",
        method_name="run",
        schedule_type="interval",
        schedule_config={"minutes": 5},
        send_result={"recipients": ["ops@example.com"]},
    )


async def test_fire_id_matches_coordinator_claim_key(scheduler_redis, scheduler_namespace) -> None:
    """Ledger aa813ccc1927: fire context and Redis claim use the exact due time."""
    run_time = datetime(2026, 1, 1, tzinfo=timezone.utc)
    coordinator = RedisFireCoordinator(scheduler_redis, prefix=f"parrot:scheduler:{scheduler_namespace}:")
    assert await coordinator.claim("job", run_time)
    assert not await coordinator.claim("job", run_time)
    token = CURRENT_RUN_TIME.set(run_time)
    try:
        fire = FireContext.for_fire("job", CURRENT_RUN_TIME.get())
    finally:
        CURRENT_RUN_TIME.reset(token)
    assert fire.fire_id == f"job:{run_time.isoformat()}"


async def test_run_now_coordination_outage_is_unavailable_error(scheduler_namespace) -> None:
    """Ledger 7b5d75d2c81d: coordination outages surface as a typed scheduler error."""
    manager = SchedulerManager(registered_name=scheduler_namespace)
    manager._fire_coordinator = SimpleNamespace(
        try_acquire_running=AsyncMock(side_effect=FireCoordinationError("down"))
    )
    with pytest.raises(SchedulerUnavailableError):
        await manager.run_schedule_now("job")
    await manager.stop_headless(wait=False)


async def test_success_callback_raise_does_not_skip_delivery(
    scheduler_namespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Ledger 37f02d3c2474: a callback failure is recorded without suppressing delivery."""
    manager = SchedulerManager(registered_name=scheduler_namespace)
    manager._memory_state = MemoryRunState()
    manager._run_state_for = lambda _backend: manager._memory_state  # type: ignore[method-assign]
    sent = AsyncMock(return_value={"status": "sent"})
    monkeypatch.setattr(manager, "_send_result_email", sent)
    callback = AsyncMock(side_effect=RuntimeError("callback failed"))
    try:
        outcomes = await manager._handle_job_success(_definition(), "result", callback)
        assert outcomes[0]["status"] == "failed"
        sent.assert_awaited_once()
    finally:
        await manager.stop_headless(wait=False)
