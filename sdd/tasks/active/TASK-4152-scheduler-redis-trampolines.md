# TASK-4152: run_redis_job / run_redis_job_now trampolines and SchedulerManager-typed registry in jobs.py

**Feature**: FEAT-644 — SchedulerManager base (db | redis | code backends)
**Spec**: `sdd/specs/scheduler-manager-base.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 4 (trampolines). APScheduler persists a job's callable as `module:function`, so every job points at a
module-level coroutine in `jobs.py` that resolves the live manager by `registered_name` at fire time
(`packages/ai-parrot-server/src/parrot/scheduler/jobs.py:1-8`). `backend='redis'` jobs need two new entrypoints. Their kwargs are data-only and versioned
(design research S8): `{manager_name, schedule_id, definition_version, definition}`.

---

## Scope

- Add `run_redis_job(manager_name, schedule_id, definition_version, definition)` delegating to `manager._run_redis_job(schedule_id, definition_version=..., definition=...)`.
- Add `run_redis_job_now(manager_name, schedule_id)` delegating to `manager._run_redis_job(schedule_id, run_now=True)` and ALWAYS releasing the run-now guard (mirror of `run_db_schedule_now`).
- Add an optional `run_now: bool = False` kwarg to `run_auto_schedule` passed through to `_run_auto_task` (code-job run-now, spec CRUD matrix).
- Retype the registry to `SchedulerManager` (string annotation under `TYPE_CHECKING`, importing from `.base`).
- Extend `test_jobs.py` with fake managers.

**NOT in scope**: `_run_redis_job` itself (TASK-4157); adding jobs (TASK-4156).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-server/src/parrot/scheduler/jobs.py` | MODIFY | New trampolines; registry typed to SchedulerManager |
| `packages/ai-parrot-server/tests/scheduler/test_jobs.py` | MODIFY | Trampoline delegation tests |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: This section contains VERIFIED code references from the actual codebase (verified on `dev` @ `3555841e9`, 2026-10-08).
> The implementing agent MUST use these exact imports, class names, and method signatures.
> **DO NOT** invent, guess, or assume any import, attribute, or method not listed here.
> If you need something not listed, VERIFY it exists first with `grep` or `read`.

### Verified Imports
```python
# packages/ai-parrot-server/src/parrot/scheduler/jobs.py:10-16 (existing)
from __future__ import annotations
import logging
from typing import TYPE_CHECKING, Any, Dict, Final
if TYPE_CHECKING:
    from .manager import AgentSchedulerManager      # line 16 — change to: from .base import SchedulerManager
```

### Existing Signatures to Use
```python
_MANAGERS: Dict[str, "AgentSchedulerManager"] = {}                               # line 32
def register_manager(manager: "AgentSchedulerManager") -> None:                   # line 35
def get_manager(name: str) -> "AgentSchedulerManager":                            # line 48 (raises LookupError)
async def run_db_schedule(manager_name: str, schedule_id: str, fingerprint: str) -> Any:   # line 60
async def run_db_schedule_now(manager_name: str, schedule_id: str) -> Any:        # line 65
    manager = get_manager(manager_name)
    try:
        return await manager._run_db_schedule(schedule_id, None, run_now=True)
    finally:
        await manager._fire_coordinator.release_running(str(schedule_id))
async def run_auto_schedule(manager_name: str, job_id: str) -> Any:               # line 74
```

### Does NOT Exist
- ~~`parrot.scheduler.base`~~ at this task's base commit — it is created by TASK-4154; the `TYPE_CHECKING` import is never executed at runtime, so this task does not depend on it.
- ~~`run_redis_job`~~, ~~`run_redis_job_now`~~, ~~`SchedulerManager._run_redis_job`~~ — the first two are created here; the method by TASK-4157.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot-server/src/parrot/scheduler/jobs.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot-server/tests/scheduler/test_jobs.py",
      "action": "MODIFY"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-server/src/parrot/scheduler/jobs.py#run_db_schedule_now",
    "sym:packages/ai-parrot-server/src/parrot/scheduler/jobs.py#get_manager",
    "sym:packages/ai-parrot-server/src/parrot/scheduler/jobs.py#run_auto_schedule",
    "sym:packages/ai-parrot-server/src/parrot/scheduler/jobs.py#register_manager"
  ]
}
```

---

## Implementation Notes

`_run_redis_job` receives the definition from the trampoline kwargs instead of re-reading the job, because a
one-shot (`once`) job may already be removed from the jobstore by the time its coroutine runs (APScheduler removes
exhausted jobs right after submission). This extends the spec skeleton's `_run_redis_job(self, schedule_id, *,
run_now=False)` with two optional keyword arguments — record it in the Completion Note.

### Key Constraints
- Async-first; never block the event loop. `self.logger` / module `logger`, never `print`.
- Google-style docstrings and strict type hints; 120-column lines; `ruff check` (TID251) must pass on every touched file.
- Every timestamp the scheduler writes goes through `utcnow()` (UTC-aware) — never `datetime.now()` (spec AC7).
- Run every command from the feature worktree with `PYTHONPATH=packages/ai-parrot-server/src:packages/ai-parrot/src:packages/ai-parrot-integrations/src` — the shared `.venv` is editable-installed against the main checkout, so a bare `pytest` imports the wrong branch.

---

## Implementation Blueprint

> **Executor-ready starting point.** Write each block to its declared path nearly verbatim, then complete every
> `# FILL IN:` marker. Never change a signature, class name, or file path the blueprint fixes (they come from the
> spec's §3 Interface Skeletons). Anchors were re-verified with `grep -c` at task-generation time.

### Steps (in order)
1. Change the `TYPE_CHECKING` import and the three annotations — *why*: the registry holds `SchedulerManager` (and its subclass) after TASK-4158.
2. Add the two Redis trampolines after `run_db_schedule_now` — *why*: same release-in-finally discipline as the DB run-now.
3. Add `run_now` to `run_auto_schedule`; update the module docstring to say 'scheduler' not 'agent scheduler'.
4. Extend `test_jobs.py` with a `SimpleNamespace` fake manager recording calls.

### `packages/ai-parrot-server/src/parrot/scheduler/jobs.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '    from .manager import AgentSchedulerManager' packages/ai-parrot-server/src/parrot/scheduler/jobs.py)
# REPLACE line 16:
    from .base import SchedulerManager
# REPLACE every "AgentSchedulerManager" string annotation (lines 32, 35, 48) with "SchedulerManager".

# occurrences: 1 (verified: grep -c '^async def run_auto_schedule(manager_name: str, job_id: str) -> Any:' packages/ai-parrot-server/src/parrot/scheduler/jobs.py)
# BEFORE `async def run_auto_schedule` (verified: jobs.py:74) — insert:
async def run_redis_job(
    manager_name: str, schedule_id: str, definition_version: int, definition: Dict[str, Any]
) -> Any:
    """Entrypoint for ``backend='redis'`` jobs (data-only, versioned kwargs — FEAT-644 S8)."""
    return await get_manager(manager_name)._run_redis_job(
        schedule_id, definition_version=definition_version, definition=definition
    )


async def run_redis_job_now(manager_name: str, schedule_id: str) -> Any:
    """Run-now one-shot for a redis job; always releases the run-now guard."""
    manager = get_manager(manager_name)
    try:
        return await manager._run_redis_job(schedule_id, run_now=True)
    finally:
        await manager._fire_coordinator.release_running(str(schedule_id))


# REPLACE run_auto_schedule:
async def run_auto_schedule(manager_name: str, job_id: str, run_now: bool = False) -> Any:
    """Entrypoint for decorator-registered ``auto_*`` jobs (delegates to ``_run_auto_task``)."""
    # FILL IN: when run_now, release the run-now guard in `finally` like run_redis_job_now.
    return await get_manager(manager_name)._run_auto_task(job_id, run_now=run_now)
```
**Why**: the kwarg names are the persisted job contract (spec §2 "Redis job kwargs"); renaming them later would orphan
every armed Redis job, so they are fixed here.

### FILL IN checklist
- [ ] `run_auto_schedule` — release the run-now guard only when `run_now` is true.

---

## Acceptance Criteria

- [ ] `run_redis_job` passes `definition_version` and `definition` through unchanged.
- [ ] `run_redis_job_now` releases the guard even when `_run_redis_job` raises.
- [ ] `run_auto_schedule(name, job_id)` still works with the legacy manager (default `run_now=False` — note the legacy `_run_auto_task(job_id)` takes no `run_now`; pass it only when true).
- [ ] Existing `test_jobs.py` tests still pass.

---

## Validation Commands

> File-level pytest only — no directories, no package roots. Run every command from the feature worktree with `PYTHONPATH=packages/ai-parrot-server/src:packages/ai-parrot/src:packages/ai-parrot-integrations/src` — the shared `.venv` is editable-installed against the main checkout, so a bare `pytest` imports the wrong branch.

- `pytest packages/ai-parrot-server/tests/scheduler/test_jobs.py -q`

---

## Test Specification

```python
# additions to packages/ai-parrot-server/tests/scheduler/test_jobs.py
async def test_run_redis_job_delegates_with_definition(): ...
async def test_run_redis_job_now_releases_guard_on_error(): ...
async def test_run_auto_schedule_run_now_releases_guard(): ...
```

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `dev`
   (`python -m scripts.sdd.ensure_worktree --slug scheduler-manager-base --feature-id FEAT-644 --spec sdd/specs/scheduler-manager-base.spec.md --index sdd/tasks/index/scheduler-manager-base.json`)
2. **Read the spec** at `sdd/specs/scheduler-manager-base.spec.md` (§2 Overview, the CRUD matrix, Data Models, and the §3 module this task implements)
3. **Check dependencies** — every `Depends-on` task must be `"done"` in `sdd/tasks/index/scheduler-manager-base.json`
4. **Verify the Codebase Contract** — re-`grep` every anchor and signature before writing code; if one moved, fix
   the contract in this file first; never reference anything listed under "Does NOT Exist"
5. **Update status** in the per-spec index → `"in-progress"` (set `started_at`) and commit only that index file
6. **Implement** from the Implementation Blueprint, completing every `# FILL IN:` marker
7. **Verify** — `ruff check` the touched files and run every Validation Command
8. **Commit the code** — stage only the files this task lists (never `git add .` / `-A`):
   `feat(scheduler-manager-base): TASK-4152 — run_redis_job / run_redis_job_now trampolines and SchedulerManager-typed registry in jobs.py`
9. **Close the task** with `scripts/sdd/close_task.sh TASK-4152 scheduler-manager-base verified` (never move the file by hand)
10. **Fill in the Completion Note** below, then commit the staged SDD state: `sdd: complete TASK-4152 — run_redis_job / run_redis_job_now trampolines and SchedulerManager-typed registry in jobs.py`

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
