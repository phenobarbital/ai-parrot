# TASK-5669: Budgeted context packing and delivery manifests

**Feature**: FEAT-892 - Agent Memory — Unified Integration, User Knowledge and Dynamics
**Spec**: `sdd/specs/agent-memory-mixin.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2–4h)
**Depends-on**: TASK-5658, TASK-5656
**Assigned-to**: unassigned
**Parallel**: true
**Parallelism notes**: Consumes MemoryCandidate and extended MemoryContext from TASK-5658; Consumes versioned MemoryExposure/MemoryCitation schema from TASK-5656

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

- Pack complete scoped candidates with accurate delivered refs (`packages/ai-parrot/src/parrot/memory/unified/context.py`).
- Budget/legacy assembly and trimmed-reference tests (`packages/ai-parrot/tests/memory/unified/test_context.py`).

**NOT in scope:** FEAT-889 brain stores/schedulers/HTTP/PBAC; optimizer/fitting; provider SDK
or clients/base.py changes; dependency additions; deletion of persisted user/episode data
except the separately authorized scoped forget API; unrelated refactoring.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/memory/unified/context.py` | MODIFY | Pack complete scoped candidates with accurate delivered refs |
| `packages/ai-parrot/tests/memory/unified/test_context.py` | MODIFY | Budget/legacy assembly and trimmed-reference tests |

## Codebase Contract

### Verified Imports

The imports below are the complete blueprint import inventory. Standard-library modules are
built in; pydantic/aiosqlite/click/pytest are already declared in the core pyproject. Existing
repository imports use the verified paths below. Imports from new files are **planned**, supplied
by the named dependencies or this task; re-verify them after dependencies land. The optional
BrainService TYPE_CHECKING reference is explicitly external/future, never a verified production import.

```python
from .models import MemoryCandidate, MemoryContext
from parrot.memory.agent_memory.models import MemoryRequestScope
from parrot.memory.unified.context import ContextAssembler
```

### Existing Signatures and Anchors

- `packages/ai-parrot/src/parrot/memory/unified/context.py:17`: `class ContextAssembler:` (exact-line occurrence count 1).
- `packages/ai-parrot/tests/memory/unified/test_context.py:8`: `class TestContextAssembler:` (exact-line occurrence count 1).
- `packages/ai-parrot/src/parrot/memory/unified/context.py:41` — `ContextAssembler.__init__`: `def __init__(self, config: MemoryConfig | None=None) -> None:`
- `packages/ai-parrot/src/parrot/memory/unified/context.py:49` — `ContextAssembler.assemble`: `def assemble(self, episodic_warnings: str='', relevant_skills: str='', conversation: str='', semantic_knowledge: str='') -> MemoryContext:`

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
      "path": "packages/ai-parrot/src/parrot/memory/unified/context.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/memory/unified/test_context.py",
      "action": "MODIFY"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/memory/unified/context.py#ContextAssembler",
    "sym:packages/ai-parrot/src/parrot/memory/unified/context.py#ContextAssembler.__init__",
    "sym:packages/ai-parrot/src/parrot/memory/unified/context.py#ContextAssembler.assemble",
    "sym:packages/ai-parrot/tests/memory/unified/test_context.py#TestContextAssembler"
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

### `packages/ai-parrot/src/parrot/memory/unified/context.py` (MODIFY)

```python
# occurrences: 1 (verified: grep -F -x -c -- 'class ContextAssembler:' packages/ai-parrot/src/parrot/memory/unified/context.py)
# MODIFY anchor at packages/ai-parrot/src/parrot/memory/unified/context.py:17: class ContextAssembler:
from parrot.memory.agent_memory.models import MemoryRequestScope
from .models import MemoryCandidate, MemoryContext

# Add to ContextAssembler while keeping assemble(...) for explicit legacy text callers.
def assemble_candidates(self, candidates: list[MemoryCandidate], *,
                        scope: MemoryRequestScope) -> MemoryContext:
    """Pack whole scoped blocks and retain references only for content actually included."""
    # FILL IN: per-section budget/user priority and deterministic packed digest — AC03/AC11.
    # Drop whole versioned blocks, or identify fragments explicitly; retrieval is not exposure.
    raise NotImplementedError
```

**Why:** Only packed content was delivered; retaining references to dropped text would credit evidence the model never saw.

### `packages/ai-parrot/tests/memory/unified/test_context.py` (MODIFY)

```python
# occurrences: 1 (verified: grep -F -x -c -- 'class TestContextAssembler:' packages/ai-parrot/tests/memory/unified/test_context.py)
# MODIFY anchor at packages/ai-parrot/tests/memory/unified/test_context.py:8: class TestContextAssembler:
# Extend/migrate the anchored tests; retain unrelated coverage.
# FILL IN: AC03: one bounded supplementary block; existing assemble and text formatting remain available to explicit callers.
# FILL IN: AC11: refs match delivered whole blocks or explicitly versioned fragments; dropped/trimmed candidates cannot be cited as full memories.
# FILL IN: AC05/AC06: scope admission precedes packing; user priority and validity are independent of experiential grades.
```

**Why:** Only packed content was delivered; retaining references to dropped text would credit evidence the model never saw.

### FILL IN checklist

- [ ] `packages/ai-parrot/src/parrot/memory/unified/context.py` — Pack complete scoped candidates with accurate delivered refs; bounded by the acceptance criteria below.
- [ ] `packages/ai-parrot/tests/memory/unified/test_context.py` — Budget/legacy assembly and trimmed-reference tests; bounded by the acceptance criteria below.
- [ ] Replace every blueprint-only stub with working behavior; completed implementation files contain no placeholders.
- [ ] Verify planned imports after dependencies land and refresh contracts on drift.

## Acceptance Criteria

- [ ] AC03: one bounded supplementary block; existing assemble and text formatting remain available to explicit callers.
- [ ] AC11: refs match delivered whole blocks or explicitly versioned fragments; dropped/trimmed candidates cannot be cited as full memories.
- [ ] AC05/AC06: scope admission precedes packing; user priority and validity are independent of experiential grades.
- [ ] Narrow task checks pass; scoped black/ruff pass for touched Python; validation logs identify skipped external coverage explicitly.

## Validation Commands

- `pytest packages/ai-parrot/tests/memory/unified/test_context.py -q`

## Test Specification

- `whole_block_budget_and_digest`: AC03: one bounded supplementary block; existing assemble and text formatting remain available to explicit callers.
- `trimmed_candidates_are_uncitable`: AC11: refs match delivered whole blocks or explicitly versioned fragments; dropped/trimmed candidates cannot be cited as full memories.
- `legacy_assemble_and_user_priority`: AC05/AC06: scope admission precedes packing; user priority and validity are independent of experiential grades.

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
