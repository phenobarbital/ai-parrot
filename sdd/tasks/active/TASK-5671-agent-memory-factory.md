# TASK-5671: Memory resource factory and ownership lifecycle

**Feature**: FEAT-892 - Agent Memory — Unified Integration, User Knowledge and Dynamics
**Spec**: `sdd/specs/agent-memory-mixin.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2–4h)
**Depends-on**: TASK-5670, TASK-5661, TASK-5667
**Assigned-to**: unassigned
**Parallel**: true
**Parallelism notes**: Consumes UnifiedMemoryManager constructor and cleanup contract from TASK-5670; Consumes SQLiteEpisodeBackend from TASK-5661; Consumes independent UserMemoryStore from TASK-5667

## Context

Implement the bounded M6/A1 slice of FEAT-892 revision 0.2. The owner's accepted
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

- Explicit configured acquisition and partial-failure unwind (`packages/ai-parrot/src/parrot/memory/agent_memory/factory.py`).
- Failure unwind, owned/borrowed resources and flag construction (`packages/ai-parrot/tests/memory/agent_memory/test_factory.py`).

**NOT in scope:** FEAT-889 brain stores/schedulers/HTTP/PBAC; optimizer/fitting; provider SDK
or clients/base.py changes; dependency additions; deletion of persisted user/episode data
except the separately authorized scoped forget API; unrelated refactoring.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/memory/agent_memory/factory.py` | CREATE | Explicit configured acquisition and partial-failure unwind |
| `packages/ai-parrot/tests/memory/agent_memory/test_factory.py` | CREATE | Failure unwind, owned/borrowed resources and flag construction |

## Codebase Contract

### Verified Imports

The imports below are the complete blueprint import inventory. Standard-library modules are
built in; pydantic/aiosqlite/click/pytest are already declared in the core pyproject. Existing
repository imports use the verified paths below. Imports from new files are **planned**, supplied
by the named dependencies or this task; re-verify them after dependencies land. The optional
BrainService TYPE_CHECKING reference is explicitly external/future, never a verified production import.

```python
from .models import AgentMemoryConfig
from parrot.memory.episodic.models import MemoryNamespace
from parrot.memory.unified.manager import UnifiedMemoryManager
import pytest
```

### Existing Signatures and Anchors

- This task creates new files and consumes only the explicitly declared prerequisite contracts.

### Does NOT Exist

- `packages/ai-parrot/src/parrot/memory/agent_memory/factory.py` is a new delivery path, absent on the verified base.
- `packages/ai-parrot/tests/memory/agent_memory/test_factory.py` is a new delivery path, absent on the verified base.
- `parrot.memory.agent.mixin` does not exist; `memory/agent.py` is the existing AnswerMemory compatibility module.
- Production `BrainService` is a future FEAT-889 contract, not an existing runtime import; never implement its placeholder here.
- No production optimizer/fitting module is authorized by this feature.

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/memory/agent_memory/factory.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot/tests/memory/agent_memory/test_factory.py",
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

### `packages/ai-parrot/src/parrot/memory/agent_memory/factory.py` (CREATE)

```python
"""Construct explicitly enabled memory resources with deterministic ownership."""
from parrot.memory.episodic.models import MemoryNamespace
from parrot.memory.unified.manager import UnifiedMemoryManager
from .models import AgentMemoryConfig

async def create_memory_manager(config: AgentMemoryConfig, *, namespace: MemoryNamespace) -> UnifiedMemoryManager:
    """Build enabled resources and unwind any partial acquisition before propagating failure."""
    # FILL IN: own-table user-only connection, episodic backend choice, no startup flush — AC04/AC07.
    # Resolve secrets from environment and persisted paths before opening; retain explicit skill setup.
    # Share configured SQLite database safely without double-closing borrowed dependencies.
    raise NotImplementedError
```

**Why:** Explicit owned versus borrowed resources permit partial-failure cleanup without closing shared dependencies or deleting existing storage.

### `packages/ai-parrot/tests/memory/agent_memory/test_factory.py` (CREATE)

```python
"""Behavioral acceptance tests for Memory resource factory and ownership lifecycle."""
import pytest

def test_user_only_does_not_construct_episodes() -> None:
    """Verify user only does not construct episodes."""
    # FILL IN: real subject/isolated fixture and observable assertions — task acceptance criteria below.
    # Use pytest.mark.asyncio and async def for async subject calls; never run paid/shared services.
    raise NotImplementedError

def test_partial_open_unwinds_resources() -> None:
    """Verify partial open unwinds resources."""
    # FILL IN: real subject/isolated fixture and observable assertions — task acceptance criteria below.
    # Use pytest.mark.asyncio and async def for async subject calls; never run paid/shared services.
    raise NotImplementedError

def test_owned_and_borrowed_cleanup() -> None:
    """Verify owned and borrowed cleanup."""
    # FILL IN: real subject/isolated fixture and observable assertions — task acceptance criteria below.
    # Use pytest.mark.asyncio and async def for async subject calls; never run paid/shared services.
    raise NotImplementedError
```

**Why:** Explicit owned versus borrowed resources permit partial-failure cleanup without closing shared dependencies or deleting existing storage.

### FILL IN checklist

- [ ] `packages/ai-parrot/src/parrot/memory/agent_memory/factory.py` — Explicit configured acquisition and partial-failure unwind; bounded by the acceptance criteria below.
- [ ] `packages/ai-parrot/tests/memory/agent_memory/test_factory.py` — Failure unwind, owned/borrowed resources and flag construction; bounded by the acceptance criteria below.
- [ ] Replace every blueprint-only stub with working behavior; completed implementation files contain no placeholders.
- [ ] Verify planned imports after dependencies land and refresh contracts on drift.

## Acceptance Criteria

- [ ] AC04/AC07: disabled modes acquire no corresponding store; partial failure closes only owned resources and preserves cancellation.
- [ ] AC07/AC08: configured paths and legacy persisted records remain intact; no implicit flush, duplicate lifecycle or secret literals.
- [ ] Narrow task checks pass; scoped black/ruff pass for touched Python; validation logs identify skipped external coverage explicitly.

## Validation Commands

- `pytest packages/ai-parrot/tests/memory/agent_memory/test_factory.py -q`

## Test Specification

- `user_only_does_not_construct_episodes`: AC04/AC07: disabled modes acquire no corresponding store; partial failure closes only owned resources and preserves cancellation.
- `partial_open_unwinds_resources`: AC07/AC08: configured paths and legacy persisted records remain intact; no implicit flush, duplicate lifecycle or secret literals.
- `owned_and_borrowed_cleanup`: AC04/AC07: disabled modes acquire no corresponding store; partial failure closes only owned resources and preserves cancellation.

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
