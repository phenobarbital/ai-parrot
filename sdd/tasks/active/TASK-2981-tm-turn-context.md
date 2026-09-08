# TASK-2981: Implement turn declaration registry and invocation receipts

**Feature**: FEAT-538 - Recoverable Task Memory for WorkingMemoryToolkit
**Spec**: `sdd/specs/workingmemory-toolkit.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-2971
**Assigned-to**: unassigned
**Parallel**: true
**Parallelism notes**: May run with ready disjoint tasks such as TASK-2972, TASK-2973, TASK-2974 after prerequisites. Owns distinct output files; do not modify package exports or shared fixtures outside this scope.
**Delivery**: A
**Spec acceptance**: AC4, AC11, AC14

---

## Context

Implements §2 Single Observer and Turn Context of the approved specification. Delivery A establishes in-process continuity and must not be advertised as durable. Consume the committed contracts from TASK-2971 before implementation.

## Scope

- Implement request-local TurnTaskSession with a lock-protected declaration registry and frozen per-invocation TaskContext snapshots.
- Carry invocation/parent/attempt and optional plan mapping receipts across child tasks and explicit thread/worker boundaries.
- Implement finally-safe context lifecycle and deterministic zero/one/multiple declaration attribution; no global cross-session state.

**NOT in scope**: Other task deliverables and files not listed here; provider/client schema changes, unrelated refactors, and new dependencies. Later-task APIs may be represented by explicit protocol fixtures, never runtime stubs shipped as complete implementations.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/tools/working_memory/task_memory/context.py` | CREATE | Scoped implementation |
| `packages/ai-parrot/tests/tools/working_memory/task_memory/test_task_context.py` | CREATE | Task-specific verification / fixtures |

Ownership includes only these files and this task's SDD status/completion fields. You are not alone in the codebase: preserve others' edits and coordinate changes to shared files. CREATE refers to new feature outputs; MODIFY may reference a file created by an earlier dependency.

## Codebase Contract (Anti-Hallucination)

Re-read against core source at `0b4920b2f` on 2026-09-08. The core source tree is unchanged from the spec's pinned implementation commit; task artifacts do not implement the new APIs.

### Verified Imports

```python
from parrot.memory.compaction.models import ToolInvocation, ToolStatus, ContextBudget  # packages/ai-parrot/src/parrot/memory/compaction/models.py:46
from parrot.bots.flows.plan.node import PlanToolNode, build_manifest  # packages/ai-parrot/src/parrot/bots/flows/plan/node.py:347
```

### Existing Signatures to Use

Signature/field excerpts below identify existing APIs, not runnable replacement implementations.

**`packages/ai-parrot/src/parrot/memory/compaction/models.py:46`**

```python
class ToolInvocation:
    tool_name: str
    input: Dict[str, Any]
    output: Optional[str]
    status: ToolStatus
```

ToolInvocation is a dataclass with output/error/elapsed_ms/output_chars/omitted/wm_key; ToolStatus at 24 has COMPLETED and ERROR only; ContextBudget begins at 161.

**`packages/ai-parrot/src/parrot/bots/flows/plan/node.py:347`**

```python
async def _store(self, key: str, payload: Any, *, index: Optional[int]) -> int:
# _call_with_retry at line 414:
async def _call_with_retry(self, args: Dict[str, Any]) -> Any:
```

_call_with_retry dispatches through the manager at 431; _store awaits store_result at 350 after dispatch returns. _read_key at 392 accesses catalog.get synchronously. Factory closure starts around 530.

### Does NOT Exist

- No call ID, CANCELLED/UNKNOWN enum members or task attribution fields exist on this model.
- No plan node ID automatically equals a runtime TaskStep ID; no receipt persists beyond dispatcher context reset yet.
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

- `packages/ai-parrot/src/parrot/memory/compaction/models.py:46` — ToolInvocation is a dataclass with output/error/elapsed_ms/output_chars/omitted/wm_key; ToolStatus at 24 has COMPLETED and ERROR only; ContextBudget begins at 161.
- `packages/ai-parrot/src/parrot/bots/flows/plan/node.py:347` — _call_with_retry dispatches through the manager at 431; _store awaits store_result at 350 after dispatch returns. _read_key at 392 accesses catalog.get synchronously. Factory closure starts around 530.

## Acceptance Criteria

- [ ] A successful running declaration in a child is visible to later siblings through the shared registry.
- [ ] Two declarations before a dispatch yield ambiguous; prior dispatch snapshots never change retroactively.
- [ ] Exceptions, nested invocations and cancellation reset ContextVars without leaking scope.
- [ ] Scope is implemented without changes outside the ownership table, apart from required SDD status/completion updates.
- [ ] Spec criteria AC4, AC11, AC14 are verified for this task's scope and failure cases.
- [ ] Focused verification passes: `uv run pytest packages/ai-parrot/tests/tools/working_memory/task_memory/test_task_context.py -q`; retain output in `artifacts/logs/task-2981-tm-turn-context.log`.
- [ ] Relevant existing regressions and import/format checks pass; any environmental skip is reported explicitly rather than labeled a passed acceptance case.

## Test Specification

Use deterministic fixtures and assert externally observable behavior, including failure atomicity. The following named cases are required; implement them in the test files above with pytest/pytest-asyncio. For the investigation/benchmark deliverable, verify the equivalent measurements and assertions in its runnable benchmark.

| Required case | Expected result |
|---|---|
| `test_child_publish` | A successful running declaration in a child is visible to later siblings through the shared registry. |
| `test_attribution` | Two declarations before a dispatch yield ambiguous; prior dispatch snapshots never change retroactively. |
| `test_reset` | Exceptions, nested invocations and cancellation reset ContextVars without leaking scope. |

New test modules should use local fixtures unless the shared fixture task is already completed. PostgreSQL/Redis concurrency and restart claims require real isolated test services; unit doubles verify only local protocol behavior. Never contact production services or use production data for these tests.

## Agent Instructions

1. Read the approved spec and this task in the feature worktree.
2. Verify every dependency is done in `sdd/tasks/index/workingmemory-toolkit.json` and its completed task artifact exists.
3. Reverify the imports/signatures and read prerequisite implementations; update stale task-specific contract anchors before coding.
4. Set only this task's index status to `in-progress` with assignment/start timestamps and your session ID.
5. Implement the scoped deliverable, preserving others' changes and respecting shared-file ownership/dependency ordering.
6. Run focused tests and relevant regressions, saving logs under `artifacts/logs/`.
7. Move this task to `sdd/tasks/completed/TASK-2981-tm-turn-context.md` after acceptance passes.
8. Update only this task's per-spec index entry to `done`, set completed_at/file/verification, and fill the completion note. Never use the historical monolithic index.
9. Commit scoped implementation and task state as required by `$sdd-start`; do not mark the feature complete after Delivery A alone.

## Completion Note

Not completed. The implementing agent records completed-by, date, verification evidence, notes, and any approved deviations here when acceptance passes.
