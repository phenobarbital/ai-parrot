# TASK-2973: Implement pure task and plan transition reduction

**Feature**: FEAT-538 - Recoverable Task Memory for WorkingMemoryToolkit
**Spec**: `sdd/specs/workingmemory-toolkit.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-2971
**Assigned-to**: unassigned
**Parallel**: true
**Parallelism notes**: May run with ready disjoint tasks such as TASK-2972, TASK-2975, TASK-2976 after prerequisites. Owns distinct output files; do not modify package exports or shared fixtures outside this scope.
**Delivery**: A
**Spec acceptance**: AC2, AC7

---

## Context

Implements §2 Reducer and Completion Rules of the approved specification. Delivery A establishes in-process continuity and must not be advertised as durable. Consume the committed contracts from TASK-2971 before implementation.

## Scope

- Implement pure versioned reduce for task lifecycle, plan updates, step starts/blocking/completion/reopen/cancel, decisions and hints.
- Reject malformed/unknown events, forward sequence gaps, cycles, duplicate/missing dependencies and illegal terminal mutations; no-op already applied sequences.
- Implement supersession with evidence retention, transitive upstream_reopened blocking and guarded task completion for complete plans only.

**NOT in scope**: Other task deliverables and files not listed here; provider/client schema changes, unrelated refactors, and new dependencies. Later-task APIs may be represented by explicit protocol fixtures, never runtime stubs shipped as complete implementations.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/tools/working_memory/task_memory/reducer.py` | CREATE | Scoped implementation |
| `packages/ai-parrot/tests/tools/working_memory/task_memory/test_reducer_plan.py` | CREATE | Task-specific verification / fixtures |

Ownership includes only these files and this task's SDD status/completion fields. You are not alone in the codebase: preserve others' edits and coordinate changes to shared files. CREATE refers to new feature outputs; MODIFY may reference a file created by an earlier dependency.

## Codebase Contract (Anti-Hallucination)

Re-read against core source at `0b4920b2f` on 2026-09-08. The core source tree is unchanged from the spec's pinned implementation commit; task artifacts do not implement the new APIs.

### Verified Imports

```python
from pydantic import BaseModel, Field  # packages/ai-parrot/src/parrot/tools/working_memory/models.py:7
from parrot.memory.compaction.models import ToolInvocation, ToolStatus, ContextBudget  # packages/ai-parrot/src/parrot/memory/compaction/models.py:46
```

### Existing Signatures to Use

Signature/field excerpts below identify existing APIs, not runnable replacement implementations.

**`packages/ai-parrot/src/parrot/tools/working_memory/models.py:7`**

```python
# Existing input model at line 268:
class GetResultInput(BaseModel):
    key: str
    max_length: int
    include_raw: bool
```

OperationSpecInput begins at 104; GetResultInput default max_length=500 and include_raw=False. Existing Pydantic import is at line 7.

**`packages/ai-parrot/src/parrot/memory/compaction/models.py:46`**

```python
class ToolInvocation:
    tool_name: str
    input: Dict[str, Any]
    output: Optional[str]
    status: ToolStatus
```

ToolInvocation is a dataclass with output/error/elapsed_ms/output_chars/omitted/wm_key; ToolStatus at 24 has COMPLETED and ERROR only; ContextBudget begins at 161.

### Does NOT Exist

- No task-memory Pydantic models or PlanChanges command union exists at this commit.
- No call ID, CANCELLED/UNKNOWN enum members or task attribution fields exist on this model.
- The new `parrot.tools.working_memory.task_memory` package and new interface contracts are absent at the verification commit. Dependencies in this task are responsible for introducing them; do not claim their proposed signatures are existing imports.

## Implementation Notes

### Pattern to Follow

Compose the service/backend contracts from completed prerequisites. Keep new methods private unless the spec explicitly lists an LLM-facing tool. Keep the disabled path behavior and schemas unchanged.

### Key Constraints

- Use only the approved spec's semantics and defaults; no new dependencies, schema routing parameters, SQLite backend or autonomous retries.
- Existing imports above are verified at the recorded commit. New task-memory symbols are produced by prerequisites; read their committed definitions before importing them.
- Use strict type hints and Pydantic input models for new domain APIs; preserve existing dataclass serializers. Follow black/isort and inherited toolkit logging.
- Keep mutations atomic and scope-bound, heavy work off the event loop, and raw payloads/credentials out of recall and journal context.
- Log focused verification to artifacts/logs/. Re-run existing regressions relevant to touched shared files; service-gated tests must distinguish skipped from passed.

### References in Codebase

- `packages/ai-parrot/src/parrot/tools/working_memory/models.py:7` — OperationSpecInput begins at 104; GetResultInput default max_length=500 and include_raw=False. Existing Pydantic import is at line 7.
- `packages/ai-parrot/src/parrot/memory/compaction/models.py:46` — ToolInvocation is a dataclass with output/error/elapsed_ms/output_chars/omitted/wm_key; ToolStatus at 24 has COMPLETED and ERROR only; ContextBudget begins at 161.

## Acceptance Criteria

- [ ] Identical sequences reproduce identical state without clock/random/I/O calls.
- [ ] Invalid plan batches fail; completed criteria cannot silently change; superseded dependencies never count complete.
- [ ] Partial exhausted plans remain active; transitive reopen/hint staleness and task terminal rules hold.
- [ ] Scope is implemented without changes outside the ownership table, apart from required SDD status/completion updates.
- [ ] Spec criteria AC2, AC7 are verified for this task's scope and failure cases.
- [ ] Focused verification passes: `uv run pytest packages/ai-parrot/tests/tools/working_memory/task_memory/test_reducer_plan.py -q`; retain output in `artifacts/logs/task-2973-tm-reducer-plan.log`.
- [ ] Relevant existing regressions and import/format checks pass; any environmental skip is reported explicitly rather than labeled a passed acceptance case.

## Test Specification

Use deterministic fixtures and assert externally observable behavior, including failure atomicity. The following named cases are required; implement them in the test files above with pytest/pytest-asyncio. For the investigation/benchmark deliverable, verify the equivalent measurements and assertions in its runnable benchmark.

| Required case | Expected result |
|---|---|
| `test_replay` | Identical sequences reproduce identical state without clock/random/I/O calls. |
| `test_plan_validation` | Invalid plan batches fail; completed criteria cannot silently change; superseded dependencies never count complete. |
| `test_completion` | Partial exhausted plans remain active; transitive reopen/hint staleness and task terminal rules hold. |

New test modules should use local fixtures unless the shared fixture task is already completed. PostgreSQL/Redis concurrency and restart claims require real isolated test services; unit doubles verify only local protocol behavior. Never contact production services or use production data for these tests.

## Agent Instructions

1. Read the approved spec and this task in the feature worktree.
2. Verify every dependency is done in `sdd/tasks/index/workingmemory-toolkit.json` and its completed task artifact exists.
3. Reverify the imports/signatures and read prerequisite implementations; update stale task-specific contract anchors before coding.
4. Set only this task's index status to `in-progress` with assignment/start timestamps and your session ID.
5. Implement the scoped deliverable, preserving others' changes and respecting shared-file ownership/dependency ordering.
6. Run focused tests and relevant regressions, saving logs under `artifacts/logs/`.
7. Move this task to `sdd/tasks/completed/TASK-2973-tm-reducer-plan.md` after acceptance passes.
8. Update only this task's per-spec index entry to `done`, set completed_at/file/verification, and fill the completion note. Never use the historical monolithic index.
9. Commit scoped implementation and task state as required by `$sdd-start`; do not mark the feature complete after Delivery A alone.

## Completion Note

Not completed. The implementing agent records completed-by, date, verification evidence, notes, and any approved deviations here when acceptance passes.
