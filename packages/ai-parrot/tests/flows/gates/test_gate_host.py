"""Unit tests for the generic gate host."""

from __future__ import annotations

from typing import Any

import pytest

from parrot.bots.flows.core.gates import (
    AUTO_APPROVER,
    GateError,
    GateErrorCode,
    GateHost,
    GateRecord,
    GateSpec,
    PreReviewVerdict,
    register_gate_kind,
)


class InMemoryGateStore:
    """Small async GateStore implementation for host unit tests."""

    def __init__(self) -> None:
        """Initialize an empty record mapping."""
        self.records: dict[str, GateRecord] = {}

    async def put(self, record: GateRecord) -> None:
        """Persist a record in memory."""
        self.records[record.gate_id] = record

    async def get(self, gate_id: str) -> GateRecord | None:
        """Return one record by identifier."""
        return self.records.get(gate_id)

    async def pending(self, owner: str | None = None) -> list[GateRecord]:
        """Return pending records, optionally restricted to an owner."""
        return [
            record
            for record in self.records.values()
            if record.status == "pending" and (owner is None or record.owner == owner)
        ]


class RecordingNotifier:
    """Minimal non-blocking human notifier fake."""

    def __init__(self) -> None:
        """Initialize the recorded request list."""
        self.interactions: list[Any] = []

    async def request_human_input_async(self, interaction: Any) -> str:
        """Record delivery and return the interaction id."""
        self.interactions.append(interaction)
        return interaction.interaction_id


def gate_spec(kind: str, **updates: Any) -> GateSpec:
    """Build a registered-gate specification for a test.

    Args:
        kind: Unique kind registered for this test.
        updates: Optional GateSpec field overrides.

    Returns:
        Configured gate specification.
    """
    register_gate_kind(kind, description=kind)
    return GateSpec(kind=kind, title="Review changes", instructions="Please review.", **updates)


@pytest.mark.asyncio
async def test_open_resolve_notifies_and_emits_events() -> None:
    """Opening then resolving persists state, delivers, and emits events."""
    store = InMemoryGateStore()
    notifier = RecordingNotifier()
    events = []
    host = GateHost(store, notifier=notifier)  # type: ignore[arg-type]

    async def record_event(event: Any) -> None:
        events.append(event)

    host.subscribe(record_event)
    record = await host.open(gate_spec("test-host-roundtrip"), owner="flow-1", payload_ref="artifact://1")
    resolved = await host.resolve(
        record.gate_id,
        "approved",
        resolved_by="human:1",
        comment="Looks good",
        answers={"risk": "low"},
    )

    assert record.status == "pending"
    assert store.records[record.gate_id] == resolved
    assert resolved.status == "approved"
    assert resolved.answers == {"risk": "low"}
    assert [event.type for event in events] == ["opened", "resolved"]
    assert len(notifier.interactions) == 1
    assert notifier.interactions[0].question == record.spec.title


@pytest.mark.asyncio
async def test_resolve_requires_an_existing_pending_gate() -> None:
    """Resolution rejects missing and already terminal records."""
    store = InMemoryGateStore()
    host = GateHost(store)

    with pytest.raises(GateError) as missing:
        await host.resolve("missing", "approved", resolved_by="human:1")
    assert missing.value.code is GateErrorCode.NOT_FOUND

    record = await host.open(gate_spec("test-host-not-pending"), owner="flow-1")
    await host.resolve(record.gate_id, "rejected", resolved_by="human:1")
    with pytest.raises(GateError) as terminal:
        await host.resolve(record.gate_id, "approved", resolved_by="human:2")
    assert terminal.value.code is GateErrorCode.NOT_PENDING


@pytest.mark.asyncio
async def test_recover_applies_both_expiry_policies_after_downtime() -> None:
    """Recovery transitions elapsed fail-closed and fail-open records."""
    store = InMemoryGateStore()
    host = GateHost(store)
    fail_closed = await host.open(
        gate_spec("test-host-expire-fail", ttl_seconds=1, on_expiry="fail"), owner="flow-1"
    )
    fail_open = await host.open(
        gate_spec("test-host-expire-approve", ttl_seconds=1, on_expiry="approve"), owner="flow-1"
    )

    recovered = await host.recover(now=max(fail_closed.expires_at or 0, fail_open.expires_at or 0) + 1)

    records = {record.gate_id: record for record in recovered}
    assert records[fail_closed.gate_id].status == "expired"
    assert records[fail_open.gate_id].status == "approved"
    assert records[fail_open.gate_id].resolved_by == AUTO_APPROVER
    assert records[fail_open.gate_id].resolved_at is not None


@pytest.mark.asyncio
async def test_pre_review_is_advisory_and_errors_are_captured() -> None:
    """Pre-review results never resolve gates, including reviewer failures."""
    async def reviewer(record: GateRecord) -> PreReviewVerdict:
        return PreReviewVerdict(expert="reviewer", recommendation="reject", summary=record.gate_id)

    reviewed = await GateHost(InMemoryGateStore(), pre_reviewer=reviewer).open(
        gate_spec("test-host-pre-review", pre_review="reviewer"), owner="flow-1"
    )
    assert reviewed.status == "pending"
    assert reviewed.pre_review is not None
    assert reviewed.pre_review.recommendation == "reject"

    async def failing_reviewer(record: GateRecord) -> PreReviewVerdict:
        raise RuntimeError(f"cannot review {record.gate_id}")

    failed = await GateHost(InMemoryGateStore(), pre_reviewer=failing_reviewer).open(
        gate_spec("test-host-pre-review-error", pre_review="reviewer"), owner="flow-1"
    )
    assert failed.status == "pending"
    assert failed.pre_review is not None
    assert failed.pre_review.recommendation == "unsure"
    assert failed.pre_review.error.startswith("cannot review")
