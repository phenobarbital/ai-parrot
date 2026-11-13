# TASK-5668: User forgetting, suppression and derivative retry

**Feature**: FEAT-892 - Agent Memory — Unified Integration, User Knowledge and Dynamics
**Spec**: `sdd/specs/agent-memory-mixin.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2–4h)
**Depends-on**: TASK-5667
**Assigned-to**: unassigned
**Parallel**: true
**Parallelism notes**: Consumes UserMemoryStore tables/event transactions and overlapping file from TASK-5667

## Context

Implement the bounded U1 slice of FEAT-892 revision 0.2. The owner's accepted
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

- Physical erasure and suppression independent of capability toggle (`packages/ai-parrot/src/parrot/memory/user/store.py`).
- Erasure, stale replay, later explicit declaration and retry durability (`packages/ai-parrot/tests/memory/user/test_forget.py`).

**NOT in scope:** FEAT-889 brain stores/schedulers/HTTP/PBAC; optimizer/fitting; provider SDK
or clients/base.py changes; dependency additions; deletion of persisted user/episode data
except the separately authorized scoped forget API; unrelated refactoring.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/memory/user/store.py` | MODIFY | Physical erasure and suppression independent of capability toggle |
| `packages/ai-parrot/tests/memory/user/test_forget.py` | CREATE | Erasure, stale replay, later explicit declaration and retry durability |

## Codebase Contract

### Verified Imports

The imports below are the complete blueprint import inventory. Standard-library modules are
built in; pydantic/aiosqlite/click/pytest are already declared in the core pyproject. Existing
repository imports use the verified paths below. Imports from new files are **planned**, supplied
by the named dependencies or this task; re-verify them after dependencies land. The optional
BrainService TYPE_CHECKING reference is explicitly external/future, never a verified production import.

```python
import pytest
```

### Existing Signatures and Anchors

- `packages/ai-parrot/src/parrot/memory/user/store.py` is created by TASK-5667; anchor `class UserMemoryStore:` is planned, not an existing verified symbol.

### Does NOT Exist

- `packages/ai-parrot/tests/memory/user/test_forget.py` is a new delivery path, absent on the verified base.
- `parrot.memory.agent.mixin` does not exist; `memory/agent.py` is the existing AnswerMemory compatibility module.
- Production `BrainService` is a future FEAT-889 contract, not an existing runtime import; never implement its placeholder here.
- No production optimizer/fitting module is authorized by this feature.

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/memory/user/store.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/memory/user/test_forget.py",
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

### `packages/ai-parrot/src/parrot/memory/user/store.py` (MODIFY)

```python
# DEPENDENCY-CREATED MODIFY: packages/ai-parrot/src/parrot/memory/user/store.py from TASK-5667.
# Expected unique anchor: class UserMemoryStore:
# occurrences now: 0 (file does not exist on base); prerequisite blueprint declares 1.
# Re-read and verify exact count 1 after dependency lands; stop on mismatch.
# Add the accepted Q2 operation to UserMemoryStore.
async def forget(self, command: UserKnowledgeCommand, *, scope: MemoryRequestScope) -> UserMemoryReceipt:
    """Delete the fact, persist suppression and retain durable derivative-invalidation work."""
    # FILL IN: one scoped transaction; retained evidence/stale extraction cannot resurrect — AC06/Q2.
    # Only a later explicit statement from the same trusted user can lift suppression.
    # Track affected source episodes for BrainService.forget_derived without importing brain internals.
    raise NotImplementedError
```

**Why:** Erasure alone cannot stop stale extraction from resurrecting facts; durable suppression and derivative retry close that replay path.

### `packages/ai-parrot/tests/memory/user/test_forget.py` (CREATE)

```python
"""Behavioral acceptance tests for User forgetting, suppression and derivative retry."""
import pytest

def test_forget_physically_erases_and_suppresses() -> None:
    """Verify forget physically erases and suppresses."""
    # FILL IN: real subject/isolated fixture and observable assertions — task acceptance criteria below.
    # Use pytest.mark.asyncio and async def for async subject calls; never run paid/shared services.
    raise NotImplementedError

def test_stale_replay_cannot_resurrect() -> None:
    """Verify stale replay cannot resurrect."""
    # FILL IN: real subject/isolated fixture and observable assertions — task acceptance criteria below.
    # Use pytest.mark.asyncio and async def for async subject calls; never run paid/shared services.
    raise NotImplementedError

def test_later_explicit_statement_lifts_marker() -> None:
    """Verify later explicit statement lifts marker."""
    # FILL IN: real subject/isolated fixture and observable assertions — task acceptance criteria below.
    # Use pytest.mark.asyncio and async def for async subject calls; never run paid/shared services.
    raise NotImplementedError

def test_derivative_retry_survives_restart() -> None:
    """Verify derivative retry survives restart."""
    # FILL IN: real subject/isolated fixture and observable assertions — task acceptance criteria below.
    # Use pytest.mark.asyncio and async def for async subject calls; never run paid/shared services.
    raise NotImplementedError
```

**Why:** Erasure alone cannot stop stale extraction from resurrecting facts; durable suppression and derivative retry close that replay path.

### FILL IN checklist

- [ ] `packages/ai-parrot/src/parrot/memory/user/store.py` — Physical erasure and suppression independent of capability toggle; bounded by the acceptance criteria below.
- [ ] `packages/ai-parrot/tests/memory/user/test_forget.py` — Erasure, stale replay, later explicit declaration and retry durability; bounded by the acceptance criteria below.
- [ ] Replace every blueprint-only stub with working behavior; completed implementation files contain no placeholders.
- [ ] Verify planned imports after dependencies land and refresh contracts on drift.

## Acceptance Criteria

- [ ] AC06/Q2: physical deletion removes fact content and persists a minimal suppression marker; re-extraction/replay from retained evidence cannot recreate it.
- [ ] AC06: only later explicit same-user evidence lifts suppression; duplicate forget is idempotent and disablement alone never deletes facts.
- [ ] AC15: derivative invalidation is keyed by tenant/source-episode lineage, remains retryable across restart, and uses only the sibling service boundary.
- [ ] Narrow task checks pass; scoped black/ruff pass for touched Python; validation logs identify skipped external coverage explicitly.

## Validation Commands

- `pytest packages/ai-parrot/tests/memory/user/test_forget.py -q`

## Test Specification

- `forget_physically_erases_and_suppresses`: AC06/Q2: physical deletion removes fact content and persists a minimal suppression marker; re-extraction/replay from retained evidence cannot recreate it.
- `stale_replay_cannot_resurrect`: AC06: only later explicit same-user evidence lifts suppression; duplicate forget is idempotent and disablement alone never deletes facts.
- `later_explicit_statement_lifts_marker`: AC15: derivative invalidation is keyed by tenant/source-episode lineage, remains retryable across restart, and uses only the sibling service boundary.
- `derivative_retry_survives_restart`: AC06/Q2: physical deletion removes fact content and persists a minimal suppression marker; re-extraction/replay from retained evidence cannot recreate it.

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
