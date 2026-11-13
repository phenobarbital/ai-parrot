# TASK-5658: Typed memory candidates and compatible context models

**Feature**: FEAT-892 - Agent Memory — Unified Integration, User Knowledge and Dynamics
**Spec**: `sdd/specs/agent-memory-mixin.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2–4h)
**Depends-on**: TASK-5653
**Assigned-to**: unassigned
**Parallel**: true
**Parallelism notes**: Consumes MemoryRequestScope and capability/budget policies from TASK-5653

## Context

Implement the bounded A1/M3 slice of FEAT-892 revision 0.2. The owner's accepted
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

- Typed candidates and user/delivery metadata (`packages/ai-parrot/src/parrot/memory/unified/models.py`).
- Compatibility and typed candidate tests (`packages/ai-parrot/tests/memory/unified/test_models.py`).

**NOT in scope:** FEAT-889 brain stores/schedulers/HTTP/PBAC; optimizer/fitting; provider SDK
or clients/base.py changes; dependency additions; deletion of persisted user/episode data
except the separately authorized scoped forget API; unrelated refactoring.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/memory/unified/models.py` | MODIFY | Typed candidates and user/delivery metadata |
| `packages/ai-parrot/tests/memory/unified/test_models.py` | MODIFY | Compatibility and typed candidate tests |

## Codebase Contract

### Verified Imports

The imports below are the complete blueprint import inventory. Standard-library modules are
built in; pydantic/aiosqlite/click/pytest are already declared in the core pyproject. Existing
repository imports use the verified paths below. Imports from new files are **planned**, supplied
by the named dependencies or this task; re-verify them after dependencies land. The optional
BrainService TYPE_CHECKING reference is explicitly external/future, never a verified production import.

```python
from parrot.memory.agent_memory.models import MemoryRequestScope
```

### Existing Signatures and Anchors

- `packages/ai-parrot/src/parrot/memory/unified/models.py:12`: `class MemoryContext(BaseModel):` (exact-line occurrence count 1).
- `packages/ai-parrot/tests/memory/unified/test_models.py:12`: `class TestMemoryContext:` (exact-line occurrence count 1).

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
      "path": "packages/ai-parrot/src/parrot/memory/unified/models.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/memory/unified/test_models.py",
      "action": "MODIFY"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/memory/unified/models.py#MemoryContext",
    "sym:packages/ai-parrot/tests/memory/unified/test_models.py#TestMemoryContext"
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

### `packages/ai-parrot/src/parrot/memory/unified/models.py` (MODIFY)

```python
# occurrences: 1 (verified: grep -F -x -c -- 'class MemoryContext(BaseModel):' packages/ai-parrot/src/parrot/memory/unified/models.py)
# MODIFY anchor at packages/ai-parrot/src/parrot/memory/unified/models.py:12: class MemoryContext(BaseModel):
from parrot.memory.agent_memory.models import MemoryRequestScope

class MemoryCandidate(BaseModel):
    """Scoped supplementary content with relevance separate from ranking."""
    scope: MemoryRequestScope
    memory_id: str
    content_version: str
    source: str
    text: str
    relevance: float = Field(ge=0.0, le=1.0)
    ranking_score: float | None = None
    # FILL IN: typed provenance and experiential state reference without grading user facts — AC06/AC14.

# Add fields to MemoryContext and formatter support; retain all existing string/token fields.
# FILL IN: user knowledge, ordered delivered refs, digest/exposure metadata — AC03/AC11.
# Extend MemoryConfig section weighting without changing standalone history/text compatibility.
```

**Why:** Separate relevance and ranking fields preserve similarity thresholds, and typed user content avoids applying experiential forgetting to facts.

### `packages/ai-parrot/tests/memory/unified/test_models.py` (MODIFY)

```python
# occurrences: 1 (verified: grep -F -x -c -- 'class TestMemoryContext:' packages/ai-parrot/tests/memory/unified/test_models.py)
# MODIFY anchor at packages/ai-parrot/tests/memory/unified/test_models.py:12: class TestMemoryContext:
# Extend/migrate the anchored tests; retain unrelated coverage.
# FILL IN: AC03: existing MemoryContext strings and to_prompt_string remain usable; user content is contextual data and never a higher-priority instruction.
# FILL IN: AC14: relevance/similarity stay in [0,1]; ranking is separate; user candidates cannot receive a dynamics grade.
# FILL IN: AC04: section budgets normalize only enabled capabilities without a second conversation injection in the agent path.
```

**Why:** Separate relevance and ranking fields preserve similarity thresholds, and typed user content avoids applying experiential forgetting to facts.

### FILL IN checklist

- [ ] `packages/ai-parrot/src/parrot/memory/unified/models.py` — Typed candidates and user/delivery metadata; bounded by the acceptance criteria below.
- [ ] `packages/ai-parrot/tests/memory/unified/test_models.py` — Compatibility and typed candidate tests; bounded by the acceptance criteria below.
- [ ] Replace every blueprint-only stub with working behavior; completed implementation files contain no placeholders.
- [ ] Verify planned imports after dependencies land and refresh contracts on drift.

## Acceptance Criteria

- [ ] AC03: existing MemoryContext strings and to_prompt_string remain usable; user content is contextual data and never a higher-priority instruction.
- [ ] AC14: relevance/similarity stay in [0,1]; ranking is separate; user candidates cannot receive a dynamics grade.
- [ ] AC04: section budgets normalize only enabled capabilities without a second conversation injection in the agent path.
- [ ] Narrow task checks pass; scoped black/ruff pass for touched Python; validation logs identify skipped external coverage explicitly.

## Validation Commands

- `pytest packages/ai-parrot/tests/memory/unified/test_models.py -q`

## Test Specification

- `legacy_text_context_round_trip`: AC03: existing MemoryContext strings and to_prompt_string remain usable; user content is contextual data and never a higher-priority instruction.
- `candidate_scope_and_bounded_similarity`: AC14: relevance/similarity stay in [0,1]; ranking is separate; user candidates cannot receive a dynamics grade.
- `independent_user_section`: AC04: section budgets normalize only enabled capabilities without a second conversation injection in the agent path.

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
