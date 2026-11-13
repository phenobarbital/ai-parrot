# TASK-5657: Pure FSRS transition and retrievability

**Feature**: FEAT-892 - Agent Memory — Unified Integration, User Knowledge and Dynamics
**Spec**: `sdd/specs/agent-memory-mixin.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2–4h)
**Depends-on**: TASK-5655
**Assigned-to**: unassigned
**Parallel**: true
**Parallelism notes**: Consumes Grade/MemoryState/MemoryParameters from TASK-5655

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

- Deterministic pure numerical transitions (`packages/ai-parrot/src/parrot/memory/dynamics/fsrs.py`).
- Pinned parity, boundary and clock tests (`packages/ai-parrot/tests/memory/dynamics/test_core.py`).

**NOT in scope:** FEAT-889 brain stores/schedulers/HTTP/PBAC; optimizer/fitting; provider SDK
or clients/base.py changes; dependency additions; deletion of persisted user/episode data
except the separately authorized scoped forget API; unrelated refactoring.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/memory/dynamics/fsrs.py` | CREATE | Deterministic pure numerical transitions |
| `packages/ai-parrot/tests/memory/dynamics/test_core.py` | CREATE | Pinned parity, boundary and clock tests |

## Codebase Contract

### Verified Imports

The imports below are the complete blueprint import inventory. Standard-library modules are
built in; pydantic/aiosqlite/click/pytest are already declared in the core pyproject. Existing
repository imports use the verified paths below. Imports from new files are **planned**, supplied
by the named dependencies or this task; re-verify them after dependencies land. The optional
BrainService TYPE_CHECKING reference is explicitly external/future, never a verified production import.

```python
from .models import Grade, MemoryParameters, MemoryState
from datetime import datetime
import pytest
```

### Existing Signatures and Anchors

- This task creates new files and consumes only the explicitly declared prerequisite contracts.

### Does NOT Exist

- `packages/ai-parrot/src/parrot/memory/dynamics/fsrs.py` is a new delivery path, absent on the verified base.
- `packages/ai-parrot/tests/memory/dynamics/test_core.py` is a new delivery path, absent on the verified base.
- `parrot.memory.agent.mixin` does not exist; `memory/agent.py` is the existing AnswerMemory compatibility module.
- Production `BrainService` is a future FEAT-889 contract, not an existing runtime import; never implement its placeholder here.
- No production optimizer/fitting module is authorized by this feature.

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/memory/dynamics/fsrs.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot/tests/memory/dynamics/test_core.py",
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

### `packages/ai-parrot/src/parrot/memory/dynamics/fsrs.py` (CREATE)

```python
"""Pure FSRS calculations using an explicit clock and immutable parameters."""
from datetime import datetime
from .models import Grade, MemoryParameters, MemoryState

def retrievability(state: MemoryState, *, now: datetime, parameters: MemoryParameters) -> float:
    """Return bounded retrievability, with neutral treatment of uninitialized legacy state."""
    # FILL IN: accepted reference and elapsed-time policy — AC10; do not read a global clock.
    raise NotImplementedError

def transition(state: MemoryState, grade: Grade, *, reviewed_at: datetime,
               parameters: MemoryParameters) -> MemoryState:
    """Compute a new state without I/O or modifying the input parameter/state objects."""
    # FILL IN: all grade branches and same-day clamp — accepted G1/AC10.
    raise NotImplementedError
```

**Why:** Injected time and immutable inputs make reference parity and crash replay deterministic; pure calculations remain reusable outside agents.

### `packages/ai-parrot/tests/memory/dynamics/test_core.py` (CREATE)

```python
"""Behavioral acceptance tests for Pure FSRS transition and retrievability."""
import pytest

def test_reference_parity_all_grades() -> None:
    """Verify reference parity all grades."""
    # FILL IN: real subject/isolated fixture and observable assertions — task acceptance criteria below.
    # Use pytest.mark.asyncio and async def for async subject calls; never run paid/shared services.
    raise NotImplementedError

def test_same_day_and_out_of_order() -> None:
    """Verify same day and out of order."""
    # FILL IN: real subject/isolated fixture and observable assertions — task acceptance criteria below.
    # Use pytest.mark.asyncio and async def for async subject calls; never run paid/shared services.
    raise NotImplementedError

def test_legacy_neutral_and_no_global_clock() -> None:
    """Verify legacy neutral and no global clock."""
    # FILL IN: real subject/isolated fixture and observable assertions — task acceptance criteria below.
    # Use pytest.mark.asyncio and async def for async subject calls; never run paid/shared services.
    raise NotImplementedError
```

**Why:** Injected time and immutable inputs make reference parity and crash replay deterministic; pure calculations remain reusable outside agents.

### FILL IN checklist

- [ ] `packages/ai-parrot/src/parrot/memory/dynamics/fsrs.py` — Deterministic pure numerical transitions; bounded by the acceptance criteria below.
- [ ] `packages/ai-parrot/tests/memory/dynamics/test_core.py` — Pinned parity, boundary and clock tests; bounded by the acceptance criteria below.
- [ ] Replace every blueprint-only stub with working behavior; completed implementation files contain no placeholders.
- [ ] Verify planned imports after dependencies land and refresh contracts on drift.

## Acceptance Criteria

- [ ] AC10: all grades and the accepted S1 parity sequence meet its tolerance; same-day and out-of-order inputs obey the frozen time policy.
- [ ] AC10/AC18: pure production code does not import spike/test modules or an optimizer; preserve reference attribution/license when translating accepted equations.
- [ ] Narrow task checks pass; scoped black/ruff pass for touched Python; validation logs identify skipped external coverage explicitly.

## Validation Commands

- `pytest packages/ai-parrot/tests/memory/dynamics/test_core.py -q`

## Test Specification

- `reference_parity_all_grades`: AC10: all grades and the accepted S1 parity sequence meet its tolerance; same-day and out-of-order inputs obey the frozen time policy.
- `same_day_and_out_of_order`: AC10/AC18: pure production code does not import spike/test modules or an optimizer; preserve reference attribution/license when translating accepted equations.
- `legacy_neutral_and_no_global_clock`: AC10: all grades and the accepted S1 parity sequence meet its tolerance; same-day and out-of-order inputs obey the frozen time policy.

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
