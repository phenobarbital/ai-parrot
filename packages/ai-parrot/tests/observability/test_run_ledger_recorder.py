"""Unit tests for FEAT-479 Module 4b — RunLedgerRecorder, the per-run usage
ledger sink.

This is a SINK (``AbstractLogger``), not a subscriber — it has no
``register()``. Being append-only is what fixes spec Finding 2 (retry
cycles overwriting each other in session state); a free-string ``seat`` is
what fixes Finding 3 (pool-worker seats silently dropped by the closed
``NodeId`` ``Literal``).
"""

from __future__ import annotations

from parrot.observability.recorders.models import UsageRecord
from parrot.observability.recorders.run_ledger import RunLedgerRecorder


def _rec(seat, node_id, inp, out, *, reported=True, status="completed"):
    return UsageRecord(
        provider="anthropic",
        model="claude-opus-5",
        seat=seat,
        node_id=node_id,
        input_tokens=inp,
        output_tokens=out,
        usage_reported=reported,
        status=status,
    )


async def test_ledger_accumulates_across_cycles():
    """Regression guard for FEAT-479 Finding 2 — session state overwrote:
        after round 1: in=1000 out=500
        after round 2: in=2000 out=700   <- round 1 erased
    Appending must instead total 3000/1200."""
    led = RunLedgerRecorder(run_id="run-1")
    await led.record(_rec("development", "development", 1000, 500))
    await led.record(_rec("development", "development", 2000, 700))
    (seat,) = led.by_seat()
    assert [c.cycle for c in seat.cycles] == [1, 2]
    assert seat.input_tokens == 3000
    assert seat.output_tokens == 1200


async def test_ledger_records_pool_worker_seat():
    """Regression guard for Finding 3 — 'development.w1' could not exist as a
    NodeId, so pool telemetry was silently dropped."""
    led = RunLedgerRecorder(run_id="run-1")
    await led.record(_rec("development.w1", "development", 100, 50))
    await led.record(_rec("development.w2", "development", 200, 60))
    seats = {s.seat: s for s in led.by_seat()}
    assert set(seats) == {"development.w1", "development.w2"}
    assert all(s.node_id == "development" for s in seats.values())


async def test_ledger_never_fabricates_zero():
    led = RunLedgerRecorder(run_id="run-1")
    await led.record(_rec("qa", "qa", 0, 0, reported=False))
    (seat,) = led.by_seat()
    assert seat.input_tokens is None  # not 0
    assert seat.output_tokens is None


async def test_failed_record_retained_and_counted():
    led = RunLedgerRecorder(run_id="run-1")
    await led.record(_rec("qa", "qa", 900, 100, status="failed"))
    (seat,) = led.by_seat()
    assert seat.failures == 1
    assert seat.input_tokens == 900  # tokens burned before failing


async def test_does_not_mutate_incoming_record():
    led = RunLedgerRecorder(run_id="run-1")
    rec = _rec("qa", "qa", 1, 1)
    await led.record(rec)
    assert rec.cycle is None  # the sink copied, not mutated


def test_mark_partial_is_idempotent():
    led = RunLedgerRecorder(run_id="run-1")
    led.mark_partial("resumed in a new process")
    led.mark_partial("something else")
    assert led.partial is True
    assert led.partial_reason == "resumed in a new process"


def test_has_no_register_method():
    """v0.3: this is a SINK. A register() would recreate the duplicate
    subscriber the spec rejected."""
    assert not hasattr(RunLedgerRecorder(run_id="r"), "register")


async def test_record_never_raises_on_malformed_seat():
    """A record with no seat at all must not break the ledger."""
    led = RunLedgerRecorder(run_id="run-1")
    rec = UsageRecord(provider="openai", model="gpt-4o", input_tokens=1, output_tokens=1)
    await led.record(rec)  # must not raise
    assert len(led.records) == 1


def test_next_cycle_is_one_based_and_seat_scoped():
    led = RunLedgerRecorder(run_id="run-1")
    assert led.next_cycle("qa") == 1


async def test_records_property_returns_a_copy():
    led = RunLedgerRecorder(run_id="run-1")
    await led.record(_rec("qa", "qa", 1, 1))
    records = led.records
    records.append(_rec("qa", "qa", 2, 2))
    assert len(led.records) == 1  # the internal list was not mutated


async def test_aclose_is_a_noop():
    led = RunLedgerRecorder(run_id="run-1")
    await led.aclose()  # must not raise
