"""Strict replay, expiry, deduplication and payload bounds for the suspension ledger (FEAT-559 M1)."""

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from pydantic import ValidationError

from parrot.knowledge.wiki.ledger.coder_suspensions import (
    CoderSuspensionStore,
    ModelKey,
    SuspensionHistoryError,
    SuspensionRecord,
    render_suspension_history,
)
from parrot.knowledge.wiki.ledger.events import InsightRecordedPayload, LedgerEvent
from parrot.knowledge.wiki.ledger.log import LedgerLog
from parrot.knowledge.wiki.store import estimate_tokens

UTC = timezone.utc


def _key(model: str = "qwen", backend: str = "nova") -> ModelKey:
    """Build the default matching model identity used across these tests."""
    return ModelKey(backend=backend, model=model)


def suspension(**overrides: object) -> SuspensionRecord:
    """Build one valid engine-sourced timeout incident with a reusable baseline."""
    occurred_at = overrides.pop("occurred_at", datetime(2026, 9, 16, 12, 0, 0, tzinfo=UTC))
    cooldown_seconds = overrides.pop("cooldown_seconds", 1800)
    data: dict[str, object] = dict(
        execution_id="exec-1",
        feature_id="FEAT-559",
        task_id="TASK-0001",
        attempt_uid="attempt-1",
        job_id="job-1",
        source="engine",
        seat_label="qwen",
        backend="nova",
        configured_model="qwen",
        resolved_model="qwen",
        blocked_keys=[_key()],
        reason="timeout",
        occurred_at=occurred_at,
        expires_at=occurred_at + timedelta(seconds=cooldown_seconds),
        duration_s=12.5,
        exception_class="TimeoutError",
        evidence_ref="job:job-1",
        explanation="Dispatch timed out after the configured deadline.",
    )
    data.update(overrides)
    return SuspensionRecord(**data)


@pytest.fixture
def store(tmp_path: Path) -> CoderSuspensionStore:
    """Use an isolated durable ledger without external services."""
    return CoderSuspensionStore(LedgerLog(str(tmp_path / "events.jsonl")))


async def test_duplicate_incident_preserves_expiry(store: CoderSuspensionStore) -> None:
    """Repeated record/replay of the same incident is one occurrence; expiry never refreshes."""
    first = suspension()
    await store.record(first)
    await store.record(first)  # simulate a retried persistence call for the same incident
    restarted = CoderSuspensionStore(LedgerLog(store.log.path))
    now = first.occurred_at + timedelta(seconds=1)
    records = await restarted.recent([_key()], now)
    assert len(records) == 1
    assert records[0].suspension_id == first.suspension_id
    assert records[0].expires_at == first.expires_at

    # Exact boundary: at now == expires_at the record is no longer "recent" ...
    assert await restarted.recent([_key()], first.expires_at) == []
    # ... but for_execution still returns it regardless of cooldown expiry.
    for_exec = await restarted.for_execution(first.execution_id)
    assert len(for_exec) == 1
    assert for_exec[0].suspension_id == first.suspension_id


async def test_latest_real_incident_extends_exclusion(store: CoderSuspensionStore) -> None:
    """Two distinct real failures for the same model both apply; effective exclusion uses max expiry."""
    first = suspension(attempt_uid="attempt-1")
    second = suspension(attempt_uid="attempt-2", occurred_at=first.occurred_at + timedelta(seconds=10))
    await store.record(first)
    await store.record(second)
    now = first.occurred_at + timedelta(seconds=5)
    records = await store.recent([_key()], now)
    assert {record.suspension_id for record in records} == {first.suspension_id, second.suspension_id}
    assert max(record.expires_at for record in records) == second.expires_at


async def test_cooldown_starts_at_failure_observation(store: CoderSuspensionStore) -> None:
    """A long-running attempt's cooldown is measured from failure observation, never attempt start."""
    occurred_at = datetime(2026, 9, 16, 12, 30, 0, tzinfo=UTC)
    record = suspension(occurred_at=occurred_at, duration_s=1800.0, cooldown_seconds=1800)
    await store.record(record)
    assert record.expires_at == occurred_at + timedelta(seconds=1800)
    just_before = record.expires_at - timedelta(seconds=1)
    just_after = record.expires_at + timedelta(seconds=1)
    assert await store.recent([_key()], just_before) != []
    assert await store.recent([_key()], just_after) == []


async def test_summary_budget_does_not_limit_exclusion(store: CoderSuspensionStore) -> None:
    """A truncated (or zero-token) rendered summary must never shrink the structured selection."""
    first = suspension(attempt_uid="attempt-1")
    second = suspension(attempt_uid="attempt-2", occurred_at=first.occurred_at + timedelta(seconds=1))
    await store.record(first)
    await store.record(second)
    now = first.occurred_at + timedelta(seconds=2)
    records = await store.recent([_key()], now)
    assert len(records) == 2
    for budget in (0, 1, 50, 1200):
        text = render_suspension_history(records, now, max_tokens=budget)
        assert estimate_tokens(text) <= budget
    # Even a fully-truncated (budget=0) summary changes nothing about selection.
    assert len(await store.recent([_key()], now)) == 2


async def test_corrupt_history_is_not_empty_history(store: CoderSuspensionStore) -> None:
    """Mid-file corruption in a matching record must raise, never look like a clean history."""
    good = suspension()
    await store.record(good)
    # A second, syntactically-valid ledger envelope whose `fact` is not a
    # valid SuspensionRecord -- and it is NOT the final line once appended.
    corrupt_event = LedgerEvent(
        kind="insight.recorded",
        subject="coder-suspension:corrupt",
        actor="agent:sdd-worker",
        payload=InsightRecordedPayload(
            title="timeout",
            category="coder_suspension",
            fact="{not valid json fact}",
            derived_from="execution:exec-1",
        ).model_dump(),
    )
    store.log.append(corrupt_event)
    with pytest.raises(SuspensionHistoryError):
        await store.recent([_key()], good.occurred_at + timedelta(seconds=1))
    with pytest.raises(SuspensionHistoryError):
        await store.for_execution(good.execution_id)

    # Unrelated, valid non-suspension categories never trigger this failure.
    clean = CoderSuspensionStore(LedgerLog(str(Path(store.log.path).with_name("clean.jsonl"))))
    clean.log.append(
        LedgerEvent(
            kind="issue.opened",
            subject="issue:1",
            actor="test",
            payload={"title": "x", "body": "y", "discovered_from": "task:TASK-0001"},
        )
    )
    assert await clean.recent([_key()], good.occurred_at) == []


async def test_event_payload_and_redaction_bounds(store: CoderSuspensionStore) -> None:
    """Multibyte evidence cannot exceed the ledger's 4 KiB event cap; invalid payloads are rejected."""
    with pytest.raises(ValidationError):
        suspension(explanation="漢" * 1401)  # exceeds the field's own bound

    oversized = suspension(explanation="漢" * 1400, evidence_ref="漢" * 300)
    with pytest.raises(ValueError, match="4 KiB"):
        await store.record(oversized)
    assert list(store.log.iter_events()) == []
