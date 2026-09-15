# TASK-3132: Token Budget Pydantic Records, Typed Errors and `InvokeResult.budget_report`

**Feature**: FEAT-550 — Cumulative Question Token Budgets for Bedrock and Mantle
**Spec**: `sdd/specs/token-budget-bedrock.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Module 1 (spec §3 "Module 1: Models and Atomic Ledger") is split in two. This task
ships every **immutable record** the whole feature shares (spec §2 "Data Models"),
the `BudgetError` family (spec §2 "Data Models", error table) and the one optional
field `InvokeResult.budget_report` (spec §2.3). TASK-3133 builds the mutable
`QuestionBudget` ledger on top of these records.

Errors live in `parrot.core.exceptions` (not in the models module) to avoid a
model/base-class import cycle (spec §2 "New Public Interfaces").

---

## Scope

- Implement `packages/ai-parrot/src/parrot/models/token_budget.py` with the six
  Pydantic records: `TokenBudgetPolicy`, `TokenEstimate`, `BudgetUsage`,
  `BudgetReservation`, `BudgetReport`, `BudgetSnapshot` — all `frozen=True`,
  `extra="forbid"`, `strict=True` numerics.
- Implement `TokenBudgetPolicy` validation exactly per spec §2.1: reject
  `bool`/`str`/negative/non-integral `token_budget`; reserve is an `int` in
  `[0, B]` or a finite `float` in `[0, 1]`; `final_reserve_tokens` computed as
  `floor(B * fraction)` via `decimal` string arithmetic; integer `1` = one token,
  `1.0` = whole budget; zero disables finalization.
- Add the `BudgetError` hierarchy (8 subclasses with stable `code`) to
  `packages/ai-parrot/src/parrot/core/exceptions.py`.
- Add `budget_report: Optional[Dict[str, Any]] = None` to `InvokeResult`.
- Write the "Policy validation" unit-test group (spec §4) in
  `packages/ai-parrot/tests/unit/clients/test_token_budget.py`.

**NOT in scope**: the mutable ledger (`QuestionBudget`, TASK-3133), scope/registry
(TASK-3134), any client/bot edit, the `parrot.clients.budget` re-export module
(TASK-3133 creates it).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/models/token_budget.py` | CREATE | Six immutable Pydantic records + policy validation |
| `packages/ai-parrot/src/parrot/core/exceptions.py` | MODIFY | `BudgetError` + 8 typed subclasses |
| `packages/ai-parrot/src/parrot/models/responses.py` | MODIFY | Optional `InvokeResult.budget_report` field |
| `packages/ai-parrot/tests/unit/clients/test_token_budget.py` | CREATE | Policy validation + record immutability tests (ledger tests appended by TASK-3133) |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: Verified against dev `755c61347` on 2026-09-11. Use these exact
> imports/signatures; verify anything else with `grep` before using it.

### Verified Imports
```python
from pydantic import BaseModel, Field, ConfigDict, model_validator  # verified: packages/ai-parrot/src/parrot/models/responses.py:7
from parrot.exceptions import ParrotError                           # verified: packages/ai-parrot/src/parrot/exceptions.py:12; already imported at core/exceptions.py:9
from parrot.models.responses import InvokeResult                    # verified: packages/ai-parrot/src/parrot/models/responses.py:1388
from parrot.models.basic import CompletionUsage                     # verified: packages/ai-parrot/src/parrot/models/basic.py:48
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/exceptions.py:12
class ParrotError(Exception):
    def __init__(self, message: Any, *args, **kwargs) -> None:   # line 26
        # sets self.message, self.stacktrace = kwargs.get('stacktrace'), self.args = kwargs

# packages/ai-parrot/src/parrot/core/exceptions.py:12  (42-line module; only class today)
class HumanInteractionInterrupt(ParrotError):
    def __init__(self, prompt: str, interaction_id: Optional[str] = None, policy_id: Optional[str] = None, *args, **kwargs)
    # last statement of the module, line 41: `        self.messages = None`

# packages/ai-parrot/src/parrot/models/responses.py:1388
class InvokeResult(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)
    output: Any                                # line 1407
    output_type: Optional[type] = None         # line 1410
    model: str                                 # line 1414
    usage: CompletionUsage                     # line 1417
    raw_response: Optional[Any] = Field(default=None, ...)   # line 1420 — LAST field today
```

### Does NOT Exist
- ~~`parrot.models.token_budget`~~ — this task creates it.
- ~~`parrot.clients.budget`~~, ~~`parrot.clients.budget_scope`~~ — created by TASK-3133 / TASK-3134.
- ~~`BudgetError`~~ and every subclass — created here; `grep -rn BudgetError packages/*/src` returns nothing today.
- ~~`InvokeResult.metadata`~~ — `InvokeResult` has no metadata dict; add the explicit `budget_report` field, never assign an undeclared attribute.
- ~~`CompletionUsage.cache_read_input_tokens`~~ — cache counters live only in `extra_usage`; `BudgetUsage` is a separate record and must not subclass `CompletionUsage`.
- ~~`parrot.exceptions.BudgetError`~~ — errors go in `parrot.core.exceptions`, not the top-level `parrot.exceptions` module.

---

## Implementation Notes

### Pattern to Follow
```python
# Immutable strict record — the style every record in this task uses
class TokenBudgetPolicy(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)
```

### Key Constraints
- `strict=True` makes Pydantic reject `True`/`"100"` for `int` fields automatically;
  still add explicit validators for negative values, NaN/inf floats and the
  `[0, B]` / `[0, 1]` reserve ranges (AC "Policy validation").
- Fraction resolution MUST use `decimal.Decimal(str(fraction)) * Decimal(B)` then
  `int(...)` (floor for nonnegative) — never binary float multiplication.
- Records other than `TokenBudgetPolicy` carry no business logic; they are wire/
  report shapes. `BudgetUsage.total_tokens` is a computed field = input + output.
- `BudgetReport` and `BudgetSnapshot` are distinct schemas (spec §2.6): a report is
  informational; a snapshot is an authority record with `schema_version=1`, nonce
  and floors. Do not make one inherit from the other.
- Every `BudgetError` carries `code: str`, `operation_id: Optional[str]`, and
  `report: Optional[BudgetReport]` as attributes; `code` is a class attribute so
  `except BudgetError as e: e.code` works without instantiation logic.

### References in Codebase
- `packages/ai-parrot/src/parrot/memory/compaction/models.py` — existing frozen Pydantic config style (ContextBudget).
- `packages/ai-parrot/src/parrot/exceptions.py` — `ParrotError` message/kwargs handling.

---

## Implementation Blueprint

### Steps (in order)
1. Create `models/token_budget.py` with the six records — *why*: every later task imports these shapes; signatures are fixed by spec §2 "Data Models".
2. Add the error hierarchy at the END of `core/exceptions.py` — *why*: `HumanInteractionInterrupt` stays first and untouched; errors must be importable without importing any client module.
3. Add `budget_report` to `InvokeResult` after `raw_response` — *why*: spec §2.3 requires an explicit optional field with default `None`, preserving every existing positional/keyword construction.
4. Write the policy-validation tests, then run `pytest packages/ai-parrot/tests/unit/clients/test_token_budget.py -q`.

### `packages/ai-parrot/src/parrot/models/token_budget.py` (CREATE)
```python
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
```
**Why this shape**: the spec fixes field names and semantics in §2 "Data Models"; `final_reserve_tokens` is the single place the 15% rule is resolved (AC "15% rounding"). `strict=True` implements "reject booleans, strings" for free; validators cover ranges. Cache categories are folded into `input_tokens` by the *adapter* (TASK-3139/3142) — `BudgetUsage` only stores the result plus `details` for inspection, so nothing here re-adds them.

### `packages/ai-parrot/src/parrot/models/token_budget.py` (CREATE, continued — same file, append below `BudgetReservation`)
```python
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
    "BudgetMode", "EstimateQuality", "ReservationPhase", "OperationState",
    "TokenBudgetPolicy", "TokenEstimate", "BudgetUsage", "BudgetReservation",
    "BudgetReport", "BudgetSnapshot",
]
```
**Why this shape**: `BudgetReport` carries every flag the outer boundary must expose (spec §2.3 `budget_exhausted` / `finalization_attempted` / `finalized` / `answer_complete`, plus `overrun_tokens` unclamped). `BudgetSnapshot` deliberately has **no** in-flight/uncertain fields — spec §2.6 says a snapshot exists only when there are none.

### `packages/ai-parrot/src/parrot/core/exceptions.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '        self.messages = None' packages/ai-parrot/src/parrot/core/exceptions.py)
# AFTER — append at end of module, below `        self.messages = None` (verified: core/exceptions.py:41)


class BudgetError(ParrotError):
    """Base for question-token-budget control errors (FEAT-550, spec §2 Data Models).

    Attributes:
        code: Stable machine-readable code (class attribute, overridden per subclass).
        operation_id: The ``budget_operation_id`` this error belongs to, if known.
        report: Optional serialized ``BudgetReport`` (a plain dict — no model import here).
    """

    code: str = "budget_error"

    def __init__(self, message: Any, *, operation_id: Optional[str] = None, report: Optional[dict] = None, **kwargs) -> None:
        super().__init__(message, **kwargs)
        self.operation_id = operation_id
        self.report = report


class BudgetExhausted(BudgetError):
    """Ordinary admission denied / forced termination — translated to a partial result at the bot boundary."""
    code = "budget_exhausted"


class BudgetUnsupported(BudgetError):
    """Provider/method/strict-combination cannot honour a requested or inherited budget."""
    code = "budget_unsupported"


class BudgetScopeConflict(BudgetError):
    """A child call tried to disable or replace the active question policy."""
    code = "budget_scope_conflict"


class BudgetStateMissing(BudgetError):
    """Resume without a live ledger or an admissible snapshot."""
    code = "budget_state_missing"


class BudgetResumeConflict(BudgetError):
    """Suspension nonce already consumed (duplicate/concurrent resume)."""
    code = "budget_resume_conflict"


class BudgetSnapshotInvalid(BudgetError):
    """Snapshot identity/policy/nonce/floor check failed."""
    code = "budget_snapshot_invalid"


class BudgetAccountingError(BudgetError):
    """Contradictory settlement, malformed usage, or strict reservation violation."""
    code = "budget_accounting_error"


class BudgetRegistryFull(BudgetError):
    """Registry retention capacity exhausted; call ``release()`` first."""
    code = "budget_registry_full"
```
**Why**: spec §2 fixes these eight codes; `report` is typed as `dict` here so `parrot.core.exceptions` never imports `parrot.models` (cycle guard, spec §2 "New Public Interfaces"). `Optional`/`Any` are already imported at line 8 — extend that import to `from typing import Any, Optional`.

### `packages/ai-parrot/src/parrot/models/responses.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '    raw_response: Optional[Any] = Field(' packages/ai-parrot/src/parrot/models/responses.py)
# AFTER — insert below the closing `)` of the `raw_response` Field (verified: responses.py:1420-1423)
    budget_report: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Serialized BudgetReport when a question token budget was active (FEAT-550); None otherwise",
    )
```
**Why**: spec §2.3 — "`InvokeResult` gains an optional `budget_report` field with default `None`". A dict (not the model) keeps `parrot.models.responses` free of a `token_budget` import and matches `AIMessage.metadata["token_budget"]`, which is also a serialized dict. `Dict`/`Any`/`Optional` are already imported at line 1.

### `packages/ai-parrot/tests/unit/clients/test_token_budget.py` (CREATE)
```python
"""FEAT-550 M1 — policy validation and record semantics (spec §4 'Policy validation')."""
from __future__ import annotations

import math

import pytest
from pydantic import ValidationError

from parrot.core.exceptions import BudgetError, BudgetExhausted, BudgetRegistryFull
from parrot.models.responses import InvokeResult
from parrot.models.basic import CompletionUsage
from parrot.models.token_budget import BudgetUsage, TokenBudgetPolicy


class TestTokenBudgetPolicy:
    @pytest.mark.parametrize("bad", [True, "100", -1, 10.5, float("nan")])
    def test_rejects_invalid_budget(self, bad):
        with pytest.raises(ValidationError):
            TokenBudgetPolicy(token_budget=bad)

    def test_default_fraction_rounds_down(self):
        # FILL IN: assert TokenBudgetPolicy(token_budget=10_000).final_reserve_tokens == 1_500
        #          and token_budget=999 -> 149 (floor), bounded by spec §2.1 "F = floor(B * fraction)"
        raise NotImplementedError

    def test_int_one_is_one_token_and_float_one_is_whole_budget(self):
        # FILL IN: reserve 1 -> 1 token; reserve 1.0 -> == token_budget
        raise NotImplementedError

    @pytest.mark.parametrize("bad", [-0.1, 1.5, math.inf, 10_001])
    def test_rejects_out_of_range_reserve(self, bad):
        with pytest.raises(ValidationError):
            TokenBudgetPolicy(token_budget=10_000, final_answer_reserve=bad)

    def test_zero_reserve_disables_finalization(self):
        # FILL IN: final_reserve_tokens == 0 for reserve 0 and for reserve 0.0
        raise NotImplementedError

    def test_policy_is_frozen_and_forbids_extra(self):
        # FILL IN: assignment raises; unknown field raises ValidationError
        raise NotImplementedError


class TestRecords:
    def test_budget_usage_total_is_input_plus_output(self):
        # FILL IN: BudgetUsage(input_tokens=950, output_tokens=50, ...).total_tokens == 1000
        raise NotImplementedError

    def test_errors_have_stable_codes(self):
        assert BudgetExhausted("x").code == "budget_exhausted"
        assert issubclass(BudgetRegistryFull, BudgetError)
        # FILL IN: assert all eight codes from spec §2 Data Models

    def test_invoke_result_budget_report_defaults_none(self):
        res = InvokeResult(output="x", model="m", usage=CompletionUsage())
        assert res.budget_report is None
```
**Why this shape**: mirrors spec §4 "Policy validation" row exactly; the test bodies that need specific arithmetic are left as `FILL IN` with the bound named.

### FILL IN checklist
- [ ] `test_token_budget.py::TestTokenBudgetPolicy.test_default_fraction_rounds_down` — floor arithmetic assertions; bounded by spec §2.1 decimal rule
- [ ] `test_token_budget.py::TestTokenBudgetPolicy.test_int_one_is_one_token_and_float_one_is_whole_budget` — spec §2.1 "`1` means one token, `1.0` whole budget"
- [ ] `test_token_budget.py::TestTokenBudgetPolicy.test_zero_reserve_disables_finalization` — spec §2.1 "Zero disables finalization"
- [ ] `test_token_budget.py::TestTokenBudgetPolicy.test_policy_is_frozen_and_forbids_extra` — spec §2 "immutable … `extra='forbid'`"
- [ ] `test_token_budget.py::TestRecords.*` — remaining assertions; bounded by spec §2 Data Models table

---

## Acceptance Criteria

- [ ] `from parrot.models.token_budget import TokenBudgetPolicy, TokenEstimate, BudgetUsage, BudgetReservation, BudgetReport, BudgetSnapshot` works
- [ ] `from parrot.core.exceptions import BudgetError, BudgetExhausted, BudgetUnsupported, BudgetScopeConflict, BudgetStateMissing, BudgetResumeConflict, BudgetSnapshotInvalid, BudgetAccountingError, BudgetRegistryFull` works and each `code` matches spec §2
- [ ] `TokenBudgetPolicy(token_budget=10_000).final_reserve_tokens == 1500`; bool/str/negative/NaN/inf rejected
- [ ] `InvokeResult(...)` without `budget_report` still constructs; field defaults to `None`
- [ ] `pytest packages/ai-parrot/tests/unit/clients/test_token_budget.py -v` passes
- [ ] Existing suites untouched: `pytest packages/ai-parrot/tests/unit/clients -q` still passes
- [ ] `ruff check packages/ai-parrot/src/parrot/models/token_budget.py packages/ai-parrot/src/parrot/core/exceptions.py` clean

---

## Test Specification

See the CREATE block above — it is the scaffold. Add a parametrized case proving
`TokenBudgetPolicy(token_budget=0)` is valid (zero admits no inference) and that
`final_answer_reserve=0` on `token_budget=0` is valid.

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context (§2 Data Models, §2.1, §2.3)
2. **Check dependencies** — none
3. **Verify the Codebase Contract** — `grep -n "self.messages = None" packages/ai-parrot/src/parrot/core/exceptions.py` and `grep -n "raw_response" packages/ai-parrot/src/parrot/models/responses.py` before editing
4. **Update status** in `sdd/tasks/index/token-budget-bedrock.json` → `"in-progress"`
5. **Implement** from the Blueprint; do not rename any record or field
6. **Verify** all acceptance criteria
7. **Move this file** to `sdd/tasks/completed/TASK-3132-token-budget-models-and-errors.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: sdd-worker orchestrator (parrot-sdd-coder pool: qwen attempt 1 timed out, gemini attempt 2 succeeded)
**Date**: 2026-09-11
**Notes**: Implemented the six immutable Pydantic records (`TokenBudgetPolicy`,
`TokenEstimate`, `BudgetUsage`, `BudgetReservation`, `BudgetReport`,
`BudgetSnapshot`) in `parrot/models/token_budget.py` with strict validation and
decimal-string arithmetic for `final_reserve_tokens` rounding. Added the
`BudgetError` hierarchy (8 typed subclasses) to `parrot/core/exceptions.py`.
Added the optional `budget_report` field (default `None`) to `InvokeResult` in
`parrot/models/responses.py`. All acceptance criteria verified in the
orchestrator worktree: imports resolve, `TokenBudgetPolicy(token_budget=10_000
).final_reserve_tokens == 1500`, `InvokeResult` constructs without
`budget_report`, `pytest packages/ai-parrot/tests/unit/clients/test_token_budget.py
-v` → 14 passed, `pytest packages/ai-parrot/tests/unit/clients -q` → 359 passed /
1 pre-existing failure unrelated to this task (`test_client_class_attrs[google]`,
confirmed failing on `dev` HEAD before this change too), `ruff check` clean on
both touched files.

**Deviations from spec**: none

Seat: qwen (attempt 1, timed out after 553.9s) → gemini (attempt 2, succeeded) · Backend: nova → google-compat · Model: qwen.qwen3-coder-480b-a35b-instruct → gemini-3.5-flash · Attempts: 2 · Duration: 635.65s · Tokens: 651315 in / 6543 out
