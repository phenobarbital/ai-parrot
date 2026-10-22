"""Delivery outcome persistence through backend-neutral run state."""

from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import pytest

from parrot.scheduler.manager import AgentSchedulerManager
from parrot.scheduler.models import FireContext, JobDefinition
from parrot.scheduler.runstate import MemoryRunState, aggregate_delivery_status


@pytest.fixture
def manager(monkeypatch: pytest.MonkeyPatch) -> AgentSchedulerManager:
    instance = AgentSchedulerManager()
    instance._memory_state = MemoryRunState("db")
    monkeypatch.setattr(instance, "_run_state_for", lambda _backend: instance._memory_state)
    return instance


def _definition() -> JobDefinition:
    return JobDefinition(
        schedule_id="s1",
        backend="db",
        target_kind="agent",
        target_name="agent",
        schedule_type="interval",
        schedule_config={"minutes": 5},
    )


def _fire() -> FireContext:
    return FireContext.for_fire("s1", datetime.now(timezone.utc))


def _cb(response=None, exc=None):
    return AsyncMock(return_value=response, side_effect=exc)


async def test_handle_job_success_isolates_callbacks(manager: AgentSchedulerManager) -> None:
    definition = _definition().model_copy(
        update={"callbacks": [{"type": "send_email_report"}], "send_result": {"recipients": ["a@x"]}}
    )
    with (
        patch("parrot.scheduler.base.build_scheduler_callback", return_value=_cb(exc=RuntimeError("boom"))),
        patch.object(manager, "_send_result_email", new=AsyncMock(return_value={"status": "success"})) as send_result,
    ):
        outcomes = await manager._handle_job_success(definition, "res", None)
    assert [outcome["status"] for outcome in outcomes] == ["failed", "sent"]
    send_result.assert_awaited_once()


@pytest.mark.parametrize(
    "statuses,expected",
    [(["sent", "saved"], "ok"), (["sent", "failed"], "partial"), (["failed"], "failed"), ([], None)],
)
def test_aggregate_delivery_status(statuses: list[str], expected: str | None) -> None:
    outcomes = [{"callback": "c", "status": status, "error": None} for status in statuses]
    assert aggregate_delivery_status(outcomes) == expected


async def test_process_job_success_stamps_delivery(
    manager: AgentSchedulerManager, monkeypatch: pytest.MonkeyPatch
) -> None:
    definition = _definition()
    outcomes = [{"callback": "c", "status": "failed", "error": "x"}]
    monkeypatch.setattr(manager, "_handle_job_success", AsyncMock(return_value=outcomes))
    await manager._process_job_success(definition, _fire(), "result", None)
    state = await manager._memory_state.read("s1")
    assert state is not None
    assert state.last_status == "success"
    assert state.last_callbacks == outcomes
    assert state.last_delivery_status == "failed"
    assert state.last_delivery_at is not None


async def test_process_job_success_ignores_delivery_store_failure(
    manager: AgentSchedulerManager, monkeypatch: pytest.MonkeyPatch
) -> None:
    manager._memory_state.stamp_delivery = AsyncMock(side_effect=RuntimeError("boom"))
    monkeypatch.setattr(
        manager, "_handle_job_success", AsyncMock(return_value=[{"callback": "c", "status": "sent", "error": None}])
    )
    await manager._process_job_success(_definition(), _fire(), "result", None)
