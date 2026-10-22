# TASK-4065: Cross-worker run-now guard, run-now trampoline, and the fail-closed `lock_unavailable` stamp

**Feature**: FEAT-631 — Scheduler multi-worker correctness
**Spec**: `sdd/specs/scheduler-multiworker-correctness.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-4064
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 3 (run-now and unavailable parts) / AC4, AC5, AC6. After TASK-4064, run-now is the last `add_job` using a
bound method (`self._run_now_wrapper`), and its 409 guard (`_run_now_active`) only covers one worker. This task:
- moves run-now onto `jobs.run_db_schedule_now`;
- moves the guard into the coordinator;
- removes `_run_now_wrapper` and `_run_now_active`;
- implements the hook the executor calls when Redis is down, which stamps `metadata.last_status = "lock_unavailable"`
  without bumping `run_count`.

The FEAT-467 run-now contract must hold unchanged: a paused schedule runs once and stays paused, a concurrent run-now gets 409,
the guard is released on success and on failure, and `job_success` recovers `schedule_id` from the `run_now:` job-id prefix.

---

## Scope

- `run_schedule_now`: guard with `await self._fire_coordinator.try_acquire_running(schedule_id)`. False → raise
  `SchedulerRunNowConflictError` (same message). `FireCoordinationError` is NOT a conflict: never run unguarded, and surface it
  as an error (the exact exception is a blueprint FILL IN). Job func is `jobs.run_db_schedule_now`, with kwargs
  `{"manager_name": self.registered_name, "schedule_id": schedule_id}`, and the job id stays `f"{_RUN_NOW_JOB_PREFIX}{schedule_id}"`.
  If `add_job` fails, release the guard.
- Remove `_run_now_wrapper` and the `_run_now_active` attribute.
- Add `_on_coordination_unavailable(job_id, exc)` and pass it to the executor (`CoordinatedAsyncIOExecutor(on_unavailable=self._on_coordination_unavailable)`
  in `__init__`, or `executor._on_unavailable = ...` once `self` exists. Choose the constructor form).
- Adapt `tests/scheduler/test_run_now.py` only where it reaches the removed internals. Never change what it asserts.
- Add the run-now/unavailable tests to a new `tests/scheduler/test_run_now_coordination.py`.

**NOT in scope**: changing the `/scheduler/schedules/{id}` PATCH handler's 409 mapping (unchanged); multi-worker integration tests (TASK-4066).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-server/src/parrot/scheduler/manager.py` | MODIFY | run-now migration, unavailable hook, removals |
| `packages/ai-parrot-server/tests/scheduler/test_run_now.py` | MODIFY | adapt to removed internals only |
| `packages/ai-parrot-server/tests/scheduler/test_run_now_coordination.py` | CREATE | cross-worker 409 + lock_unavailable tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from . import jobs                                            # in manager.py since TASK-4063
from .coordination import CoordinatedAsyncIOExecutor, FireCoordinationError   # TASK-4062 (add FireCoordinationError to the TASK-4064 import line)
from parrot.scheduler.manager import AgentSchedulerManager, SchedulerRunNowConflictError   # verified: test_run_now.py:31
from parrot.scheduler import manager as manager_module       # verified: test_run_now.py:30
```

### Existing Signatures to Use
```python
# packages/ai-parrot-server/src/parrot/scheduler/manager.py  (base b38a49b9d; lines shift after TASK-4063/4064 — re-grep)
_RUN_NOW_JOB_PREFIX = "run_now:"                                  # line 86
class SchedulerRunNowConflictError(Exception)                      # line 74
    self._run_now_active: Set[str] = set()                         # line 354 (remove)
    async def _update_schedule_run(self, schedule_id, success=True, error=None, result=None)  # line 863 — pattern for the DB write (awaited AgentSchedule.get, Meta.connection = conn)
    async def run_schedule_now(self, schedule_id: str) -> AgentSchedule:   # line 1521
        if schedule_id in self._run_now_active:                     # line 1553
        self._run_now_active.add(schedule_id)                       # line 1557
        self.scheduler.add_job(self._run_now_wrapper, ...)          # lines 1567-1575
            self._run_now_active.discard(schedule_id)               # line 1577 (except branch)
    async def _run_now_wrapper(self, schedule_id: str, **kwargs) -> Any:  # line 1582 (remove)
# coordination.py (TASK-4062): FireCoordinator.try_acquire_running / release_running; FireCoordinationError;
#   CoordinatedAsyncIOExecutor(coordinator=None, on_unavailable=None)
# jobs.py (TASK-4061): run_db_schedule_now(manager_name, schedule_id) — releases the guard in finally
# tests/scheduler/test_run_now.py: TestManagerRunNow tests at 137 (executes once), 153 (preserves state), 167 (paused),
#   179 (concurrent 409), 189/204 (last_result), 218 (unknown schedule bubbles); fixture `manager` at 118-127
```

### Does NOT Exist
- ~~`AgentSchedulerManager._run_now_active` after this task~~: removed. Tests must not reference it.
- ~~`AgentSchedulerManager._run_now_wrapper` after this task~~: removed.
- ~~a `lock_unavailable` column~~: it is a value of the existing `metadata["last_status"]` key.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot-server/src/parrot/scheduler/manager.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot-server/tests/scheduler/test_run_now.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot-server/tests/scheduler/test_run_now_coordination.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-server/src/parrot/scheduler/manager.py#AgentSchedulerManager.run_schedule_now",
    "sym:packages/ai-parrot-server/src/parrot/scheduler/manager.py#AgentSchedulerManager._run_now_wrapper",
    "sym:packages/ai-parrot-server/src/parrot/scheduler/manager.py#AgentSchedulerManager._update_schedule_run",
    "sym:packages/ai-parrot-server/src/parrot/scheduler/manager.py#SchedulerRunNowConflictError"
  ]
}
```

---

## Implementation Blueprint

### Steps (in order)
1. Add `_on_coordination_unavailable` and wire it into the executor in `__init__`. *Why*: G5/AC6 require a DB-visible trace when a fire is skipped for lack of Redis.
2. Rewrite the guard and `add_job` in `run_schedule_now`. *Why*: AC4 (cross-worker 409) and AC5 (no bound methods).
3. Delete `_run_now_wrapper` and `_run_now_active`. *Why*: superseded; leaving them invites drift.
4. Run `test_run_now.py`. Fix only the references to removed internals.
5. Write `test_run_now_coordination.py`.

### `manager.py` (MODIFY): executor hook in `__init__`
```python
# occurrences: 1 (verified after TASK-4064: grep -c '        executors = {"default": CoordinatedAsyncIOExecutor()}' manager.py)
# REPLACE with:
        executors = {"default": CoordinatedAsyncIOExecutor(on_unavailable=self._on_coordination_unavailable)}
# and DELETE the line `        self._run_now_active: Set[str] = set()` together with its 4-line comment above it (manager.py:350-353 comment, 354 attribute, at base)
```

### `manager.py` (MODIFY): new method (place right after `_update_schedule_run`)
```python
    async def _on_coordination_unavailable(self, job_id: str, exc: BaseException) -> None:
        """Record a fire skipped because the coordination backend was down (fail closed, FEAT-631 G5).

        Stamps ``metadata.last_status='lock_unavailable'`` and ``last_error`` on DB-backed rows;
        does NOT touch ``run_count``/``last_run`` (the job did not run). Never raises.
        """
        job_id = str(job_id)
        if job_id.startswith("auto_"):
            return  # decorator jobs have no row
        schedule_id = job_id[len(_RUN_NOW_JOB_PREFIX):] if job_id.startswith(_RUN_NOW_JOB_PREFIX) else job_id
        try:
            # FILL IN: acquire pool (self._pool may be None → log and return), AgentSchedule.Meta.connection = conn,
            #          schedule = await AgentSchedule.get(schedule_id=schedule_id), set metadata keys
            #          last_status="lock_unavailable", last_error=f"coordination unavailable: {exc}", last_error_time=iso now,
            #          await schedule.update() — bounded by AC6 (run_count unchanged) and the FEAT-467 awaited-get pattern (manager.py:886-915)
            ...
        except Exception as stamp_error:  # pragma: no cover - safety net
            self.logger.error("Failed to stamp lock_unavailable for %s: %s", schedule_id, stamp_error)
```

### `manager.py` (MODIFY): `run_schedule_now` guard + job
```python
# REPLACE the block from `        if schedule_id in self._run_now_active:` (verified: manager.py:1553, occurrences 1)
# through the `except Exception:` / `self._run_now_active.discard(schedule_id)` / `raise` (manager.py:1576-1578) and the trailing `return schedule` (1580) with:
        try:
            acquired = await self._fire_coordinator.try_acquire_running(schedule_id)
        except FireCoordinationError as exc:
            # FILL IN: decide the surface — re-raise as RuntimeError("Scheduler coordination unavailable") from exc
            #          (the PATCH handler already maps unexpected errors to 500) — bounded by G5: never run unguarded
            raise
        if not acquired:
            raise SchedulerRunNowConflictError(f"A run-now execution is already active for schedule {schedule_id}.")

        try:
            schedule = await self.get_schedule(schedule_id)
            self.scheduler.add_job(
                jobs.run_db_schedule_now,
                trigger=DateTrigger(run_date=datetime.now()),
                id=f"{_RUN_NOW_JOB_PREFIX}{schedule_id}",
                name=f"{schedule.agent_name}_run_now",
                kwargs={"manager_name": self.registered_name, "schedule_id": schedule_id},
                jobstore=self._safe_jobstore(schedule.scheduler_type),
                replace_existing=False,
            )
        except Exception:
            await self._fire_coordinator.release_running(schedule_id)
            raise
        return schedule
# Keep the existing docstring; update its "_run_now_wrapper" mentions to "jobs.run_db_schedule_now" and note the guard is cross-worker.
# NOTE order change vs base: get_schedule now runs AFTER acquiring the guard, so an unknown id must release it (the except does) — test_run_now_unknown_schedule_bubbles still sees the original exception.
```

### `tests/scheduler/test_run_now.py` (MODIFY)
```python
# FILL IN: run the file first. Only edit tests that reference `_run_now_active` / `_run_now_wrapper` (grep shows none at base —
#          if all pass unchanged, leave this file untouched and say so in the Completion Note). Never weaken an assertion.
```

### `tests/scheduler/test_run_now_coordination.py` (CREATE)
```python
"""Cross-worker run-now guard + fail-closed stamp (FEAT-631 TASK-4065)."""
from unittest.mock import AsyncMock

import pytest

from parrot.scheduler.coordination import FireCoordinationError, RedisFireCoordinator
from parrot.scheduler.manager import AgentSchedulerManager, SchedulerRunNowConflictError

# FILL IN: reuse a dict-backed FakeRedis (copy the class from test_coordination.py — do not import across test modules)
# FILL IN: test_run_now_conflict_across_workers — two managers (distinct registered_name) with RedisFireCoordinator over ONE FakeRedis
#          installed via manager._fire_coordinator = ...; first run_schedule_now ok, second (other manager) → SchedulerRunNowConflictError
# FILL IN: test_run_now_guard_released_after_completion_and_failure
# FILL IN: test_run_now_paused_schedule_still_runs_once (AC4)
# FILL IN: test_unavailable_stamps_lock_unavailable — call manager._on_coordination_unavailable("<uuid>", ConnectionError()) with a fake pool;
#          metadata.last_status == "lock_unavailable", run_count unchanged
# FILL IN: test_unavailable_ignores_auto_jobs — "auto_bot_m" → no DB access
# FILL IN: test_no_bound_method_add_job — inspect.getsource(manager_module) has no `add_job(\n\s*self\._` (regex) (AC5)
```

### FILL IN checklist
- [ ] `_on_coordination_unavailable` DB write; bounded by AC6
- [ ] the `FireCoordinationError` surface in `run_schedule_now`; bounded by G5
- [ ] the `test_run_now.py` check; bounded by "never weaken an assertion"
- [ ] the 6 new tests

---

## Acceptance Criteria

- [ ] `grep -nE "add_job\(\s*$" -A1 packages/ai-parrot-server/src/parrot/scheduler/manager.py | grep "self\._"` returns nothing (AC5).
- [ ] `_run_now_wrapper` and `_run_now_active` no longer appear in `manager.py`.
- [ ] A concurrent run-now from another manager over the same Redis raises `SchedulerRunNowConflictError` (AC4).
- [ ] The executor's unavailable path stamps `lock_unavailable` with `run_count` unchanged (AC6).
- [ ] `test_run_now.py` passes with no assertion weakened. `ruff check` is clean.

---

## Validation Commands

- `pytest packages/ai-parrot-server/tests/scheduler/test_run_now_coordination.py -q`
- `pytest packages/ai-parrot-server/tests/scheduler/test_run_now.py -q`

---

## Test Specification

See the blocks above.

---

## Agent Instructions

1. Work in the feature worktree (`python -m scripts.sdd.ensure_worktree --slug scheduler-multiworker-correctness --feature-id FEAT-631 --spec sdd/specs/scheduler-multiworker-correctness.spec.md --index sdd/tasks/index/scheduler-multiworker-correctness.json`). TASK-4064 must be `done`.
2. Re-grep every anchor (lines moved in TASK-4063/4064). A count of 0 means drift: stop and report.
3. Implement and validate with `PYTHONPATH=packages/ai-parrot-server/src:packages/ai-parrot/src`.
4. Commit only the listed files: `feat(scheduler-multiworker-correctness): TASK-4065 — cross-worker run-now + fail-closed stamp`.
5. Run `scripts/sdd/close_task.sh TASK-4065 scheduler-multiworker-correctness verified`, fill in the Completion Note, commit, and push.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: gpt-5.6-terra (codex), orchestrated by sdd-worker
**Date**: 2026-10-05
**Notes**: run-now guard moved to coordinator; scheduler tests 200 passed. Merge-tier run has the same unrelated pre-existing failures as TASK-4063. Closed via close_task.sh.

**Deviations from spec**: none
