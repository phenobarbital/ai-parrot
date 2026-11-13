# TASK-5662: Atomic review commit, concurrency and replay

**Feature**: FEAT-892 - Agent Memory — Unified Integration, User Knowledge and Dynamics
**Spec**: `sdd/specs/agent-memory-mixin.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2–4h)
**Depends-on**: TASK-5661, TASK-5656
**Assigned-to**: unassigned
**Parallel**: true
**Parallelism notes**: Consumes SQLiteEpisodeBackend connection/schema and overlapping file from TASK-5661; Consumes ReviewCommand/ReviewReceipt/ReviewBackend from TASK-5656

## Context

Implement the bounded M2 slice of FEAT-892 revision 0.2. The owner's accepted
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

- Commit dedupe/revision/review/state together (`packages/ai-parrot/src/parrot/memory/episodic/backends/sqlite.py`).
- Real multiprocess, crash, duplicate and CAS persistence (`packages/ai-parrot/tests/memory/dynamics/test_storage.py`).

**NOT in scope:** FEAT-889 brain stores/schedulers/HTTP/PBAC; optimizer/fitting; provider SDK
or clients/base.py changes; dependency additions; deletion of persisted user/episode data
except the separately authorized scoped forget API; unrelated refactoring.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/memory/episodic/backends/sqlite.py` | MODIFY | Commit dedupe/revision/review/state together |
| `packages/ai-parrot/tests/memory/dynamics/test_storage.py` | CREATE | Real multiprocess, crash, duplicate and CAS persistence |

## Codebase Contract

### Verified Imports

The imports below are the complete blueprint import inventory. Standard-library modules are
built in; pydantic/aiosqlite/click/pytest are already declared in the core pyproject. Existing
repository imports use the verified paths below. Imports from new files are **planned**, supplied
by the named dependencies or this task; re-verify them after dependencies land. The optional
BrainService TYPE_CHECKING reference is explicitly external/future, never a verified production import.

```python
from parrot.memory.dynamics.models import ReviewCommand, ReviewReceipt
import pytest
```

### Existing Signatures and Anchors

- `packages/ai-parrot/src/parrot/memory/episodic/backends/sqlite.py` is created by TASK-5661; anchor `class SQLiteEpisodeBackend:` is planned, not an existing verified symbol.

### Does NOT Exist

- `packages/ai-parrot/tests/memory/dynamics/test_storage.py` is a new delivery path, absent on the verified base.
- `parrot.memory.agent.mixin` does not exist; `memory/agent.py` is the existing AnswerMemory compatibility module.
- Production `BrainService` is a future FEAT-889 contract, not an existing runtime import; never implement its placeholder here.
- No production optimizer/fitting module is authorized by this feature.

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/memory/episodic/backends/sqlite.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/memory/dynamics/test_storage.py",
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

### `packages/ai-parrot/src/parrot/memory/episodic/backends/sqlite.py` (MODIFY)

```python
# DEPENDENCY-CREATED MODIFY: packages/ai-parrot/src/parrot/memory/episodic/backends/sqlite.py from TASK-5661.
# Expected unique anchor: class SQLiteEpisodeBackend:
# occurrences now: 0 (file does not exist on base); prerequisite blueprint declares 1.
# Re-read and verify exact count 1 after dependency lands; stop on mismatch.
from parrot.memory.dynamics.models import ReviewCommand, ReviewReceipt

# Add to SQLiteEpisodeBackend:
async def apply_review(self, command: ReviewCommand) -> ReviewReceipt:
    """Atomically dedupe, check revision and commit review/state before acknowledging."""
    # FILL IN: one transaction and scoped payload-conflict handling — AC12.
    # Crash after commit before acknowledgement must replay as duplicate, never a new review.
    # Keep export/outbox replay durable and independent of episode TTL — U4/AC18.
    raise NotImplementedError
```

**Why:** One transaction makes dedupe and state inseparable, including the commit-before-ack crash window that pre-commit tests cannot cover.

### `packages/ai-parrot/tests/memory/dynamics/test_storage.py` (CREATE)

```python
"""Behavioral acceptance tests for Atomic review commit, concurrency and replay."""
import pytest

def test_eight_process_zero_loss() -> None:
    """Verify eight process zero loss."""
    # FILL IN: real subject/isolated fixture and observable assertions — task acceptance criteria below.
    # Use pytest.mark.asyncio and async def for async subject calls; never run paid/shared services.
    raise NotImplementedError

def test_duplicate_and_payload_conflict() -> None:
    """Verify duplicate and payload conflict."""
    # FILL IN: real subject/isolated fixture and observable assertions — task acceptance criteria below.
    # Use pytest.mark.asyncio and async def for async subject calls; never run paid/shared services.
    raise NotImplementedError

def test_crash_before_and_after_commit() -> None:
    """Verify crash before and after commit."""
    # FILL IN: real subject/isolated fixture and observable assertions — task acceptance criteria below.
    # Use pytest.mark.asyncio and async def for async subject calls; never run paid/shared services.
    raise NotImplementedError

def test_archive_replay_after_export_failure() -> None:
    """Verify archive replay after export failure."""
    # FILL IN: real subject/isolated fixture and observable assertions — task acceptance criteria below.
    # Use pytest.mark.asyncio and async def for async subject calls; never run paid/shared services.
    raise NotImplementedError
```

**Why:** One transaction makes dedupe and state inseparable, including the commit-before-ack crash window that pre-commit tests cannot cover.

### FILL IN checklist

- [ ] `packages/ai-parrot/src/parrot/memory/episodic/backends/sqlite.py` — Commit dedupe/revision/review/state together; bounded by the acceptance criteria below.
- [ ] `packages/ai-parrot/tests/memory/dynamics/test_storage.py` — Real multiprocess, crash, duplicate and CAS persistence; bounded by the acceptance criteria below.
- [ ] Replace every blueprint-only stub with working behavior; completed implementation files contain no placeholders.
- [ ] Verify planned imports after dependencies land and refresh contracts on drift.

## Acceptance Criteria

- [ ] AC12: eight isolated processes produce zero lost acknowledged writes; duplicates/CAS conflicts have exactly one durable application.
- [ ] AC12: test pre-commit rollback and crash-after-commit-before-ack/export; pending exists only with durable replay backing.
- [ ] AC18/U4: replayable archives retain required evidence and parameter identity without demanding the full corpus remain hot.
- [ ] Narrow task checks pass; scoped black/ruff pass for touched Python; validation logs identify skipped external coverage explicitly.

## Validation Commands

- `pytest packages/ai-parrot/tests/memory/dynamics/test_storage.py -q`

## Test Specification

- `eight_process_zero_loss`: AC12: eight isolated processes produce zero lost acknowledged writes; duplicates/CAS conflicts have exactly one durable application.
- `duplicate_and_payload_conflict`: AC12: test pre-commit rollback and crash-after-commit-before-ack/export; pending exists only with durable replay backing.
- `crash_before_and_after_commit`: AC18/U4: replayable archives retain required evidence and parameter identity without demanding the full corpus remain hot.
- `archive_replay_after_export_failure`: AC12: eight isolated processes produce zero lost acknowledged writes; duplicates/CAS conflicts have exactly one durable application.

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
