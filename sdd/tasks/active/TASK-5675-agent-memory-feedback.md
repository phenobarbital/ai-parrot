# TASK-5675: Permanent coder feedback adapter and historical import

**Feature**: FEAT-892 - Agent Memory — Unified Integration, User Knowledge and Dynamics
**Spec**: `sdd/specs/agent-memory-mixin.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2–4h)
**Depends-on**: TASK-5665, TASK-5662, TASK-5674
**Assigned-to**: unassigned
**Parallel**: true
**Parallelism notes**: Consumes scope-correct ranked episodic retrieval from TASK-5665; Consumes durable dedupe/archive replay from TASK-5662; Consumes verified evidence admission contract from TASK-5674

## Context

Implement the bounded M5 slice of FEAT-892 revision 0.2. The owner's accepted
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

- Stable import/retraction and namespace adapter (`packages/ai-parrot/src/parrot/memory/dynamics/feedback.py`).
- Preserve public context/record/retract through permanent adapter (`packages/ai-parrot/src/parrot/knowledge/wiki/ledger/coder_feedback.py`).
- Deprecation notice while retaining max_age_days effect (`packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/models.py`).
- Import IDs, retractions, outage semantics and age compatibility (`packages/ai-parrot/tests/memory/dynamics/test_feedback.py`).

**NOT in scope:** FEAT-889 brain stores/schedulers/HTTP/PBAC; optimizer/fitting; provider SDK
or clients/base.py changes; dependency additions; deletion of persisted user/episode data
except the separately authorized scoped forget API; unrelated refactoring.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/memory/dynamics/feedback.py` | CREATE | Stable import/retraction and namespace adapter |
| `packages/ai-parrot/src/parrot/knowledge/wiki/ledger/coder_feedback.py` | MODIFY | Preserve public context/record/retract through permanent adapter |
| `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/models.py` | MODIFY | Deprecation notice while retaining max_age_days effect |
| `packages/ai-parrot/tests/memory/dynamics/test_feedback.py` | CREATE | Import IDs, retractions, outage semantics and age compatibility |

## Codebase Contract

### Verified Imports

The imports below are the complete blueprint import inventory. Standard-library modules are
built in; pydantic/aiosqlite/click/pytest are already declared in the core pyproject. Existing
repository imports use the verified paths below. Imports from new files are **planned**, supplied
by the named dependencies or this task; re-verify them after dependencies land. The optional
BrainService TYPE_CHECKING reference is explicitly external/future, never a verified production import.

```python
from parrot.knowledge.wiki.ledger.coder_feedback import CoderFeedbackStore
from parrot.memory.episodic.models import MemoryNamespace
from parrot.memory.episodic.store import EpisodicMemoryStore
from pathlib import Path
import pytest
```

### Existing Signatures and Anchors

- `packages/ai-parrot/src/parrot/knowledge/wiki/ledger/coder_feedback.py:80`: `class CoderFeedbackStore:` (exact-line occurrence count 1).
- `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/models.py:225`: `class FeedbackConfig(BaseModel):` (exact-line occurrence count 1).
- `packages/ai-parrot/src/parrot/knowledge/wiki/ledger/coder_feedback.py`: 80:class CoderFeedbackStore:
- `packages/ai-parrot/src/parrot/knowledge/wiki/ledger/coder_feedback.py:96` — `CoderFeedbackStore.record`: `async def record(self, feedback: CoderFeedback) -> CoderFeedbackReceipt:`
- `packages/ai-parrot/src/parrot/knowledge/wiki/ledger/coder_feedback.py:114` — `CoderFeedbackStore.retract`: `async def retract(self, feedback_id: str, reason: str, actor: str) -> bool:`
- `packages/ai-parrot/src/parrot/knowledge/wiki/ledger/coder_feedback.py:160` — `CoderFeedbackStore.context`: `async def context(self, backend: str, model: str, files: list[str], max_tokens: int=1800, max_age_days: int=90) -> str:`

### Does NOT Exist

- `packages/ai-parrot/src/parrot/memory/dynamics/feedback.py` is a new delivery path, absent on the verified base.
- `packages/ai-parrot/tests/memory/dynamics/test_feedback.py` is a new delivery path, absent on the verified base.
- `parrot.memory.agent.mixin` does not exist; `memory/agent.py` is the existing AnswerMemory compatibility module.
- Production `BrainService` is a future FEAT-889 contract, not an existing runtime import; never implement its placeholder here.
- No production optimizer/fitting module is authorized by this feature.

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/memory/dynamics/feedback.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot/src/parrot/knowledge/wiki/ledger/coder_feedback.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/models.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/memory/dynamics/test_feedback.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/models.py#FeedbackConfig",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/ledger/coder_feedback.py#CoderFeedbackStore",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/ledger/coder_feedback.py#CoderFeedbackStore.context",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/ledger/coder_feedback.py#CoderFeedbackStore.record",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/ledger/coder_feedback.py#CoderFeedbackStore.retract"
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

### `packages/ai-parrot/src/parrot/memory/dynamics/feedback.py` (CREATE)

```python
"""Import historical coder feedback without inventing grades or losing retractions."""
from pathlib import Path
from parrot.memory.episodic.models import MemoryNamespace
from parrot.memory.episodic.store import EpisodicMemoryStore

async def import_feedback(root: Path, *, store: EpisodicMemoryStore,
                          namespace: MemoryNamespace) -> dict[str, int]:
    """Idempotently import lessons and tombstones with original provenance and stable IDs."""
    # FILL IN: accepted permanent UUID namespace, first occurrence and retraction replay — AC16/G2.
    # Resolve shared SDD root, not worker CWD; preserve original timestamp/backend/model/files.
    raise NotImplementedError
```

**Why:** Stable IDs and retraction tombstones make repeated legacy import safe; unavailable feedback must never masquerade as an empty clean history.

### `packages/ai-parrot/src/parrot/knowledge/wiki/ledger/coder_feedback.py` (MODIFY)

```python
# occurrences: 1 (verified: grep -F -x -c -- 'class CoderFeedbackStore:' packages/ai-parrot/src/parrot/knowledge/wiki/ledger/coder_feedback.py)
# MODIFY anchor at packages/ai-parrot/src/parrot/knowledge/wiki/ledger/coder_feedback.py:80: class CoderFeedbackStore:
# Preserve public context/record/retract through permanent adapter.
# FILL IN: AC16/U2: permanent adapter preserves public feedback/context/retract contracts and original stable IDs/timestamps/review_ref provenance.
# FILL IN: AC16/U5: max_age_days warns but retains its current effect this release; no hidden second bound; outage means unavailable, never clean history.
# FILL IN: AC16: re-import honors tombstones; FEAT-887 experience.pitfall and cohort aggregates never become fabricated per-memory grades.
```

**Why:** Stable IDs and retraction tombstones make repeated legacy import safe; unavailable feedback must never masquerade as an empty clean history.

### `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/models.py` (MODIFY)

```python
# occurrences: 1 (verified: grep -F -x -c -- 'class FeedbackConfig(BaseModel):' packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/models.py)
# MODIFY anchor at packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/models.py:225: class FeedbackConfig(BaseModel):
# Deprecation notice while retaining max_age_days effect.
# FILL IN: AC16/U2: permanent adapter preserves public feedback/context/retract contracts and original stable IDs/timestamps/review_ref provenance.
# FILL IN: AC16/U5: max_age_days warns but retains its current effect this release; no hidden second bound; outage means unavailable, never clean history.
# FILL IN: AC16: re-import honors tombstones; FEAT-887 experience.pitfall and cohort aggregates never become fabricated per-memory grades.
```

**Why:** Stable IDs and retraction tombstones make repeated legacy import safe; unavailable feedback must never masquerade as an empty clean history.

### `packages/ai-parrot/tests/memory/dynamics/test_feedback.py` (CREATE)

```python
"""Behavioral acceptance tests for Permanent coder feedback adapter and historical import."""
import pytest

def test_stable_import_and_retraction_idempotency() -> None:
    """Verify stable import and retraction idempotency."""
    # FILL IN: real subject/isolated fixture and observable assertions — task acceptance criteria below.
    # Use pytest.mark.asyncio and async def for async subject calls; never run paid/shared services.
    raise NotImplementedError

def test_outage_is_not_clean_history() -> None:
    """Verify outage is not clean history."""
    # FILL IN: real subject/isolated fixture and observable assertions — task acceptance criteria below.
    # Use pytest.mark.asyncio and async def for async subject calls; never run paid/shared services.
    raise NotImplementedError

def test_age_warning_preserves_current_effect() -> None:
    """Verify age warning preserves current effect."""
    # FILL IN: real subject/isolated fixture and observable assertions — task acceptance criteria below.
    # Use pytest.mark.asyncio and async def for async subject calls; never run paid/shared services.
    raise NotImplementedError
```

**Why:** Stable IDs and retraction tombstones make repeated legacy import safe; unavailable feedback must never masquerade as an empty clean history.

### FILL IN checklist

- [ ] `packages/ai-parrot/src/parrot/memory/dynamics/feedback.py` — Stable import/retraction and namespace adapter; bounded by the acceptance criteria below.
- [ ] `packages/ai-parrot/src/parrot/knowledge/wiki/ledger/coder_feedback.py` — Preserve public context/record/retract through permanent adapter; bounded by the acceptance criteria below.
- [ ] `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/models.py` — Deprecation notice while retaining max_age_days effect; bounded by the acceptance criteria below.
- [ ] `packages/ai-parrot/tests/memory/dynamics/test_feedback.py` — Import IDs, retractions, outage semantics and age compatibility; bounded by the acceptance criteria below.
- [ ] Replace every blueprint-only stub with working behavior; completed implementation files contain no placeholders.
- [ ] Verify planned imports after dependencies land and refresh contracts on drift.

## Acceptance Criteria

- [ ] AC16/U2: permanent adapter preserves public feedback/context/retract contracts and original stable IDs/timestamps/review_ref provenance.
- [ ] AC16/U5: max_age_days warns but retains its current effect this release; no hidden second bound; outage means unavailable, never clean history.
- [ ] AC16: re-import honors tombstones; FEAT-887 experience.pitfall and cohort aggregates never become fabricated per-memory grades.
- [ ] Narrow task checks pass; scoped black/ruff pass for touched Python; validation logs identify skipped external coverage explicitly.

## Validation Commands

- `pytest packages/ai-parrot/tests/memory/dynamics/test_feedback.py -q`

## Test Specification

- `stable_import_and_retraction_idempotency`: AC16/U2: permanent adapter preserves public feedback/context/retract contracts and original stable IDs/timestamps/review_ref provenance.
- `outage_is_not_clean_history`: AC16/U5: max_age_days warns but retains its current effect this release; no hidden second bound; outage means unavailable, never clean history.
- `age_warning_preserves_current_effect`: AC16: re-import honors tombstones; FEAT-887 experience.pitfall and cohort aggregates never become fabricated per-memory grades.

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
