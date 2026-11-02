"""FEAT-783 TASK-4985 — UsageRecord SDD identity (AC-1, AC-2)."""

from __future__ import annotations

import pytest

from parrot.core.events.lifecycle import TraceContext
from parrot.core.events.lifecycle.events import AfterClientCallEvent, ClientCallFailedEvent
from parrot.observability.attribution import UsageAttribution
from parrot.observability.context import usage_attribution
from parrot.observability.recorders.models import UsageRecord
from parrot.observability.recorders.subscriber import UsageRecordingSubscriber


class _Capture:
    """In-memory recorder for subscriber assertions."""

    name = "capture"

    def __init__(self) -> None:
        self.records: list[UsageRecord] = []

    async def record(self, record: UsageRecord) -> None:
        """Capture one normalized usage record."""
        self.records.append(record)

    async def aclose(self) -> None:
        """Meet the recorder protocol."""


def _attribution(suffix: str) -> UsageAttribution:
    """Build a complete, distinguishable SDD attribution."""
    return UsageAttribution(
        feat_id=f"FEAT-{suffix}",
        task_id=f"TASK-{suffix}",
        attempt_uid=f"attempt-{suffix}",
        execution_id=f"execution-{suffix}",
        dispatch_kind="cli",
        roster_seat=f"seat-{suffix}",
    )


def _after_event() -> AfterClientCallEvent:
    """Build a successful event whose attribution snapshots at construction."""
    return AfterClientCallEvent(
        trace_context=TraceContext.new_root(),
        client_name="openai",
        model="gpt-4o-mini",
        duration_ms=42.0,
        input_tokens=10,
        output_tokens=5,
    )


def _sdd_fields(record: UsageRecord) -> tuple[str | None, str | None, str | None, str | None, str | None, str | None]:
    """Return the SDD identity fields in their record order."""
    return (
        record.feat_id,
        record.task_id,
        record.attempt_uid,
        record.execution_id,
        record.dispatch_kind,
        record.roster_seat,
    )


@pytest.mark.asyncio
async def test_record_carries_sdd_fields_and_keeps_run_seat() -> None:
    """AC-1: SDD fields supplement, rather than replace, run/seat attribution."""
    capture = _Capture()
    subscriber = UsageRecordingSubscriber(recorders=[capture])
    attribution = _attribution("783")

    with usage_attribution("run-783", "development.w1", attribution):
        await subscriber._on_client_after(_after_event())

    record = capture.records[0]
    assert _sdd_fields(record) == ("FEAT-783", "TASK-783", "attempt-783", "execution-783", "cli", "seat-783")
    assert (record.run_id, record.seat, record.node_id) == ("run-783", "development.w1", "development")


@pytest.mark.asyncio
async def test_forwarded_event_keeps_original_attribution() -> None:
    """AC-2: a forwarded event's snapshot wins over handling-time context."""
    capture = _Capture()
    subscriber = UsageRecordingSubscriber(recorders=[capture])

    with usage_attribution("run-a", "development.w1", _attribution("A")):
        event = _after_event()

    with usage_attribution("run-b", "qa", _attribution("B")):
        await subscriber._on_client_after(event)

    record = capture.records[0]
    assert _sdd_fields(record) == ("FEAT-A", "TASK-A", "attempt-A", "execution-A", "cli", "seat-A")
    assert (record.run_id, record.seat) == ("run-b", "qa")


@pytest.mark.asyncio
async def test_contextvar_fallback_when_event_has_none() -> None:
    """AC-2: handling-time attribution is used only when the event has none."""
    capture = _Capture()
    subscriber = UsageRecordingSubscriber(recorders=[capture])
    event = _after_event()
    assert event.attribution is None

    with usage_attribution("run-b", "qa", _attribution("B")):
        await subscriber._on_client_after(event)

    assert _sdd_fields(capture.records[0]) == ("FEAT-B", "TASK-B", "attempt-B", "execution-B", "cli", "seat-B")


@pytest.mark.asyncio
async def test_failed_event_attributed() -> None:
    """The failure path copies the same SDD identity onto its UsageRecord."""
    capture = _Capture()
    subscriber = UsageRecordingSubscriber(recorders=[capture])

    with usage_attribution("run-783", "development", _attribution("FAIL")):
        event = ClientCallFailedEvent(
            trace_context=TraceContext.new_root(),
            client_name="openai",
            model="gpt-4o-mini",
            duration_ms=7.0,
            error_type="RuntimeError",
        )

    await subscriber._on_client_failed(event)

    record = capture.records[0]
    assert _sdd_fields(record) == ("FEAT-FAIL", "TASK-FAIL", "attempt-FAIL", "execution-FAIL", "cli", "seat-FAIL")
    assert record.status == "failed"
