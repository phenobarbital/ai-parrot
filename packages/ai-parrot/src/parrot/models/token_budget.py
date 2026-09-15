"""Immutable records for cumulative question token budgets (FEAT-550, spec §2).

Policy, estimate, usage, reservation, report and snapshot shapes shared by the
ledger (``parrot.clients.budget``), the scope registry
(``parrot.clients.budget_scope``) and the provider adapters. All records are
frozen, strict and forbid extra fields.
"""

from __future__ import annotations

from decimal import Decimal, ROUND_FLOOR
from math import isfinite
from typing import Any, Dict, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, computed_field, model_validator

BudgetMode = Literal["estimated", "strict"]
EstimateQuality = Literal["estimated", "exact", "upper_bound"]
ReservationPhase = Literal["work", "final"]
OperationState = Literal["active", "suspended", "draining", "finalizing", "closed"]

_STRICT = ConfigDict(frozen=True, extra="forbid", strict=True)


class TokenBudgetPolicy(BaseModel):
    """Immutable per-question policy (spec §2.1 table)."""

    model_config = _STRICT

    token_budget: int = Field(..., ge=0, description="Cumulative ceiling B; 0 admits no inference")
    budget_mode: BudgetMode = "estimated"
    final_answer_reserve: int | float = Field(0.15, description="int = absolute tokens; float = fraction of B")
    enforcement: Literal["enforce", "observe"] = "enforce"
    """Whether this ledger may refuse work, or only account for it.

    ``"observe"`` means: admit every request without consulting available
    funds, and return ``output_cap = max_output_tokens`` verbatim so no
    caller's output cap is ever rewritten. It exists so a long agent loop can
    be measured with the same machinery that would enforce, without the
    measurement perturbing the run it measures (spec §2, §10 R1-R2).

    Defaults to ``"enforce"`` — every policy written before FEAT-554 keeps
    today's behaviour exactly.
    """

    @model_validator(mode="after")
    def _validate_reserve(self) -> "TokenBudgetPolicy":
        """Reject bool/NaN/inf/out-of-range reserves (spec §2.1)."""
        r = self.final_answer_reserve
        if isinstance(r, bool):
            raise ValueError("final_answer_reserve must not be a bool")
        if isinstance(r, float):
            if not isfinite(r) or not 0.0 <= r <= 1.0:
                raise ValueError("fractional final_answer_reserve must be finite and within [0, 1]")
        elif not 0 <= r <= self.token_budget:
            raise ValueError("absolute final_answer_reserve must be within [0, token_budget]")
        return self

    @computed_field  # type: ignore[misc]
    @property
    def final_reserve_tokens(self) -> int:
        """F = floor(B * fraction) via decimal-string arithmetic, or the absolute int."""
        r = self.final_answer_reserve
        if isinstance(r, float):
            return int((Decimal(str(r)) * Decimal(self.token_budget)).to_integral_value(rounding=ROUND_FLOOR))
        return r


class TokenEstimate(BaseModel):
    """Counted/estimated input for one prepared request (spec §2 Data Models)."""

    model_config = _STRICT

    input_tokens: int = Field(..., ge=0)
    method: str
    quality: EstimateQuality
    request_fingerprint: str
    qualification_id: Optional[str] = None


class BudgetUsage(BaseModel):
    """Normalized actual usage of one physical attempt; input already sums cache categories."""

    model_config = _STRICT

    input_tokens: int = Field(..., ge=0)
    output_tokens: int = Field(..., ge=0)
    details: Dict[str, int] = Field(default_factory=dict, description="Disjoint categories, inspection only")
    provider: str
    model: str
    route: str

    @computed_field  # type: ignore[misc]
    @property
    def total_tokens(self) -> int:
        """input + output; never re-add provider totals."""
        return self.input_tokens + self.output_tokens


class BudgetReservation(BaseModel):
    """One admitted attempt's allocation (spec §2.2)."""

    model_config = _STRICT

    reservation_id: str
    operation_id: str
    call_id: str
    round_number: int = Field(..., ge=0)
    attempt_number: int = Field(..., ge=1)
    phase: ReservationPhase
    input_allowance: int = Field(..., ge=0)
    output_cap: int = Field(..., ge=0)
    request_fingerprint: str

    @computed_field  # type: ignore[misc]
    @property
    def total(self) -> int:
        """Reserved I + O."""
        return self.input_allowance + self.output_cap


class BudgetReport(BaseModel):
    """Informational snapshot of one operation's accounting (spec §2.3 flags)."""

    model_config = _STRICT

    operation_id: str
    policy: TokenBudgetPolicy
    state: OperationState
    revision: int = Field(..., ge=0)
    input_tokens: int = Field(..., ge=0)
    output_tokens: int = Field(..., ge=0)
    total_tokens: int = Field(..., ge=0)
    in_flight_tokens: int = Field(..., ge=0)
    uncertain_tokens: int = Field(..., ge=0)
    remaining_work_tokens: int = Field(..., ge=0)
    remaining_total_tokens: int = Field(..., ge=0)
    counting_methods: tuple[str, ...] = ()
    settled_estimate_input_tokens: int = Field(0, ge=0)
    """Sum of admission estimates for SETTLED reservations only.

    ``settled_estimate_input_tokens - input_tokens`` is the estimation error of
    ``budget_mode="estimated"``: both sides describe the same requests.
    Released reservations are excluded on purpose — ``release_unspent`` means
    the request was proven never dispatched (parrot/clients/budget.py:244), so
    its estimate has no provider counterpart and would manufacture error out of
    a request that never happened (spec §10 R5).
    """
    released_estimate_tokens: int = Field(0, ge=0)
    """Estimates of released reservations. An operational counter, NEVER part
    of the calibration comparison above."""
    overrun_tokens: int = Field(0, ge=0)
    accounting_complete: bool
    budget_exhausted: bool
    finalization_attempted: bool
    finalized: bool
    answer_complete: bool
    terminal_reason: Optional[str] = None


class BudgetSnapshot(BaseModel):
    """Trusted, versioned transfer record exported only at quiescent suspension (spec §2.6)."""

    model_config = _STRICT

    schema_version: Literal[1] = 1
    operation_id: str
    policy: TokenBudgetPolicy
    settled_input_tokens: int = Field(..., ge=0)
    settled_output_tokens: int = Field(..., ge=0)
    revision: int = Field(..., ge=0)
    consumed_floor: int = Field(..., ge=0)
    resume_nonce: str
    attempt_count: int = Field(..., ge=0)
    round_count: int = Field(..., ge=0)
    owner_call_id: Optional[str] = None
    suspended_metadata: Dict[str, Any] = Field(default_factory=dict)


__all__ = [
    "BudgetMode",
    "EstimateQuality",
    "ReservationPhase",
    "OperationState",
    "TokenBudgetPolicy",
    "TokenEstimate",
    "BudgetUsage",
    "BudgetReservation",
    "BudgetReport",
    "BudgetSnapshot",
]
