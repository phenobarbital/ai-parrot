# TASK-5655: Dynamics state and immutable parameter models

**Feature**: FEAT-892 - Agent Memory — Unified Integration, User Knowledge and Dynamics
**Spec**: `sdd/specs/agent-memory-mixin.spec.md`
**Status**: blocked
**Priority**: high
**Estimated effort**: M (2–4h)
**Depends-on**: TASK-5653
**Assigned-to**: unassigned
**Parallel**: true
**Parallelism notes**: Consumes FEAT-571 ownership amendment; configuration's independent dynamics enablement from TASK-5653

## Context

Implement the bounded M1 slice of FEAT-892 revision 0.2. The owner's accepted
section 8 decisions govern defaults; earlier proposed wording is not permission to change them.
These are planning artifacts, not evidence that carried G1–G4 gates passed.

## Release Preconditions

G1/G2: accepted production reference/time policy and canonical namespace/content-version encoding must be amended into the spec before release.

Before releasing any blocked task, record the accepted amendment in the spec, expand its
Validation Contract with the released module test paths, regenerate the index test contract
using `parrot sdd tests contract`, and change status through the normal SDD workflow.
Do not infer gate acceptance from a completed spike or from the spec's approved body label.
The current scheduler treats every non-done status as pending: `blocked` is documentary,
not an automatic dispatch fence. Do not launch this feature unattended while gates remain;
the task executor must stop before code if its release preconditions are unmet.

## Scope

- Lightweight dynamics package (`packages/ai-parrot/src/parrot/memory/dynamics/__init__.py`).
- Grade, state, parameters and scoped version refs (`packages/ai-parrot/src/parrot/memory/dynamics/models.py`).
- State validation and parameter immutability (`packages/ai-parrot/tests/memory/dynamics/test_models.py`).

**NOT in scope:** FEAT-889 brain stores/schedulers/HTTP/PBAC; optimizer/fitting; provider SDK
or clients/base.py changes; dependency additions; deletion of persisted user/episode data
except the separately authorized scoped forget API; unrelated refactoring.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/memory/dynamics/__init__.py` | CREATE | Lightweight dynamics package |
| `packages/ai-parrot/src/parrot/memory/dynamics/models.py` | CREATE | Grade, state, parameters and scoped version refs |
| `packages/ai-parrot/tests/memory/dynamics/test_models.py` | CREATE | State validation and parameter immutability |

## Codebase Contract

### Verified Imports

The imports below are the complete blueprint import inventory. Standard-library modules are
built in; pydantic/aiosqlite/click/pytest are already declared in the core pyproject. Existing
repository imports use the verified paths below. Imports from new files are **planned**, supplied
by the named dependencies or this task; re-verify them after dependencies land. The optional
BrainService TYPE_CHECKING reference is explicitly external/future, never a verified production import.

```python
from __future__ import annotations
from datetime import datetime
from enum import IntEnum
from parrot.memory.episodic.models import EpisodicMemory
from parrot.memory.episodic.models import MemoryNamespace
from pydantic import BaseModel, ConfigDict, Field
import pytest
```

### Existing Signatures and Anchors

- `packages/ai-parrot/src/parrot/memory/episodic/models.py`: 214:class MemoryNamespace(BaseModel):
- `packages/ai-parrot/src/parrot/memory/episodic/models.py:179` — `EpisodicMemory.to_dict`: `def to_dict(self) -> dict[str, Any]:`
- `packages/ai-parrot/src/parrot/memory/episodic/models.py:191` — `EpisodicMemory.from_dict`: `def from_dict(cls, data: dict[str, Any]) -> EpisodicMemory:`
- `packages/ai-parrot/src/parrot/memory/episodic/models.py:246` — `MemoryNamespace.build_filter`: `def build_filter(self) -> dict[str, Any]:`
- `packages/ai-parrot/src/parrot/memory/episodic/models.py:283` — `MemoryNamespace.redis_prefix`: `def redis_prefix(self) -> str:`

### Does NOT Exist

- `packages/ai-parrot/src/parrot/memory/dynamics/__init__.py` is a new delivery path, absent on the verified base.
- `packages/ai-parrot/src/parrot/memory/dynamics/models.py` is a new delivery path, absent on the verified base.
- `packages/ai-parrot/tests/memory/dynamics/test_models.py` is a new delivery path, absent on the verified base.
- `parrot.memory.agent.mixin` does not exist; `memory/agent.py` is the existing AnswerMemory compatibility module.
- Production `BrainService` is a future FEAT-889 contract, not an existing runtime import; never implement its placeholder here.
- No production optimizer/fitting module is authorized by this feature.

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/memory/dynamics/__init__.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot/src/parrot/memory/dynamics/models.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot/tests/memory/dynamics/test_models.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/memory/episodic/models.py#EpisodicMemory.from_dict",
    "sym:packages/ai-parrot/src/parrot/memory/episodic/models.py#EpisodicMemory.to_dict",
    "sym:packages/ai-parrot/src/parrot/memory/episodic/models.py#MemoryNamespace",
    "sym:packages/ai-parrot/src/parrot/memory/episodic/models.py#MemoryNamespace.build_filter",
    "sym:packages/ai-parrot/src/parrot/memory/episodic/models.py#MemoryNamespace.redis_prefix"
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

### `packages/ai-parrot/src/parrot/memory/dynamics/__init__.py` (CREATE)

```python
"""Pure persistent-memory dynamics; no storage, optimizer or test-reference imports."""
```

**Why:** Immutable parameter identity makes replay reproducible, while neutral legacy state avoids granting unearned review credit.

### `packages/ai-parrot/src/parrot/memory/dynamics/models.py` (CREATE)

```python
"""Versioned dynamics state; review evidence is added by the evidence-contract task."""
from __future__ import annotations
from datetime import datetime
from enum import IntEnum
from pydantic import BaseModel, ConfigDict, Field
from parrot.memory.episodic.models import MemoryNamespace

class Grade(IntEnum):
    """Ordered FSRS grades, admitted only after evidence verification."""
    AGAIN = 1
    HARD = 2
    GOOD = 3
    EASY = 4

class MemoryParameters(BaseModel):
    """Immutable algorithm, time-policy and parameter identity."""
    model_config = ConfigDict(frozen=True, extra="forbid")
    algorithm: str
    time_policy: str
    parameter_id: str
    weights: tuple[float, ...]
    # FILL IN: 21 finite bounded weights, reference pin and provenance — accepted G1/AC10.

class MemoryState(BaseModel):
    """Persisted state and earned-review count; uninitialized legacy state is neutral."""
    model_config = ConfigDict(frozen=True, extra="forbid")
    difficulty: float | None = None
    stability: float | None = None
    reviewed_at: datetime | None = None
    review_count: int = Field(default=0, ge=0)
    apply_revision: int = Field(default=0, ge=0)
    status: str = "uninitialized"
    # FILL IN: accepted finite state bounds, UTC validation and parameter identity — AC10/AC12.

class MemoryRef(BaseModel):
    """Identify a delivered version inside its full namespace."""
    model_config = ConfigDict(frozen=True, extra="forbid")
    namespace: MemoryNamespace
    kind: str
    memory_id: str
    content_version: str
    # FILL IN: restrict kind to episode/brain and freeze canonical encoding — G2/AC11.
```

**Why:** Immutable parameter identity makes replay reproducible, while neutral legacy state avoids granting unearned review credit.

### `packages/ai-parrot/tests/memory/dynamics/test_models.py` (CREATE)

```python
"""Behavioral acceptance tests for Dynamics state and immutable parameter models."""
import pytest

def test_parameter_bounds_and_immutability() -> None:
    """Verify parameter bounds and immutability."""
    # FILL IN: real subject/isolated fixture and observable assertions — task acceptance criteria below.
    # Use pytest.mark.asyncio and async def for async subject calls; never run paid/shared services.
    raise NotImplementedError

def test_neutral_legacy_state() -> None:
    """Verify neutral legacy state."""
    # FILL IN: real subject/isolated fixture and observable assertions — task acceptance criteria below.
    # Use pytest.mark.asyncio and async def for async subject calls; never run paid/shared services.
    raise NotImplementedError

def test_versioned_namespace_identity() -> None:
    """Verify versioned namespace identity."""
    # FILL IN: real subject/isolated fixture and observable assertions — task acceptance criteria below.
    # Use pytest.mark.asyncio and async def for async subject calls; never run paid/shared services.
    raise NotImplementedError
```

**Why:** Immutable parameter identity makes replay reproducible, while neutral legacy state avoids granting unearned review credit.

### FILL IN checklist

- [ ] `packages/ai-parrot/src/parrot/memory/dynamics/__init__.py` — Lightweight dynamics package; bounded by the acceptance criteria below.
- [ ] `packages/ai-parrot/src/parrot/memory/dynamics/models.py` — Grade, state, parameters and scoped version refs; bounded by the acceptance criteria below.
- [ ] `packages/ai-parrot/tests/memory/dynamics/test_models.py` — State validation and parameter immutability; bounded by the acceptance criteria below.
- [ ] Replace every blueprint-only stub with working behavior; completed implementation files contain no placeholders.
- [ ] Verify planned imports after dependencies land and refresh contracts on drift.

## Acceptance Criteria

- [ ] AC10: parameter sets have exactly 21 finite values within accepted G1 bounds; algorithm/time-policy/parameter provenance cannot be mutated.
- [ ] AC11/AC12: scoped refs include delivered content version; initial/inherited state has zero earned reviews and no promotion credit.
- [ ] Narrow task checks pass; scoped black/ruff pass for touched Python; validation logs identify skipped external coverage explicitly.

## Validation Commands

- `pytest packages/ai-parrot/tests/memory/dynamics/test_models.py -q`

## Test Specification

- `parameter_bounds_and_immutability`: AC10: parameter sets have exactly 21 finite values within accepted G1 bounds; algorithm/time-policy/parameter provenance cannot be mutated.
- `neutral_legacy_state`: AC11/AC12: scoped refs include delivered content version; initial/inherited state has zero earned reviews and no promotion credit.
- `versioned_namespace_identity`: AC10: parameter sets have exactly 21 finite values within accepted G1 bounds; algorithm/time-policy/parameter provenance cannot be mutated.

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
