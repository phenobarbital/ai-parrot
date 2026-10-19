"""FEAT-706 — worker-event models."""
from datetime import date, datetime

from parrot_tools.interfaces.workday.models import (
    FieldChange,
    JobChange,
    JobSnapshot,
    ResolvedWorkerReference,
    WorkerEvent,
)
from parrot_tools.interfaces.workday.models.worker_event import (
    COMPENSATION_EVENT_TYPES,
    JOB_CHANGE_EVENT_TYPES,
)


def test_event_type_tuples() -> None:
    """Expose the fixed event names used by job-change filtering."""
    assert JOB_CHANGE_EVENT_TYPES == (
        "Hire",
        "Change Job",
        "Change Organization Assignments for Worker",
        "Edit Position",
    )
    assert COMPENSATION_EVENT_TYPES == (
        "Propose Compensation Change",
        "Request Compensation Change",
    )
    assert not set(JOB_CHANGE_EVENT_TYPES).intersection(COMPENSATION_EVENT_TYPES)


def test_resolved_reference_is_contingent() -> None:
    """Identify contingent workers only when no employee identifier exists."""
    assert not ResolvedWorkerReference(wid="wid", employee_id="employee").is_contingent
    assert ResolvedWorkerReference(wid="wid", contingent_worker_id="contingent").is_contingent
    assert not ResolvedWorkerReference(wid="wid", employee_id="employee", contingent_worker_id="contingent").is_contingent


def test_job_snapshot_defaults_and_diff_exclude() -> None:
    """Keep every optional snapshot value absent until its parser supplies it."""
    snapshot = JobSnapshot(as_of=date(2026, 6, 8))

    assert all(value is None for name, value in snapshot.model_dump().items() if name != "as_of")
    assert "DIFF_EXCLUDE" not in JobSnapshot.model_fields
    assert "as_of" in JobSnapshot.DIFF_EXCLUDE
    assert {
        "wage",
        "pay_currency",
        "pay_frequency",
        "compensation_package",
        "compensation_grade",
        "compensation_grade_profile",
        "compensation_effective_date",
        "compensation_elements",
    }.issubset(JobSnapshot.model_fields)


def test_job_change_nested_roundtrip() -> None:
    """Preserve nested snapshot and diff values across a model dump and reconstruction."""
    original = JobChange(
        worker_wid="wid",
        effective_date=date(2026, 6, 8),
        kind="change",
        before=JobSnapshot(as_of=date(2026, 6, 7), position_id="A"),
        after=JobSnapshot(as_of=date(2026, 6, 8), position_id="B"),
        changes=[FieldChange(field="position_id", before="A", after="B")],
    )

    assert JobChange(**original.model_dump()) == original
    assert not original.includes_compensation


def test_worker_event_coerces_iso_strings() -> None:
    """Coerce Workday ISO date and datetime strings to typed values."""
    event = WorkerEvent(
        worker_wid="w",
        event_id="e",
        effective_date="2026-06-08",
        completed_at="2026-06-08T10:00:00",
    )

    assert event.effective_date == date(2026, 6, 8)
    assert event.completed_at == datetime(2026, 6, 8, 10, 0)
