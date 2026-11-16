# TASK-5667: Independent SQLite user knowledge service

**Feature**: FEAT-892 - Agent Memory — Unified Integration, User Knowledge and Dynamics
**Spec**: `sdd/specs/agent-memory-mixin.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2–4h)
**Depends-on**: TASK-5666, TASK-5661
**Assigned-to**: unassigned
**Parallel**: true
**Parallelism notes**: Consumes UserKnowledge/Candidate/Command/Receipt from TASK-5666; Consumes accepted shared database schema/connection ownership contract, without constructing SQLiteEpisodeBackend in user-only mode from TASK-5661

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

- Scoped facts, CAS, correction and own-table lifecycle (`packages/ai-parrot/src/parrot/memory/user/store.py`).
- Real user-only persistence and conflict semantics (`packages/ai-parrot/tests/memory/user/test_store.py`).

**NOT in scope:** FEAT-889 brain stores/schedulers/HTTP/PBAC; optimizer/fitting; provider SDK
or clients/base.py changes; dependency additions; deletion of persisted user/episode data
except the separately authorized scoped forget API; unrelated refactoring.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/memory/user/store.py` | CREATE | Scoped facts, CAS, correction and own-table lifecycle |
| `packages/ai-parrot/tests/memory/user/test_store.py` | CREATE | Real user-only persistence and conflict semantics |

## Codebase Contract

### Verified Imports

The imports below are the complete blueprint import inventory. Standard-library modules are
built in; pydantic/aiosqlite/click/pytest are already declared in the core pyproject. Existing
repository imports use the verified paths below. Imports from new files are **planned**, supplied
by the named dependencies or this task; re-verify them after dependencies land. The optional
BrainService TYPE_CHECKING reference is explicitly external/future, never a verified production import.

```python
from .models import UserKnowledge, UserKnowledgeCommand, UserMemoryReceipt
from __future__ import annotations
from parrot.memory.agent_memory.models import MemoryRequestScope
from pathlib import Path
import aiosqlite
import pytest
```

### Existing Signatures and Anchors

- This task creates new files and consumes only the explicitly declared prerequisite contracts.

### Does NOT Exist

- `packages/ai-parrot/src/parrot/memory/user/store.py` is a new delivery path, absent on the verified base.
- `packages/ai-parrot/tests/memory/user/test_store.py` is a new delivery path, absent on the verified base.
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
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot/tests/memory/user/test_store.py",
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

### `packages/ai-parrot/src/parrot/memory/user/store.py` (CREATE)

```python
"""Scoped user knowledge in independent tables of the configured SQLite database."""
from __future__ import annotations
from pathlib import Path
import aiosqlite
from parrot.memory.agent_memory.models import MemoryRequestScope
from .models import UserKnowledge, UserKnowledgeCommand, UserMemoryReceipt

class UserMemoryStore:
    """Manage revisioned cross-session facts without constructing an episodic store."""
    def __init__(self, path: Path) -> None:
        """Retain SQLite configuration; user-only mode acquires only its own resources."""
        self.path = path
        # FILL IN: resource ownership and idempotent schema lifecycle — AC04/AC07.

    async def recall(self, query: str, *, scope: MemoryRequestScope, limit: int = 5) -> list[UserKnowledge]:
        """Return relevant active valid facts in the permitted user/context."""
        # FILL IN: identity admission before query/limit, no FSRS decay — AC05/AC06.
        raise NotImplementedError

    async def list(self, *, scope: MemoryRequestScope, limit: int = 100) -> list[UserKnowledge]:
        """List authorized facts with their status and provenance."""
        # FILL IN: scoped query with bounded limit — AC05/AC06.
        raise NotImplementedError

    async def upsert(self, command: UserKnowledgeCommand, *, scope: MemoryRequestScope) -> UserMemoryReceipt:
        """Apply an idempotent CAS candidate, keeping inference pending."""
        # FILL IN: transaction, explicit-vs-inferred and context semantics — AC06/Q1.
        raise NotImplementedError

    async def correct(self, command: UserKnowledgeCommand, *, scope: MemoryRequestScope) -> UserMemoryReceipt:
        """Keep superseded history while making the latest valid explicit correction active."""
        # FILL IN: expected revision, evidence, suppression checks and same-context ordering — AC06/Q1.
        raise NotImplementedError

    # The following task adds forget; do not advertise an unavailable method or ship a stub.
```

**Why:** Own tables and resource ownership allow cross-session user knowledge without constructing an episodic store; CAS protects explicit corrections.

### `packages/ai-parrot/tests/memory/user/test_store.py` (CREATE)

```python
"""Behavioral acceptance tests for Independent SQLite user knowledge service."""
import pytest

def test_user_only_real_store_reopen() -> None:
    """Verify user only real store reopen."""
    # FILL IN: real subject/isolated fixture and observable assertions — task acceptance criteria below.
    # Use pytest.mark.asyncio and async def for async subject calls; never run paid/shared services.
    raise NotImplementedError

def test_explicit_correction_and_scoped_history() -> None:
    """Verify explicit correction and scoped history."""
    # FILL IN: real subject/isolated fixture and observable assertions — task acceptance criteria below.
    # Use pytest.mark.asyncio and async def for async subject calls; never run paid/shared services.
    raise NotImplementedError

def test_duplicate_event_and_cas_conflict() -> None:
    """Verify duplicate event and cas conflict."""
    # FILL IN: real subject/isolated fixture and observable assertions — task acceptance criteria below.
    # Use pytest.mark.asyncio and async def for async subject calls; never run paid/shared services.
    raise NotImplementedError

def test_missing_identity_denies_query() -> None:
    """Verify missing identity denies query."""
    # FILL IN: real subject/isolated fixture and observable assertions — task acceptance criteria below.
    # Use pytest.mark.asyncio and async def for async subject calls; never run paid/shared services.
    raise NotImplementedError
```

**Why:** Own tables and resource ownership allow cross-session user knowledge without constructing an episodic store; CAS protects explicit corrections.

### FILL IN checklist

- [ ] `packages/ai-parrot/src/parrot/memory/user/store.py` — Scoped facts, CAS, correction and own-table lifecycle; bounded by the acceptance criteria below.
- [ ] `packages/ai-parrot/tests/memory/user/test_store.py` — Real user-only persistence and conflict semantics; bounded by the acceptance criteria below.
- [ ] Replace every blueprint-only stub with working behavior; completed implementation files contain no placeholders.
- [ ] Verify planned imports after dependencies land and refresh contracts on drift.

## Acceptance Criteria

- [ ] AC04: user-only mode persists across sessions in own tables of the configured SQLite database without creating EpisodicMemoryStore.
- [ ] AC06/Q1: latest explicit same-context declaration wins; superseded facts remain history but are not served; inference stays pending and project constraints do not overwrite global preferences.
- [ ] AC05/AC12: trusted user identity required before any query; transactional CAS/event dedupe prevents double application; conflicting reuse returns conflict.
- [ ] Narrow task checks pass; scoped black/ruff pass for touched Python; validation logs identify skipped external coverage explicitly.

## Validation Commands

- `pytest packages/ai-parrot/tests/memory/user/test_store.py -q`

## Test Specification

- `user_only_real_store_reopen`: AC04: user-only mode persists across sessions in own tables of the configured SQLite database without creating EpisodicMemoryStore.
- `explicit_correction_and_scoped_history`: AC06/Q1: latest explicit same-context declaration wins; superseded facts remain history but are not served; inference stays pending and project constraints do not overwrite global preferences.
- `duplicate_event_and_cas_conflict`: AC05/AC12: trusted user identity required before any query; transactional CAS/event dedupe prevents double application; conflicting reuse returns conflict.
- `missing_identity_denies_query`: AC04: user-only mode persists across sessions in own tables of the configured SQLite database without creating EpisodicMemoryStore.

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
