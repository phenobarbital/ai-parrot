"""Tests for the backend-independent scheduler model contracts."""

import uuid
from datetime import datetime, timezone

import pytest

pytest.importorskip("asyncdb")

from pydantic import ValidationError
from parrot.scheduler.models import (
    CodeJobRecord,
    FireContext,
    JobDefinition,
    ServiceSchedule,
    schedule_fingerprint,
    utcnow,
)


def _definition(**overrides: object) -> JobDefinition:
    """Build a valid database-backed job definition."""
    base: dict[str, object] = {
        "schedule_id": str(uuid.uuid4()),
        "backend": "db",
        "target_kind": "service",
        "target_name": "svc",
        "method_name": "run",
        "schedule_type": "interval",
        "schedule_config": {"minutes": 5},
        "misfire_grace_time": 300,
    }
    base.update(overrides)
    return JobDefinition(**base)


def test_utcnow_is_aware() -> None:
    """The scheduler clock always returns an aware UTC datetime."""
    assert utcnow().tzinfo is timezone.utc


@pytest.mark.parametrize("legacy_field", ["agent_name", "is_crew", "scheduler_type"])
def test_definition_rejects_legacy_fields(legacy_field: str) -> None:
    """Hard-cut legacy schedule fields are forbidden."""
    with pytest.raises(ValidationError):
        _definition(**{legacy_field: "legacy"})


@pytest.mark.parametrize("value", [lambda: None, datetime.now(timezone.utc)])
def test_definition_rejects_non_json_metadata(value: object) -> None:
    """Definitions cannot carry process-local values in JSON fields."""
    with pytest.raises(ValidationError, match="metadata"):
        _definition(metadata={"invalid": value})


def test_service_schedule_roundtrip_definition() -> None:
    """Database rows preserve definition fields and leave run state at defaults."""
    definition = _definition(
        target_id="target-1",
        tenant="tenant-1",
        prompt="hello",
        metadata={"answer": 42},
        send_result={"email": "person@example.test"},
        callbacks=[{"name": "notify"}],
        created_by=7,
        created_email="owner@example.test",
    )

    schedule = ServiceSchedule.from_definition(definition)

    assert schedule.to_definition() == definition
    assert schedule.run_count == 0
    assert schedule.last_status is None
    assert schedule.consecutive_failures == 0
    assert ServiceSchedule.Meta.name == "service_scheduler"
    assert "tenant VARCHAR" in ServiceSchedule.__doc__
    assert "scheduler_type" not in ServiceSchedule.__doc__


def test_fingerprint_covers_misfire_and_target_fields() -> None:
    """Every field specified by the fingerprint contract changes the hash."""
    definition = _definition(
        target_id="target-1",
        prompt="prompt",
        metadata={"metadata": 1},
        send_result={"email": "person@example.test"},
        callbacks=[{"name": "notify"}],
    )
    baseline = schedule_fingerprint(definition)
    changes = {
        "target_kind": "agent",
        "target_name": "other",
        "target_id": "target-2",
        "prompt": "other prompt",
        "method_name": "other_method",
        "schedule_type": "cron",
        "schedule_config": {"hour": 8},
        "metadata": {"metadata": 2},
        "send_result": {"email": "other@example.test"},
        "callbacks": [{"name": "other"}],
        "misfire_grace_time": 301,
    }

    for field_name, value in changes.items():
        assert schedule_fingerprint(_definition(**{field_name: value})) != baseline


def test_fire_context_for_fire_matches_claim_key() -> None:
    """Fire IDs use the exact timestamp representation used by the coordinator."""
    scheduled_at = datetime(2026, 10, 8, 12, 0, tzinfo=timezone.utc)

    context = FireContext.for_fire("schedule-1", scheduled_at, run_now=True)

    assert context.fire_id == f"schedule-1:{scheduled_at.isoformat()}"
    assert context.scheduled_at is scheduled_at
    assert context.run_now is True


async def _method() -> None:
    """Provide a callable for a process-local code job record."""


def test_code_job_record_to_definition_has_no_callable() -> None:
    """Code records expose data only and never serialize their bound callable."""
    record = CodeJobRecord(
        job_id="auto_service_run",
        target_name="service",
        method_name="run",
        method=_method,
        schedule_type="interval",
        schedule_config={"minutes": 5},
        callbacks=[{"name": "notify"}],
    )

    definition = record.to_definition()

    assert definition.backend == "code"
    assert definition.target_kind == "service"
    assert "method" not in definition.model_dump()
