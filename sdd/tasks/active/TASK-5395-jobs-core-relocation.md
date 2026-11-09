# TASK-5395: Move job primitives into core with compatibility shims

**Feature**: FEAT-851 - Queued chat commands for the integrations
**Spec**: `sdd/specs/queued-commands-integrations.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

## Context

Implements the scoped FEAT-851 deliverable below. Read spec §§2–7 for the fixed behavior and edge cases. This task creates implementation artifacts only when picked up by sdd-start.

## Scope

- Move the existing models, manager and Redis store to parrot.jobs, preserving behavior and all public names.
- Replace the three old server implementation files with re-export shims; keep server __init__, mixin and worker unchanged.
- Keep Redis optional and lazily imported; do not edit dependency manifests or install packages.

**NOT in scope**: files outside the table, new dependencies, external workers, cross-worker cancel/dedup, or changes to strict review semantics beyond the declared registration update.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/jobs/models.py` | CREATE | Relocate the complete existing implementation |
| `packages/ai-parrot/src/parrot/jobs/manager.py` | CREATE | Relocate the complete existing implementation |
| `packages/ai-parrot/src/parrot/jobs/redis_store.py` | CREATE | Relocate the complete existing implementation |
| `packages/ai-parrot/src/parrot/jobs/__init__.py` | CREATE | Core public exports |
| `packages/ai-parrot-server/src/parrot/handlers/jobs/job.py` | MODIFY | Replace implementation with compatibility re-export |
| `packages/ai-parrot-server/src/parrot/handlers/jobs/models.py` | MODIFY | Replace implementation with compatibility re-export |
| `packages/ai-parrot-server/src/parrot/handlers/jobs/redis_store.py` | MODIFY | Replace implementation with compatibility re-export |
| `packages/ai-parrot/tests/test_parrot_jobs_core.py` | CREATE | Task-owned regression coverage |

## Codebase Contract (Anti-Hallucination)

Verified against the current dev source on 2026-11-09. Existing signatures below were re-read with AST and source inspection; MODIFY anchors were re-counted with `grep -cF`. Symbols provided by dependencies are explicitly future contracts, not existing imports.

### Verified Imports

```python
from parrot.handlers.jobs import JobManager, JobStatus, RedisJobStore
from parrot.handlers.jobs.models import Job
import pytest
from .models import Job, JobStatus
from .manager import JobManager
from .redis_store import RedisJobStore
from parrot.jobs.manager import JobManager
from parrot.jobs.models import Job, JobStatus
from parrot.jobs.redis_store import RedisJobStore
from parrot.jobs import Job, JobManager, JobStatus, RedisJobStore
```

Standard-library imports are available; pydantic/pytest and platform SDK imports reuse the declared project stack. New imports are supplied only by this task or its named prerequisites; revalidate them when prerequisites land. Existing source relocation preserves its original import block.

### Existing Signatures to Use

```python
# packages/ai-parrot-server/src/parrot/handlers/jobs/job.py:22
class JobManager()

# packages/ai-parrot-server/src/parrot/handlers/jobs/models.py:16
class Job()

# packages/ai-parrot-server/src/parrot/handlers/jobs/models.py:6
class JobStatus(str, Enum)

# packages/ai-parrot-server/src/parrot/handlers/jobs/redis_store.py:120
class RedisJobStore()

# packages/ai-parrot-server/src/parrot/handlers/jobs/worker.py:15
def configure_job_manager(app: web.Application, *, use_redis: bool=False, redis_url: Optional[str]=None, key_prefix: str='parrot:jobs', job_ttl: int=86400) -> JobManager
```

### Does NOT Exist

- parrot.jobs does not exist at planning time; this task creates it.
- No extra worker/broker or replacement Job model is required.

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/jobs/models.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot/src/parrot/jobs/manager.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot/src/parrot/jobs/redis_store.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot/src/parrot/jobs/__init__.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot-server/src/parrot/handlers/jobs/job.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot-server/src/parrot/handlers/jobs/models.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot-server/src/parrot/handlers/jobs/redis_store.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/test_parrot_jobs_core.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-server/src/parrot/handlers/jobs/job.py#JobManager",
    "sym:packages/ai-parrot-server/src/parrot/handlers/jobs/models.py#Job",
    "sym:packages/ai-parrot-server/src/parrot/handlers/jobs/models.py#JobStatus",
    "sym:packages/ai-parrot-server/src/parrot/handlers/jobs/redis_store.py#RedisJobStore",
    "sym:packages/ai-parrot-server/src/parrot/handlers/jobs/worker.py#configure_job_manager"
  ]
}
```

## Implementation Notes



**Parallelism**: Independent: owns packages/ai-parrot/src/parrot/jobs/models.py, packages/ai-parrot/src/parrot/jobs/manager.py, packages/ai-parrot/src/parrot/jobs/redis_store.py, packages/ai-parrot/src/parrot/jobs/__init__.py, packages/ai-parrot-server/src/parrot/handlers/jobs/job.py, packages/ai-parrot-server/src/parrot/handlers/jobs/models.py, packages/ai-parrot-server/src/parrot/handlers/jobs/redis_store.py, packages/ai-parrot/tests/test_parrot_jobs_core.py; consumes only existing APIs and changes no shared external state.

## Implementation Blueprint

Planning skeletons only: complete all bounded FILL IN items; never leave placeholders in implementation files. Preserve the spec interface signatures.

### Steps (in order)

1. Verify prerequisites and the exact anchors below — dependent files may have moved since planning.
2. Apply only the declared per-file changes — this bounds ownership and preserves unrelated behavior.
3. Complete the acceptance-criteria branches and regression tests — these pin failure, ownership and compatibility boundaries.
4. Run the task validation and format/lint touched Python files — publish complete working files only.

### `packages/ai-parrot/src/parrot/jobs/models.py` (CREATE)

```python
# MOVE the complete verified source packages/ai-parrot-server/src/parrot/handlers/jobs/models.py to this path.
# Preserve its imports, class signatures, helper functions and bodies verbatim.
# Relative .models/.redis_store imports still resolve inside parrot.jobs.
# FILL IN: adjust only references required by relocation; preserve all public behavior.
# Do not replace the source with this directive or duplicate its implementation.
```

**Why**: Relocate the complete existing implementation. Move the existing models, manager and Redis store to parrot.jobs, preserving behavior and all public names.

### `packages/ai-parrot/src/parrot/jobs/manager.py` (CREATE)

```python
# MOVE the complete verified source packages/ai-parrot-server/src/parrot/handlers/jobs/job.py to this path.
# Preserve its imports, class signatures, helper functions and bodies verbatim.
# Relative .models/.redis_store imports still resolve inside parrot.jobs.
# FILL IN: adjust only references required by relocation; preserve all public behavior.
# Do not replace the source with this directive or duplicate its implementation.
```

**Why**: Relocate the complete existing implementation. Move the existing models, manager and Redis store to parrot.jobs, preserving behavior and all public names.

### `packages/ai-parrot/src/parrot/jobs/redis_store.py` (CREATE)

```python
# MOVE the complete verified source packages/ai-parrot-server/src/parrot/handlers/jobs/redis_store.py to this path.
# Preserve its imports, class signatures, helper functions and bodies verbatim.
# Relative .models/.redis_store imports still resolve inside parrot.jobs.
# FILL IN: adjust only references required by relocation; preserve all public behavior.
# Do not replace the source with this directive or duplicate its implementation.
```

**Why**: Relocate the complete existing implementation. Move the existing models, manager and Redis store to parrot.jobs, preserving behavior and all public names.

### `packages/ai-parrot/src/parrot/jobs/__init__.py` (CREATE)

```python
"""Shared asynchronous job primitives."""
from .models import Job, JobStatus
from .manager import JobManager
from .redis_store import RedisJobStore
__all__ = ("Job", "JobStatus", "JobManager", "RedisJobStore")
```

**Why**: Core public exports. Move the existing models, manager and Redis store to parrot.jobs, preserving behavior and all public names.

### `packages/ai-parrot-server/src/parrot/handlers/jobs/job.py` (MODIFY)

- Anchor `class JobManager:`; occurrences: **1** (`grep -cF`); packages/ai-parrot-server/src/parrot/handlers/jobs/job.py:22.

```python
"""Compatibility exports for the core job primitives."""
from parrot.jobs.manager import JobManager
from parrot.jobs.models import Job, JobStatus
__all__ = ("JobManager", "Job", "JobStatus")
```

**Why**: Replace implementation with compatibility re-export. Move the existing models, manager and Redis store to parrot.jobs, preserving behavior and all public names.

### `packages/ai-parrot-server/src/parrot/handlers/jobs/models.py` (MODIFY)

- Anchor `class JobStatus(str, Enum):`; occurrences: **1** (`grep -cF`); packages/ai-parrot-server/src/parrot/handlers/jobs/models.py:6.

```python
"""Compatibility exports for the core job primitives."""
from parrot.jobs.models import Job, JobStatus
__all__ = ("Job", "JobStatus")
```

**Why**: Replace implementation with compatibility re-export. Move the existing models, manager and Redis store to parrot.jobs, preserving behavior and all public names.

### `packages/ai-parrot-server/src/parrot/handlers/jobs/redis_store.py` (MODIFY)

- Anchor `class RedisJobStore:`; occurrences: **1** (`grep -cF`); packages/ai-parrot-server/src/parrot/handlers/jobs/redis_store.py:120.

```python
"""Compatibility exports for the core job primitives."""
from parrot.jobs.redis_store import RedisJobStore
__all__ = ("RedisJobStore",)
```

**Why**: Replace implementation with compatibility re-export. Move the existing models, manager and Redis store to parrot.jobs, preserving behavior and all public names.

### `packages/ai-parrot/tests/test_parrot_jobs_core.py` (CREATE)

```python
"""Regression coverage for Move job primitives into core with compatibility shims."""
import pytest
from parrot.jobs import Job, JobManager, JobStatus, RedisJobStore

async def test_core_and_server_paths_are_the_same_objects() -> None:
    """Verify the corresponding Test Specification behavior below."""
    # FILL IN: arrange deterministic doubles and assert the named behavior; see ACs.
    raise NotImplementedError
```

**Why**: Task-owned regression coverage. Move the existing models, manager and Redis store to parrot.jobs, preserving behavior and all public names.

### FILL IN checklist

- [ ] packages/ai-parrot/src/parrot/jobs/models.py — finish the scoped behavior/test branches above, bounded by AC1–AC3.
- [ ] packages/ai-parrot/src/parrot/jobs/manager.py — finish the scoped behavior/test branches above, bounded by AC1–AC3.
- [ ] packages/ai-parrot/src/parrot/jobs/redis_store.py — finish the scoped behavior/test branches above, bounded by AC1–AC3.
- [ ] packages/ai-parrot/src/parrot/jobs/__init__.py — finish the scoped behavior/test branches above, bounded by AC1–AC3.
- [ ] packages/ai-parrot-server/src/parrot/handlers/jobs/job.py — finish the scoped behavior/test branches above, bounded by AC1–AC3.
- [ ] packages/ai-parrot-server/src/parrot/handlers/jobs/models.py — finish the scoped behavior/test branches above, bounded by AC1–AC3.
- [ ] packages/ai-parrot-server/src/parrot/handlers/jobs/redis_store.py — finish the scoped behavior/test branches above, bounded by AC1–AC3.
- [ ] packages/ai-parrot/tests/test_parrot_jobs_core.py — finish the scoped behavior/test branches above, bounded by AC1–AC3.

## Acceptance Criteria

- [ ] AC1: Core imports work without ai-parrot-server; no core import refers to parrot.handlers.
- [ ] AC2: Core and all legacy server paths resolve to identical class objects.
- [ ] AC3: Existing Job behavior, serialization helpers, enqueue/fetch compatibility and progress API are preserved.

## Validation Commands

- `pytest packages/ai-parrot/tests/test_parrot_jobs_core.py -q`

## Test Specification

| Test | Module | Required behavior |
|---|---|---|
| `test_core_and_server_paths_are_the_same_objects` | M1 | `parrot.jobs.JobManager is parrot.handlers.jobs.JobManager` (and `.job.JobManager`, `.models.Job`, `.redis_store.RedisJobStore`) |

Use deterministic doubles for external systems; no live platform/GitHub/LLM credentials. Add all scoped AC cases, not only the scaffold examples. Store test logs under artifacts/logs/.

## Agent Instructions

1. Implement in the feature worktree provisioned by `$sdd-start TASK-5395`; never implement on dev.
2. Read this task/spec and verify all dependencies in `sdd/tasks/index/queued-commands-integrations.json`.
3. Revalidate source contracts and dependency-created anchors before edits.
4. Implement only declared files, complete all FILL IN items, and run Validation Commands.
5. Commit only scoped implementation files. Use `parrot sdd task finalize` with real TaskCompletionEvidence and implementation HEAD, inspect generated Completion Note/staged state, then commit that state. Do not manually move task files.

## Completion Note

Pending; generated by task finalization with validation and commit evidence.
