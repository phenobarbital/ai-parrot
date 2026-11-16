# TASK-5659: Verified grade selection and experiential ranking

**Feature**: FEAT-892 - Agent Memory — Unified Integration, User Knowledge and Dynamics
**Spec**: `sdd/specs/agent-memory-mixin.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2–4h)
**Depends-on**: TASK-5656, TASK-5657, TASK-5658
**Assigned-to**: unassigned
**Parallel**: true
**Parallelism notes**: Consumes ReviewSignal from TASK-5656; Consumes retrievability from TASK-5657; Consumes MemoryCandidate from TASK-5658

## Context

Implement the bounded M1 slice of FEAT-892 revision 0.2. The owner's accepted
section 8 decisions govern defaults; earlier proposed wording is not permission to change them.
These are planning artifacts, not evidence that carried G1–G4 gates passed.

## Release Preconditions

No additional owner decision is required beyond completed dependency contracts. Do not bypass a blocked dependency.

Before releasing any blocked task, record the accepted amendment in the spec, expand its
Validation Contract with the released module test paths, regenerate the index test contract
using `parrot sdd tests contract`, and change status through the normal SDD workflow.
Do not infer gate acceptance from a completed spike or from the spec's approved body label.
The current scheduler treats every non-done status as pending: `blocked` is documentary,
not an automatic dispatch fence. Do not launch this feature unattended while gates remain;
the task executor must stop before code if its release preconditions are unmet.

## Scope

- Ordered pure grade selection (`packages/ai-parrot/src/parrot/memory/dynamics/grade.py`).
- Stable relevance/retrievability/importance ranking (`packages/ai-parrot/src/parrot/memory/dynamics/ranking.py`).
- Grade precedence and no-review cases (`packages/ai-parrot/tests/memory/dynamics/test_reviews.py`).
- Formula, stable ties, legacy neutrality and exclusions (`packages/ai-parrot/tests/memory/dynamics/test_ranking.py`).

**NOT in scope:** FEAT-889 brain stores/schedulers/HTTP/PBAC; optimizer/fitting; provider SDK
or clients/base.py changes; dependency additions; deletion of persisted user/episode data
except the separately authorized scoped forget API; unrelated refactoring.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/memory/dynamics/grade.py` | CREATE | Ordered pure grade selection |
| `packages/ai-parrot/src/parrot/memory/dynamics/ranking.py` | CREATE | Stable relevance/retrievability/importance ranking |
| `packages/ai-parrot/tests/memory/dynamics/test_reviews.py` | CREATE | Grade precedence and no-review cases |
| `packages/ai-parrot/tests/memory/dynamics/test_ranking.py` | CREATE | Formula, stable ties, legacy neutrality and exclusions |

## Codebase Contract

### Verified Imports

The imports below are the complete blueprint import inventory. Standard-library modules are
built in; pydantic/aiosqlite/click/pytest are already declared in the core pyproject. Existing
repository imports use the verified paths below. Imports from new files are **planned**, supplied
by the named dependencies or this task; re-verify them after dependencies land. The optional
BrainService TYPE_CHECKING reference is explicitly external/future, never a verified production import.

```python
from .fsrs import retrievability
from .models import Grade, ReviewSignal
from .models import MemoryParameters
from datetime import datetime
from parrot.memory.unified.models import MemoryCandidate
import pytest
```

### Existing Signatures and Anchors

- This task creates new files and consumes only the explicitly declared prerequisite contracts.

### Does NOT Exist

- `packages/ai-parrot/src/parrot/memory/dynamics/grade.py` is a new delivery path, absent on the verified base.
- `packages/ai-parrot/src/parrot/memory/dynamics/ranking.py` is a new delivery path, absent on the verified base.
- `packages/ai-parrot/tests/memory/dynamics/test_reviews.py` is a new delivery path, absent on the verified base.
- `packages/ai-parrot/tests/memory/dynamics/test_ranking.py` is a new delivery path, absent on the verified base.
- `parrot.memory.agent.mixin` does not exist; `memory/agent.py` is the existing AnswerMemory compatibility module.
- Production `BrainService` is a future FEAT-889 contract, not an existing runtime import; never implement its placeholder here.
- No production optimizer/fitting module is authorized by this feature.

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/memory/dynamics/grade.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot/src/parrot/memory/dynamics/ranking.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot/tests/memory/dynamics/test_reviews.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot/tests/memory/dynamics/test_ranking.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": []
}
```

## Implementation Notes

Use async I/O, strict hints, Pydantic v2 and Google docstrings; log through self.logger or
the module logger. Format Python with black (120) and run scoped ruff. Keep test logs under
artifacts/logs. All DB/process fixtures are isolated; no shared DDL or dependency mutation is
authorized. User explicitly confirmed that the new AgentMemoryToolkit remains in core at
parrot.memory.agent_memory; do not move it into parrot_tools.

## Implementation Blueprint

### Steps (in order)

1. Verify release preconditions and dependency contracts — unresolved evidence must not become invented implementation policy.
2. Recheck the exact anchors and imports below after dependencies land — overlapping writers deliberately run in sequence.
3. Apply each per-file block and complete its bounded FILL IN items — preserve public contracts outside this task's scope.
4. Implement the behavioral cases below with real temporary stores where persistence matters — mocks alone cannot prove durability.
5. Run the narrow validation commands and scoped style checks — do not mark missing backend evidence as a passing persistence test.

### `packages/ai-parrot/src/parrot/memory/dynamics/grade.py` (CREATE)

```python
"""Grade selection after trusted evidence and attribution admission."""
from .models import Grade, ReviewSignal

def select_grade(signal: ReviewSignal, *, attributed: bool,
                 memory_error_signature: str | None, verified_recovery: bool) -> Grade | None:
    """Choose AGAIN/EASY/HARD/GOOD in contract order, or no review."""
    # FILL IN: repeated normalized nonempty matching failure -> AGAIN; linked recovery -> EASY;
    # confirmed corrections -> HARD; verified first-attempt success -> GOOD — AC11/G3.
    # Missing attribution, unrelated failure, cancellation or incomplete outcome -> None.
    raise NotImplementedError
```

**Why:** Ordered admission rejects unrelated outcomes before choosing a grade; one ranking function prevents warnings and room recall from disagreeing.

### `packages/ai-parrot/src/parrot/memory/dynamics/ranking.py` (CREATE)

```python
"""Deterministic ranking for experiential candidates, separate from fact validity."""
from datetime import datetime
from parrot.memory.unified.models import MemoryCandidate
from .models import MemoryParameters
from .fsrs import retrievability

def rank_candidates(candidates: list[MemoryCandidate], *, now: datetime,
                    parameters: MemoryParameters) -> list[MemoryCandidate]:
    """Rank experiential candidates with stable-ID ties and anti-pattern grouping."""
    # FILL IN: relevance * retrievability * (1 + importance/10) — AC14.
    # Preserve raw similarity; keep user-knowledge relevance/validity outside FSRS.
    raise NotImplementedError
```

**Why:** Ordered admission rejects unrelated outcomes before choosing a grade; one ranking function prevents warnings and room recall from disagreeing.

### `packages/ai-parrot/tests/memory/dynamics/test_reviews.py` (CREATE)

```python
"""Behavioral acceptance tests for Verified grade selection and experiential ranking."""
import pytest

def test_ordered_grade_precedence() -> None:
    """Verify ordered grade precedence."""
    # FILL IN: real subject/isolated fixture and observable assertions — task acceptance criteria below.
    # Use pytest.mark.asyncio and async def for async subject calls; never run paid/shared services.
    raise NotImplementedError

def test_missing_or_unrelated_signal_no_review() -> None:
    """Verify missing or unrelated signal no review."""
    # FILL IN: real subject/isolated fixture and observable assertions — task acceptance criteria below.
    # Use pytest.mark.asyncio and async def for async subject calls; never run paid/shared services.
    raise NotImplementedError

def test_ranking_formula_and_stable_ties() -> None:
    """Verify ranking formula and stable ties."""
    # FILL IN: real subject/isolated fixture and observable assertions — task acceptance criteria below.
    # Use pytest.mark.asyncio and async def for async subject calls; never run paid/shared services.
    raise NotImplementedError
```

**Why:** Ordered admission rejects unrelated outcomes before choosing a grade; one ranking function prevents warnings and room recall from disagreeing.

### `packages/ai-parrot/tests/memory/dynamics/test_ranking.py` (CREATE)

```python
"""Behavioral acceptance tests for Verified grade selection and experiential ranking."""
import pytest

def test_ordered_grade_precedence() -> None:
    """Verify ordered grade precedence."""
    # FILL IN: real subject/isolated fixture and observable assertions — task acceptance criteria below.
    # Use pytest.mark.asyncio and async def for async subject calls; never run paid/shared services.
    raise NotImplementedError

def test_missing_or_unrelated_signal_no_review() -> None:
    """Verify missing or unrelated signal no review."""
    # FILL IN: real subject/isolated fixture and observable assertions — task acceptance criteria below.
    # Use pytest.mark.asyncio and async def for async subject calls; never run paid/shared services.
    raise NotImplementedError

def test_ranking_formula_and_stable_ties() -> None:
    """Verify ranking formula and stable ties."""
    # FILL IN: real subject/isolated fixture and observable assertions — task acceptance criteria below.
    # Use pytest.mark.asyncio and async def for async subject calls; never run paid/shared services.
    raise NotImplementedError
```

**Why:** Ordered admission rejects unrelated outcomes before choosing a grade; one ranking function prevents warnings and room recall from disagreeing.

### FILL IN checklist

- [ ] `packages/ai-parrot/src/parrot/memory/dynamics/grade.py` — Ordered pure grade selection; bounded by the acceptance criteria below.
- [ ] `packages/ai-parrot/src/parrot/memory/dynamics/ranking.py` — Stable relevance/retrievability/importance ranking; bounded by the acceptance criteria below.
- [ ] `packages/ai-parrot/tests/memory/dynamics/test_reviews.py` — Grade precedence and no-review cases; bounded by the acceptance criteria below.
- [ ] `packages/ai-parrot/tests/memory/dynamics/test_ranking.py` — Formula, stable ties, legacy neutrality and exclusions; bounded by the acceptance criteria below.
- [ ] Replace every blueprint-only stub with working behavior; completed implementation files contain no placeholders.
- [ ] Verify planned imports after dependencies land and refresh contracts on drift.

## Acceptance Criteria

- [ ] AC11: exact admission/grade order; overlap recovery is capped at GOOD, and unrelated/missing evidence produces no review.
- [ ] AC14: every experiential ranking route uses the same formula and stable ties; anti-patterns are metadata, not a new enum category.
- [ ] Narrow task checks pass; scoped black/ruff pass for touched Python; validation logs identify skipped external coverage explicitly.

## Validation Commands

- `pytest packages/ai-parrot/tests/memory/dynamics/test_reviews.py packages/ai-parrot/tests/memory/dynamics/test_ranking.py -q`

## Test Specification

- `ordered_grade_precedence`: AC11: exact admission/grade order; overlap recovery is capped at GOOD, and unrelated/missing evidence produces no review.
- `missing_or_unrelated_signal_no_review`: AC14: every experiential ranking route uses the same formula and stable ties; anti-patterns are metadata, not a new enum category.
- `ranking_formula_and_stable_ties`: AC11: exact admission/grade order; overlap recovery is capped at GOOD, and unrelated/missing evidence produces no review.

Use deterministic clocks, runtime-derived identities and isolated temporary stores. Preserve
CancelledError. Use subprocesses for crash/multiprocess checks, never shared production data.

## Agent Instructions

1. Use the FEAT-892 worktree provisioned by sdd-start; never implement on dev.
2. Check every Depends-on task is done and each Release Preconditions item is met; blocked is not runnable.
3. Read the full spec and reverify this task's Codebase Contract; refresh stale evidence before editing.
4. Implement only declared files plus normal SDD state; preserve concurrent/unrelated changes.
5. Run validation, commit scoped implementation, and finalize with `parrot sdd task finalize`
   using real TaskCompletionEvidence and the exact implementation HEAD. Let finalization own
   the completion note and active-to-completed move; do not fabricate completion evidence.
