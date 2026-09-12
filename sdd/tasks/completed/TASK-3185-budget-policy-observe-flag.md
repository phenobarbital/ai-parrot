# TASK-3185: Add `enforcement` to TokenBudgetPolicy and estimate fields to BudgetReport

**Feature**: FEAT-554 — Empirical Token-Budget Sizing for sdd-coder Bedrock Seats
**Spec**: `sdd/specs/sdd-coder-bedrock-token-telemetry.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 1, first half. Everything else in FEAT-554 rests on two additive
model changes: a policy flag that selects a non-enforcing ledger, and report
fields that make the *settled* admission estimate observable.

Both are pure Pydantic changes with no behavioural code, which is why they are
their own task: TASK-3186 (ledger semantics) and TASK-3187 (funnel branch) both
import these names, and splitting them means those two tasks never race on this
file.

---

## Scope

- Add `enforcement: Literal["enforce", "observe"] = "enforce"` to `TokenBudgetPolicy`.
- Add `settled_estimate_input_tokens: int` and `released_estimate_tokens: int`
  to `BudgetReport`, both with defaults.
- Write unit tests for the defaults and for backward compatibility of both models.

**NOT in scope**: any ledger behaviour (TASK-3186), the funnel branch
(TASK-3187), populating the new report fields (TASK-3186). This task only makes
the fields exist and default correctly.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/models/token_budget.py` | MODIFY | Add the policy flag and the three report fields |
| `packages/ai-parrot/tests/unit/clients/test_token_budget.py` | MODIFY | Add defaults + backward-compat tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.models.token_budget import TokenBudgetPolicy, BudgetReport, TokenEstimate  # verified: parrot/models/token_budget.py:25,110,57
```
`Literal` is already imported in this module (it types `BudgetMode`); confirm with
`grep -n "^from typing" packages/ai-parrot/src/parrot/models/token_budget.py` before adding an import.

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/models/token_budget.py
class TokenBudgetPolicy(BaseModel):                                   # line 25
    token_budget: int = Field(..., ge=0, description="Cumulative ceiling B; 0 admits no inference")  # line 30
    budget_mode: BudgetMode = "estimated"                             # line 31
    final_answer_reserve: int | float = Field(0.15, description="int = absolute tokens; float = fraction of B")  # line 32
    @model_validator(mode="after")
    def _validate_reserve(self) -> "TokenBudgetPolicy": ...           # line 35
    @property
    def final_reserve_tokens(self) -> int: ...                        # line 49

class BudgetReport(BaseModel):                                        # line 110
    counting_methods: tuple[str, ...] = ()                            # line 126
    overrun_tokens: int = Field(0, ge=0)                              # line 127
    accounting_complete: bool                                         # line 128
    terminal_reason: Optional[str] = None                             # line 133
```

### Does NOT Exist
- ~~`TokenBudgetPolicy.enforcement`~~ — this task adds it. Today every ledger enforces.
- ~~`BudgetReport.estimated_input_tokens`~~ — never exists in any version. The name is
  `settled_estimate_input_tokens`; an undifferentiated total would fabricate estimation
  error out of released reservations (spec §10 R5).
- ~~`BudgetReport.estimate_quality`~~ / ~~`TokenEstimate.settled`~~ — not real attributes.
- ~~`BudgetReport.estimate_methods`~~ — deliberately NOT added: `reserve()` already
  feeds every `estimate.method` into `_counting_methods` (`parrot/clients/budget.py:128`),
  so the existing `counting_methods` field already answers this. Do not add a second one.
- ~~`EnforcementMode`~~ — no such type alias; use the inline `Literal`.

---

## Implementation Notes

### Key Constraints
- **Additive only.** Every new field carries a default, so a `BudgetReport`
  or `TokenBudgetPolicy` constructed by pre-FEAT-554 code (and every persisted
  payload) still validates. This is the same compatibility rule
  `session_state.DispatchCompleted` documents at `session_state.py:479`.
- Do NOT touch `_validate_reserve` or `final_reserve_tokens`.
- Docstrings must say *why*, not just what — these fields exist to prevent a
  specific accounting error, and the next reader needs that.

### References in Codebase
- `packages/ai-parrot/src/parrot/flows/dev_loop/session_state.py:476-486` — the
  optional-field-with-default compatibility pattern to mirror.
- `packages/ai-parrot/tests/unit/clients/test_token_budget.py` — existing ledger tests.

---

## Implementation Blueprint

### Steps (in order)
1. Add the `enforcement` field to `TokenBudgetPolicy` below `final_answer_reserve` — *why*: it belongs with the other admission-shaping fields, and `_validate_reserve` (a model validator below it) must keep running unchanged.
2. Add the three fields to `BudgetReport` immediately after `counting_methods` — *why*: they are counting metadata, so they read next to the methods that produced them.
3. Add the tests — *why*: AC-5 requires backward compatibility to be proven, not assumed.

### `packages/ai-parrot/src/parrot/models/token_budget.py` (MODIFY — policy)
```python
# occurrences: 1 (verified: grep -c '    final_answer_reserve: int | float = Field(0.15' packages/ai-parrot/src/parrot/models/token_budget.py)
# AFTER — insert below `    final_answer_reserve: int | float = Field(0.15, description="int = absolute tokens; float = fraction of B")` (verified: packages/ai-parrot/src/parrot/models/token_budget.py:32)
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
```
**Why this shape**: The flag is orthogonal to `budget_mode` (which selects *how* input is counted, estimated vs strict) — it selects *whether* the count can deny. Keeping them separate is what lets observational mode still use `budget_mode="estimated"`, which is all Mantle qualifies for (`amazon/budget.py:326-330`). Do not collapse the two into one enum, and do not make `"observe"` the default.

### `packages/ai-parrot/src/parrot/models/token_budget.py` (MODIFY — report)
```python
# occurrences: 1 (verified: grep -c '    counting_methods: tuple[str, ...] = ()' packages/ai-parrot/src/parrot/models/token_budget.py)
# AFTER — insert below `    counting_methods: tuple[str, ...] = ()` (verified: packages/ai-parrot/src/parrot/models/token_budget.py:126)
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
```
**Why**: Splitting settled from released is the whole point of the field — an undifferentiated "estimated input" total was this spec's v0.1 mistake and would have made every calibration number wrong in the same direction. There is deliberately **no** `estimate_methods` field: `reserve()` already does `self._counting_methods.add(estimate.method)` (verified: `parrot/clients/budget.py:128`), so the existing `BudgetReport.counting_methods` *is* the set of estimate methods. Adding a second field would be duplicate state that can drift.

### FILL IN checklist
*(none — this task is fully determined; if you find yourself needing a decision, the design is wrong and belongs back in the spec)*

---

## Acceptance Criteria

- [ ] `TokenBudgetPolicy(token_budget=1).enforcement == "enforce"`.
- [ ] `TokenBudgetPolicy(token_budget=1, enforcement="observe")` validates; any other string raises `ValidationError`.
- [ ] A `BudgetReport` built from the exact kwargs `_report_locked` passes today (no new fields) validates, with `settled_estimate_input_tokens == 0` and `released_estimate_tokens == 0`.
- [ ] `_validate_reserve` and `final_reserve_tokens` behave exactly as before (existing tests untouched and passing).
- [ ] All tests pass: `pytest packages/ai-parrot/tests/unit/clients/test_token_budget.py -v`
- [ ] The pre-existing FEAT-550 suite passes unmodified (AC-23): `pytest packages/ai-parrot/tests/integration/test_question_token_budget.py packages/ai-parrot-client-amazon/tests/unit/test_token_budget_mantle.py -q`
- [ ] No linting errors: `ruff check packages/ai-parrot/src/parrot/models/token_budget.py`

---

## Test Specification

```python
# packages/ai-parrot/tests/unit/clients/test_token_budget.py  (append)
import pytest
from pydantic import ValidationError

from parrot.models.token_budget import BudgetReport, TokenBudgetPolicy


class TestEnforcementFlag:
    def test_defaults_to_enforce(self):
        assert TokenBudgetPolicy(token_budget=1000).enforcement == "enforce"

    def test_observe_is_accepted(self):
        assert TokenBudgetPolicy(token_budget=1000, enforcement="observe").enforcement == "observe"

    def test_unknown_mode_rejected(self):
        with pytest.raises(ValidationError):
            TokenBudgetPolicy(token_budget=1000, enforcement="advisory")


class TestReportEstimateFields:
    def test_defaults_when_absent(self):
        # FILL IN: build a BudgetReport with exactly the kwargs _report_locked
        # passes today (parrot/clients/budget.py:340-358) and assert the three
        # new fields default — bounded by AC: "a report built without the new
        # fields still validates"
        raise NotImplementedError
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above — §3 Module 1 and §10 R5.
2. **Check dependencies** — none.
3. **Verify the Codebase Contract** — confirm the anchor lines and the `typing` imports before editing.
4. **Update status** in `sdd/tasks/index/sdd-coder-bedrock-token-telemetry.json` → `"in-progress"`.
5. **Implement** from the blueprint; change no signature or field name it fixes.
6. **Verify** all acceptance criteria.
7. **Move this file** to `sdd/tasks/completed/TASK-3185-budget-policy-observe-flag.md`.
8. **Update index** → `"done"`.
9. **Fill in the Completion Note** below.

---

## Completion Note

**Completed by**: sdd-coder (qwen seat) via parrot-sdd-coder orchestrator, merged by sdd-worker
**Date**: 2026-09-12
**Notes**: Added `enforcement: Literal["enforce", "observe"] = "enforce"` to
`TokenBudgetPolicy` and `settled_estimate_input_tokens` /
`released_estimate_tokens` to `BudgetReport`, both additive with defaults
that preserve every existing FEAT-550 consumer. All 29 tests in
`test_token_budget.py` pass, plus the pre-existing FEAT-550 regression
suites (`test_question_token_budget.py`, `test_token_budget_mantle.py`, 30
tests total) pass unmodified. `ruff check` clean.

**Deviations from spec**: none

Seat: qwen · Backend: nova · Model: qwen.qwen3-coder-480b-a35b-instruct · Attempts: 1 · Duration: 89.9s · Tokens: 538483/3468
