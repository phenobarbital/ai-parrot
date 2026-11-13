# TASK-5653: Common configuration and FEAT-571 scope handoff

**Feature**: FEAT-892 - Agent Memory — Unified Integration, User Knowledge and Dynamics
**Spec**: `sdd/specs/agent-memory-mixin.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2–4h)
**Depends-on**: none
**Assigned-to**: unassigned
**Parallel**: true
**Parallelism notes**: Creates independent capability/scope contracts and the FEAT-571 ownership amendment; no other task produces these inputs.

## Context

Implement the bounded A0/X1 slice of FEAT-892 revision 0.2. The owner's accepted
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

- Lightweight package exports (`packages/ai-parrot/src/parrot/memory/agent_memory/__init__.py`).
- Capability, scope, event and receipt contracts (`packages/ai-parrot/src/parrot/memory/agent_memory/models.py`).
- Transfer pending ownership without changing gate verdicts (`sdd/specs/memory-dynamics.spec.md`).
- Independent flags, precedence and rejected legacy flags (`packages/ai-parrot/tests/memory/agent_memory/test_config.py`).

**NOT in scope:** FEAT-889 brain stores/schedulers/HTTP/PBAC; optimizer/fitting; provider SDK
or clients/base.py changes; dependency additions; deletion of persisted user/episode data
except the separately authorized scoped forget API; unrelated refactoring.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/memory/agent_memory/__init__.py` | CREATE | Lightweight package exports |
| `packages/ai-parrot/src/parrot/memory/agent_memory/models.py` | CREATE | Capability, scope, event and receipt contracts |
| `sdd/specs/memory-dynamics.spec.md` | MODIFY | Transfer pending ownership without changing gate verdicts |
| `packages/ai-parrot/tests/memory/agent_memory/test_config.py` | CREATE | Independent flags, precedence and rejected legacy flags |

## Codebase Contract

### Verified Imports

The imports below are the complete blueprint import inventory. Standard-library modules are
built in; pydantic/aiosqlite/click/pytest are already declared in the core pyproject. Existing
repository imports use the verified paths below. Imports from new files are **planned**, supplied
by the named dependencies or this task; re-verify them after dependencies land. The optional
BrainService TYPE_CHECKING reference is explicitly external/future, never a verified production import.

```python
from .models import AgentMemoryConfig, MemoryEvent, MemoryRequestScope, MemoryWriteReceipt
from __future__ import annotations
from datetime import datetime
from pydantic import BaseModel, ConfigDict, Field
from typing import Any, Literal
import pytest
```

### Existing Signatures and Anchors

- `sdd/specs/memory-dynamics.spec.md:4`: `id: FEAT-571` (exact-line occurrence count 1).

### Does NOT Exist

- `packages/ai-parrot/src/parrot/memory/agent_memory/__init__.py` is a new delivery path, absent on the verified base.
- `packages/ai-parrot/src/parrot/memory/agent_memory/models.py` is a new delivery path, absent on the verified base.
- `packages/ai-parrot/tests/memory/agent_memory/test_config.py` is a new delivery path, absent on the verified base.
- `parrot.memory.agent.mixin` does not exist; `memory/agent.py` is the existing AnswerMemory compatibility module.
- Production `BrainService` is a future FEAT-889 contract, not an existing runtime import; never implement its placeholder here.
- No production optimizer/fitting module is authorized by this feature.

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/memory/agent_memory/__init__.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot/src/parrot/memory/agent_memory/models.py",
      "action": "CREATE"
    },
    {
      "path": "sdd/specs/memory-dynamics.spec.md",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/memory/agent_memory/test_config.py",
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

### `packages/ai-parrot/src/parrot/memory/agent_memory/__init__.py` (CREATE)

```python
"""Agent persistent-memory contracts; no eager storage or brain imports."""
from .models import AgentMemoryConfig, MemoryEvent, MemoryRequestScope, MemoryWriteReceipt

__all__ = ["AgentMemoryConfig", "MemoryEvent", "MemoryRequestScope", "MemoryWriteReceipt"]
```

**Why:** Independent flags and immutable scope prevent user-only mode from accidentally constructing episodic storage; the ownership amendment prevents duplicated FEAT-571 work.

### `packages/ai-parrot/src/parrot/memory/agent_memory/models.py` (CREATE)

```python
"""Independent persistent-memory configuration and trusted invocation data."""
from __future__ import annotations
from datetime import datetime
from typing import Any, Literal
from pydantic import BaseModel, ConfigDict, Field

class AgentMemoryConfig(BaseModel):
    """Configure capabilities without coupling user knowledge to episodes."""
    model_config = ConfigDict(extra="forbid")
    enable_episodic_memory: bool = False
    enable_user_memory: bool = False
    enable_brain: bool = False
    memory_dynamics: bool = False
    max_context_tokens: int = Field(default=2000, ge=0)
    # FILL IN: section budgets, explicit skills policy and backend options — AC04/AC07, Q4.
    # Resolve secret values from environment; preserve configured data paths and never flush at startup.

class MemoryRequestScope(BaseModel):
    """Carry immutable runtime-derived identity; missing identity never names a profile."""
    model_config = ConfigDict(frozen=True, extra="forbid")
    tenant_id: str
    agent_id: str
    user_id: str | None = None
    session_id: str | None = None
    room_id: str | None = None
    crew_id: str | None = None
    model_id: str | None = None
    execution_id: str | None = None
    turn_id: str
    identity_provenance: str
    # FILL IN: validate trusted provenance and nonempty required dimensions — AC05/Q4.

class MemoryEvent(BaseModel):
    """Identify one observed tool attempt, response or knowledge event."""
    model_config = ConfigDict(frozen=True, extra="forbid")
    event_id: str
    kind: Literal["tool", "response", "user_knowledge"]
    scope: MemoryRequestScope
    observed_at: datetime
    evidence_refs: tuple[str, ...] = ()
    payload: dict[str, Any] = Field(default_factory=dict)
    # FILL IN: aware UTC time, bounded payload and retry identity validation — AC05/AC09.

class MemoryWriteReceipt(BaseModel):
    """Report committed effects and constituent failures without false acknowledgement."""
    model_config = ConfigDict(frozen=True, extra="forbid")
    event_id: str
    scope: MemoryRequestScope
    status: Literal["applied", "duplicate", "conflict", "ignored", "storage_unavailable"]
    episode_ids: tuple[str, ...] = ()
    knowledge_ids: tuple[str, ...] = ()
    review_ids: tuple[str, ...] = ()
    # FILL IN: represent mixed-operation failures explicitly — AC12; pending requires durable replay.
```

**Why:** Independent flags and immutable scope prevent user-only mode from accidentally constructing episodic storage; the ownership amendment prevents duplicated FEAT-571 work.

### `sdd/specs/memory-dynamics.spec.md` (MODIFY)

```markdown
# occurrences: 1 (verified: grep -F -x -c -- 'id: FEAT-571' sdd/specs/memory-dynamics.spec.md)
# MODIFY anchor at sdd/specs/memory-dynamics.spec.md:4: id: FEAT-571
<!-- Add an ownership amendment alongside the module/gate rules, not inside YAML. -->
FEAT-892 owns pending M1/M2/M3/M5/M6 and agent integration. FEAT-889 phase 2
(M8–M9) owns M4. G1–G4/M0 task history and evidence remain unchanged.
<!-- FILL IN: link both successor specs and retain every unaccepted gate as blocked — AC01/AC02. -->
```

**Why:** Independent flags and immutable scope prevent user-only mode from accidentally constructing episodic storage; the ownership amendment prevents duplicated FEAT-571 work.

### `packages/ai-parrot/tests/memory/agent_memory/test_config.py` (CREATE)

```python
"""Behavioral acceptance tests for Common configuration and FEAT-571 scope handoff."""
import pytest

def test_capability_matrix_and_brain_implication() -> None:
    """Verify capability matrix and brain implication."""
    # FILL IN: real subject/isolated fixture and observable assertions — task acceptance criteria below.
    # Use pytest.mark.asyncio and async def for async subject calls; never run paid/shared services.
    raise NotImplementedError

def test_constructor_precedence_and_legacy_flag_error() -> None:
    """Verify constructor precedence and legacy flag error."""
    # FILL IN: real subject/isolated fixture and observable assertions — task acceptance criteria below.
    # Use pytest.mark.asyncio and async def for async subject calls; never run paid/shared services.
    raise NotImplementedError

def test_frozen_scope_and_bounded_event() -> None:
    """Verify frozen scope and bounded event."""
    # FILL IN: real subject/isolated fixture and observable assertions — task acceptance criteria below.
    # Use pytest.mark.asyncio and async def for async subject calls; never run paid/shared services.
    raise NotImplementedError
```

**Why:** Independent flags and immutable scope prevent user-only mode from accidentally constructing episodic storage; the ownership amendment prevents duplicated FEAT-571 work.

### FILL IN checklist

- [ ] `packages/ai-parrot/src/parrot/memory/agent_memory/__init__.py` — Lightweight package exports; bounded by the acceptance criteria below.
- [ ] `packages/ai-parrot/src/parrot/memory/agent_memory/models.py` — Capability, scope, event and receipt contracts; bounded by the acceptance criteria below.
- [ ] `sdd/specs/memory-dynamics.spec.md` — Transfer pending ownership without changing gate verdicts; bounded by the acceptance criteria below.
- [ ] `packages/ai-parrot/tests/memory/agent_memory/test_config.py` — Independent flags, precedence and rejected legacy flags; bounded by the acceptance criteria below.
- [ ] Replace every blueprint-only stub with working behavior; completed implementation files contain no placeholders.
- [ ] Verify planned imports after dependencies land and refresh contracts on drift.

## Acceptance Criteria

- [ ] AC01: FEAT-571 explicitly transfers only pending M1/M2/M3/M5/M6; M4 stays with FEAT-889 and completed tasks/index/evidence are unchanged.
- [ ] AC04/Q4: all four user/episode combinations are representable; brain implies effective episodes but never user knowledge; constructor kwargs override class defaults then model defaults.
- [ ] AC05: scope/events reject untrusted or malformed identities and mutable request rebinding; missing user identity is distinct from anonymous history fallback.
- [ ] AC07: legacy flags are rejected with replacement names; section budgets are bounded and no existing storage path is deleted or implicitly flushed.
- [ ] Narrow task checks pass; scoped black/ruff pass for touched Python; validation logs identify skipped external coverage explicitly.

## Validation Commands

- `pytest packages/ai-parrot/tests/memory/agent_memory/test_config.py -q`

## Test Specification

- `capability_matrix_and_brain_implication`: AC01: FEAT-571 explicitly transfers only pending M1/M2/M3/M5/M6; M4 stays with FEAT-889 and completed tasks/index/evidence are unchanged.
- `constructor_precedence_and_legacy_flag_error`: AC04/Q4: all four user/episode combinations are representable; brain implies effective episodes but never user knowledge; constructor kwargs override class defaults then model defaults.
- `frozen_scope_and_bounded_event`: AC05: scope/events reject untrusted or malformed identities and mutable request rebinding; missing user identity is distinct from anonymous history fallback.

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
