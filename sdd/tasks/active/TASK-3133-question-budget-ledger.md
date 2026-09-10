# TASK-3133: `QuestionBudget` Atomic Ledger and `parrot.clients.budget` Entry Module

**Feature**: FEAT-550 — Cumulative Question Token Budgets for Bedrock and Mantle
**Spec**: `sdd/specs/token-budget-bedrock.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-3132
**Assigned-to**: unassigned

---

## Context

Second half of Module 1 (spec §3 "Module 1: Models and Atomic Ledger"). The
`QuestionBudget` is the single mutable ledger for one question on one event loop.
It implements the §2.2 arithmetic (`B`, `F`, `C`, `U`, `R`, `A_work`, `A_final`),
the exactly-once attempt state machine (`reserved -> settled | uncertain | released`),
the operation state machine (`active -> draining -> finalizing -> closed`, plus
`suspended`), and the one-owner finalization claim (§2.3).

`parrot.clients.budget` is also the **stable public entry point**: it re-exports the
records from `parrot.models.token_budget` and the errors from `parrot.core.exceptions`.

---

## Scope

- Implement `packages/ai-parrot/src/parrot/clients/budget.py` with `QuestionBudget`
  exactly per the spec §3 Module 1 interface skeleton (signatures are not negotiable).
- Implement §2.2 arithmetic under one `asyncio.Lock`; count/prepare/network happen
  outside the lock — the ledger only performs state transitions.
- Admission rule: `O = min(M, A - I)`, admit only when `O >= m`; reserve `I + O`
  atomically; `phase="final"` uses `A_final` and requires a prior successful
  `claim_finalization`; `phase="work"` uses `A_work`.
- Exactly-once: identical duplicate `settle` is inert; contradictory settle raises
  `BudgetAccountingError`; `uncertain -> settled` allowed once; `released` is terminal.
- Estimated-mode overrun: record full actual debit, `overrun_tokens = max(0, C - B)`
  unclamped; strict-mode violation → `BudgetAccountingError` and no further admission.
- Denial on `phase="work"` transitions `active -> draining` once and raises
  `BudgetExhausted` carrying the serialized report.
- Re-export records + errors; `__all__` lists everything an application needs.
- Append "Reservation arithmetic", "Exactly-once accounting", "Unknown outcomes"
  (ledger part) and "Concurrency" (ledger part) test groups to
  `packages/ai-parrot/tests/unit/clients/test_token_budget.py`.

**NOT in scope**: `BudgetScope`/`BudgetRegistry`/ContextVars (TASK-3134), suspension
nonce logic (TASK-3134), any provider counting or normalization (TASK-3139/3142).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/clients/budget.py` | CREATE | `QuestionBudget` ledger + public re-exports |
| `packages/ai-parrot/tests/unit/clients/test_token_budget.py` | MODIFY | Append ledger test groups |

---

## Codebase Contract (Anti-Hallucination)

> Verified against dev `755c61347` on 2026-09-11 plus TASK-3132's declared outputs.

### Verified Imports
```python
from parrot.models.token_budget import (           # created by TASK-3132 (models/token_budget.py)
    TokenBudgetPolicy, TokenEstimate, BudgetUsage, BudgetReservation, BudgetReport, BudgetSnapshot,
    BudgetMode, EstimateQuality, ReservationPhase, OperationState,
)
from parrot.core.exceptions import (               # created by TASK-3132 (core/exceptions.py, appended)
    BudgetError, BudgetExhausted, BudgetUnsupported, BudgetScopeConflict, BudgetStateMissing,
    BudgetResumeConflict, BudgetSnapshotInvalid, BudgetAccountingError, BudgetRegistryFull,
)
import asyncio, uuid, logging                      # stdlib
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/models/token_budget.py (TASK-3132)
class TokenBudgetPolicy(BaseModel):
    token_budget: int; budget_mode: Literal["estimated","strict"]; final_answer_reserve: int | float
    final_reserve_tokens: int   # computed_field
class BudgetReservation(BaseModel):
    reservation_id: str; operation_id: str; call_id: str; round_number: int; attempt_number: int
    phase: Literal["work","final"]; input_allowance: int; output_cap: int; request_fingerprint: str
    total: int   # computed_field
class BudgetUsage(BaseModel):
    input_tokens: int; output_tokens: int; details: Dict[str,int]; provider: str; model: str; route: str
    total_tokens: int   # computed_field

# packages/ai-parrot/src/parrot/core/exceptions.py (TASK-3132)
class BudgetError(ParrotError):
    code: str
    def __init__(self, message, *, operation_id: Optional[str] = None, report: Optional[dict] = None, **kwargs)
```

### Does NOT Exist
- ~~`parrot.clients.budget`~~ — this task creates it. `packages/ai-parrot/src/parrot/clients/__init__.py` uses `extend_path` (line 10) and imports only `base`/`openai_base` (lines 14-15); do NOT add an eager import of `budget` there (keeps the no-budget import path free of new work, AC "no ledger allocation … added to the no-budget path").
- ~~`QuestionBudget.consume()`~~, ~~`.charge()`~~, ~~`.spend()`~~ — the only mutators are the six methods in the spec skeleton.
- ~~`asyncio.Lock(loop=...)`~~ — removed in Python 3.10; create the lock lazily inside the first coroutine call or in `__init__` without a loop argument.
- ~~A "soft threshold" or per-child sub-budget~~ — explicitly non-goals (spec §1).

---

## Implementation Notes

### Pattern to Follow
```python
# Lock only around state transitions (spec §7 "Acquire ledger locks only for state transitions")
async def reserve(self, estimate, *, ...):
    async with self._lock:
        available = self._available(phase)
        # arithmetic + transition, no awaits inside except the lock itself
```

### Key Constraints
- All counters are plain `int`s on the instance; `report()` builds an immutable
  `BudgetReport` from them under the lock (consistent snapshot).
- `_attempts: dict[str, _Attempt]` keeps per-reservation state
  (`reservation`, `status`, `usage | None`). `U` is the sum of `total` for
  `uncertain` attempts; `R` is the sum of `total` for `reserved` attempts.
- `settle()` on an `uncertain` attempt: subtract its reserved total from `U`,
  add actual to `C`, mark `settled`. On a `settled` attempt with identical usage:
  no-op. With different usage: `BudgetAccountingError`.
- `release_unspent()` only from `reserved` (pre-dispatch failure); on any other
  status raise `BudgetAccountingError` (a dispatched request is never "free").
- `claim_finalization(owner_call_id)` returns `True` once, only from `draining`,
  and only when no attempt is still `reserved` (in-flight must resolve first).
  Store `_finalization_owner`. Second call → `False`. From `active`/`closed` →
  `False` (do not raise; the caller decides).
- `reserve(phase="final")` requires `self._finalization_owner == call_id`
  else `BudgetAccountingError`; on denial for `phase="final"` do NOT raise
  `BudgetExhausted` — return via raising `BudgetExhausted` too? **No**: spec §2.3
  says final-does-not-fit yields a partial result without inference; raise
  `BudgetExhausted` with `report.finalization_attempted=False` so the caller's
  boundary translates it. Both phases raise the same typed error; the report
  distinguishes them.
- `overrun_tokens` is recomputed at every `settle` as `max(0, C - B)`; in strict
  mode an attempt whose actual `total_tokens > reservation.total` sets
  `_strict_violated = True`, raises `BudgetAccountingError` and makes every
  later `reserve` deny.
- `revision` increments on every successful mutation (used by TASK-3134 floors).
- Provide `close()` (async, sets state `closed`, idempotent) and read-only
  properties `operation_id`, `policy`, `state`, `revision`.

### References in Codebase
- `packages/ai-parrot/src/parrot/clients/base.py:903-935` — per-loop lock idiom (`_get_or_create_lock`), for loop-affinity awareness (the ledger itself stays single-loop; TASK-3134 enforces it).

---

## Implementation Blueprint

### Steps (in order)
1. Create `clients/budget.py` with imports, re-exports and the `_Attempt` dataclass — *why*: applications import from here (spec §2 "New Public Interfaces").
2. Write `QuestionBudget.__init__` and the availability helpers — *why*: §2.2 formulas are the contract every test asserts.
3. Implement `reserve` / `settle` / `mark_uncertain` / `release_unspent` / `claim_finalization` / `report` / `close` — *why*: signatures are fixed by the spec skeleton.
4. Append the ledger tests; use `asyncio.Event` barriers, never `sleep`, for concurrency (spec §4 fixtures).

### `packages/ai-parrot/src/parrot/clients/budget.py` (CREATE)
```python
"""Question token budget ledger and public feature entry point (FEAT-550, spec §2.2/§2.3/§3 M1)."""
from __future__ import annotations

import asyncio
import logging
import uuid
from dataclasses import dataclass, field
from typing import Literal, Optional

from parrot.core.exceptions import (  # created by TASK-3132
    BudgetAccountingError, BudgetError, BudgetExhausted, BudgetRegistryFull, BudgetResumeConflict,
    BudgetScopeConflict, BudgetSnapshotInvalid, BudgetStateMissing, BudgetUnsupported,
)
from parrot.models.token_budget import (  # created by TASK-3132
    BudgetMode, BudgetReport, BudgetReservation, BudgetSnapshot, BudgetUsage, EstimateQuality,
    OperationState, ReservationPhase, TokenBudgetPolicy, TokenEstimate,
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
```
**Why this shape**: `_available` is the literal §2.2 formula (`A_work = max(0, B-F-C-U-R)`, `A_final = max(0, B-C-U-R)`); keeping it a sync helper called under the lock is what makes reservation atomic (AC "concurrent callers cannot oversubscribe").

### `packages/ai-parrot/src/parrot/clients/budget.py` (CREATE, continued — methods inside `QuestionBudget`)
```python
    async def reserve(
        self, estimate: TokenEstimate, *, max_output_tokens: int, min_output_tokens: int,
        call_id: str, round_number: int, attempt_number: int, phase: ReservationPhase,
    ) -> BudgetReservation:
        """Reserve I+O or raise typed denial; final requires the owner claim."""
        async with self._lock:
            self._counting_methods.add(estimate.method)
            if self._state == "closed" or self._strict_violated:
                raise BudgetExhausted("operation cannot admit inference", operation_id=self._operation_id, report=self._report_locked().model_dump())
            if phase == "final" and self._finalization_owner != call_id:
                raise BudgetAccountingError("final reservation without a finalization claim", operation_id=self._operation_id)
            if phase == "work" and self._state not in ("active", "suspended"):
                raise BudgetExhausted("operation is draining", operation_id=self._operation_id, report=self._report_locked().model_dump())
            available = self._available(phase)
            output_cap = min(max_output_tokens, available - estimate.input_tokens)
            if output_cap < min_output_tokens:
                # FILL IN: on phase="work" transition active->draining once, set _terminal_reason="budget_exhausted";
                #          on phase="final" leave state (caller returns partial). Bounded by spec §2.3 state table.
                raise BudgetExhausted("insufficient budget", operation_id=self._operation_id, report=self._report_locked().model_dump())
            reservation = BudgetReservation(
                reservation_id=str(uuid.uuid4()), operation_id=self._operation_id, call_id=call_id,
                round_number=round_number, attempt_number=attempt_number, phase=phase,
                input_allowance=estimate.input_tokens, output_cap=output_cap,
                request_fingerprint=estimate.request_fingerprint,
            )
            self._attempts[reservation.reservation_id] = _Attempt(reservation)
            if phase == "final":
                self._finalization_attempted = True
                self._state = "finalizing"
            self._revision += 1
            self.logger.debug("reserve %s phase=%s I=%d O=%d", reservation.reservation_id, phase, estimate.input_tokens, output_cap)
            return reservation

    async def settle(self, reservation_id: str, usage: BudgetUsage) -> None:
        """Reconcile actual usage once; identical duplicate settlement is inert."""
        async with self._lock:
            attempt = self._require(reservation_id)
            # FILL IN: state machine — reserved->settled, uncertain->settled (once), settled+identical->no-op,
            #          settled+different -> BudgetAccountingError, released -> BudgetAccountingError.
            #          Strict mode: usage.total_tokens > reservation.total => _strict_violated=True + raise.
            #          Bounded by spec §2.2 "Resolve its state once" and AC "Exactly-once accounting".
            raise NotImplementedError

    async def mark_uncertain(self, reservation_id: str, reason: str) -> None:
        """Retain the entire admitted debit when actual usage is unknown."""
        async with self._lock:
            attempt = self._require(reservation_id)
            # FILL IN: only from reserved; keep reservation.total counted in U; store reason. Bounded by spec §2.4.
            raise NotImplementedError

    async def release_unspent(self, reservation_id: str) -> None:
        """Release only a request proven not to have been dispatched/consumed."""
        async with self._lock:
            attempt = self._require(reservation_id)
            # FILL IN: only from reserved -> released; else BudgetAccountingError. Bounded by spec §2.4 "Merely receiving an HTTP error does not establish zero charge".
            raise NotImplementedError

    async def claim_finalization(self, owner_call_id: str) -> bool:
        """Claim the one final attempt after draining; false if already claimed."""
        async with self._lock:
            # FILL IN: True only if state=="draining", no attempt is "reserved", and no owner yet. Bounded by spec §2.3.
            raise NotImplementedError

    async def report(self) -> BudgetReport:
        """Return an immutable consistent snapshot of current accounting."""
        async with self._lock:
            return self._report_locked()

    async def close(self, *, terminal_reason: Optional[str] = None) -> None:
        """Mark the operation closed (idempotent); late descendants can no longer spend."""
        async with self._lock:
            # FILL IN: set state closed, keep uncertain debits, bump revision. Bounded by spec §2.3 "a completed root closes the inherited scope".
            raise NotImplementedError

    def _require(self, reservation_id: str) -> _Attempt:
        try:
            return self._attempts[reservation_id]
        except KeyError as exc:
            raise BudgetAccountingError(f"unknown reservation {reservation_id}", operation_id=self._operation_id) from exc

    def _report_locked(self) -> BudgetReport:
        # FILL IN: build BudgetReport from counters — overrun_tokens=max(0, C-B) unclamped,
        #          accounting_complete = no reserved/uncertain attempts, budget_exhausted = state in (draining, finalizing, closed with terminal_reason).
        #          Bounded by spec §2.3 flag definitions and §2.2 overrun rule.
        raise NotImplementedError


__all__ = [
    "QuestionBudget", "AttemptStatus",
    "TokenBudgetPolicy", "TokenEstimate", "BudgetUsage", "BudgetReservation", "BudgetReport", "BudgetSnapshot",
    "BudgetMode", "EstimateQuality", "ReservationPhase", "OperationState",
    "BudgetError", "BudgetExhausted", "BudgetUnsupported", "BudgetScopeConflict", "BudgetStateMissing",
    "BudgetResumeConflict", "BudgetSnapshotInvalid", "BudgetAccountingError", "BudgetRegistryFull",
]
```
**Why this shape**: every method name/signature is copied from the spec §3 Module 1 skeleton and must not change. Denials raise `BudgetExhausted` with the serialized report so the bot boundary (TASK-3137) can translate without re-querying the ledger.

### `packages/ai-parrot/tests/unit/clients/test_token_budget.py` (MODIFY)
```python
# occurrences: 1 (verified after TASK-3132: grep -c 'class TestRecords' packages/ai-parrot/tests/unit/clients/test_token_budget.py)
# AFTER — append at end of file (below class TestRecords)
from parrot.clients.budget import QuestionBudget  # noqa: E402
from parrot.models.token_budget import TokenEstimate  # noqa: E402
from parrot.core.exceptions import BudgetAccountingError  # noqa: E402


def _est(n: int) -> TokenEstimate:
    return TokenEstimate(input_tokens=n, method="test", quality="estimated", request_fingerprint=f"fp{n}")


def _usage(i: int, o: int) -> BudgetUsage:
    return BudgetUsage(input_tokens=i, output_tokens=o, provider="fake", model="m", route="r")


async def _ledger(b: int = 10_000, reserve=0.15) -> QuestionBudget:
    return QuestionBudget(TokenBudgetPolicy(token_budget=b, final_answer_reserve=reserve), "op-1")


class TestReservationArithmetic:
    async def test_default_reserve_example(self):
        """Spec §2.3 example: 2000+500, 3000+700 -> A_work=2300, A_final=3800; 3200 input denied for work."""
        q = await _ledger()
        r1 = await q.reserve(_est(2000), max_output_tokens=4096, min_output_tokens=1, call_id="c", round_number=1, attempt_number=1, phase="work")
        await q.settle(r1.reservation_id, _usage(2000, 500))
        # FILL IN: round 2 (3000/700), then assert report.remaining_work_tokens == 2300 and remaining_total_tokens == 3800,
        #          then reserve(_est(3200), phase="work") raises BudgetExhausted. Bounded by spec §2.3 example.
        raise NotImplementedError

    async def test_final_phase_requires_claim_and_uses_a_final(self):
        # FILL IN: after denial state is draining; claim_finalization("c") True; reserve(_est(3200), phase="final") gives output_cap==600;
        #          _est(4000) final raises BudgetExhausted. Bounded by spec §2.3 example.
        raise NotImplementedError


class TestExactlyOnce:
    async def test_duplicate_settle_inert_and_contradiction_typed(self):
        # FILL IN: settle twice identical OK; different usage -> BudgetAccountingError. Bounded by spec §2.2.
        raise NotImplementedError

    async def test_uncertain_then_late_settle_once(self):
        # FILL IN: mark_uncertain then settle moves U->C once; second different settle raises. Bounded by spec §2.2.
        raise NotImplementedError

    async def test_release_only_from_reserved(self):
        # FILL IN: release after settle raises BudgetAccountingError. Bounded by spec §2.4.
        raise NotImplementedError


class TestConcurrency:
    async def test_competing_reservations_cannot_oversubscribe(self):
        """Barrier-controlled: two coroutines race for the last allowance; exactly one wins."""
        q = await _ledger(b=1000, reserve=0)
        gate = asyncio.Event()

        async def contender():
            await gate.wait()
            try:
                return await q.reserve(_est(600), max_output_tokens=300, min_output_tokens=100, call_id="c", round_number=1, attempt_number=1, phase="work")
            except BudgetExhausted:
                return None

        tasks = [asyncio.create_task(contender()) for _ in range(2)]
        gate.set()
        results = await asyncio.gather(*tasks)
        assert sum(r is not None for r in results) == 1

    async def test_claim_finalization_single_owner(self):
        # FILL IN: two claims after drain, exactly one True. Bounded by spec §2.3 "Only the answer owner can claim".
        raise NotImplementedError
```
**Why**: these are the spec §4 rows "Reservation arithmetic", "Exactly-once accounting", "Concurrency" at ledger level; fixture numbers are the spec §4 fixture values.

### FILL IN checklist
- [ ] `budget.py::QuestionBudget.reserve` denial branch — draining transition + terminal reason; bounded by spec §2.3 state table
- [ ] `budget.py::QuestionBudget.settle` — full attempt state machine + strict violation; bounded by spec §2.2
- [ ] `budget.py::QuestionBudget.mark_uncertain` / `release_unspent` — status guards; bounded by spec §2.4
- [ ] `budget.py::QuestionBudget.claim_finalization` — draining + no in-flight + single owner; bounded by spec §2.3
- [ ] `budget.py::QuestionBudget.close` / `_report_locked` — flags and overrun; bounded by spec §2.3 flag definitions
- [ ] all `test_token_budget.py` FILL IN bodies — bounded by spec §2.3 example and §4 fixture values

---

## Acceptance Criteria

- [ ] `from parrot.clients.budget import QuestionBudget, TokenBudgetPolicy, BudgetExhausted` works
- [ ] Spec §2.3 default-reserve example reproduces exactly (2300 / 3800 / cap 600 / 4000 denied)
- [ ] Duplicate identical settle inert; contradictory settle raises `BudgetAccountingError`
- [ ] Two barrier-synchronized contenders for one remaining allowance: exactly one admitted
- [ ] `claim_finalization` returns `True` exactly once, only from `draining` with no in-flight attempts
- [ ] Strict-mode observed violation flips the ledger to deny-all and raises `BudgetAccountingError`
- [ ] `pytest packages/ai-parrot/tests/unit/clients/test_token_budget.py -v` passes
- [ ] `ruff check packages/ai-parrot/src/parrot/clients/budget.py` clean; no import of `parrot.clients.budget` added to `parrot/clients/__init__.py`

---

## Test Specification

Scaffold is in the MODIFY block above. Also add: `test_estimated_overrun_recorded_unclamped`
(settle 1_200 tokens against a 1_000 budget → `report().overrun_tokens == 200`, state still
allows finalization only if `A_final > 0`, else denies) and
`test_zero_budget_admits_nothing` (`token_budget=0` → first `reserve` raises `BudgetExhausted`).

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** §2.2, §2.3, §3 Module 1
2. **Check dependencies** — TASK-3132 in `sdd/tasks/completed/`
3. **Verify the Codebase Contract** — import `parrot.models.token_budget` and `parrot.core.exceptions.BudgetError` in a REPL before coding
4. **Update status** in `sdd/tasks/index/token-budget-bedrock.json` → `"in-progress"`
5. **Implement** from the Blueprint; never change a skeleton signature
6. **Verify** all acceptance criteria
7. **Move this file** to `sdd/tasks/completed/TASK-3133-question-budget-ledger.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**:

**Deviations from spec**: none | describe if any
