# TASK-5680: Hard-cut mixin exports and live consumer migration

**Feature**: FEAT-892 - Agent Memory — Unified Integration, User Knowledge and Dynamics
**Spec**: `sdd/specs/agent-memory-mixin.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2–4h)
**Depends-on**: TASK-5673, TASK-5674, TASK-5665
**Assigned-to**: unassigned
**Parallel**: true
**Parallelism notes**: Consumes BasicAgent built-in AgentMemoryMixin and real invocation paths from TASK-5673; Consumes single tool/response ownership from TASK-5674; Consumes legacy preference/room behavior from TASK-5665

## Context

Implement the bounded X1 slice of FEAT-892 revision 0.2. The owner's accepted
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

- Replace old mixin exports while preserving other memory names (`packages/ai-parrot/src/parrot/memory/__init__.py`).
- Remove EpisodicMemoryMixin export (`packages/ai-parrot/src/parrot/memory/episodic/__init__.py`).
- Remove LongTermMemoryMixin export (`packages/ai-parrot/src/parrot/memory/unified/__init__.py`).
- DELETE obsolete code file after all consumers migrate (`packages/ai-parrot/src/parrot/memory/episodic/mixin.py`).
- DELETE obsolete code file after all consumers migrate (`packages/ai-parrot/src/parrot/memory/unified/mixin.py`).
- Use BasicAgent's built-in capability without duplicate MRO (`examples/shoply/sample.py`).
- Migrate facade behavior tests (`packages/ai-parrot/tests/memory/unified/test_mixin.py`).
- New public imports and absent old mixins (`packages/ai-parrot/tests/memory/unified/test_imports.py`).
- Real bot integration rather than duplicate mixin stub (`packages/ai-parrot/tests/memory/unified/test_bot_integration.py`).
- Retain preference/sala/tool behavior under new flags (`packages/ai-parrot/tests/test_episodic_memory.py`).

**NOT in scope:** FEAT-889 brain stores/schedulers/HTTP/PBAC; optimizer/fitting; provider SDK
or clients/base.py changes; dependency additions; deletion of persisted user/episode data
except the separately authorized scoped forget API; unrelated refactoring.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/memory/__init__.py` | MODIFY | Replace old mixin exports while preserving other memory names |
| `packages/ai-parrot/src/parrot/memory/episodic/__init__.py` | MODIFY | Remove EpisodicMemoryMixin export |
| `packages/ai-parrot/src/parrot/memory/unified/__init__.py` | MODIFY | Remove LongTermMemoryMixin export |
| `packages/ai-parrot/src/parrot/memory/episodic/mixin.py` | MODIFY | DELETE obsolete code file after all consumers migrate |
| `packages/ai-parrot/src/parrot/memory/unified/mixin.py` | MODIFY | DELETE obsolete code file after all consumers migrate |
| `examples/shoply/sample.py` | MODIFY | Use BasicAgent's built-in capability without duplicate MRO |
| `packages/ai-parrot/tests/memory/unified/test_mixin.py` | MODIFY | Migrate facade behavior tests |
| `packages/ai-parrot/tests/memory/unified/test_imports.py` | MODIFY | New public imports and absent old mixins |
| `packages/ai-parrot/tests/memory/unified/test_bot_integration.py` | MODIFY | Real bot integration rather than duplicate mixin stub |
| `packages/ai-parrot/tests/test_episodic_memory.py` | MODIFY | Retain preference/sala/tool behavior under new flags |

## Codebase Contract

### Verified Imports

The imports below are the complete blueprint import inventory. Standard-library modules are
built in; pydantic/aiosqlite/click/pytest are already declared in the core pyproject. Existing
repository imports use the verified paths below. Imports from new files are **planned**, supplied
by the named dependencies or this task; re-verify them after dependencies land. The optional
BrainService TYPE_CHECKING reference is explicitly external/future, never a verified production import.

```python

```

### Existing Signatures and Anchors

- `packages/ai-parrot/src/parrot/memory/__init__.py:19`: `from .episodic import (` (exact-line occurrence count 1).
- `packages/ai-parrot/src/parrot/memory/episodic/__init__.py:8`: `from .mixin import EpisodicMemoryMixin` (exact-line occurrence count 1).
- `packages/ai-parrot/src/parrot/memory/unified/__init__.py:11`: `from .mixin import LongTermMemoryMixin` (exact-line occurrence count 1).
- `packages/ai-parrot/src/parrot/memory/episodic/mixin.py:77`: `class EpisodicMemoryMixin:` (exact-line occurrence count 1).
- `packages/ai-parrot/src/parrot/memory/unified/mixin.py:24`: `class LongTermMemoryMixin:` (exact-line occurrence count 1).
- `examples/shoply/sample.py:34`: `from parrot.memory.episodic.mixin import EpisodicMemoryMixin` (exact-line occurrence count 1).
- `packages/ai-parrot/tests/memory/unified/test_mixin.py:8`: `class MockAgent(LongTermMemoryMixin):` (exact-line occurrence count 1).
- `packages/ai-parrot/tests/memory/unified/test_imports.py:4`: `def test_unified_package_imports():` (exact-line occurrence count 1).
- `packages/ai-parrot/tests/memory/unified/test_bot_integration.py:41`: `class MixinBot(LongTermMemoryMixin, StubBot):` (exact-line occurrence count 1).
- `packages/ai-parrot/tests/test_episodic_memory.py:1084`: `class TestMixinIntegration:` (exact-line occurrence count 1).
- `packages/ai-parrot/src/parrot/memory/agent.py`: 7:class AnswerMemory:

### Does NOT Exist

- `parrot.memory.agent.mixin` does not exist; `memory/agent.py` is the existing AnswerMemory compatibility module.
- Production `BrainService` is a future FEAT-889 contract, not an existing runtime import; never implement its placeholder here.
- No production optimizer/fitting module is authorized by this feature.

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/memory/__init__.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/src/parrot/memory/episodic/__init__.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/src/parrot/memory/unified/__init__.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/src/parrot/memory/episodic/mixin.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/src/parrot/memory/unified/mixin.py",
      "action": "MODIFY"
    },
    {
      "path": "examples/shoply/sample.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/memory/unified/test_mixin.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/memory/unified/test_imports.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/memory/unified/test_bot_integration.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/test_episodic_memory.py",
      "action": "MODIFY"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/memory/agent.py#AnswerMemory",
    "sym:packages/ai-parrot/src/parrot/memory/episodic/mixin.py#EpisodicMemoryMixin",
    "sym:packages/ai-parrot/src/parrot/memory/unified/mixin.py#LongTermMemoryMixin",
    "sym:packages/ai-parrot/tests/memory/unified/test_bot_integration.py#MixinBot",
    "sym:packages/ai-parrot/tests/memory/unified/test_mixin.py#MockAgent",
    "sym:packages/ai-parrot/tests/test_episodic_memory.py#TestMixinIntegration"
  ]
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

### `packages/ai-parrot/src/parrot/memory/__init__.py` (MODIFY)

```python
# occurrences: 1 (verified: grep -F -x -c -- 'from .episodic import (' packages/ai-parrot/src/parrot/memory/__init__.py)
# MODIFY anchor at packages/ai-parrot/src/parrot/memory/__init__.py:19: from .episodic import (
# Replace old mixin exports while preserving other memory names.
# FILL IN: AC08: remove old classes/files/exports with no shims; new public import is parrot.memory.agent_memory.AgentMemoryMixin, also re-exported by parrot.memory.
# FILL IN: AC08: preserve AgentMemory = AnswerMemory and store APIs/text compatibility; no deletion/relocation of persisted snapshots/rows.
# FILL IN: AC08: migrate live example and tests without adding the mixin twice to BasicAgent subclasses; inventory all live consumers and report downstream release coordination.
```

**Why:** A coordinated hard-cut removes both duplicate memory paths while preserving independent store APIs, AnswerMemory and persisted data.

### `packages/ai-parrot/src/parrot/memory/episodic/__init__.py` (MODIFY)

```python
# occurrences: 1 (verified: grep -F -x -c -- 'from .mixin import EpisodicMemoryMixin' packages/ai-parrot/src/parrot/memory/episodic/__init__.py)
# MODIFY anchor at packages/ai-parrot/src/parrot/memory/episodic/__init__.py:8: from .mixin import EpisodicMemoryMixin
# Remove EpisodicMemoryMixin export.
# FILL IN: AC08: remove old classes/files/exports with no shims; new public import is parrot.memory.agent_memory.AgentMemoryMixin, also re-exported by parrot.memory.
# FILL IN: AC08: preserve AgentMemory = AnswerMemory and store APIs/text compatibility; no deletion/relocation of persisted snapshots/rows.
# FILL IN: AC08: migrate live example and tests without adding the mixin twice to BasicAgent subclasses; inventory all live consumers and report downstream release coordination.
```

**Why:** A coordinated hard-cut removes both duplicate memory paths while preserving independent store APIs, AnswerMemory and persisted data.

### `packages/ai-parrot/src/parrot/memory/unified/__init__.py` (MODIFY)

```python
# occurrences: 1 (verified: grep -F -x -c -- 'from .mixin import LongTermMemoryMixin' packages/ai-parrot/src/parrot/memory/unified/__init__.py)
# MODIFY anchor at packages/ai-parrot/src/parrot/memory/unified/__init__.py:11: from .mixin import LongTermMemoryMixin
# Remove LongTermMemoryMixin export.
# FILL IN: AC08: remove old classes/files/exports with no shims; new public import is parrot.memory.agent_memory.AgentMemoryMixin, also re-exported by parrot.memory.
# FILL IN: AC08: preserve AgentMemory = AnswerMemory and store APIs/text compatibility; no deletion/relocation of persisted snapshots/rows.
# FILL IN: AC08: migrate live example and tests without adding the mixin twice to BasicAgent subclasses; inventory all live consumers and report downstream release coordination.
```

**Why:** A coordinated hard-cut removes both duplicate memory paths while preserving independent store APIs, AnswerMemory and persisted data.

### `packages/ai-parrot/src/parrot/memory/episodic/mixin.py` (MODIFY)

```python
# occurrences: 1 (verified: grep -F -x -c -- 'class EpisodicMemoryMixin:' packages/ai-parrot/src/parrot/memory/episodic/mixin.py)
# MODIFY anchor at packages/ai-parrot/src/parrot/memory/episodic/mixin.py:77: class EpisodicMemoryMixin:
# DELETE obsolete code file after all consumers migrate.
# FILL IN: AC08: remove old classes/files/exports with no shims; new public import is parrot.memory.agent_memory.AgentMemoryMixin, also re-exported by parrot.memory.
# FILL IN: AC08: preserve AgentMemory = AnswerMemory and store APIs/text compatibility; no deletion/relocation of persisted snapshots/rows.
# FILL IN: AC08: migrate live example and tests without adding the mixin twice to BasicAgent subclasses; inventory all live consumers and report downstream release coordination.
```

**Why:** A coordinated hard-cut removes both duplicate memory paths while preserving independent store APIs, AnswerMemory and persisted data.

### `packages/ai-parrot/src/parrot/memory/unified/mixin.py` (MODIFY)

```python
# occurrences: 1 (verified: grep -F -x -c -- 'class LongTermMemoryMixin:' packages/ai-parrot/src/parrot/memory/unified/mixin.py)
# MODIFY anchor at packages/ai-parrot/src/parrot/memory/unified/mixin.py:24: class LongTermMemoryMixin:
# DELETE obsolete code file after all consumers migrate.
# FILL IN: AC08: remove old classes/files/exports with no shims; new public import is parrot.memory.agent_memory.AgentMemoryMixin, also re-exported by parrot.memory.
# FILL IN: AC08: preserve AgentMemory = AnswerMemory and store APIs/text compatibility; no deletion/relocation of persisted snapshots/rows.
# FILL IN: AC08: migrate live example and tests without adding the mixin twice to BasicAgent subclasses; inventory all live consumers and report downstream release coordination.
```

**Why:** A coordinated hard-cut removes both duplicate memory paths while preserving independent store APIs, AnswerMemory and persisted data.

### `examples/shoply/sample.py` (MODIFY)

```python
# occurrences: 1 (verified: grep -F -x -c -- 'from parrot.memory.episodic.mixin import EpisodicMemoryMixin' examples/shoply/sample.py)
# MODIFY anchor at examples/shoply/sample.py:34: from parrot.memory.episodic.mixin import EpisodicMemoryMixin
# Use BasicAgent's built-in capability without duplicate MRO.
# FILL IN: AC08: remove old classes/files/exports with no shims; new public import is parrot.memory.agent_memory.AgentMemoryMixin, also re-exported by parrot.memory.
# FILL IN: AC08: preserve AgentMemory = AnswerMemory and store APIs/text compatibility; no deletion/relocation of persisted snapshots/rows.
# FILL IN: AC08: migrate live example and tests without adding the mixin twice to BasicAgent subclasses; inventory all live consumers and report downstream release coordination.
```

**Why:** A coordinated hard-cut removes both duplicate memory paths while preserving independent store APIs, AnswerMemory and persisted data.

### `packages/ai-parrot/tests/memory/unified/test_mixin.py` (MODIFY)

```python
# occurrences: 1 (verified: grep -F -x -c -- 'class MockAgent(LongTermMemoryMixin):' packages/ai-parrot/tests/memory/unified/test_mixin.py)
# MODIFY anchor at packages/ai-parrot/tests/memory/unified/test_mixin.py:8: class MockAgent(LongTermMemoryMixin):
# Extend/migrate the anchored tests; retain unrelated coverage.
# FILL IN: AC08: remove old classes/files/exports with no shims; new public import is parrot.memory.agent_memory.AgentMemoryMixin, also re-exported by parrot.memory.
# FILL IN: AC08: preserve AgentMemory = AnswerMemory and store APIs/text compatibility; no deletion/relocation of persisted snapshots/rows.
# FILL IN: AC08: migrate live example and tests without adding the mixin twice to BasicAgent subclasses; inventory all live consumers and report downstream release coordination.
# FILL IN: AC03/AC09: real BaseBot coverage remains and unchanged M0 regression passes; historical spike evidence is not rewritten as a live consumer.
```

**Why:** A coordinated hard-cut removes both duplicate memory paths while preserving independent store APIs, AnswerMemory and persisted data.

### `packages/ai-parrot/tests/memory/unified/test_imports.py` (MODIFY)

```python
# occurrences: 1 (verified: grep -F -x -c -- 'def test_unified_package_imports():' packages/ai-parrot/tests/memory/unified/test_imports.py)
# MODIFY anchor at packages/ai-parrot/tests/memory/unified/test_imports.py:4: def test_unified_package_imports():
# Extend/migrate the anchored tests; retain unrelated coverage.
# FILL IN: AC08: remove old classes/files/exports with no shims; new public import is parrot.memory.agent_memory.AgentMemoryMixin, also re-exported by parrot.memory.
# FILL IN: AC08: preserve AgentMemory = AnswerMemory and store APIs/text compatibility; no deletion/relocation of persisted snapshots/rows.
# FILL IN: AC08: migrate live example and tests without adding the mixin twice to BasicAgent subclasses; inventory all live consumers and report downstream release coordination.
# FILL IN: AC03/AC09: real BaseBot coverage remains and unchanged M0 regression passes; historical spike evidence is not rewritten as a live consumer.
```

**Why:** A coordinated hard-cut removes both duplicate memory paths while preserving independent store APIs, AnswerMemory and persisted data.

### `packages/ai-parrot/tests/memory/unified/test_bot_integration.py` (MODIFY)

```python
# occurrences: 1 (verified: grep -F -x -c -- 'class MixinBot(LongTermMemoryMixin, StubBot):' packages/ai-parrot/tests/memory/unified/test_bot_integration.py)
# MODIFY anchor at packages/ai-parrot/tests/memory/unified/test_bot_integration.py:41: class MixinBot(LongTermMemoryMixin, StubBot):
# Extend/migrate the anchored tests; retain unrelated coverage.
# FILL IN: AC08: remove old classes/files/exports with no shims; new public import is parrot.memory.agent_memory.AgentMemoryMixin, also re-exported by parrot.memory.
# FILL IN: AC08: preserve AgentMemory = AnswerMemory and store APIs/text compatibility; no deletion/relocation of persisted snapshots/rows.
# FILL IN: AC08: migrate live example and tests without adding the mixin twice to BasicAgent subclasses; inventory all live consumers and report downstream release coordination.
# FILL IN: AC03/AC09: real BaseBot coverage remains and unchanged M0 regression passes; historical spike evidence is not rewritten as a live consumer.
```

**Why:** A coordinated hard-cut removes both duplicate memory paths while preserving independent store APIs, AnswerMemory and persisted data.

### `packages/ai-parrot/tests/test_episodic_memory.py` (MODIFY)

```python
# occurrences: 1 (verified: grep -F -x -c -- 'class TestMixinIntegration:' packages/ai-parrot/tests/test_episodic_memory.py)
# MODIFY anchor at packages/ai-parrot/tests/test_episodic_memory.py:1084: class TestMixinIntegration:
# Extend/migrate the anchored tests; retain unrelated coverage.
# FILL IN: AC08: remove old classes/files/exports with no shims; new public import is parrot.memory.agent_memory.AgentMemoryMixin, also re-exported by parrot.memory.
# FILL IN: AC08: preserve AgentMemory = AnswerMemory and store APIs/text compatibility; no deletion/relocation of persisted snapshots/rows.
# FILL IN: AC08: migrate live example and tests without adding the mixin twice to BasicAgent subclasses; inventory all live consumers and report downstream release coordination.
# FILL IN: AC03/AC09: real BaseBot coverage remains and unchanged M0 regression passes; historical spike evidence is not rewritten as a live consumer.
```

**Why:** A coordinated hard-cut removes both duplicate memory paths while preserving independent store APIs, AnswerMemory and persisted data.

### FILL IN checklist

- [ ] `packages/ai-parrot/src/parrot/memory/__init__.py` — Replace old mixin exports while preserving other memory names; bounded by the acceptance criteria below.
- [ ] `packages/ai-parrot/src/parrot/memory/episodic/__init__.py` — Remove EpisodicMemoryMixin export; bounded by the acceptance criteria below.
- [ ] `packages/ai-parrot/src/parrot/memory/unified/__init__.py` — Remove LongTermMemoryMixin export; bounded by the acceptance criteria below.
- [ ] `packages/ai-parrot/src/parrot/memory/episodic/mixin.py` — DELETE obsolete code file after all consumers migrate; bounded by the acceptance criteria below.
- [ ] `packages/ai-parrot/src/parrot/memory/unified/mixin.py` — DELETE obsolete code file after all consumers migrate; bounded by the acceptance criteria below.
- [ ] `examples/shoply/sample.py` — Use BasicAgent's built-in capability without duplicate MRO; bounded by the acceptance criteria below.
- [ ] `packages/ai-parrot/tests/memory/unified/test_mixin.py` — Migrate facade behavior tests; bounded by the acceptance criteria below.
- [ ] `packages/ai-parrot/tests/memory/unified/test_imports.py` — New public imports and absent old mixins; bounded by the acceptance criteria below.
- [ ] `packages/ai-parrot/tests/memory/unified/test_bot_integration.py` — Real bot integration rather than duplicate mixin stub; bounded by the acceptance criteria below.
- [ ] `packages/ai-parrot/tests/test_episodic_memory.py` — Retain preference/sala/tool behavior under new flags; bounded by the acceptance criteria below.
- [ ] Replace every blueprint-only stub with working behavior; completed implementation files contain no placeholders.
- [ ] Verify planned imports after dependencies land and refresh contracts on drift.

## Acceptance Criteria

- [ ] AC08: remove old classes/files/exports with no shims; new public import is parrot.memory.agent_memory.AgentMemoryMixin, also re-exported by parrot.memory.
- [ ] AC08: preserve AgentMemory = AnswerMemory and store APIs/text compatibility; no deletion/relocation of persisted snapshots/rows.
- [ ] AC08: migrate live example and tests without adding the mixin twice to BasicAgent subclasses; inventory all live consumers and report downstream release coordination.
- [ ] AC03/AC09: real BaseBot coverage remains and unchanged M0 regression passes; historical spike evidence is not rewritten as a live consumer.
- [ ] Narrow task checks pass; scoped black/ruff pass for touched Python; validation logs identify skipped external coverage explicitly.

## Validation Commands

- `pytest packages/ai-parrot/tests/memory/unified/test_mixin.py packages/ai-parrot/tests/memory/unified/test_imports.py packages/ai-parrot/tests/memory/unified/test_bot_integration.py packages/ai-parrot/tests/test_episodic_memory.py -q`

## Test Specification

- `new_exports_and_old_imports_fail`: AC08: remove old classes/files/exports with no shims; new public import is parrot.memory.agent_memory.AgentMemoryMixin, also re-exported by parrot.memory.
- `live_consumer_capability_matrix`: AC08: preserve AgentMemory = AnswerMemory and store APIs/text compatibility; no deletion/relocation of persisted snapshots/rows.
- `room_preference_and_tool_contracts`: AC08: migrate live example and tests without adding the mixin twice to BasicAgent subclasses; inventory all live consumers and report downstream release coordination.

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

## Hard-cut File Removal

The two old mixin code files are MODIFY targets for complexity schema 1 (which only accepts
CREATE/MODIFY); their explicit final change is deletion. Verify the live-consumer inventory
before `git rm` of those two tracked code paths. Never remove non-code data or add aliases.
