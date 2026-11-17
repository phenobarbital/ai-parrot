"""FEAT-783 AC-11 — usage + failure for one attempt is one round."""

from typing import Literal

import pytest

from parrot.observability.recorders.models import UsageRecord
from parrot.observability.recorders.run_ledger import RunLedgerRecorder


def _record(*, attempt_uid: str | None, status: Literal["completed", "failed"] = "completed") -> UsageRecord:
    """Build one attributed usage record for the run-ledger tests."""
    return UsageRecord(
        provider="anthropic",
        model="claude-opus-5",
        seat="development.w1",
        node_id="development",
        attempt_uid=attempt_uid,
        input_tokens=10,
        output_tokens=5,
        status=status,
    )


@pytest.mark.asyncio
async def test_usage_and_failure_same_attempt_is_one_round() -> None:
    ledger = RunLedgerRecorder(run_id="run-1")
    await ledger.record(_record(attempt_uid="attempt-1"))
    await ledger.record(_record(attempt_uid="attempt-1", status="failed"))

    (seat,) = ledger.by_seat()

    assert seat.rounds == 1
    assert seat.failures == 1
    assert len(seat.cycles) == 2


@pytest.mark.asyncio
async def test_records_without_attempt_uid_keep_legacy_count() -> None:
    ledger = RunLedgerRecorder(run_id="run-1")
    await ledger.record(_record(attempt_uid=None))
    await ledger.record(_record(attempt_uid=None, status="failed"))

    (seat,) = ledger.by_seat()

    assert seat.rounds == 2
    assert seat.failures == 1
    assert len(seat.cycles) == 2
