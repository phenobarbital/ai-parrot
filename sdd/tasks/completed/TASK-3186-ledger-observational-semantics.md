# TASK-3186: Observational reserve semantics and settled-estimate reporting

**Feature**: FEAT-554 — Empirical Token-Budget Sizing for sdd-coder Bedrock Seats
**Spec**: `sdd/specs/sdd-coder-bedrock-token-telemetry.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-3185
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 1, second half, and the resolution of §10 R1. `QuestionBudget`
today always enforces: `reserve()` computes
`output_cap = min(max_output_tokens, available - estimate.input_tokens)`
(`budget.py:147`), so accumulated consumption alone can shrink a caller's output
cap, and a depleted ledger denies work. FEAT-554 needs a ledger that counts a
40-60 turn coding loop without ever changing what that loop sends.

Under `enforcement="observe"` this task makes admission unconditional and the
cap pass-through, and reports the *settled* estimate total so estimation error
becomes computable.

---

## Scope

- In `reserve()`, when `self._policy.enforcement == "observe"`: skip the
  availability computation and every denial branch, and build the
  `BudgetReservation` with `output_cap = max_output_tokens` verbatim.
- In `_report_locked()`, derive and report `settled_estimate_input_tokens` and
  `released_estimate_tokens` from `self._attempts.values()`.
- Write unit tests for both, plus a regression test that `enforce` is untouched.

**NOT in scope**: the funnel's SDK-view branch (TASK-3187), any change to
`settle()`, `mark_uncertain()`, `release_unspent()`, `close()` or the snapshot
API, and any new mutable counter (the totals are derived).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/clients/budget.py` | MODIFY | Observational branch in `reserve()`; derived totals in `_report_locked()` |
| `packages/ai-parrot/tests/unit/clients/test_token_budget.py` | MODIFY | Observational + derivation + enforce-regression tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.models.token_budget import (  # verified: parrot/models/token_budget.py:25,57,88,110
    TokenBudgetPolicy, TokenEstimate, BudgetReservation, BudgetReport,
)
```
All of these are already imported at the top of `budget.py` (verified: `budget.py:24-34`) — add nothing.

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/clients/budget.py
@dataclass
class _Attempt:                                                       # line ~39
    reservation: BudgetReservation                                    # line 42
    status: AttemptStatus = "reserved"                                # line 43
    usage: Optional[BudgetUsage] = None                               # line 44
    reason: Optional[str] = None                                      # line 45

class QuestionBudget:
    self._attempts: dict[str, _Attempt] = {}                          # line 61
    self._counting_methods: set[str] = set()                          # line 67
    def _consumed(self) -> int: ...                                   # line 101
    def _available(self, phase: ReservationPhase) -> int: ...         # line 110
    async def reserve(self, estimate: TokenEstimate, *, max_output_tokens: int,
                      min_output_tokens: int, call_id: str, round_number: int,
                      attempt_number: int, phase: ReservationPhase
                      ) -> BudgetReservation:                          # line 115
        self._counting_methods.add(estimate.method)                   # line 128
        available = self._available(phase)                            # line 146
        output_cap = min(max_output_tokens, available - estimate.input_tokens)  # line 147
        #   input_allowance=estimate.input_tokens                      # line 165
        #   self._attempts[reservation.reservation_id] = _Attempt(reservation)  # line 169
    async def settle(self, reservation_id, usage: BudgetUsage) -> None: ...    # line 183
    async def release_unspent(self, reservation_id: str) -> None: ...  # line 244
    def _report_locked(self) -> BudgetReport: ...                      # line 327
        #   counting_methods=tuple(self._counting_methods),            # line 352

# packages/ai-parrot/src/parrot/models/token_budget.py
class BudgetReservation(BaseModel):
    input_allowance: int = Field(..., ge=0)   # == estimate.input_tokens  # line 99
    output_cap: int = Field(..., ge=0)                                  # line 100
```

### Does NOT Exist
- ~~`QuestionBudget._settled_estimate`~~ / ~~`self._released_estimate`~~ — do NOT add
  counters. Both totals are derived from `self._attempts.values()`: each `_Attempt`
  already holds `reservation.input_allowance` (the estimate) and its `status`.
- ~~`QuestionBudget.observe()`~~ / ~~`QuestionBudget.set_enforcement()`~~ — the mode
  comes from the immutable policy, never from a setter.
- ~~`AttemptStatus.ESTIMATED`~~ — the statuses are the existing `"reserved"`,
  `"settled"`, `"uncertain"`, `"released"` literals.
- ~~`BudgetReport.estimate_methods`~~ — not added; `counting_methods` already holds them.

---

## Implementation Notes

### Key Constraints
- `enforcement="observe"` must not reach ANY `raise` in `reserve()`, must not
  call `_available()`, and must not transition `self._state`.
- `self._counting_methods.add(estimate.method)` (line 128) runs in **both**
  modes — the analysis needs the method even when nothing is enforced.
- Keep incrementing `self._revision` exactly as today so snapshot/resume
  semantics are unchanged.
- Derive, never accumulate: a counter updated in `settle()` and
  `release_unspent()` would be a second source of truth that can drift from
  `self._attempts`.

### References in Codebase
- `packages/ai-parrot/src/parrot/clients/budget.py:335` — `accounting_complete`
  already derives from `self._attempts.values()`; mirror that style exactly.

---

## Implementation Blueprint

### Steps (in order)
1. Read `reserve()` end to end (lines 115-182) before touching it — *why*: the denial branches interleave with state transitions, and the observational path has to skip all of them without skipping the bookkeeping (`_counting_methods`, `_attempts`, `_revision`).
2. Insert the observational short-circuit after the `_counting_methods.add(...)` line and before the first denial branch — *why*: the method must be recorded in both modes, but nothing after it may deny in observe mode.
3. Add the two derived totals to `_report_locked()`'s return — *why*: a report is the only way the dispatcher reads the ledger, and AC-5 compares these against `input_tokens`.
4. Write the enforce-regression test first, then the observe tests — *why*: the risk in this task is breaking enforcement, not failing to add observation.

### `packages/ai-parrot/src/parrot/clients/budget.py` (MODIFY — reserve)
```python
# occurrences: 1 (verified: grep -c '            self._counting_methods.add(estimate.method)' packages/ai-parrot/src/parrot/clients/budget.py)
# AFTER — insert below `            self._counting_methods.add(estimate.method)` (verified: packages/ai-parrot/src/parrot/clients/budget.py:128)
            if self._policy.enforcement == "observe":
                # Observational ledger: account, never refuse, never resize.
                # Deliberately does NOT consult `_available()` (line 146) nor
                # compute `min(max_output_tokens, available - estimate.input_tokens)`
                # (line 147) — a measurement must not change the request it
                # measures (spec §2, §10 R1).
                self._revision += 1
                # FILL IN: build and register the reservation exactly as the
                # enforcing path does at lines 156-169 — same reservation_id
                # scheme, same `input_allowance=estimate.input_tokens`,
                # `output_cap=max_output_tokens` verbatim, then
                # `self._attempts[...] = _Attempt(reservation)` — and return it.
                # Bounded by: no state transition, no raise, no `_available()`
                # call on this path (AC-3).
                raise NotImplementedError
```
**Why this shape**: The short-circuit sits *after* `_counting_methods.add` so the estimate method is recorded in both modes, and *before* every denial branch so observation can never refuse. It is deliberately a separate early return rather than conditionals sprinkled through the enforcing path: the enforcing logic is FEAT-550's contract and must read exactly as it does today (AC-23). `min_output_tokens` is intentionally ignored here — it exists to decide whether a shrunken cap is still usable, and no cap is ever shrunk in this mode.

### `packages/ai-parrot/src/parrot/clients/budget.py` (MODIFY — report)
```python
# occurrences: 1 (verified: grep -c '            counting_methods=tuple(self._counting_methods),' packages/ai-parrot/src/parrot/clients/budget.py)
# AFTER — insert below `            counting_methods=tuple(self._counting_methods),` (verified: packages/ai-parrot/src/parrot/clients/budget.py:352)
            settled_estimate_input_tokens=sum(
                a.reservation.input_allowance for a in self._attempts.values() if a.status == "settled"
            ),
            released_estimate_tokens=sum(
                a.reservation.input_allowance for a in self._attempts.values() if a.status == "released"
            ),
```
**Why**: `input_allowance` *is* the admission estimate (`budget.py:165`), so the comparison against the report's provider-settled `input_tokens` describes the same requests. Only `"settled"` attempts qualify: a `"released"` reservation was proven never dispatched (`budget.py:244`) and an `"uncertain"` one has no confirmed usage, so counting either would fabricate estimation error (spec §10 R5). Derived inline rather than accumulated — `accounting_complete` two lines above already reads `self._attempts.values()` the same way, so there is nothing new to keep in sync.

### FILL IN checklist
- [ ] `budget.py::QuestionBudget.reserve` observational branch — build/register/return the reservation mirroring lines 156-169; bounded by "no raise, no state transition, no `_available()` call, `output_cap == max_output_tokens`" (AC-3)

---

## Acceptance Criteria

- [ ] With `enforcement="observe"` and `token_budget=1`, ten successive `reserve(...)` calls each return `output_cap == max_output_tokens` and none raises.
- [ ] With `enforcement="observe"`, `reserve()` never calls `_available()` (assert via monkeypatching it to raise).
- [ ] With `enforcement="observe"`, the ledger's `state` stays `"active"` through a reserve/settle cycle that far exceeds `token_budget`.
- [ ] `settled_estimate_input_tokens` counts settled reservations only; a released reservation's estimate appears in `released_estimate_tokens` and in neither total twice; an uncertain one appears in neither.
- [ ] `counting_methods` is populated in observational mode too.
- [ ] `enforcement="enforce"` behaviour is byte-identical: `pytest packages/ai-parrot/tests/unit/clients/test_token_budget.py -v` passes with no existing test modified.
- [ ] AC-23 holds: `pytest packages/ai-parrot/tests/integration/test_question_token_budget.py packages/ai-parrot-client-amazon/tests/unit/test_token_budget_mantle.py -q`
- [ ] No linting errors: `ruff check packages/ai-parrot/src/parrot/clients/budget.py`

---

## Test Specification

```python
# packages/ai-parrot/tests/unit/clients/test_token_budget.py  (append)
import pytest

from parrot.clients.budget import QuestionBudget
from parrot.models.token_budget import TokenBudgetPolicy, TokenEstimate


def _estimate(n: int = 5000, method: str = "tiktoken:o200k_base") -> TokenEstimate:
    return TokenEstimate(input_tokens=n, method=method, quality="estimated", request_fingerprint="fp")


@pytest.fixture
def observing_ledger() -> QuestionBudget:
    """A ledger whose ceiling is absurdly below demand, in observe mode."""
    return QuestionBudget(TokenBudgetPolicy(token_budget=1, enforcement="observe"), "op-observe")


class TestObservationalReserve:
    async def test_never_denies_and_preserves_cap(self, observing_ledger):
        for round_no in range(1, 11):
            res = await observing_ledger.reserve(
                _estimate(), max_output_tokens=8192, min_output_tokens=1,
                call_id="c1", round_number=round_no, attempt_number=1, phase="work",
            )
            assert res.output_cap == 8192

    async def test_does_not_consult_available(self, observing_ledger, monkeypatch):
        # FILL IN: monkeypatch QuestionBudget._available to raise, then assert a
        # reserve() still succeeds — bounded by AC "never calls _available()"
        raise NotImplementedError

    async def test_state_stays_active_past_the_ceiling(self, observing_ledger):
        # FILL IN: reserve + settle usage far above token_budget, then assert
        # (await observing_ledger.report()).state == "active"
        raise NotImplementedError


class TestSettledEstimateReporting:
    async def test_released_excluded_from_calibration(self):
        # FILL IN: one settled reservation (estimate=100, usage=100) and one
        # released (estimate=1000); assert settled_estimate_input_tokens == 100,
        # released_estimate_tokens == 1000, input_tokens == 100 — the exact
        # scenario spec §10 R5 describes
        raise NotImplementedError

    async def test_uncertain_counted_in_neither(self):
        # FILL IN: mark_uncertain a reservation; assert it appears in neither
        # estimate total — bounded by AC "an uncertain one appears in neither"
        raise NotImplementedError
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** — §3 Module 1 and §10 R1/R5.
2. **Check dependencies** — TASK-3185 must be in `sdd/tasks/completed/`; `TokenBudgetPolicy.enforcement` must exist before you start.
3. **Verify the Codebase Contract** — re-read `reserve()` (115-182) and `_report_locked()` (327-359); the anchors must match.
4. **Update status** in `sdd/tasks/index/sdd-coder-bedrock-token-telemetry.json` → `"in-progress"`.
5. **Implement** from the blueprint; never change `reserve()`'s signature.
6. **Verify** all acceptance criteria, especially the enforce regression.
7. **Move this file** to `sdd/tasks/completed/TASK-3186-ledger-observational-semantics.md`.
8. **Update index** → `"done"`.
9. **Fill in the Completion Note** below.

---

## Completion Note

**Completed by**: sdd-coder (minimax seat) via parrot-sdd-coder orchestrator; fidelity violation and a test-assertion bug repaired by sdd-worker
**Date**: 2026-09-12
**Notes**: Added the `enforcement="observe"` branch to `QuestionBudget.reserve()`
(never consults `_available()`, returns `output_cap == max_output_tokens`
verbatim, `state` stays `"active"` past the ceiling) and the
`settled_estimate_input_tokens`/`released_estimate_tokens` derived totals
to `_report_locked()`. The first merge attempt was refused by the
orchestrator's fidelity gate (`dirty_task_worktree`): the coder left an
UNTRACKED scratch script (`packages/ai-parrot/test_observational.py`,
never committed) in its sub-worktree. sdd-worker deleted the stray file
(a working-tree cleanup, not a code change) and the merge succeeded on
retry. Verification then found one test-authoring bug in the coder's own
new test — `test_uncertain_counted_in_neither` asserted
`uncertain_tokens == 100` (input-only), but that pre-existing counter is
keyed on `.total` (input+output), per the established assertion elsewhere
in the same file; corrected to `r1.total`. All 34 tests in
`test_token_budget.py` pass, plus both FEAT-550 regression suites
(30 tests); `ruff check` clean.

**Deviations from spec**: none (fidelity cleanup + test-assertion fix, see note above)

Seat: minimax · Backend: nova · Model: minimax.minimax-m2.5 · Attempts: 1 · Duration: 289.1s · Tokens: 1752420/10468
