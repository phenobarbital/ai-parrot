# TASK-5676: Coder checked-pattern evidence and review plumbing

**Feature**: FEAT-892 - Agent Memory — Unified Integration, User Knowledge and Dynamics
**Spec**: `sdd/specs/agent-memory-mixin.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2–4h)
**Depends-on**: TASK-5675, TASK-5656, TASK-5674
**Assigned-to**: unassigned
**Parallel**: true
**Parallelism notes**: Consumes permanent feedback adapter from TASK-5675; Consumes CheckedPattern/ReviewSignal from TASK-5656; Consumes versioned exposure and trusted checks from TASK-5674

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

- Add backward-compatible checked_patterns claims (`packages/ai-parrot/src/parrot/flows/dev_loop/models/base.py`).
- Preserve audit/cohorts while linking outcome evidence (`packages/ai-parrot/src/parrot/knowledge/wiki/ledger/coder_reviews.py`).
- Verify delivered refs/checks before memory review (`packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/engine.py`).
- Keep execution_id and public review arguments unchanged (`packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/toolkit.py`).
- Engine-owned exposure/checks, zero-fix delivery and review_ref (`packages/ai-parrot/tests/memory/dynamics/test_coder_evidence.py`).

**NOT in scope:** FEAT-889 brain stores/schedulers/HTTP/PBAC; optimizer/fitting; provider SDK
or clients/base.py changes; dependency additions; deletion of persisted user/episode data
except the separately authorized scoped forget API; unrelated refactoring.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/flows/dev_loop/models/base.py` | MODIFY | Add backward-compatible checked_patterns claims |
| `packages/ai-parrot/src/parrot/knowledge/wiki/ledger/coder_reviews.py` | MODIFY | Preserve audit/cohorts while linking outcome evidence |
| `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/engine.py` | MODIFY | Verify delivered refs/checks before memory review |
| `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/toolkit.py` | MODIFY | Keep execution_id and public review arguments unchanged |
| `packages/ai-parrot/tests/memory/dynamics/test_coder_evidence.py` | CREATE | Engine-owned exposure/checks, zero-fix delivery and review_ref |

## Codebase Contract

### Verified Imports

The imports below are the complete blueprint import inventory. Standard-library modules are
built in; pydantic/aiosqlite/click/pytest are already declared in the core pyproject. Existing
repository imports use the verified paths below. Imports from new files are **planned**, supplied
by the named dependencies or this task; re-verify them after dependencies land. The optional
BrainService TYPE_CHECKING reference is explicitly external/future, never a verified production import.

```python
from parrot.flows.dev_loop.sdd_coder.engine import SddCoderEngine
from parrot.flows.dev_loop.sdd_coder.toolkit import SddCoderToolkit
from parrot.knowledge.wiki.ledger.coder_reviews import CoderReviewStore
from parrot.memory.dynamics.models import CheckedPattern
import pytest
```

### Existing Signatures and Anchors

- `packages/ai-parrot/src/parrot/flows/dev_loop/models/base.py:527`: `class DevelopmentOutput(BaseModel):` (exact-line occurrence count 1).
- `packages/ai-parrot/src/parrot/knowledge/wiki/ledger/coder_reviews.py:21`: `class CoderReview(BaseModel):` (exact-line occurrence count 1).
- `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/engine.py:2766`: `    async def record_review(` (exact-line occurrence count 1).
- `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/toolkit.py:381`: `    async def coder_record_review(` (exact-line occurrence count 1).
- `packages/ai-parrot/src/parrot/flows/dev_loop/models/base.py`: 527:class DevelopmentOutput(BaseModel):
- `packages/ai-parrot/src/parrot/knowledge/wiki/ledger/coder_reviews.py`: 21:class CoderReview(BaseModel):
- `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/engine.py:2766` — `SddCoderEngine.record_review`: `async def record_review(self, feature: str, worktree: str, review: CoderReview, execution_id: Optional[str]=None) -> CoderReviewReceipt:`
- `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/toolkit.py:381` — `SddCoderToolkit.coder_record_review`: `async def coder_record_review(self, feature: str, worktree: str, review: Union[Dict[str, Any], BaseModel], execution_id: str) -> CoderResult:`
- `packages/ai-parrot/src/parrot/knowledge/wiki/ledger/coder_reviews.py:77` — `CoderReviewStore.record`: `async def record(self, review: CoderReviewMeasurement) -> CoderFeedbackReceipt:`

### Does NOT Exist

- `packages/ai-parrot/tests/memory/dynamics/test_coder_evidence.py` is a new delivery path, absent on the verified base.
- `parrot.memory.agent.mixin` does not exist; `memory/agent.py` is the existing AnswerMemory compatibility module.
- Production `BrainService` is a future FEAT-889 contract, not an existing runtime import; never implement its placeholder here.
- No production optimizer/fitting module is authorized by this feature.

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/flows/dev_loop/models/base.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/src/parrot/knowledge/wiki/ledger/coder_reviews.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/engine.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/toolkit.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/memory/dynamics/test_coder_evidence.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/models/base.py#DevelopmentOutput",
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/engine.py#SddCoderEngine.record_review",
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/toolkit.py#SddCoderToolkit.coder_record_review",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/ledger/coder_reviews.py#CoderReview",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/ledger/coder_reviews.py#CoderReviewStore.record"
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

### `packages/ai-parrot/src/parrot/flows/dev_loop/models/base.py` (MODIFY)

```python
# occurrences: 1 (verified: grep -F -x -c -- 'class DevelopmentOutput(BaseModel):' packages/ai-parrot/src/parrot/flows/dev_loop/models/base.py)
# MODIFY anchor at packages/ai-parrot/src/parrot/flows/dev_loop/models/base.py:527: class DevelopmentOutput(BaseModel):
from parrot.memory.dynamics.models import CheckedPattern

# Add to DevelopmentOutput; preserve FEAT-887 lessons and all current delivery fields.
checked_patterns: list[CheckedPattern] = Field(default_factory=list)
```

**Why:** The engine owns attempt/check evidence, so checked_patterns remain claims until matched to the actual delivered version and durable review artifact.

### `packages/ai-parrot/src/parrot/knowledge/wiki/ledger/coder_reviews.py` (MODIFY)

```python
# occurrences: 1 (verified: grep -F -x -c -- 'class CoderReview(BaseModel):' packages/ai-parrot/src/parrot/knowledge/wiki/ledger/coder_reviews.py)
# MODIFY anchor at packages/ai-parrot/src/parrot/knowledge/wiki/ledger/coder_reviews.py:21: class CoderReview(BaseModel):
# Preserve audit/cohorts while linking outcome evidence.
# FILL IN: AC16: DevelopmentOutput.checked_patterns defaults empty; preserve lessons[] and all FEAT-887 interfaces.
# FILL IN: AC11/AC16: engine checks actual attempt/execution/worktree/exposure and durable check evidence; public caller claims cannot assign grades.
# FILL IN: AC16: independently verified zero-fix first attempt can earn GOOD without a fictional correction commit; keep cohort audit and durable review_ref behavior.
```

**Why:** The engine owns attempt/check evidence, so checked_patterns remain claims until matched to the actual delivered version and durable review artifact.

### `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/engine.py` (MODIFY)

```python
# occurrences: 1 (verified: grep -F -x -c -- '    async def record_review(' packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/engine.py)
# MODIFY anchor at packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/engine.py:2766:     async def record_review(
# Verify delivered refs/checks before memory review.
# FILL IN: AC16: DevelopmentOutput.checked_patterns defaults empty; preserve lessons[] and all FEAT-887 interfaces.
# FILL IN: AC11/AC16: engine checks actual attempt/execution/worktree/exposure and durable check evidence; public caller claims cannot assign grades.
# FILL IN: AC16: independently verified zero-fix first attempt can earn GOOD without a fictional correction commit; keep cohort audit and durable review_ref behavior.
```

**Why:** The engine owns attempt/check evidence, so checked_patterns remain claims until matched to the actual delivered version and durable review artifact.

### `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/toolkit.py` (MODIFY)

```python
# occurrences: 1 (verified: grep -F -x -c -- '    async def coder_record_review(' packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/toolkit.py)
# MODIFY anchor at packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/toolkit.py:381:     async def coder_record_review(
# Keep execution_id and public review arguments unchanged.
# FILL IN: AC16: DevelopmentOutput.checked_patterns defaults empty; preserve lessons[] and all FEAT-887 interfaces.
# FILL IN: AC11/AC16: engine checks actual attempt/execution/worktree/exposure and durable check evidence; public caller claims cannot assign grades.
# FILL IN: AC16: independently verified zero-fix first attempt can earn GOOD without a fictional correction commit; keep cohort audit and durable review_ref behavior.
```

**Why:** The engine owns attempt/check evidence, so checked_patterns remain claims until matched to the actual delivered version and durable review artifact.

### `packages/ai-parrot/tests/memory/dynamics/test_coder_evidence.py` (CREATE)

```python
"""Behavioral acceptance tests for Coder checked-pattern evidence and review plumbing."""
import pytest

def test_empty_checked_patterns_backward_compatible() -> None:
    """Verify empty checked patterns backward compatible."""
    # FILL IN: real subject/isolated fixture and observable assertions — task acceptance criteria below.
    # Use pytest.mark.asyncio and async def for async subject calls; never run paid/shared services.
    raise NotImplementedError

def test_forged_or_wrong_attempt_rejected() -> None:
    """Verify forged or wrong attempt rejected."""
    # FILL IN: real subject/isolated fixture and observable assertions — task acceptance criteria below.
    # Use pytest.mark.asyncio and async def for async subject calls; never run paid/shared services.
    raise NotImplementedError

def test_verified_zero_fix_success_keeps_review_ref() -> None:
    """Verify verified zero fix success keeps review ref."""
    # FILL IN: real subject/isolated fixture and observable assertions — task acceptance criteria below.
    # Use pytest.mark.asyncio and async def for async subject calls; never run paid/shared services.
    raise NotImplementedError
```

**Why:** The engine owns attempt/check evidence, so checked_patterns remain claims until matched to the actual delivered version and durable review artifact.

### FILL IN checklist

- [ ] `packages/ai-parrot/src/parrot/flows/dev_loop/models/base.py` — Add backward-compatible checked_patterns claims; bounded by the acceptance criteria below.
- [ ] `packages/ai-parrot/src/parrot/knowledge/wiki/ledger/coder_reviews.py` — Preserve audit/cohorts while linking outcome evidence; bounded by the acceptance criteria below.
- [ ] `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/engine.py` — Verify delivered refs/checks before memory review; bounded by the acceptance criteria below.
- [ ] `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/toolkit.py` — Keep execution_id and public review arguments unchanged; bounded by the acceptance criteria below.
- [ ] `packages/ai-parrot/tests/memory/dynamics/test_coder_evidence.py` — Engine-owned exposure/checks, zero-fix delivery and review_ref; bounded by the acceptance criteria below.
- [ ] Replace every blueprint-only stub with working behavior; completed implementation files contain no placeholders.
- [ ] Verify planned imports after dependencies land and refresh contracts on drift.

## Acceptance Criteria

- [ ] AC16: DevelopmentOutput.checked_patterns defaults empty; preserve lessons[] and all FEAT-887 interfaces.
- [ ] AC11/AC16: engine checks actual attempt/execution/worktree/exposure and durable check evidence; public caller claims cannot assign grades.
- [ ] AC16: independently verified zero-fix first attempt can earn GOOD without a fictional correction commit; keep cohort audit and durable review_ref behavior.
- [ ] Narrow task checks pass; scoped black/ruff pass for touched Python; validation logs identify skipped external coverage explicitly.

## Validation Commands

- `pytest packages/ai-parrot/tests/memory/dynamics/test_coder_evidence.py -q`

## Test Specification

- `empty_checked_patterns_backward_compatible`: AC16: DevelopmentOutput.checked_patterns defaults empty; preserve lessons[] and all FEAT-887 interfaces.
- `forged_or_wrong_attempt_rejected`: AC11/AC16: engine checks actual attempt/execution/worktree/exposure and durable check evidence; public caller claims cannot assign grades.
- `verified_zero_fix_success_keeps_review_ref`: AC16: independently verified zero-fix first attempt can earn GOOD without a fictional correction commit; keep cohort audit and durable review_ref behavior.

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
