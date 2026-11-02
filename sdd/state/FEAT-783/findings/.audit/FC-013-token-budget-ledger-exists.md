---
id: FC-013
query_id: Q019
type: read
intent: "Read clients/budget.py - existing token budget accounting that the usage plane may subscribe to instead of duplicating."
executed_at: 2026-10-30T23:05:00Z
duration_ms: 400
parent_id: null
depth: 0
---

# FC-013 — A reservation-based token budget ledger (FEAT-550) already accounts tokens with estimate/settled/uncertain states

## Summary

`clients/budget.py` is the "Question token budget ledger and public feature entry point
(FEAT-550)" — a per-question reservation ledger with a four-state attempt lifecycle
(`reserved | settled | uncertain | released`) and nine dedicated exception types. Its model
layer, `parrot/models/token_budget.py`, defines `TokenBudgetPolicy`, `TokenEstimate`,
`BudgetUsage`, `BudgetReservation`, `BudgetReport`, `BudgetSnapshot`, `EstimateQuality`,
`OperationState`, `ReservationPhase`, `BudgetMode`. `BudgetReport` carries
`input_tokens`, `output_tokens`, `counting_methods`, `settled_estimate_input_tokens`
(whose docstring defines the estimation error as
`settled_estimate_input_tokens - input_tokens`) and `accounting_complete`.

These are precisely the `ledger_*` fields already projected into every sdd-coder attempt
row (FC-004, telemetry.py:194-201). So parrot has **two independent token accounts per
call** — the provider's reported counts and this estimate-vs-settled ledger — and the
telemetry row already records both plus a `calibration_eligible` flag that says when they
are comparable. The source's proposed "cross-check" (`source_cost_usd` vs the plane's
`usd`, with a 5% drift rule) has a working precedent here at the *token* level; it does
not need to be invented, only extended to cost.

## Citations

- path: `packages/ai-parrot/src/parrot/clients/budget.py`
  lines: 1
  symbol: `module docstring`
  excerpt: |
    """Question token budget ledger and public feature entry point (FEAT-550, spec §2.2/§2.3/§3 M1)."""

- path: `packages/ai-parrot/src/parrot/clients/budget.py`
  lines: 11-35
  symbol: `imports + AttemptStatus`
  excerpt: |
    from parrot.core.exceptions import (
        BudgetAccountingError, BudgetError, BudgetExhausted, BudgetRegistryFull,
        BudgetResumeConflict, BudgetScopeConflict, BudgetSnapshotInvalid,
        BudgetStateMissing, BudgetUnsupported, )
    from parrot.models.token_budget import (
        BudgetMode, BudgetReport, BudgetReservation, BudgetSnapshot, BudgetUsage,
        EstimateQuality, OperationState, ReservationPhase, TokenBudgetPolicy, TokenEstimate, )
    AttemptStatus = Literal["reserved", "settled", "uncertain", "released"]

- path: `packages/ai-parrot/src/parrot/models/token_budget.py`
  lines: 122-153
  symbol: `BudgetReport`
  excerpt: |
    class BudgetReport(BaseModel):
        input_tokens: int = Field(..., ge=0)
        output_tokens: int = Field(..., ge=0)
        counting_methods: tuple[str, ...] = ()
        settled_estimate_input_tokens: int = Field(0, ge=0)
        ``settled_estimate_input_tokens - input_tokens`` is the estimation error of
        accounting_complete: bool

- path: `packages/ai-parrot/src/parrot/clients/budget.py`
  lines: 223-236
  symbol: `settle`
  excerpt: |
    and attempt.usage.input_tokens == usage.input_tokens
    and attempt.usage.output_tokens == usage.output_tokens
    ...
    self._settled_input += usage.input_tokens
    self._settled_output += usage.output_tokens

- path: `packages/ai-parrot/src/parrot/clients/budget_scope.py`
  lines: 221-255
  symbol: `snapshot <-> report bridge`
  excerpt: |
    input_tokens=snapshot.settled_input_tokens,
    output_tokens=snapshot.settled_output_tokens,
    ...
    settled_input_tokens=report.input_tokens,
    settled_output_tokens=report.output_tokens,

## Notes

- Neither `BudgetUsage` nor `BudgetReport` has a cache-token field: the budget ledger is a
  two-counter model (`input_tokens`, `output_tokens`, `total_tokens` as their sum,
  token_budget.py:97). Extending the four-counter model therefore touches three layers —
  price table, budget models, telemetry row — not one.
- `counting_methods: tuple[str, ...]` already records *how* a number was obtained, which is
  the closest existing analogue to the source's per-seat `billed`/`subscription`/`estimate`
  policy, applied to tokens rather than money.
