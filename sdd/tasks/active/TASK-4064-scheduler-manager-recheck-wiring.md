# TASK-4064: Route scheduler jobs through trampolines, re-check rows at fire time, install the coordinator

**Feature**: FEAT-631 — Scheduler multi-worker correctness
**Spec**: `sdd/specs/scheduler-multiworker-correctness.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-4061, TASK-4062, TASK-4063
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 3 / Goals G2, G3, G4, G6 / AC2, AC3, AC5, AC7, AC9. This task joins the pieces:
- every `add_job` (except run-now) points at a `parrot.scheduler.jobs` trampoline with `str`-only kwargs;
- each DB fire re-reads its row (missing or disabled → skip and drop the local job; changed trigger → reschedule and skip; otherwise run with the row's fields);
- the `CoordinatedAsyncIOExecutor` is installed, and `start_headless` builds the coordinator.

Run-now migration and the `lock_unavailable` stamp are TASK-4065. This task must leave run-now **working** (see Step 7).

---

## Scope

- Imports + module-level `schedule_fingerprint(schedule) -> str`.
- `__init__`: `_fire_coordinator = NullFireCoordinator()`, `_local_callbacks`, `_auto_tasks`, executor = `CoordinatedAsyncIOExecutor()`,
  `jobs.register_manager(self)`. Leave `_run_now_active` in place (TASK-4065 removes it).
- `start_headless(..., coordination: Optional[str] = None)`: build the coordinator with `build_fire_coordinator(coordination, use_redis=use_redis)`,
  install it on the executor **before** `scheduler.start()`. `stop_headless`: close the coordinator (suppressed) and `jobs.unregister_manager(self.registered_name)`.
- `_execution_fields(schedule)` (new, the old `_job_kwargs_from_schedule` body) and `_job_kwargs_from_schedule(schedule)`, which now returns
  `{"manager_name", "schedule_id", "fingerprint"}`.
- `_run_db_schedule(schedule_id, fingerprint, *, run_now=False)` and `_run_auto_task(job_id)` (new).
- Switch these `add_job` sites to trampolines: `add_schedule` (also move `success_callback` into `_local_callbacks`),
  `load_schedules_from_db`, `update_schedule`, `register_bot_schedules` (store the bound method etc. in `_auto_tasks`),
  `SchedulerHandler.patch`.
- Keep run-now working: in `run_schedule_now` use `self._execution_fields(schedule)` for the `_run_now_wrapper` kwargs.
- Write `tests/scheduler/test_fire_recheck.py`.

**NOT in scope**: the run-now trampoline, the cross-worker 409 and removing `_run_now_wrapper`/`_run_now_active` (TASK-4065);
`_on_coordination_unavailable` (TASK-4065; pass no `on_unavailable` hook yet); docs/integration tests (TASK-4066).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-server/src/parrot/scheduler/manager.py` | MODIFY | wiring, re-check, trampolines |
| `packages/ai-parrot-server/tests/scheduler/test_fire_recheck.py` | CREATE | re-check + picklability tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# inside manager.py (relative imports, same style as manager.py:42-55)
from . import jobs                                                   # added by TASK-4063 — do not add twice
from .coordination import CoordinatedAsyncIOExecutor, FireCoordinator, NullFireCoordinator, build_fire_coordinator  # TASK-4062
from asyncdb.exceptions import NoDataFound                           # verified: asyncdb/exceptions/exceptions.py:110; raised by Model.get on a missing row (asyncdb/models/model.py:387)
import hashlib                                                       # stdlib
from .sanitize import normalize_schedule_type, sanitize_schedule_config, normalize_jobstore_alias   # verified: manager.py:43-52
from apscheduler.jobstores.base import JobLookupError                # verified: manager.py:29
```

### Existing Signatures to Use
```python
# packages/ai-parrot-server/src/parrot/scheduler/manager.py  (base b38a49b9d — re-verify after TASK-4063 lands; lines shift by ~+10)
class AgentSchedulerManager:                                          # line 324
    def __init__(self, bot_manager: Any = None, **kwargs):            # line 338
        self._run_now_active: Set[str] = set()                        # line 354
        self.registered_name = kwargs.get("registered_name", self.registered_name)   # line 355
        executors = {"default": AsyncIOExecutor()}                    # line 365
    async def _execute_agent_job(self, schedule_id: str, agent_name: str, prompt=None, method_name=None, metadata=None,
        *, is_crew=False, success_callback=None, send_result=None, callbacks=None)   # line 609 — keep the signature unchanged
    def _create_trigger(self, schedule_type: str, config: Dict[str, Any])           # line 920
    async def add_schedule(...)                                       # line 975; `# Add to APScheduler` at 1067; add_job at 1071-1082 (kwargs include "success_callback")
    async def _execute_agent_task(self, job_id, agent_name, method, *, success_callback=None, send_result=None, callbacks=None)  # line 1098 — keep unchanged
    def register_bot_schedules(self, bot: Any) -> int:                # line 1146; job_id = f"auto_{bot_name}_{method_name}" at 1189; add_job at 1195-1208
    async def load_schedules_from_db(self):                           # line 1237; add_job at 1271-1288
    def _job_kwargs_from_schedule(self, schedule: AgentSchedule) -> Dict[str, Any]:   # line 1322 (returns the 8 execution fields)
    async def get_schedule(self, schedule_id: str) -> AgentSchedule:  # line 1419 — tests monkeypatch THIS; use it in _run_db_schedule
    async def update_schedule(self, schedule_id, updates)             # line 1443; add_job at 1493-1501
    async def run_schedule_now(self, schedule_id: str) -> AgentSchedule:   # line 1521; `job_kwargs = self._job_kwargs_from_schedule(schedule)` inside
    def _safe_jobstore(self, value: Any, *, strict: bool = False) -> str:  # line 1658
    async def start_headless(self, *, dsn=None, use_redis=False, register_listeners=True) -> None:  # line 1720; `if not self.scheduler.running:` at 1762
    async def stop_headless(self, *, wait: bool = True) -> None:      # line 1770
class SchedulerHandler(CorsViewMixin, web.View):                      # line 1897; patch re-add `scheduler_manager.scheduler.add_job(` at 2005
```

### Does NOT Exist
- ~~`AgentSchedulerManager._on_coordination_unavailable`~~: TASK-4065 creates it. Do not reference it here.
- ~~`jobs.run_db_schedule_now` usage in this task~~: TASK-4065 wires it.
- ~~`AgentSchedule.get` returning `None` for a missing row~~: it raises `NoDataFound`.
- ~~persisting `success_callback` on the row~~: it is code-only and stays process-local (`_local_callbacks`).

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot-server/src/parrot/scheduler/manager.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot-server/tests/scheduler/test_fire_recheck.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-server/src/parrot/scheduler/manager.py#AgentSchedulerManager.__init__",
    "sym:packages/ai-parrot-server/src/parrot/scheduler/manager.py#AgentSchedulerManager._execute_agent_job",
    "sym:packages/ai-parrot-server/src/parrot/scheduler/manager.py#AgentSchedulerManager._execute_agent_task",
    "sym:packages/ai-parrot-server/src/parrot/scheduler/manager.py#AgentSchedulerManager.add_schedule",
    "sym:packages/ai-parrot-server/src/parrot/scheduler/manager.py#AgentSchedulerManager.register_bot_schedules",
    "sym:packages/ai-parrot-server/src/parrot/scheduler/manager.py#AgentSchedulerManager.load_schedules_from_db",
    "sym:packages/ai-parrot-server/src/parrot/scheduler/manager.py#AgentSchedulerManager._job_kwargs_from_schedule",
    "sym:packages/ai-parrot-server/src/parrot/scheduler/manager.py#AgentSchedulerManager.get_schedule",
    "sym:packages/ai-parrot-server/src/parrot/scheduler/manager.py#AgentSchedulerManager.update_schedule",
    "sym:packages/ai-parrot-server/src/parrot/scheduler/manager.py#AgentSchedulerManager.run_schedule_now",
    "sym:packages/ai-parrot-server/src/parrot/scheduler/manager.py#AgentSchedulerManager.start_headless",
    "sym:packages/ai-parrot-server/src/parrot/scheduler/manager.py#AgentSchedulerManager.stop_headless",
    "sym:packages/ai-parrot-server/src/parrot/scheduler/manager.py#SchedulerHandler.patch"
  ]
}
```

---

## Implementation Blueprint

### Steps (in order)
1. Add the imports and `schedule_fingerprint`. *Why*: the fingerprint is the cross-process "did the trigger change" signal (G3).
2. Update `__init__`. *Why*: the executor must exist at construction because `AsyncIOScheduler` takes executors in its constructor (`manager.py:372`).
3. Update `start_headless`/`stop_headless`. *Why*: Redis is only known at start time (G6); agentd must keep `none` by default (AC9).
4. Split `_job_kwargs_from_schedule` into `_execution_fields` + trampoline kwargs.
5. Add `_run_db_schedule` and `_run_auto_task`.
6. Switch the five `add_job` sites. *Why*: AC5 (`grep -n "add_job(\s*self\._"` must be empty once TASK-4065 lands).
7. In `run_schedule_now`, replace `job_kwargs = self._job_kwargs_from_schedule(schedule)` with `job_kwargs = self._execution_fields(schedule)`.
   *Why*: `_run_now_wrapper` still forwards execution fields until TASK-4065, and `test_run_now.py` must stay green.
8. Write `test_fire_recheck.py`.

### `manager.py` (MODIFY): imports + fingerprint
```python
# AFTER — insert below `from . import jobs` (added by TASK-4063; verify with grep -c 'from . import jobs' manager.py == 1)
from .coordination import CoordinatedAsyncIOExecutor, FireCoordinator, NullFireCoordinator, build_fire_coordinator
# also add `import hashlib` to the stdlib block (after `import inspect`, manager.py:11) and
# `from asyncdb.exceptions import NoDataFound` after `from asyncdb import AsyncDB` (manager.py:39)


def schedule_fingerprint(schedule: AgentSchedule) -> str:
    """Stable hash of what determines a schedule's trigger placement (FEAT-631).

    Two workers holding the same row produce the same value; a change made in any worker
    to ``schedule_type``/``schedule_config``/``scheduler_type`` changes it.
    """
    schedule_type = normalize_schedule_type(schedule.schedule_type)
    payload = json.dumps(
        {
            "schedule_type": schedule_type,
            "schedule_config": sanitize_schedule_config(schedule_type, schedule.schedule_config),
            "scheduler_type": normalize_jobstore_alias(schedule.scheduler_type),
        },
        sort_keys=True,
        default=str,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
# place this function after `_resolve_report_schedule` (manager.py:285), before `class _SchedulerNotification` (manager.py:318).
# Verified 2026-10-05: normalize_jobstore_alias(None) == "default", normalize_jobstore_alias("redis") == "redis" — no special-casing needed.
```

### `manager.py` (MODIFY): `__init__`
```python
# occurrences: 1 (verified: grep -c '        executors = {"default": AsyncIOExecutor()}' manager.py)
# REPLACE `        executors = {"default": AsyncIOExecutor()}` (verified: manager.py:365) with:
        executors = {"default": CoordinatedAsyncIOExecutor()}
# AND AFTER — insert below `        self.registered_name = kwargs.get("registered_name", self.registered_name)` (verified: manager.py:355; occurrences 1)
        # FEAT-631: cross-worker coordination (replaced in start_headless) + process-local, non-picklable job state.
        self._fire_coordinator: FireCoordinator = NullFireCoordinator()
        self._local_callbacks: Dict[str, Callable] = {}
        self._auto_tasks: Dict[str, Dict[str, Any]] = {}
        jobs.register_manager(self)
```

### `manager.py` (MODIFY): start/stop_headless
```python
# start_headless signature (verified: manager.py:1720-1726): add a keyword-only parameter after register_listeners:
        coordination: Optional[str] = None,
# document it in the Args block: "Fire coordination mode ('redis'|'none'); None → SCHEDULER_COORDINATION, else 'redis' when use_redis."
# occurrences: 1 (verified: grep -c '        if not self.scheduler.running:' manager.py)
# BEFORE `        if not self.scheduler.running:` (verified: manager.py:1762) insert:
        self._fire_coordinator = build_fire_coordinator(coordination, use_redis=use_redis)
        executor = self.scheduler._lookup_executor("default")
        if isinstance(executor, CoordinatedAsyncIOExecutor):
            executor.set_coordinator(self._fire_coordinator)
# Verified 2026-10-05: scheduler._lookup_executor("default") returns the constructor-supplied executor BEFORE start().
# stop_headless: BEFORE `        self.logger.notice("Agent Scheduler stopped (headless)")` (verified: manager.py:1792; occurrences 1)
        with contextlib.suppress(Exception):
            await self._fire_coordinator.close()
        jobs.unregister_manager(self.registered_name)
```

### `manager.py` (MODIFY): job kwargs + fire-time re-check (replaces `_job_kwargs_from_schedule`, manager.py:1322)
```python
    def _execution_fields(self, schedule: AgentSchedule) -> Dict[str, Any]:
        """Execution arguments for :meth:`_execute_agent_job`, read from the row (the old _job_kwargs_from_schedule body)."""
        return {
            "schedule_id": str(schedule.schedule_id),
            "agent_name": schedule.agent_name,
            "prompt": schedule.prompt,
            "method_name": schedule.method_name,
            "metadata": dict(schedule.metadata or {}),
            "is_crew": schedule.is_crew,
            "send_result": dict(schedule.send_result or {}),
            "callbacks": list(schedule.callbacks or []),
        }

    def _job_kwargs_from_schedule(self, schedule: AgentSchedule) -> Dict[str, Any]:
        """Picklable kwargs for :func:`jobs.run_db_schedule` — str values only (FEAT-631)."""
        return {
            "manager_name": self.registered_name,
            "schedule_id": str(schedule.schedule_id),
            "fingerprint": schedule_fingerprint(schedule),
        }

    async def _run_db_schedule(self, schedule_id: str, fingerprint: Optional[str], *, run_now: bool = False) -> Any:
        """Fire-time re-check, then execute with the row's current fields (spec §3 M3)."""
        schedule_id = str(schedule_id)
        try:
            schedule = await self.get_schedule(schedule_id)
        except NoDataFound:
            # FILL IN: log info; unless run_now, remove the local job (suppress JobLookupError); return jobs.SKIPPED — bounded by AC3
            ...
        # FILL IN: if not run_now and not schedule.enabled → remove local job, return jobs.SKIPPED — bounded by AC3/AC4
        # FILL IN: if not run_now and fingerprint and schedule_fingerprint(schedule) != fingerprint →
        #          if the jobstore alias is unchanged: self.scheduler.reschedule_job(schedule_id, jobstore=..., trigger=self._create_trigger(...))
        #          and modify_job(kwargs=self._job_kwargs_from_schedule(schedule)); else remove + re-add in the new store;
        #          return jobs.SKIPPED — bounded by AC3 + spec §7 "Reschedule on fingerprint change"
        return await self._execute_agent_job(
            **self._execution_fields(schedule),
            success_callback=self._local_callbacks.get(schedule_id),
        )

    async def _run_auto_task(self, job_id: str) -> Any:
        """Run a decorator-registered task from its process-local registration."""
        task = self._auto_tasks.get(job_id)
        if task is None:
            raise LookupError(f"Unknown auto-schedule {job_id!r} in this process")
        return await self._execute_agent_task(job_id, task["agent_name"], task["method"],
                                              success_callback=task["success_callback"],
                                              send_result=task["send_result"], callbacks=task["callbacks"])
```

### `manager.py` (MODIFY): the five `add_job` sites
```python
# 1) add_schedule (verified: `            job = self.scheduler.add_job(` occurs 2× — this one follows `        # Add to APScheduler`, manager.py:1067/1071):
#    func → jobs.run_db_schedule ; kwargs → self._job_kwargs_from_schedule(schedule)   (drop the "success_callback" kwarg)
#    and BEFORE add_job: `if success_callback is not None: self._local_callbacks[str(schedule.schedule_id)] = success_callback`
# 2) load_schedules_from_db (verified: `                            self._execute_agent_job,` occurs 1×, manager.py:1272):
#    func → jobs.run_db_schedule ; kwargs → self._job_kwargs_from_schedule(schedule_data)
# 3) update_schedule (the other `            job = self.scheduler.add_job(`, followed by `                id=job_id,`, manager.py:1493):
#    func → jobs.run_db_schedule (kwargs already come from _job_kwargs_from_schedule — unchanged call)
# 4) register_bot_schedules (verified: `                    self._execute_agent_task,` occurs 1×, manager.py:1196):
#    BEFORE add_job: self._auto_tasks[job_id] = {"agent_name": bot_name, "method": method, "success_callback": success_callback,
#                                               "send_result": send_result, "callbacks": callbacks}
#    func → jobs.run_auto_schedule ; kwargs → {"manager_name": self.registered_name, "job_id": job_id}
# 5) SchedulerHandler.patch (verified: `                    scheduler_manager.scheduler.add_job(` occurs 1×, manager.py:2005):
#    func → jobs.run_db_schedule ; kwargs → scheduler_manager._job_kwargs_from_schedule(schedule) ;
#    FILL IN: also pass jobstore=scheduler_manager._safe_jobstore(schedule.scheduler_type) (it is missing today) — bounded by AC5
```

### `packages/ai-parrot-server/tests/scheduler/test_fire_recheck.py` (CREATE)
```python
"""Fire-time re-check + trampoline wiring (FEAT-631 TASK-4064)."""
import pickle
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from asyncdb.exceptions import NoDataFound

from parrot.scheduler import jobs
from parrot.scheduler.manager import AgentSchedulerManager, schedule_fingerprint

# FILL IN: fixture `manager` — AgentSchedulerManager(registered_name="recheck_mgr"); await start_headless(); yield; await stop_headless(wait=False)
# FILL IN: test_trampoline_job_is_picklable — add an interval job via the load path helper (or add_job with jobs.run_db_schedule + _job_kwargs_from_schedule);
#          job.func_ref == "parrot.scheduler.jobs:run_db_schedule"; pickle.dumps(job.__getstate__()) succeeds
# FILL IN: test_fire_skips_deleted_row — get_schedule raises NoDataFound → SKIPPED, local job removed, _execute_agent_job not called
# FILL IN: test_fire_skips_disabled_row — enabled=False → SKIPPED
# FILL IN: test_fire_reschedules_on_fingerprint_change — stale fingerprint → reschedule called, SKIPPED
# FILL IN: test_fire_uses_row_fields — row prompt "new" → _execute_agent_job awaited with prompt="new"
# FILL IN: test_local_success_callback_forwarded — _local_callbacks[sid] passed as success_callback
# FILL IN: test_auto_task_routes_through_trampoline — register_bot_schedules on a bot with a @schedule method; job.func is jobs.run_auto_schedule
# FILL IN: test_no_bound_method_jobs — every job in manager.scheduler.get_jobs() has func.__module__ == "parrot.scheduler.jobs" (excluding run_now:* until TASK-4065)
# FILL IN: test_start_headless_installs_coordinator — coordination="none" → NullFireCoordinator on the executor; "bogus" → SchedulerConfigError
```

### FILL IN checklist
- [ ] `schedule_fingerprint` is deterministic (unit-test two equal rows → equal hash)
- [ ] `_run_db_schedule`'s three skip branches; bounded by AC3/AC4
- [ ] `SchedulerHandler.patch` jobstore argument
- [ ] the 9 tests

---

## Acceptance Criteria

- [ ] No `add_job` site except `run_schedule_now` passes a bound method; every job's kwargs are `str` only and pickle (AC5, partial; TASK-4065 finishes it).
- [ ] A missing or disabled row returns `SKIPPED` and drops the local job; a changed fingerprint reschedules; row edits are used (AC3).
- [ ] `start_headless(coordination="bogus")` raises `SchedulerConfigError`; agentd's call (`start_headless(dsn=..., use_redis=...)`) still works (AC7, AC9).
- [ ] `test_run_now.py`, `test_headless.py` and `test_manager_sanitization.py` still pass (plus `test_listeners.py` from TASK-4063, run during the merge-tier check).
- [ ] `ruff check` is clean on the changed files.

---

## Validation Commands

- `pytest packages/ai-parrot-server/tests/scheduler/test_fire_recheck.py -q`
- `pytest packages/ai-parrot-server/tests/scheduler/test_run_now.py -q`
- `pytest packages/ai-parrot-server/tests/scheduler/test_headless.py -q`
- `pytest packages/ai-parrot-server/tests/scheduler/test_manager_sanitization.py -q`

---

## Test Specification

See the `test_fire_recheck.py` block above.

---

## Agent Instructions

1. Work in the feature worktree (`python -m scripts.sdd.ensure_worktree --slug scheduler-multiworker-correctness --feature-id FEAT-631 --spec sdd/specs/scheduler-multiworker-correctness.spec.md --index sdd/tasks/index/scheduler-multiworker-correctness.json`). TASK-4061, 4062 and 4063 must be `done`.
2. Line numbers shift after TASK-4063: re-run every anchor's `grep -c`. A count of 0 means drift: stop and report.
3. Implement and validate with `PYTHONPATH=packages/ai-parrot-server/src:packages/ai-parrot/src`.
4. Commit only the listed files: `feat(scheduler-multiworker-correctness): TASK-4064 — trampolines + fire-time re-check`.
5. Run `scripts/sdd/close_task.sh TASK-4064 scheduler-multiworker-correctness verified`, fill in the Completion Note, commit, and push.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none
