"""Question token budget ledger and public feature entry point (FEAT-550, spec §2.2/§2.3/§3 M1)."""

from __future__ import annotations

import asyncio
import logging
import uuid
from dataclasses import dataclass
from typing import Literal, Optional

from parrot.core.exceptions import (  # created by TASK-3132
    BudgetAccountingError,
    BudgetError,
    BudgetExhausted,
    BudgetRegistryFull,
    BudgetResumeConflict,
    BudgetScopeConflict,
    BudgetSnapshotInvalid,
    BudgetStateMissing,
    BudgetUnsupported,
)
from parrot.models.token_budget import (  # created by TASK-3132
    BudgetMode,
    BudgetReport,
    BudgetReservation,
    BudgetSnapshot,
    BudgetUsage,
    EstimateQuality,
    OperationState,
    ReservationPhase,
    TokenBudgetPolicy,
    TokenEstimate,
)

AttemptStatus = Literal["reserved", "settled", "uncertain", "released"]


@dataclass
class _Attempt:
    """Per-reservation mutable state (ledger-internal)."""

    reservation: BudgetReservation
    status: AttemptStatus = "reserved"
    usage: Optional[BudgetUsage] = None
    reason: Optional[str] = None


class QuestionBudget:
    """Mutable ledger for one question on one event loop."""

    def __init__(self, policy: TokenBudgetPolicy, operation_id: str) -> None:
        """Create an empty active ledger; validate policy before use."""
        self.logger = logging.getLogger(__name__)
        self._policy = policy
        self._operation_id = operation_id
        self._lock = asyncio.Lock()
        self._state: OperationState = "active"
        self._revision = 0
        self._settled_input = 0
        self._settled_output = 0
        self._attempts: dict[str, _Attempt] = {}
        self._finalization_owner: Optional[str] = None
        self._finalization_attempted = False
        self._finalized = False
        self._answer_complete = True
        self._strict_violated = False
        self._counting_methods: set[str] = set()
        self._terminal_reason: Optional[str] = None
        self._restored_attempts = 0
        self._restored_rounds = 0

    # ── read-only identity ────────────────────────────────────────────
    @property
    def operation_id(self) -> str:
        return self._operation_id

    @property
    def policy(self) -> TokenBudgetPolicy:
        return self._policy

    @property
    def state(self) -> OperationState:
        return self._state

    @property
    def revision(self) -> int:
        return self._revision

    @property
    def attempt_count(self) -> int:
        """Total attempts recorded on this ledger, including a restored floor."""
        return len(self._attempts) + self._restored_attempts

    @property
    def round_count(self) -> int:
        """Distinct rounds observed on this ledger, including a restored floor."""
        rounds = {a.reservation.round_number for a in self._attempts.values()}
        return len(rounds) + self._restored_rounds

    # ── §2.2 quantities (call ONLY under self._lock) ──────────────────
    def _consumed(self) -> int:
        return self._settled_input + self._settled_output

    def _uncertain(self) -> int:
        return sum(a.reservation.total for a in self._attempts.values() if a.status == "uncertain")

    def _in_flight(self) -> int:
        return sum(a.reservation.total for a in self._attempts.values() if a.status == "reserved")

    def _available(self, phase: ReservationPhase) -> int:
        b, f = self._policy.token_budget, self._policy.final_reserve_tokens
        used = self._consumed() + self._uncertain() + self._in_flight()
        return max(0, (b - f - used) if phase == "work" else (b - used))

    async def reserve(
        self,
        estimate: TokenEstimate,
        *,
        max_output_tokens: int,
        min_output_tokens: int,
        call_id: str,
        round_number: int,
        attempt_number: int,
        phase: ReservationPhase,
    ) -> BudgetReservation:
        """Reserve I+O or raise typed denial; final requires the owner claim."""
        async with self._lock:
            self._counting_methods.add(estimate.method)
            if self._policy.enforcement == "observe":
                # Observational ledger: account, never refuse, never resize.
                # Deliberately does NOT consult `_available()` (line 146) nor
                # compute `min(max_output_tokens, available - estimate.input_tokens)`
                # (line 147) — a measurement must not change the request it
                # measures (spec §2, §10 R1).
                self._revision += 1
                reservation = BudgetReservation(
                    reservation_id=str(uuid.uuid4()),
                    operation_id=self._operation_id,
                    call_id=call_id,
                    round_number=round_number,
                    attempt_number=attempt_number,
                    phase=phase,
                    input_allowance=estimate.input_tokens,
                    output_cap=max_output_tokens,
                    request_fingerprint=estimate.request_fingerprint,
                )
                self._attempts[reservation.reservation_id] = _Attempt(reservation)
                self.logger.debug(
                    "reserve %s phase=%s I=%d O=%d (observe)",
                    reservation.reservation_id,
                    phase,
                    estimate.input_tokens,
                    max_output_tokens,
                )
                return reservation
            if self._state == "closed" or self._strict_violated:
                raise BudgetExhausted(
                    "operation cannot admit inference",
                    operation_id=self._operation_id,
                    report=self._report_locked().model_dump(),
                )
            if phase == "final" and self._finalization_owner != call_id:
                raise BudgetAccountingError(
                    "final reservation without a finalization claim",
                    operation_id=self._operation_id,
                )
            if phase == "work" and self._state not in ("active", "suspended"):
                raise BudgetExhausted(
                    "operation is draining",
                    operation_id=self._operation_id,
                    report=self._report_locked().model_dump(),
                )
            available = self._available(phase)
            output_cap = min(max_output_tokens, available - estimate.input_tokens)
            if output_cap < min_output_tokens:
                if phase == "work":
                    if self._state == "active":
                        self._state = "draining"
                        self._terminal_reason = "budget_exhausted"
                raise BudgetExhausted(
                    "insufficient budget",
                    operation_id=self._operation_id,
                    report=self._report_locked().model_dump(),
                )
            reservation = BudgetReservation(
                reservation_id=str(uuid.uuid4()),
                operation_id=self._operation_id,
                call_id=call_id,
                round_number=round_number,
                attempt_number=attempt_number,
                phase=phase,
                input_allowance=estimate.input_tokens,
                output_cap=output_cap,
                request_fingerprint=estimate.request_fingerprint,
            )
            self._attempts[reservation.reservation_id] = _Attempt(reservation)
            if phase == "final":
                self._finalization_attempted = True
                self._state = "finalizing"
            self._revision += 1
            self.logger.debug(
                "reserve %s phase=%s I=%d O=%d",
                reservation.reservation_id,
                phase,
                estimate.input_tokens,
                output_cap,
            )
            return reservation

    async def settle(self, reservation_id: str, usage: BudgetUsage) -> None:
        """Reconcile actual usage once; identical duplicate settlement is inert."""
        async with self._lock:
            attempt = self._require(reservation_id)
            if attempt.status == "released":
                raise BudgetAccountingError(
                    f"cannot settle released reservation {reservation_id}",
                    operation_id=self._operation_id,
                )
            if attempt.status == "settled":
                # identical duplicate settlement is inert
                if (
                    attempt.usage is not None
                    and attempt.usage.input_tokens == usage.input_tokens
                    and attempt.usage.output_tokens == usage.output_tokens
                ):
                    return
                raise BudgetAccountingError(
                    f"contradictory settlement for reservation {reservation_id}",
                    operation_id=self._operation_id,
                )

            # Transition from reserved or uncertain to settled
            attempt.status = "settled"
            attempt.usage = usage
            self._settled_input += usage.input_tokens
            self._settled_output += usage.output_tokens

            # Strict mode violation check
            if self._policy.budget_mode == "strict" and usage.total_tokens > attempt.reservation.total:
                self._strict_violated = True
                self._revision += 1
                raise BudgetAccountingError(
                    f"strict mode reservation violation: usage {usage.total_tokens} exceeded reservation {attempt.reservation.total}",
                    operation_id=self._operation_id,
                )

            # If we are in finalizing state and this was the final phase reservation, mark finalized
            if attempt.reservation.phase == "final":
                self._finalized = True
                # Check if answer is complete (e.g. if we got output tokens and didn't hit length cutoff, etc.)
                # The spec says: "finalized=True means it returned a terminal response, not that the original task necessarily succeeded."
                # "answer_complete=False for provider length cutoff, failed structured parsing, missing final answer or partial fallback."
                # By default, we can assume answer_complete is True unless some condition is met, or we can set it based on usage/state.
                # Let's keep self._answer_complete as True unless overridden or if we want to check something.

            self._revision += 1

    async def mark_uncertain(self, reservation_id: str, reason: str) -> None:
        """Retain the entire admitted debit when actual usage is unknown."""
        async with self._lock:
            attempt = self._require(reservation_id)
            if attempt.status != "reserved":
                raise BudgetAccountingError(
                    f"cannot mark {attempt.status} reservation {reservation_id} as uncertain",
                    operation_id=self._operation_id,
                )
            attempt.status = "uncertain"
            attempt.reason = reason
            self._revision += 1

    async def release_unspent(self, reservation_id: str) -> None:
        """Release only a request proven not to have been dispatched/consumed."""
        async with self._lock:
            attempt = self._require(reservation_id)
            if attempt.status != "reserved":
                raise BudgetAccountingError(
                    f"cannot release {attempt.status} reservation {reservation_id}",
                    operation_id=self._operation_id,
                )
            attempt.status = "released"
            self._revision += 1

    async def claim_finalization(self, owner_call_id: str) -> bool:
        """Claim the one final attempt after draining; false if already claimed.

        Spec §2.1: "Zero disables finalization" — a zero `final_answer_reserve`
        must refuse the claim outright, not merely rely on the remaining
        balance also happening to be zero (an ordinary round that underspends
        could otherwise still leave room for a closing attempt, contradicting
        the documented "zero disables" guarantee — code-reviewer finding,
        FEAT-550 wrap-up).
        """
        async with self._lock:
            if self._policy.final_reserve_tokens == 0:
                return False
            if self._state != "draining":
                return False
            if self._finalization_owner is not None:
                return False
            # "and only when no attempt is still reserved (in-flight must resolve first)"
            if any(a.status == "reserved" for a in self._attempts.values()):
                return False
            self._finalization_owner = owner_call_id
            self._revision += 1
            return True

    async def report(self) -> BudgetReport:
        """Return an immutable consistent snapshot of current accounting."""
        async with self._lock:
            return self._report_locked()

    async def close(self, *, terminal_reason: Optional[str] = None) -> None:
        """Mark the operation closed (idempotent); late descendants can no longer spend."""
        async with self._lock:
            self._state = "closed"
            if terminal_reason:
                self._terminal_reason = terminal_reason
            self._revision += 1

    async def set_answer_complete(self, value: bool) -> None:
        """Record whether the terminal answer is complete (provider cutoff, parse failure, final tool call → False)."""
        async with self._lock:
            self._answer_complete = bool(value)
            self._revision += 1

    def restore_settled(
        self,
        *,
        input_tokens: int,
        output_tokens: int,
        revision: int,
        attempt_count: int,
        round_count: int,
    ) -> None:
        """Seed a fresh ledger from a trusted snapshot (registry-only; spec §2.6)."""
        if self._attempts or self._consumed() or self._revision:
            raise BudgetAccountingError(
                "restore_settled requires an empty ledger",
                operation_id=self._operation_id,
            )
        self._settled_input, self._settled_output = input_tokens, output_tokens
        self._revision = revision
        self._restored_attempts, self._restored_rounds = attempt_count, round_count

    def _require(self, reservation_id: str) -> _Attempt:
        try:
            return self._attempts[reservation_id]
        except KeyError as exc:
            raise BudgetAccountingError(
                f"unknown reservation {reservation_id}",
                operation_id=self._operation_id,
            ) from exc

    def _report_locked(self) -> BudgetReport:
        b = self._policy.token_budget
        c = self._consumed()
        u = self._uncertain()
        r = self._in_flight()

        overrun_tokens = max(0, c - b)
        accounting_complete = not any(a.status in ("reserved", "uncertain") for a in self._attempts.values())
        budget_exhausted = self._state in ("draining", "finalizing", "closed") or self._terminal_reason is not None

        remaining_work_tokens = max(0, b - self._policy.final_reserve_tokens - c - u - r)
        remaining_total_tokens = max(0, b - c - u - r)

        return BudgetReport(
            operation_id=self._operation_id,
            policy=self._policy,
            state=self._state,
            revision=self._revision,
            input_tokens=self._settled_input,
            output_tokens=self._settled_output,
            total_tokens=c,
            uncertain_tokens=u,
            in_flight_tokens=r,
            remaining_work_tokens=remaining_work_tokens,
            remaining_total_tokens=remaining_total_tokens,
            counting_methods=tuple(self._counting_methods),
            settled_estimate_input_tokens=sum(
                a.reservation.input_allowance for a in self._attempts.values() if a.status == "settled"
            ),
            released_estimate_tokens=sum(
                a.reservation.input_allowance for a in self._attempts.values() if a.status == "released"
            ),
            overrun_tokens=overrun_tokens,
            accounting_complete=accounting_complete,
            budget_exhausted=budget_exhausted,
            finalization_attempted=self._finalization_attempted,
            finalized=self._finalized,
            answer_complete=self._answer_complete,
            terminal_reason=self._terminal_reason,
        )


__all__ = [
    "QuestionBudget",
    "AttemptStatus",
    "TokenBudgetPolicy",
    "TokenEstimate",
    "BudgetUsage",
    "BudgetReservation",
    "BudgetReport",
    "BudgetSnapshot",
    "BudgetMode",
    "EstimateQuality",
    "ReservationPhase",
    "OperationState",
    "BudgetError",
    "BudgetExhausted",
    "BudgetUnsupported",
    "BudgetScopeConflict",
    "BudgetStateMissing",
    "BudgetResumeConflict",
    "BudgetSnapshotInvalid",
    "BudgetAccountingError",
    "BudgetRegistryFull",
]
