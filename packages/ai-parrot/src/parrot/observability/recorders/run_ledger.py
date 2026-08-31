"""RunLedgerRecorder — the per-run usage ledger sink (FEAT-479 Module 4b).

An in-memory, append-only ``AbstractLogger`` sink. It is a SINK, not an
``EventProvider`` — it has no ``register()``. The EXISTING
``UsageRecordingSubscriber`` (``recorders/subscriber.py``) owns the
``AfterClientCallEvent``/``ClientCallFailedEvent`` subscription and fans
records out to this sink alongside any other configured recorders.

Being append-only is what fixes spec Finding 2 (retry cycles overwriting
each other's token counts in session state): a second cycle for the same
seat is appended, not merged, so ``by_seat()`` sums every cycle. Because
``seat`` is a free string (FEAT-479 Module 2), a pool-worker seat like
``"development.w1"`` is a first-class row here — fixing Finding 3 without
widening the closed ``NodeId`` ``Literal``.
"""

from __future__ import annotations

import logging
import threading

from pydantic import BaseModel, ConfigDict, Field

from parrot.observability.recorders.base import AbstractLogger
from parrot.observability.recorders.models import UsageRecord

logger = logging.getLogger(__name__)


class SeatUsage(BaseModel):
    """Roll-up of one seat across its cycles. Report-facing only.

    Attributes:
        seat: The accounting seat (``"qa"``, or a pool-worker seat like
            ``"development.w1"``).
        node_id: The roll-up owner node id (``"development.w1"`` rolls up
            to ``"development"``).
        provider: The ``gen_ai.system`` provider of the seat's calls (taken
            from the first cycle).
        model: The model identifier of the seat's calls (taken from the
            first cycle).
        cycles: Every retained ``UsageRecord`` for this seat, in append
            order (1-based ``cycle`` numbering).
        input_tokens: Sum of input tokens across cycles that reported
            usage; ``None`` when every cycle was unreported (never a
            fabricated ``0``).
        output_tokens: Sum of output tokens, same convention.
        rounds: Number of retained cycles for this seat.
        failures: Number of cycles with ``status == "failed"``.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    seat: str
    node_id: str
    provider: str = ""
    model: str = ""
    cycles: list[UsageRecord] = Field(default_factory=list)
    input_tokens: int | None = None
    output_tokens: int | None = None
    rounds: int | None = None
    failures: int = 0


class RunLedgerRecorder(AbstractLogger):
    """In-memory, append-only per-run usage ledger.

    Cycles accumulate because appends accumulate — nothing is ever
    overwritten. NOT an ``EventProvider``: it has no ``register()``: the
    existing ``UsageRecordingSubscriber`` owns the subscription and calls
    ``record()`` on this sink like any other ``AbstractLogger`` backend.

    Args:
        run_id: The dev-loop / dev-flow run identifier this ledger belongs
            to.
    """

    name = "run_ledger"

    def __init__(self, run_id: str) -> None:
        self._run_id = run_id
        self._records: list[UsageRecord] = []
        self._lock = threading.Lock()
        self.partial: bool = False
        self.partial_reason: str = ""

    @property
    def run_id(self) -> str:
        """The run identifier this ledger belongs to."""
        return self._run_id

    @property
    def records(self) -> list[UsageRecord]:
        """Every retained record, in append order."""
        return list(self._records)

    def next_cycle(self, seat: str) -> int:
        """Return the 1-based cycle number the next record for *seat* gets."""
        with self._lock:
            return sum(1 for r in self._records if r.seat == seat) + 1

    async def record(self, record: UsageRecord) -> None:
        """Append *record* to the ledger, assigning ``cycle`` if unset.

        Never raises: a ledger that throws would be logged as a broken
        backend by the subscriber's error-isolated fan-out on every call
        and silently lose everything. The incoming record is never
        mutated — other sinks in the same fan-out hold the same instance.
        """
        try:
            seat = record.seat or ""
            cycle = record.cycle
            if cycle is None:
                cycle = self.next_cycle(seat)
            stamped = record.model_copy(update={"cycle": cycle})
            with self._lock:
                self._records.append(stamped)
        except Exception:  # the ledger must never break a run
            logger.exception("RunLedgerRecorder failed to append a record; dropping it.")

    async def aclose(self) -> None:
        """No-op — nothing to flush; required by ``AbstractLogger``."""
        return

    def mark_partial(self, reason: str) -> None:
        """Mark this ledger as partial (§8 Q1: a resumed run found no prior
        ledger for its ``run_id``). Idempotent — keeps the first reason.
        """
        if self.partial:
            return
        self.partial = True
        self.partial_reason = reason

    def by_seat(self) -> list[SeatUsage]:
        """Roll up every retained record into one ``SeatUsage`` per seat.

        Sums skip records with ``usage_reported=False`` rather than
        coercing; a seat with no reported usage at all yields ``None`` for
        both token sums, never a fabricated ``0``.
        """
        by_seat: dict[str, list[UsageRecord]] = {}
        for rec in self._records:
            by_seat.setdefault(rec.seat or "", []).append(rec)

        result: list[SeatUsage] = []
        for seat, cycles in by_seat.items():
            node_id = cycles[0].node_id or seat.split(".", 1)[0]
            reported = [r for r in cycles if r.usage_reported]
            input_tokens = sum(r.input_tokens for r in reported) if reported else None
            output_tokens = sum(r.output_tokens for r in reported) if reported else None
            failures = sum(1 for r in cycles if r.status == "failed")
            result.append(
                SeatUsage(
                    seat=seat,
                    node_id=node_id,
                    provider=cycles[0].provider,
                    model=cycles[0].model,
                    cycles=cycles,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    rounds=len(cycles),
                    failures=failures,
                )
            )
        return result
