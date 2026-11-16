# TASK-5656: Exposure, review evidence and durable backend contracts

**Feature**: FEAT-892 - Agent Memory — Unified Integration, User Knowledge and Dynamics
**Spec**: `sdd/specs/agent-memory-mixin.spec.md`
**Status**: blocked
**Priority**: high
**Estimated effort**: M (2–4h)
**Depends-on**: TASK-5655, TASK-5653
**Assigned-to**: unassigned
**Parallel**: true
**Parallelism notes**: Consumes MemoryRef/MemoryState/MemoryParameters and shared dynamics/models.py writer from TASK-5655; Consumes MemoryRequestScope from TASK-5653

## Context

Implement the bounded M1/M3 slice of FEAT-892 revision 0.2. The owner's accepted
section 8 decisions govern defaults; earlier proposed wording is not permission to change them.
These are planning artifacts, not evidence that carried G1–G4 gates passed.

## Release Preconditions

G3/G2: concrete trusted outcome/check adapter, dedupe encoding and revision/replay contracts need accepted amendments.

Before releasing any blocked task, record the accepted amendment in the spec, expand its
Validation Contract with the released module test paths, regenerate the index test contract
using `parrot sdd tests contract`, and change status through the normal SDD workflow.
Do not infer gate acceptance from a completed spike or from the spec's approved body label.
The current scheduler treats every non-done status as pending: `blocked` is documentary,
not an automatic dispatch fence. Do not launch this feature unattended while gates remain;
the task executor must stop before code if its release preconditions are unmet.

## Scope

- Versioned exposure, review and checked-pattern models (`packages/ai-parrot/src/parrot/memory/dynamics/models.py`).
- Optional transactional review protocol (`packages/ai-parrot/src/parrot/memory/dynamics/review_log.py`).
- Rejected synthetic/cross-scope evidence and receipt invariants (`packages/ai-parrot/tests/memory/dynamics/test_evidence_models.py`).

**NOT in scope:** FEAT-889 brain stores/schedulers/HTTP/PBAC; optimizer/fitting; provider SDK
or clients/base.py changes; dependency additions; deletion of persisted user/episode data
except the separately authorized scoped forget API; unrelated refactoring.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/memory/dynamics/models.py` | MODIFY | Versioned exposure, review and checked-pattern models |
| `packages/ai-parrot/src/parrot/memory/dynamics/review_log.py` | CREATE | Optional transactional review protocol |
| `packages/ai-parrot/tests/memory/dynamics/test_evidence_models.py` | CREATE | Rejected synthetic/cross-scope evidence and receipt invariants |

## Codebase Contract

### Verified Imports

The imports below are the complete blueprint import inventory. Standard-library modules are
built in; pydantic/aiosqlite/click/pytest are already declared in the core pyproject. Existing
repository imports use the verified paths below. Imports from new files are **planned**, supplied
by the named dependencies or this task; re-verify them after dependencies land. The optional
BrainService TYPE_CHECKING reference is explicitly external/future, never a verified production import.

```python
from .models import ReviewCommand, ReviewReceipt
from parrot.memory.agent_memory.models import MemoryRequestScope
from typing import Literal, Protocol
from typing import Protocol, runtime_checkable
import pytest
```

### Existing Signatures and Anchors

- `packages/ai-parrot/src/parrot/memory/dynamics/models.py` is created by TASK-5655; anchor `class MemoryRef(BaseModel):` is planned, not an existing verified symbol.

### Does NOT Exist

- `packages/ai-parrot/src/parrot/memory/dynamics/review_log.py` is a new delivery path, absent on the verified base.
- `packages/ai-parrot/tests/memory/dynamics/test_evidence_models.py` is a new delivery path, absent on the verified base.
- `parrot.memory.agent.mixin` does not exist; `memory/agent.py` is the existing AnswerMemory compatibility module.
- Production `BrainService` is a future FEAT-889 contract, not an existing runtime import; never implement its placeholder here.
- No production optimizer/fitting module is authorized by this feature.

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/memory/dynamics/models.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/src/parrot/memory/dynamics/review_log.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot/tests/memory/dynamics/test_evidence_models.py",
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

### `packages/ai-parrot/src/parrot/memory/dynamics/models.py` (MODIFY)

```python
# DEPENDENCY-CREATED MODIFY: packages/ai-parrot/src/parrot/memory/dynamics/models.py from TASK-5655.
# Expected unique anchor: class MemoryRef(BaseModel):
# occurrences now: 0 (file does not exist on base); prerequisite blueprint declares 1.
# Re-read and verify exact count 1 after dependency lands; stop on mismatch.
# Add after MemoryRef; retain the state classes from the prerequisite.
from typing import Literal, Protocol
from parrot.memory.agent_memory.models import MemoryRequestScope

class MemoryExposure(BaseModel):
    """Runtime-minted manifest of memory actually delivered in one model attempt."""
    model_config = ConfigDict(frozen=True, extra="forbid")
    exposure_id: str
    scope: MemoryRequestScope
    attempt_id: str
    refs: tuple[MemoryRef, ...]
    packed_digest: str

class MemoryCitation(BaseModel):
    """A subset of a delivered manifest; a citation never assigns a grade."""
    model_config = ConfigDict(frozen=True, extra="forbid")
    exposure_id: str
    refs: tuple[MemoryRef, ...]

class ReviewSignal(BaseModel):
    """Immutable observed outcome with engine-verifiable provenance."""
    model_config = ConfigDict(frozen=True, extra="forbid")
    outcome_id: str
    outcome_revision: int = Field(ge=0)
    observed_at: datetime
    scope: MemoryRequestScope
    evidence_ref: str
    source: str
    # FILL IN: outcome, corrections, first-attempt and structural recovery schema — accepted G3.
    # Reject synthetic production evidence; a model-provided verified flag grants no authority.

class ReviewCommand(BaseModel):
    """Validated version-specific request for one atomic state transition."""
    model_config = ConfigDict(frozen=True, extra="forbid")
    ref: MemoryRef
    signal: ReviewSignal
    exposure_id: str
    expected_revision: int = Field(ge=0)
    # FILL IN: scoped dedupe identity and admitted grade/no-review result — AC11/AC12.

class ReviewRecord(BaseModel):
    """Replayable evidence and before/after state for a committed application."""
    command: ReviewCommand
    before: MemoryState
    after: MemoryState
    parameter_id: str

class ReviewReceipt(BaseModel):
    """Report durable application, duplicate, conflict or no-review without false success."""
    status: Literal["applied", "duplicate", "conflict", "ignored", "pending", "storage_unavailable"]
    apply_revision: int | None = None
    # FILL IN: target/outcome identity, reason and durable replay reference for pending — AC12.

class CheckedPattern(BaseModel):
    """Untrusted application claim to be checked against engine-owned evidence."""
    pattern: str
    ref: MemoryRef
    exposure_id: str
    evidence_refs: tuple[str, ...] = ()
    # FILL IN: bounded application claim; never accept a caller's grade — AC11/AC16.
```

**Why:** Separating observed outcomes, delivered versions and transaction commands prevents model assertions from becoming trusted reinforcement.

### `packages/ai-parrot/src/parrot/memory/dynamics/review_log.py` (CREATE)

```python
"""Optional durable review capability; baseline episode backends remain valid."""
from typing import Protocol, runtime_checkable
from .models import ReviewCommand, ReviewReceipt

@runtime_checkable
class ReviewBackend(Protocol):
    """Apply scoped dedupe, expected revision, review and state as one transaction."""
    async def apply_review(self, command: ReviewCommand) -> ReviewReceipt:
        """Return applied only after commit; pending requires a durable replay record."""
        ...
```

**Why:** Separating observed outcomes, delivered versions and transaction commands prevents model assertions from becoming trusted reinforcement.

### `packages/ai-parrot/tests/memory/dynamics/test_evidence_models.py` (CREATE)

```python
"""Behavioral acceptance tests for Exposure, review evidence and durable backend contracts."""
import pytest

def test_synthetic_and_forged_scope_rejected() -> None:
    """Verify synthetic and forged scope rejected."""
    # FILL IN: real subject/isolated fixture and observable assertions — task acceptance criteria below.
    # Use pytest.mark.asyncio and async def for async subject calls; never run paid/shared services.
    raise NotImplementedError

def test_receipt_requires_durable_identity() -> None:
    """Verify receipt requires durable identity."""
    # FILL IN: real subject/isolated fixture and observable assertions — task acceptance criteria below.
    # Use pytest.mark.asyncio and async def for async subject calls; never run paid/shared services.
    raise NotImplementedError

def test_checked_pattern_is_not_proof() -> None:
    """Verify checked pattern is not proof."""
    # FILL IN: real subject/isolated fixture and observable assertions — task acceptance criteria below.
    # Use pytest.mark.asyncio and async def for async subject calls; never run paid/shared services.
    raise NotImplementedError
```

**Why:** Separating observed outcomes, delivered versions and transaction commands prevents model assertions from becoming trusted reinforcement.

### FILL IN checklist

- [ ] `packages/ai-parrot/src/parrot/memory/dynamics/models.py` — Versioned exposure, review and checked-pattern models; bounded by the acceptance criteria below.
- [ ] `packages/ai-parrot/src/parrot/memory/dynamics/review_log.py` — Optional transactional review protocol; bounded by the acceptance criteria below.
- [ ] `packages/ai-parrot/tests/memory/dynamics/test_evidence_models.py` — Rejected synthetic/cross-scope evidence and receipt invariants; bounded by the acceptance criteria below.
- [ ] Replace every blueprint-only stub with working behavior; completed implementation files contain no placeholders.
- [ ] Verify planned imports after dependencies land and refresh contracts on drift.

## Acceptance Criteria

- [ ] AC11: evidence uses immutable outcome/revision/identity and delivered refs; no synthetic source or arbitrary verified boolean grants production authority.
- [ ] AC12: commands freeze expected/apply revisions and payload-conflict semantics; pending receipts identify durable replay backing.
- [ ] AC16: CheckedPattern remains a claim; absent checked_patterns later defaults empty without converting FEAT-887 lessons.
- [ ] Narrow task checks pass; scoped black/ruff pass for touched Python; validation logs identify skipped external coverage explicitly.

## Validation Commands

- `pytest packages/ai-parrot/tests/memory/dynamics/test_evidence_models.py -q`

## Test Specification

- `synthetic_and_forged_scope_rejected`: AC11: evidence uses immutable outcome/revision/identity and delivered refs; no synthetic source or arbitrary verified boolean grants production authority.
- `receipt_requires_durable_identity`: AC12: commands freeze expected/apply revisions and payload-conflict semantics; pending receipts identify durable replay backing.
- `checked_pattern_is_not_proof`: AC16: CheckedPattern remains a claim; absent checked_patterns later defaults empty without converting FEAT-887 lessons.

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
