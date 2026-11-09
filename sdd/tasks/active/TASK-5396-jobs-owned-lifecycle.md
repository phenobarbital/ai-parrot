# TASK-5396: Add owned cancellation, bounded persistence and per-user job queries

**Feature**: FEAT-851 - Queued chat commands for the integrations
**Spec**: `sdd/specs/queued-commands-integrations.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-5395
**Assigned-to**: unassigned

## Context

Implements the scoped FEAT-851 deliverable below. Read spec §§2–7 for the fixed behavior and edge cases. This task creates implementation artifacts only when picked up by sdd-start.

## Scope

- Extend the relocated JobManager and RedisJobStore with all M1 lifecycle contracts.
- Keep locally created records authoritative; never insert foreign reads or listings into the owned jobs map.
- Make start/admission local-only; connect/save/delete in tracked bounded work, serialize saves per job and bound shutdown draining.
- Preserve awaited update_metadata/report_progress persistence semantics within persistence_timeout; failed persistence retains the local record.
- Add per-user Redis indexes, pruning and terminal TTL, and non-destructive cancellation with the caller reason.

**NOT in scope**: files outside the table, new dependencies, external workers, cross-worker cancel/dedup, or changes to strict review semantics beyond the declared registration update.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/jobs/manager.py` | MODIFY | Ownership, cancellation and bounded persistence |
| `packages/ai-parrot/src/parrot/jobs/redis_store.py` | MODIFY | Per-user index maintenance and filtering |
| `packages/ai-parrot/tests/test_parrot_jobs_core.py` | MODIFY | Task-owned regression coverage |

## Codebase Contract (Anti-Hallucination)

Verified against the current dev source on 2026-11-09. Existing signatures below were re-read with AST and source inspection; MODIFY anchors were re-counted with `grep -cF`. Symbols provided by dependencies are explicitly future contracts, not existing imports.

### Verified Imports

```python
import asyncio
from typing import Any, Optional
from parrot.jobs import Job, JobManager, JobStatus, RedisJobStore
import pytest
```

Standard-library imports are available; pydantic/pytest and platform SDK imports reuse the declared project stack. New imports are supplied only by this task or its named prerequisites; revalidate them when prerequisites land. Existing source relocation preserves its original import block.

### Existing Signatures to Use

```python
# packages/ai-parrot-server/src/parrot/handlers/jobs/job.py:171
def create_job(self, job_id: str, obj_id: str, query: Any, user_id: Optional[str]=None, session_id: Optional[str]=None, execution_mode: Optional[str]=None) -> Job

# packages/ai-parrot-server/src/parrot/handlers/jobs/job.py:63
async def start(self) -> None

# packages/ai-parrot-server/src/parrot/handlers/jobs/job.py:80
async def stop(self) -> None

# packages/ai-parrot-server/src/parrot/handlers/jobs/job.py:122
async def update_metadata(self, job_id: str, **values: Any) -> Optional[Job]

# packages/ai-parrot-server/src/parrot/handlers/jobs/job.py:228
async def _run_job(self, job_id: str, execution_func: Callable[[], Awaitable[Any]]) -> None

# packages/ai-parrot-server/src/parrot/handlers/jobs/job.py:288
async def get_job_async(self, job_id: str) -> Optional[Job]

# packages/ai-parrot-server/src/parrot/handlers/jobs/job.py:347
async def list_jobs_async(self, obj_id: Optional[str]=None, status: Optional[JobStatus]=None, limit: int=100) -> list

# packages/ai-parrot-server/src/parrot/handlers/jobs/redis_store.py:209
async def save(self, job: Job) -> None

# packages/ai-parrot-server/src/parrot/handlers/jobs/redis_store.py:247
async def delete(self, job_id: str) -> bool

# packages/ai-parrot-server/src/parrot/handlers/jobs/redis_store.py:261
async def list_jobs(self, obj_id: Optional[str]=None, status: Optional[JobStatus]=None, limit: int=100) -> List[Job]
```

### Does NOT Exist

- cancel_job, user_id listing filters and per-user Redis indexes do not exist before this task.
- No distributed cancel or persistence-before-ack guarantee is introduced.

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/jobs/manager.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/src/parrot/jobs/redis_store.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/test_parrot_jobs_core.py",
      "action": "MODIFY"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-server/src/parrot/handlers/jobs/job.py#JobManager.create_job",
    "sym:packages/ai-parrot-server/src/parrot/handlers/jobs/job.py#JobManager.start",
    "sym:packages/ai-parrot-server/src/parrot/handlers/jobs/job.py#JobManager.stop",
    "sym:packages/ai-parrot-server/src/parrot/handlers/jobs/job.py#JobManager.update_metadata",
    "sym:packages/ai-parrot-server/src/parrot/handlers/jobs/job.py#JobManager._run_job",
    "sym:packages/ai-parrot-server/src/parrot/handlers/jobs/job.py#JobManager.get_job_async",
    "sym:packages/ai-parrot-server/src/parrot/handlers/jobs/job.py#JobManager.list_jobs_async",
    "sym:packages/ai-parrot-server/src/parrot/handlers/jobs/redis_store.py#RedisJobStore.save",
    "sym:packages/ai-parrot-server/src/parrot/handlers/jobs/redis_store.py#RedisJobStore.delete",
    "sym:packages/ai-parrot-server/src/parrot/handlers/jobs/redis_store.py#RedisJobStore.list_jobs"
  ]
}
```

## Implementation Notes

- Redis tests use localhost db 15 with unique prefixes and skip only those live Redis cases when unavailable. Use fake stores for mandatory boundedness/ownership tests; fakeredis is absent.
- Also cover unknown/finished cancel, all list filters and cancellation before the runner first executes. Existing progress tests remain in the feature validation contract.

**Parallelism**: TASK-5395 creates parrot.jobs.JobManager and RedisJobStore; serializes edits to the moved manager/store and test_parrot_jobs_core.py.

## Implementation Blueprint

Planning skeletons only: complete all bounded FILL IN items; never leave placeholders in implementation files. Preserve the spec interface signatures.

### Steps (in order)

1. Verify prerequisites and the exact anchors below — dependent files may have moved since planning.
2. Apply only the declared per-file changes — this bounds ownership and preserves unrelated behavior.
3. Complete the acceptance-criteria branches and regression tests — these pin failure, ownership and compatibility boundaries.
4. Run the task validation and format/lint touched Python files — publish complete working files only.

### `packages/ai-parrot/src/parrot/jobs/manager.py` (MODIFY)

Created by TASK-5395 as a behavior-preserving move. Revalidate this anchor after the dependency lands.
- Anchor `class JobManager:`; occurrences: **1** (`grep -cF`); packages/ai-parrot-server/src/parrot/handlers/jobs/job.py:22.

```python
# Within JobManager, retain all existing constructor positional parameters.
# Add keyword-only persistence_timeout: float = 0.5 and validate positivity.
# create_job(..., *, metadata: Optional[dict[str, Any]] = None) -> Job
async def cancel_job(self, job_id: str, reason: str = "Job was cancelled") -> bool:
    """Cancel an owned live task while retaining its record and supplied reason."""
    # FILL IN: liveness check, stored reason, cancellation; AC1 and pre-run race coverage.
    raise NotImplementedError
def list_jobs(self, obj_id: Optional[str] = None, status: Optional[JobStatus] = None,
              limit: int = 100, user_id: Optional[str] = None) -> list:
    """List owned records newest first after applying all filters."""
    # FILL IN: AC6, preserve other filters and existing public behavior.
    raise NotImplementedError
async def list_jobs_async(self, obj_id: Optional[str] = None, status: Optional[JobStatus] = None,
                          limit: int = 100, user_id: Optional[str] = None) -> list:
    """Read fresh store records without acquiring ownership; retain local fallback."""
    # FILL IN: AC2/AC6, forward user_id and avoid stale foreign caches.
    raise NotImplementedError
# FILL IN: start/stop, get_job_async, create_job, _persist/_remove_from_store,
# _run_job cancellation branch and every fire-and-forget persistence site: AC1-AC5.
```

**Why**: Ownership, cancellation and bounded persistence. Extend the relocated JobManager and RedisJobStore with all M1 lifecycle contracts.

### `packages/ai-parrot/src/parrot/jobs/redis_store.py` (MODIFY)

Created by TASK-5395 as a behavior-preserving move. Revalidate this anchor after the dependency lands.
- Anchor `class RedisJobStore:`; occurrences: **1** (`grep -cF`); packages/ai-parrot-server/src/parrot/handlers/jobs/redis_store.py:120.

```python
# Extend the existing save/delete/list_jobs methods, not parallel implementations.
async def list_jobs(self, obj_id: Optional[str] = None, status: Optional[JobStatus] = None,
                    limit: int = 100, user_id: Optional[str] = None) -> list[Job]:
    """Read the requested user's sorted index, pruning stale IDs while filtering."""
    # FILL IN: use {prefix}:_user:{user_id} for user reads; global index otherwise.
    # Paginate until enough matching records or exhaustion; AC6/AC7.
    raise NotImplementedError
# FILL IN: save ZADD and terminal EXPIRE; delete obtains user before deleting hash
# and removes membership from both indexes; retain lazy redis.asyncio import.
```

**Why**: Per-user index maintenance and filtering. Extend the relocated JobManager and RedisJobStore with all M1 lifecycle contracts.

### `packages/ai-parrot/tests/test_parrot_jobs_core.py` (MODIFY)

Created by TASK-5395; planned anchor `async def test_core_and_server_paths_are_the_same_objects() -> None:` occurs 1 time(s) in its blueprint. File does not exist on dev yet: verify actual count/line after the dependency lands before editing; this is dependency evidence, not a claimed current-source grep.

```python
# Preserve existing fixtures and tests; append the cases below.
"""Regression coverage for Add owned cancellation, bounded persistence and per-user job queries."""
import asyncio
import pytest

async def test_cancel_job_keeps_record_with_reason() -> None:
    """Verify the corresponding Test Specification behavior below."""
    # FILL IN: arrange deterministic doubles and assert the named behavior; see ACs.
    raise NotImplementedError

async def test_foreign_job_reads_refresh_without_ownership() -> None:
    """Verify the corresponding Test Specification behavior below."""
    # FILL IN: arrange deterministic doubles and assert the named behavior; see ACs.
    raise NotImplementedError

async def test_persistence_is_bounded_ordered_and_drained() -> None:
    """Verify the corresponding Test Specification behavior below."""
    # FILL IN: arrange deterministic doubles and assert the named behavior; see ACs.
    raise NotImplementedError

async def test_redis_user_index_lists_and_prunes() -> None:
    """Verify the corresponding Test Specification behavior below."""
    # FILL IN: arrange deterministic doubles and assert the named behavior; see ACs.
    raise NotImplementedError
```

**Why**: Task-owned regression coverage. Extend the relocated JobManager and RedisJobStore with all M1 lifecycle contracts.

### FILL IN checklist

- [ ] packages/ai-parrot/src/parrot/jobs/manager.py — finish the scoped behavior/test branches above, bounded by AC1–AC7.
- [ ] packages/ai-parrot/src/parrot/jobs/redis_store.py — finish the scoped behavior/test branches above, bounded by AC1–AC7.
- [ ] packages/ai-parrot/tests/test_parrot_jobs_core.py — finish the scoped behavior/test branches above, bounded by AC1–AC7.

## Acceptance Criteria

- [ ] AC1: cancel_job returns false for unknown, terminal or taskless jobs; cancellation retains CANCELLED/error=reason.
- [ ] AC2: Two managers sharing a store see fresh foreign progress and completion without acquiring cancel ownership.
- [ ] AC3: create_job accepts keyword-only initial metadata; first persisted snapshot includes ownership and deadlines.
- [ ] AC4: persistence_timeout defaults to 0.5 and must be positive; stalled connection/save/delete cannot block admission or leave untracked tasks.
- [ ] AC5: Ordered saves cannot overwrite terminal state with an older snapshot; shutdown drains/cancels within a finite budget.
- [ ] AC6: All three list APIs accept user_id, filter before limiting, and return newest first; local jobs remain listable during Redis failure.
- [ ] AC7: Redis user indexes are maintained on save/delete, receive terminal TTL, and prune stale IDs without starving one user behind others.

## Validation Commands

- `pytest packages/ai-parrot/tests/test_parrot_jobs_core.py -q`

## Test Specification

| Test | Module | Required behavior |
|---|---|---|
| `test_cancel_job_keeps_record_with_reason` | M1 | running job → `cancel_job(id, "x")` → status `CANCELLED`, `error == "x"`, still returned by `get_job` |
| `test_cancel_job_unknown_or_finished_returns_false` | M1 | unknown id / completed job → `False` |
| `test_list_jobs_filters_by_user_id` | M1 | memory listing with two users returns only the requested user's jobs |
| `test_redis_user_index_lists_and_prunes` | M1 | real localhost Redis db 15 + unique prefix, skipped when unreachable (no fakeredis); per-user zset written on save, read by `list_jobs(user_id=)`, stale ids pruned |
| `test_foreign_job_reads_refresh_without_ownership` | M1 | Two managers share a store: B reads A's queued/running job, A updates progress and completes, B observes every update; B never inserts the record into its owned jobs map or gains cancel ownership |
| `test_persistence_is_bounded_ordered_and_drained` | M1 | Delayed/failing saves do not block admission; older snapshots cannot overwrite completion; shutdown leaves no untracked persistence task |

Use deterministic doubles for external systems; no live platform/GitHub/LLM credentials. Add all scoped AC cases, not only the scaffold examples. Store test logs under artifacts/logs/.

## Agent Instructions

1. Implement in the feature worktree provisioned by `$sdd-start TASK-5396`; never implement on dev.
2. Read this task/spec and verify all dependencies in `sdd/tasks/index/queued-commands-integrations.json`.
3. Revalidate source contracts and dependency-created anchors before edits.
4. Implement only declared files, complete all FILL IN items, and run Validation Commands.
5. Commit only scoped implementation files. Use `parrot sdd task finalize` with real TaskCompletionEvidence and implementation HEAD, inspect generated Completion Note/staged state, then commit that state. Do not manually move task files.

## Completion Note

Pending; generated by task finalization with validation and commit evidence.
