# TASK-5654: Request-local memory scope binding

**Feature**: FEAT-892 - Agent Memory — Unified Integration, User Knowledge and Dynamics
**Spec**: `sdd/specs/agent-memory-mixin.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2–4h)
**Depends-on**: TASK-5653
**Assigned-to**: unassigned
**Parallel**: true
**Parallelism notes**: Consumes MemoryRequestScope in memory/agent_memory/models.py from TASK-5653

## Context

Implement the bounded A0 slice of FEAT-892 revision 0.2. The owner's accepted
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

- ContextVar binding with reset tokens (`packages/ai-parrot/src/parrot/memory/agent_memory/runtime.py`).
- Concurrency, nesting, cancellation and clone isolation (`packages/ai-parrot/tests/memory/agent_memory/test_scope.py`).

**NOT in scope:** FEAT-889 brain stores/schedulers/HTTP/PBAC; optimizer/fitting; provider SDK
or clients/base.py changes; dependency additions; deletion of persisted user/episode data
except the separately authorized scoped forget API; unrelated refactoring.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/memory/agent_memory/runtime.py` | CREATE | ContextVar binding with reset tokens |
| `packages/ai-parrot/tests/memory/agent_memory/test_scope.py` | CREATE | Concurrency, nesting, cancellation and clone isolation |

## Codebase Contract

### Verified Imports

The imports below are the complete blueprint import inventory. Standard-library modules are
built in; pydantic/aiosqlite/click/pytest are already declared in the core pyproject. Existing
repository imports use the verified paths below. Imports from new files are **planned**, supplied
by the named dependencies or this task; re-verify them after dependencies land. The optional
BrainService TYPE_CHECKING reference is explicitly external/future, never a verified production import.

```python
from .models import MemoryRequestScope
from contextvars import ContextVar, Token
import pytest
```

### Existing Signatures and Anchors

- This task creates new files and consumes only the explicitly declared prerequisite contracts.

### Does NOT Exist

- `packages/ai-parrot/src/parrot/memory/agent_memory/runtime.py` is a new delivery path, absent on the verified base.
- `packages/ai-parrot/tests/memory/agent_memory/test_scope.py` is a new delivery path, absent on the verified base.
- `parrot.memory.agent.mixin` does not exist; `memory/agent.py` is the existing AnswerMemory compatibility module.
- Production `BrainService` is a future FEAT-889 contract, not an existing runtime import; never implement its placeholder here.
- No production optimizer/fitting module is authorized by this feature.

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/memory/agent_memory/runtime.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot/tests/memory/agent_memory/test_scope.py",
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

### `packages/ai-parrot/src/parrot/memory/agent_memory/runtime.py` (CREATE)

```python
"""Request-local persistent-memory scope."""
from contextvars import ContextVar, Token
from .models import MemoryRequestScope

_scope: ContextVar[MemoryRequestScope | None] = ContextVar("agent_memory_scope", default=None)
_exposure: ContextVar[str | None] = ContextVar("agent_memory_exposure", default=None)

def bind_memory_scope(scope: MemoryRequestScope) -> Token:
    """Bind trusted scope and return the token required to restore its predecessor."""
    return _scope.set(scope)

def reset_memory_scope(token: Token) -> None:
    """Restore the prior scope, including after nested invocation or cancellation."""
    _scope.reset(token)

def current_memory_scope() -> MemoryRequestScope | None:
    """Return this execution context's scope without consulting shared agent state."""
    return _scope.get()

def bind_memory_exposure(exposure_id: str | None) -> Token:
    """Bind a runtime-minted final-delivery ID, or clear it for a nested invocation."""
    return _exposure.set(exposure_id)

def reset_memory_exposure(token: Token) -> None:
    """Restore the prior attempt's exposure binding in finally."""
    _exposure.reset(token)

def current_memory_exposure() -> str | None:
    """Return only the final-delivery ID bound in this execution context."""
    return _exposure.get()
```

**Why:** ContextVar tokens preserve nested and concurrent principals; clearing inherited exposure prevents a child invocation from claiming its parent's delivered memories.

### `packages/ai-parrot/tests/memory/agent_memory/test_scope.py` (CREATE)

```python
"""Behavioral acceptance tests for Request-local memory scope binding."""
import pytest

def test_parallel_principals_are_isolated() -> None:
    """Verify parallel principals are isolated."""
    # FILL IN: real subject/isolated fixture and observable assertions — task acceptance criteria below.
    # Use pytest.mark.asyncio and async def for async subject calls; never run paid/shared services.
    raise NotImplementedError

def test_nested_token_restores_outer_scope() -> None:
    """Verify nested token restores outer scope."""
    # FILL IN: real subject/isolated fixture and observable assertions — task acceptance criteria below.
    # Use pytest.mark.asyncio and async def for async subject calls; never run paid/shared services.
    raise NotImplementedError

def test_cancellation_and_clone_do_not_leak() -> None:
    """Verify cancellation and clone do not leak."""
    # FILL IN: real subject/isolated fixture and observable assertions — task acceptance criteria below.
    # Use pytest.mark.asyncio and async def for async subject calls; never run paid/shared services.
    raise NotImplementedError
```

**Why:** ContextVar tokens preserve nested and concurrent principals; clearing inherited exposure prevents a child invocation from claiming its parent's delivered memories.

### FILL IN checklist

- [ ] `packages/ai-parrot/src/parrot/memory/agent_memory/runtime.py` — ContextVar binding with reset tokens; bounded by the acceptance criteria below.
- [ ] `packages/ai-parrot/tests/memory/agent_memory/test_scope.py` — Concurrency, nesting, cancellation and clone isolation; bounded by the acceptance criteria below.
- [ ] Replace every blueprint-only stub with working behavior; completed implementation files contain no placeholders.
- [ ] Verify planned imports after dependencies land and refresh contracts on drift.

## Acceptance Criteria

- [ ] AC05: concurrent tenant/user/session scopes never leak; nested reset restores the outer identity.
- [ ] AC05: exceptions and CancelledError reset scope/exposure via finally; nested invocations clear inherited exposure until their own final delivery; cloned tool managers resolve the current request instead of retaining a captured principal.
- [ ] Narrow task checks pass; scoped black/ruff pass for touched Python; validation logs identify skipped external coverage explicitly.

## Validation Commands

- `pytest packages/ai-parrot/tests/memory/agent_memory/test_scope.py -q`

## Test Specification

- `parallel_principals_are_isolated`: AC05: concurrent tenant/user/session scopes never leak; nested reset restores the outer identity.
- `nested_token_restores_outer_scope`: AC05: exceptions and CancelledError reset scope/exposure via finally; nested invocations clear inherited exposure until their own final delivery; cloned tool managers resolve the current request instead of retaining a captured principal.
- `cancellation_and_clone_do_not_leak`: AC05: concurrent tenant/user/session scopes never leak; nested reset restores the outer identity.

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
