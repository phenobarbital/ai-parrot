# TASK-3004: Verify durable restart, concurrency and crash boundaries

**Feature**: FEAT-538 - Recoverable Task Memory for WorkingMemoryToolkit
**Spec**: `sdd/specs/workingmemory-toolkit.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-2997, TASK-2998, TASK-3002, TASK-3003
**Assigned-to**: unassigned
**Parallel**: false
**Parallelism notes**: Serial verification gate: wait for all dependencies and run without concurrent edits to production files exercised by the checks.
**Delivery**: B
**Spec acceptance**: AC1, AC2, AC4, AC5, AC8, AC9, AC10, AC11, AC12, AC14, AC15

---

## Context

Implements §4 Durable restart and crash matrix of the approved specification. Delivery B establishes durable continuity; passing in-memory tests alone does not complete this work. Consume the committed contracts from TASK-2997, TASK-2998, TASK-3002, TASK-3003 before implementation.

## Scope

- Repeat primary continuity after host plus worker restart using real PostgreSQL, Redis and safe persisted payloads.
- Exercise crash barriers before/after blob write, transaction, tool start/effect/terminal event, archive and deletion; verify truthful recovery and no repeated effects.
- Exercise multiple connections/pods, long-call heartbeat, terminal-write failure and stale completion; retain logs and distinguish unavailable-service skips from executed checks.

**NOT in scope**: Other task deliverables and files not listed here; provider/client schema changes, unrelated refactors, and new dependencies. Later-task APIs may be represented by explicit protocol fixtures, never runtime stubs shipped as complete implementations.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/tests/tools/working_memory/task_memory/test_delivery_b.py` | CREATE | Task-specific verification / fixtures |
| `packages/ai-parrot/tests/tools/working_memory/task_memory/test_crash_matrix.py` | CREATE | Task-specific verification / fixtures |

Ownership includes only these files and this task's SDD status/completion fields. You are not alone in the codebase: preserve others' edits and coordinate changes to shared files. CREATE refers to new feature outputs; MODIFY may reference a file created by an earlier dependency.

## Codebase Contract (Anti-Hallucination)

Re-read against core source at `0b4920b2f` on 2026-09-08. The core source tree is unchanged from the spec's pinned implementation commit; task artifacts do not implement the new APIs.

### Verified Imports

```python
from parrot.bots.flows.plan.node import PlanToolNode, build_manifest  # packages/ai-parrot/src/parrot/bots/flows/plan/node.py:347
from parrot.memory.redis import RedisConversation  # packages/ai-parrot/src/parrot/memory/redis.py:238
from parrot.tools.repl_worker.handle import WorkerHandle  # packages/ai-parrot/src/parrot/tools/repl_worker/handle.py:1036
from parrot.interfaces.file import FileManagerInterface  # packages/ai-parrot/src/parrot/interfaces/file/__init__.py:18
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

**`packages/ai-parrot/src/parrot/memory/redis.py:238`**

```python
async def update_history(self, history: ConversationHistory) -> None:
# _store_turn at line 261:
async def _store_turn(self, user_id: str, session_id: str, turn: ConversationTurn, chatbot_id: Optional[str] = None, *, compaction_state: Optional[Dict[str, Any]] = None) -> None:
```

_get_key at 65 includes configured prefix, bot, user and session. Both hash and full-history writers can replace metadata; compaction path reads then writes at 290–297.

**`packages/ai-parrot/src/parrot/tools/repl_worker/handle.py:1036`**

```python
async def inject_dataframe(self, name: str, df: Any) -> None:
# set_var at line 1092:
async def set_var(self, name: str, value: Any) -> None:
```

Injection calls encode_dataframe in an executor and releases shared memory after acknowledgment; namespace APIs include get_var/snapshot/reset at 1087/1103/1108.

**`packages/ai-parrot/src/parrot/interfaces/file/__init__.py:18`**

```python
# Verified export; external method signatures must be pinned in the Phase 0 task.
FileManagerInterface
```

Navigator file-manager interface plus local/temp managers are re-exported eagerly; S3/GCS are lazy exports.

### Does NOT Exist

- No plan node ID automatically equals a runtime TaskStep ID; no receipt persists beyond dispatcher context reset yet.
- No atomic task/compaction metadata merge or per-call fenced lease protocol exists.
- No strict evidence mode or generation-bound ReplBindingResolver exists.
- No versioned Parquet task store is provided by this compatibility shim; do not invent external stream/stat methods.
- The new `parrot.tools.working_memory.task_memory` package and new interface contracts are absent at the verification commit. Dependencies in this task are responsible for introducing them; do not claim their proposed signatures are existing imports.

## Implementation Notes

### Pattern to Follow

Do not mark durable acceptance complete using mocked-only runs.

### Key Constraints

- Use only the approved spec's semantics and defaults; no new dependencies, schema routing parameters, SQLite backend or autonomous retries.
- Existing imports above are verified at the recorded commit. New task-memory symbols are produced by prerequisites; read their committed definitions before importing them.
- Use strict type hints and Pydantic input models for new domain APIs; preserve existing dataclass serializers. Follow black/isort and inherited toolkit logging.
- Keep mutations atomic and scope-bound, heavy work off the event loop, and raw payloads/credentials out of recall and journal context.
- Log focused verification to artifacts/logs/. Re-run existing regressions relevant to touched shared files; service-gated tests must distinguish skipped from passed.

### References in Codebase

- `packages/ai-parrot/src/parrot/bots/flows/plan/node.py:347` — _call_with_retry dispatches through the manager at 431; _store awaits store_result at 350 after dispatch returns. _read_key at 392 accesses catalog.get synchronously. Factory closure starts around 530.
- `packages/ai-parrot/src/parrot/memory/redis.py:238` — _get_key at 65 includes configured prefix, bot, user and session. Both hash and full-history writers can replace metadata; compaction path reads then writes at 290–297.
- `packages/ai-parrot/src/parrot/tools/repl_worker/handle.py:1036` — Injection calls encode_dataframe in an executor and releases shared memory after acknowledgment; namespace APIs include get_var/snapshot/reset at 1087/1103/1108.
- `packages/ai-parrot/src/parrot/interfaces/file/__init__.py:18` — Navigator file-manager interface plus local/temp managers are re-exported eagerly; S3/GCS are lazy exports.

## Acceptance Criteria

- [ ] Supported artifacts below/above RAM cap reload and old evidence remains version-correct after restart.
- [ ] Every specified crash point leaves either committed consistent state or an explicit recoverable orphan/unknown outcome.
- [ ] Concurrent append/alias/association/lease tests prove no scope crossing, sequence gaps or double terminalization.
- [ ] Scope is implemented without changes outside the ownership table, apart from required SDD status/completion updates.
- [ ] Spec criteria AC1, AC2, AC4, AC5, AC8, AC9, AC10, AC11, AC12, AC14, AC15 are verified for this task's scope and failure cases.
- [ ] Focused verification passes: `uv run pytest packages/ai-parrot/tests/tools/working_memory/task_memory/test_delivery_b.py packages/ai-parrot/tests/tools/working_memory/task_memory/test_crash_matrix.py -q`; retain output in `artifacts/logs/task-3004-tm-delivery-b.log`.
- [ ] Relevant existing regressions and import/format checks pass; any environmental skip is reported explicitly rather than labeled a passed acceptance case.

## Test Specification

Use deterministic fixtures and assert externally observable behavior, including failure atomicity. The following named cases are required; implement them in the test files above with pytest/pytest-asyncio. For the investigation/benchmark deliverable, verify the equivalent measurements and assertions in its runnable benchmark.

| Required case | Expected result |
|---|---|
| `test_restart_primary` | Supported artifacts below/above RAM cap reload and old evidence remains version-correct after restart. |
| `test_crash_boundaries` | Every specified crash point leaves either committed consistent state or an explicit recoverable orphan/unknown outcome. |
| `test_multi_pod` | Concurrent append/alias/association/lease tests prove no scope crossing, sequence gaps or double terminalization. |

New test modules should use local fixtures unless the shared fixture task is already completed. PostgreSQL/Redis concurrency and restart claims require real isolated test services; unit doubles verify only local protocol behavior. Never contact production services or use production data for these tests.

## Agent Instructions

1. Read the approved spec and this task in the feature worktree.
2. Verify every dependency is done in `sdd/tasks/index/workingmemory-toolkit.json` and its completed task artifact exists.
3. Reverify the imports/signatures and read prerequisite implementations; update stale task-specific contract anchors before coding.
4. Set only this task's index status to `in-progress` with assignment/start timestamps and your session ID.
5. Implement the scoped deliverable, preserving others' changes and respecting shared-file ownership/dependency ordering.
6. Run focused tests and relevant regressions, saving logs under `artifacts/logs/`.
7. Move this task to `sdd/tasks/completed/TASK-3004-tm-delivery-b.md` after acceptance passes.
8. Update only this task's per-spec index entry to `done`, set completed_at/file/verification, and fill the completion note. Never use the historical monolithic index.
9. Commit scoped implementation and task state as required by `$sdd-start`; do not mark the feature complete after Delivery A alone.

## Completion Note

Not completed. The implementing agent records completed-by, date, verification evidence, notes, and any approved deviations here when acceptance passes.
