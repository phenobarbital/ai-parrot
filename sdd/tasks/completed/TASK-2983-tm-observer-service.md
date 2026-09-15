# TASK-2983: Implement canonical invocation observer lifecycle

**Feature**: FEAT-538 - Recoverable Task Memory for WorkingMemoryToolkit
**Spec**: `sdd/specs/workingmemory-toolkit.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-2980, TASK-2981, TASK-2982
**Assigned-to**: unassigned
**Parallel**: true
**Parallelism notes**: May run with ready disjoint tasks such as TASK-2986, TASK-2987, TASK-2988 after prerequisites. Owns distinct output files; do not modify package exports or shared fixtures outside this scope.
**Delivery**: A
**Spec acceptance**: AC3, AC4, AC8, AC10

---

## Context

Implements §2 Single Observer; Persistence failure modes of the approved specification. Delivery A establishes in-process continuity and must not be advertised as durable. Consume the committed contracts from TASK-2980, TASK-2981, TASK-2982 before implementation.

## Scope

- Implement observer pre-dispatch/terminal APIs and canonical InvocationRecord collector using injected TaskMemory, adapters and omission store.
- Persist starts before effects and terminals before tracked success; classify nonexecuted denials without fictitious starts; preserve cancellation.
- Expose durable fail-closed and explicit best-effort/terminal-unknown outcomes; skip journal mutation for recall/list commands and retain nested receipts.

**NOT in scope**: Other task deliverables and files not listed here; provider/client schema changes, unrelated refactors, and new dependencies. Later-task APIs may be represented by explicit protocol fixtures, never runtime stubs shipped as complete implementations.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/tools/working_memory/task_memory/observer.py` | CREATE | Scoped implementation |
| `packages/ai-parrot/tests/tools/working_memory/task_memory/test_task_observer.py` | CREATE | Task-specific verification / fixtures |

Ownership includes only these files and this task's SDD status/completion fields. You are not alone in the codebase: preserve others' edits and coordinate changes to shared files. CREATE refers to new feature outputs; MODIFY may reference a file created by an earlier dependency.

## Codebase Contract (Anti-Hallucination)

Re-read against core source at `0b4920b2f` on 2026-09-08. The core source tree is unchanged from the spec's pinned implementation commit; task artifacts do not implement the new APIs.

### Verified Imports

```python
from parrot.tools.manager import ToolManager  # packages/ai-parrot/src/parrot/tools/manager.py:1514
from parrot.memory.compaction.models import ToolInvocation, ToolStatus, ContextBudget  # packages/ai-parrot/src/parrot/memory/compaction/models.py:46
from parrot.memory.compaction.normalize import normalize_invocation  # packages/ai-parrot/src/parrot/memory/compaction/normalize.py:129
from parrot.memory.compaction.omission import OmissionStore  # packages/ai-parrot/src/parrot/memory/compaction/omission.py:61
```

### Existing Signatures to Use

Signature/field excerpts below identify existing APIs, not runnable replacement implementations.

**`packages/ai-parrot/src/parrot/tools/manager.py:1514`**

```python
async def execute_tool(self, tool_name: str, parameters: Dict[str, Any], permission_context: Optional["PermissionContext"] = None, *, return_tool_result: bool = False) -> Any:
```

ToolDefinition and AbstractTool branches share guard ordering; full-result mode preserves envelopes. Clone shares tool instances while mutable manager state is distinct (2459–2489).

**`packages/ai-parrot/src/parrot/memory/compaction/models.py:46`**

```python
class ToolInvocation:
    tool_name: str
    input: Dict[str, Any]
    output: Optional[str]
    status: ToolStatus
```

ToolInvocation is a dataclass with output/error/elapsed_ms/output_chars/omitted/wm_key; ToolStatus at 24 has COMPLETED and ERROR only; ContextBudget begins at 161.

**`packages/ai-parrot/src/parrot/memory/compaction/normalize.py:129`**

```python
def normalize_invocation(inv: ToolInvocation) -> ToolInvocation:
```

Pure normalization canonicalizes JSON/text and condenses tracebacks, rebuilding the dataclass while preserving known fields.

**`packages/ai-parrot/src/parrot/memory/compaction/omission.py:61`**

```python
async def put(self, session_key: str, content: str, *, turn_id: Optional[str] = None) -> str:
# get at line 87:
async def get(self, session_key: str, content_id: str) -> Optional[str]:
```

InMemoryOmissionStore begins at 120, RedisOmissionStore at 149. get fetches payload text; built-in IDs already include one om_ prefix.

### Does NOT Exist

- No general ToolExecutionObserver registry or task-memory call receipts exist; guard/compression hooks are not that API.
- No call ID, CANCELLED/UNKNOWN enum members or task attribution fields exist on this model.
- No secret redactor exists in normalize_invocation; normalization cannot be treated as credential removal.
- No bounded availability-probe API exists; custom stores need a backward-compatible unknown fallback.
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

- `packages/ai-parrot/src/parrot/tools/manager.py:1514` — ToolDefinition and AbstractTool branches share guard ordering; full-result mode preserves envelopes. Clone shares tool instances while mutable manager state is distinct (2459–2489).
- `packages/ai-parrot/src/parrot/memory/compaction/models.py:46` — ToolInvocation is a dataclass with output/error/elapsed_ms/output_chars/omitted/wm_key; ToolStatus at 24 has COMPLETED and ERROR only; ContextBudget begins at 161.
- `packages/ai-parrot/src/parrot/memory/compaction/normalize.py:129` — Pure normalization canonicalizes JSON/text and condenses tracebacks, rebuilding the dataclass while preserving known fields.
- `packages/ai-parrot/src/parrot/memory/compaction/omission.py:61` — InMemoryOmissionStore begins at 120, RedisOmissionStore at 149. get fetches payload text; built-in IDs already include one om_ prefix.

## Acceptance Criteria

- [ ] Durable append failure prevents side-effect counter invocation.
- [ ] Effect followed by journal failure returns unknown/degraded and never safe-to-retry success.
- [ ] Repeated recall/listing changes neither journal sequence nor task activity.
- [ ] Exactly one normalized ToolInvocation per observed physical call is available for conversation save.
- [ ] Scope is implemented without changes outside the ownership table, apart from required SDD status/completion updates.
- [ ] Spec criteria AC3, AC4, AC8, AC10 are verified for this task's scope and failure cases.
- [ ] Focused verification passes: `uv run pytest packages/ai-parrot/tests/tools/working_memory/task_memory/test_task_observer.py -q`; retain output in `artifacts/logs/task-2983-tm-observer-service.log`.
- [ ] Relevant existing regressions and import/format checks pass; any environmental skip is reported explicitly rather than labeled a passed acceptance case.

## Test Specification

Use deterministic fixtures and assert externally observable behavior, including failure atomicity. The following named cases are required; implement them in the test files above with pytest/pytest-asyncio. For the investigation/benchmark deliverable, verify the equivalent measurements and assertions in its runnable benchmark.

| Required case | Expected result |
|---|---|
| `test_start_failure` | Durable append failure prevents side-effect counter invocation. |
| `test_terminal_failure` | Effect followed by journal failure returns unknown/degraded and never safe-to-retry success. |
| `test_read_only` | Repeated recall/listing changes neither journal sequence nor task activity. |
| `test_collector` | Exactly one normalized ToolInvocation per observed physical call is available for conversation save. |

New test modules should use local fixtures unless the shared fixture task is already completed. PostgreSQL/Redis concurrency and restart claims require real isolated test services; unit doubles verify only local protocol behavior. Never contact production services or use production data for these tests.

## Agent Instructions

1. Read the approved spec and this task in the feature worktree.
2. Verify every dependency is done in `sdd/tasks/index/workingmemory-toolkit.json` and its completed task artifact exists.
3. Reverify the imports/signatures and read prerequisite implementations; update stale task-specific contract anchors before coding.
4. Set only this task's index status to `in-progress` with assignment/start timestamps and your session ID.
5. Implement the scoped deliverable, preserving others' changes and respecting shared-file ownership/dependency ordering.
6. Run focused tests and relevant regressions, saving logs under `artifacts/logs/`.
7. Move this task to `sdd/tasks/completed/TASK-2983-tm-observer-service.md` after acceptance passes.
8. Update only this task's per-spec index entry to `done`, set completed_at/file/verification, and fill the completion note. Never use the historical monolithic index.
9. Commit scoped implementation and task state as required by `$sdd-start`; do not mark the feature complete after Delivery A alone.

## Completion Note

**Completed by**: Claude Opus 5 (sdd-worker) — session `01WeeSf3QmPq58bBxturogRX`
**Date**: 2026-09-08
**Status**: done

### Evidence
- `test_task_observer.py` → **23 passed**.
  Log: `artifacts/logs/task-2983-tm-observer-service.log`.
- `ruff`/`black --line-length 120 --target-version py312`/`isort` clean.

### Acceptance mapping

| Required case | Evidence |
|---|---|
| `test_start_failure` — durable append failure prevents the side-effect counter | `test_start_failure_durable_mode_prevents_the_effect` asserts `effect.count == 0`, using a **real side-effect counter**, not a mock's call list |
| `test_terminal_failure` — effect + journal failure returns unknown/degraded, never safe-to-retry success | `test_terminal_failure_returns_unknown_not_success`: `effect.count == 1`, outcome `UNKNOWN`, `executed=True`, "do not retry automatically" |
| `test_read_only` — repeated recall/listing changes neither sequence nor activity | `test_read_only_recall_and_listing_append_nothing`: 15 read calls leave `journal.seq == 0` |
| `test_collector` — exactly one normalized `ToolInvocation` per physical call | `test_collector_*` (6 cases) |

### A bug my own test caught
The first version identified a physical attempt by `parent_call_id is
None`, which **counted the parent aggregate**: an ordinary top-level call
also has no parent, so that predicate cannot distinguish the two.
`_is_aggregate()` now asks the real question — does any other call this
turn name it as parent? Evaluated at terminal time, which is sound
because an aggregate necessarily terminates *after* the children it
aggregates.

### Design decisions
1. **A real side-effect counter, not a mock.** The property under test is
   whether an external effect *happened*; only something that records
   having happened can demonstrate that. It stores each invocation rather
   than counting, so "ran once, result lost" is distinguishable from "ran
   twice".
2. **Ordering is asserted mid-flight**, not just at the end:
   `test_start_failure_start_precedes_the_attempt` checks that at the
   instant after `begin()` the start is durable and the effect has *not*
   run.
3. **Denials get no fictitious `tool_started`.** Recording a start for a
   call that never reached a tool body would claim an execution that did
   not occur and corrupt attempt counts. `executed=False`,
   `counted=False`.
4. **Cancellation never suppresses.** Recording is shielded and bounded,
   and a journal failure *while* recording a cancellation is itself
   swallowed — a cancellation we could not record is still a
   cancellation, and bookkeeping must not turn it into a completion.
5. **Read-only exemption is per tool, not a blanket switch** — a
   mutating tool in the same turn still appends.
6. **Artifact receipts are retrievable after the dispatch finished**,
   which is the Phase 0 hazard: `PlanToolNode._store` runs once the
   manager has reset its invocation context.
7. **The observer takes a narrow `append` callable, not a whole store.**
   It appends and does nothing else, so it cannot grow a dependency on
   the store's read paths.
8. **`append=None` still collects.** The observed-but-disabled
   configuration gets canonical capture for the conversation turn without
   any journalling.
