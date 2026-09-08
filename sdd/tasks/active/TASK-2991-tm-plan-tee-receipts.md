# TASK-2991: Preserve plan and tee artifact provenance after dispatch

**Feature**: FEAT-538 - Recoverable Task Memory for WorkingMemoryToolkit
**Spec**: `sdd/specs/workingmemory-toolkit.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-2981, TASK-2984, TASK-2985
**Assigned-to**: unassigned
**Parallel**: true
**Parallelism notes**: May run with ready disjoint tasks such as TASK-2986, TASK-2987, TASK-2988 after prerequisites. Owns distinct output files; do not modify package exports or shared fixtures outside this scope.
**Delivery**: A
**Spec acceptance**: AC3, AC4, AC5, AC8, AC13

---

## Context

Implements §2 Single Observer; Catalog integration of the approved specification. Delivery A establishes in-process continuity and must not be advertised as durable. Consume the committed contracts from TASK-2981, TASK-2984, TASK-2985 before implementation.

## Scope

- Pass explicit plan run/node/item-to-domain-step mappings through the existing shared node factory and carry receipts past manager return into artifact storage.
- Use awaited enabled catalog reads and exact version descriptors while retaining legacy alias manifest behavior when disabled.
- Propagate tee persistence degradation without false evidence; distinguish aggregate parent results from child attempts and make uncertain-outcome exceptions non-retryable.

**NOT in scope**: Other task deliverables and files not listed here; provider/client schema changes, unrelated refactors, and new dependencies. Later-task APIs may be represented by explicit protocol fixtures, never runtime stubs shipped as complete implementations.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/bots/flows/plan/node.py` | MODIFY | Scoped implementation |
| `packages/ai-parrot/src/parrot/bots/flows/plan/models.py` | MODIFY | Scoped implementation |
| `packages/ai-parrot/src/parrot/tools/execution_plan/toolkit.py` | MODIFY | Scoped implementation |
| `packages/ai-parrot/src/parrot/tools/compression/tee.py` | MODIFY | Scoped implementation |
| `packages/ai-parrot/tests/tools/working_memory/task_memory/test_plan_task_receipts.py` | CREATE | Task-specific verification / fixtures |

Ownership includes only these files and this task's SDD status/completion fields. You are not alone in the codebase: preserve others' edits and coordinate changes to shared files. CREATE refers to new feature outputs; MODIFY may reference a file created by an earlier dependency.

## Codebase Contract (Anti-Hallucination)

Re-read against core source at `0b4920b2f` on 2026-09-08. The core source tree is unchanged from the spec's pinned implementation commit; task artifacts do not implement the new APIs.

### Verified Imports

```python
from parrot.bots.flows.plan.node import PlanToolNode, build_manifest  # packages/ai-parrot/src/parrot/bots/flows/plan/node.py:347
from parrot.bots.flows.plan.models import ArtifactRef, ExecutionManifest  # packages/ai-parrot/src/parrot/bots/flows/plan/models.py:413
from parrot.tools.execution_plan.toolkit import ExecutionPlanToolkit  # packages/ai-parrot/src/parrot/tools/execution_plan/toolkit.py:93
from parrot.tools.compression.tee import CompressionTee  # packages/ai-parrot/src/parrot/tools/compression/tee.py:95
```

### Existing Signatures to Use

Signature/field excerpts below identify existing APIs, not runnable replacement implementations.

**`packages/ai-parrot/src/parrot/bots/flows/plan/node.py:347`**

```python
async def _store(self, key: str, payload: Any, *, index: Optional[int]) -> int:
# _call_with_retry at line 414:
async def _call_with_retry(self, args: Dict[str, Any]) -> Any:
```

_call_with_retry dispatches through the manager at 431; _store awaits store_result at 350 after dispatch returns. _read_key at 392 accesses catalog.get synchronously. Factory closure starts around 530.

**`packages/ai-parrot/src/parrot/bots/flows/plan/models.py:413`**

```python
class ArtifactRef(BaseModel):
    node_id: str
    keys: List[str]
    status: Literal["ok", "skipped", "partial", "error"]
```

ArtifactRef carries alias keys, small facets/error status/bytes_stored; ExecutionManifest at 444 aggregates refs and nodes_failed.

**`packages/ai-parrot/src/parrot/tools/execution_plan/toolkit.py:93`**

```python
def __init__(self, *, tool_manager: Any, working_memory: "WorkingMemoryToolkit", planner_llm: Union[str, dict, Any, None] = None, plans_dir: Union[str, Path, None] = None, allowed_tools: Optional[Sequence[str]] = None, soft_timeout: float = 60.0, permission_context: Optional["PermissionContext"] = None, on_node_event: Optional[Callable[..., Any]] = None, max_completed_runs: int = 50, **kwargs: Any) -> None:
```

Constructor explicitly shares manager and working-memory instances with plan nodes.

**`packages/ai-parrot/src/parrot/tools/compression/tee.py:95`**

```python
async def store(self, tool_name: str, payload: Any, reason: str) -> Optional[str]:
```

store_result is awaited at 119; failures are caught at 127 and return None; retention drops aliases at 140.

### Does NOT Exist

- No plan node ID automatically equals a runtime TaskStep ID; no receipt persists beyond dispatcher context reset yet.
- No immutable artifact_id@version references or domain-step mapping is currently encoded in the manifest.
- No automatic task creation or task-to-plan mapping exists in this constructor.
- No task-memory durability guarantee follows from the existing never-raises tee contract.
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

- `packages/ai-parrot/src/parrot/bots/flows/plan/node.py:347` — _call_with_retry dispatches through the manager at 431; _store awaits store_result at 350 after dispatch returns. _read_key at 392 accesses catalog.get synchronously. Factory closure starts around 530.
- `packages/ai-parrot/src/parrot/bots/flows/plan/models.py:413` — ArtifactRef carries alias keys, small facets/error status/bytes_stored; ExecutionManifest at 444 aggregates refs and nodes_failed.
- `packages/ai-parrot/src/parrot/tools/execution_plan/toolkit.py:93` — Constructor explicitly shares manager and working-memory instances with plan nodes.
- `packages/ai-parrot/src/parrot/tools/compression/tee.py:95` — store_result is awaited at 119; failures are caught at 127 and return None; retention drops aliases at 140.

## Acceptance Criteria

- [ ] Plan and tee writes have the actual producer call/attempt/step after manager context reset.
- [ ] Mapped calls retain plan attribution and unmapped calls remain task-level; no automatic task/step creation.
- [ ] Plan retry loop refuses automatic retry of unknown external effects while ordinary configured transient retries remain intact.
- [ ] Scope is implemented without changes outside the ownership table, apart from required SDD status/completion updates.
- [ ] Spec criteria AC3, AC4, AC5, AC8, AC13 are verified for this task's scope and failure cases.
- [ ] Focused verification passes: `uv run pytest packages/ai-parrot/tests/tools/working_memory/task_memory/test_plan_task_receipts.py -q`; retain output in `artifacts/logs/task-2991-tm-plan-tee-receipts.log`.
- [ ] Relevant existing regressions and import/format checks pass; any environmental skip is reported explicitly rather than labeled a passed acceptance case.

## Test Specification

Use deterministic fixtures and assert externally observable behavior, including failure atomicity. The following named cases are required; implement them in the test files above with pytest/pytest-asyncio. For the investigation/benchmark deliverable, verify the equivalent measurements and assertions in its runnable benchmark.

| Required case | Expected result |
|---|---|
| `test_post_dispatch` | Plan and tee writes have the actual producer call/attempt/step after manager context reset. |
| `test_plan_parallel` | Mapped calls retain plan attribution and unmapped calls remain task-level; no automatic task/step creation. |
| `test_no_unknown_retry` | Plan retry loop refuses automatic retry of unknown external effects while ordinary configured transient retries remain intact. |

New test modules should use local fixtures unless the shared fixture task is already completed. PostgreSQL/Redis concurrency and restart claims require real isolated test services; unit doubles verify only local protocol behavior. Never contact production services or use production data for these tests.

## Agent Instructions

1. Read the approved spec and this task in the feature worktree.
2. Verify every dependency is done in `sdd/tasks/index/workingmemory-toolkit.json` and its completed task artifact exists.
3. Reverify the imports/signatures and read prerequisite implementations; update stale task-specific contract anchors before coding.
4. Set only this task's index status to `in-progress` with assignment/start timestamps and your session ID.
5. Implement the scoped deliverable, preserving others' changes and respecting shared-file ownership/dependency ordering.
6. Run focused tests and relevant regressions, saving logs under `artifacts/logs/`.
7. Move this task to `sdd/tasks/completed/TASK-2991-tm-plan-tee-receipts.md` after acceptance passes.
8. Update only this task's per-spec index entry to `done`, set completed_at/file/verification, and fill the completion note. Never use the historical monolithic index.
9. Commit scoped implementation and task state as required by `$sdd-start`; do not mark the feature complete after Delivery A alone.

## Completion Note

Not completed. The implementing agent records completed-by, date, verification evidence, notes, and any approved deviations here when acceptance passes.
