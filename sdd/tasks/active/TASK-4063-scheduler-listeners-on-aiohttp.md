# TASK-4063: Wire scheduler listeners on the aiohttp path and fix latent listener bugs

**Feature**: FEAT-631 — Scheduler multi-worker correctness
**Spec**: `sdd/specs/scheduler-multiworker-correctness.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-4061
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 4 / Goal G1 / AC1, AC8. `on_startup` passes `register_listeners=False` (`manager.py:1853`), so on aiohttp
the success stamping, `send_result` and callbacks never run. Turning the listeners on exposes three latent bugs:
- `job_status` dereferences `job.name` on a possibly-`None` job (`manager.py:484`);
- `scheduler_status` calls `print(event)` (`manager.py:457`);
- `next_run` is never refreshed.

`job_success` must also ignore the `SKIPPED` sentinel from TASK-4061.

**Deliberate behaviour change**: `tests/scheduler/test_headless.py::TestAiohttpDelegation` currently asserts the OLD
behaviour (`register_listeners=False`, `define_listeners` never called). This task inverts both tests. That is the
feature's purpose (spec G1, resolved in the proposal Q&A), not a regression.

---

## Scope

- `on_startup`: call `start_headless(use_redis=True, register_listeners=True)`; replace the FEAT-422 comment (lines 1840-1852)
  with a 3–4 line comment citing FEAT-631.
- `scheduler_status`: remove `print(event)`.
- `job_status`: tolerate `get_job()` returning `None` (`job_name = job_id`), never raise.
- `job_success`: when `event.retval is jobs.SKIPPED`, pop `_job_context` for the schedule and return `True` without scheduling `_process_job_success`.
- `_update_schedule_run`: set `schedule.next_run` from the local job's `next_run_time` when the job exists (success and error).
- `load_schedules_from_db`: after each successful `add_job`, stamp `next_run` on the row (one UPDATE per row is acceptable).
- Update `test_headless.py` (the two aiohttp tests) and add `tests/scheduler/test_listeners.py`.

**NOT in scope**: changing any `add_job` callable (TASK-4064), coordination (TASK-4062/4064), run-now (TASK-4065).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-server/src/parrot/scheduler/manager.py` | MODIFY | listeners on + latent fixes + next_run |
| `packages/ai-parrot-server/tests/scheduler/test_headless.py` | MODIFY | invert the two aiohttp-delegation assertions |
| `packages/ai-parrot-server/tests/scheduler/test_listeners.py` | CREATE | new listener tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.scheduler import jobs                      # created by TASK-4061 (jobs.SKIPPED) — inside manager.py use: from . import jobs
from apscheduler.events import EVENT_JOB_ERROR, EVENT_JOB_EXECUTED, JobExecutionEvent   # verified: manager.py:18-27
from parrot.scheduler.manager import AgentSchedulerManager   # verified: tests/scheduler/test_run_now.py:31
```

### Existing Signatures to Use
```python
# packages/ai-parrot-server/src/parrot/scheduler/manager.py  (base b38a49b9d, sha256 d94ad376…8673)
    def define_listeners(self):                                   # line 447
    def scheduler_status(self, event):                            # line 456; print(event) at 457
    def job_status(self, event: JobExecutionEvent):               # line 471; job = self.scheduler.get_job(job_id) at 483; job_name = job.name at 484
    def job_success(self, event: JobExecutionEvent):              # line 515; result = getattr(event, "retval", None) at 585
    async def _update_schedule_run(self, schedule_id: str, success: bool = True,
                                   error: Optional[str] = None, result: Any = None):   # line 863
        # schedule.last_run = datetime.now() at 897; schedule.run_count += 1 at 898; await schedule.update() at 915
    async def load_schedules_from_db(self):                       # line 1237; loaded += 1 at 1290
    async def on_startup(self, app: web.Application, conn: Callable):   # line 1831; start_headless call at 1853
# tests/scheduler/test_headless.py
class TestAiohttpDelegation:                                      # line 123
    async def test_on_startup_delegates(self, manager): ...       # line 124; asserts register_listeners=False at 134
    async def test_on_startup_never_wires_listeners_end_to_end(self, manager): ...  # line 136; mock_define.assert_not_called()
```

### Does NOT Exist
- ~~`jobs.SKIPPED` before TASK-4061 is merged~~: it depends on TASK-4061.
- ~~a `self._job_context` key other than the schedule_id string~~: context is keyed by `str(schedule_id)` (`manager.py:686`).
- ~~a feature flag for listeners~~: on by default, with no flag (resolved in the proposal Q&A).

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot-server/src/parrot/scheduler/manager.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot-server/tests/scheduler/test_headless.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot-server/tests/scheduler/test_listeners.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-server/src/parrot/scheduler/manager.py#AgentSchedulerManager.on_startup",
    "sym:packages/ai-parrot-server/src/parrot/scheduler/manager.py#AgentSchedulerManager.job_status",
    "sym:packages/ai-parrot-server/src/parrot/scheduler/manager.py#AgentSchedulerManager.job_success",
    "sym:packages/ai-parrot-server/src/parrot/scheduler/manager.py#AgentSchedulerManager.scheduler_status",
    "sym:packages/ai-parrot-server/src/parrot/scheduler/manager.py#AgentSchedulerManager._update_schedule_run",
    "sym:packages/ai-parrot-server/src/parrot/scheduler/manager.py#AgentSchedulerManager.load_schedules_from_db"
  ]
}
```

---

## Implementation Blueprint

### Steps (in order)
1. Add `from . import jobs` after `from .functions import build_scheduler_callback` (line 55). *Why*: `SKIPPED` lives there; a module import avoids name clashes.
2. Flip `on_startup` and rewrite its comment. *Why*: G1.
3. Apply the three latent fixes. *Why*: wiring the listeners makes these paths live (AC8).
4. Add the `next_run` refresh in `_update_schedule_run` and `load_schedules_from_db`. *Why*: AC1 lists `next_run`.
5. Invert the two `test_headless.py` tests and write `test_listeners.py`.

### `manager.py` (MODIFY): import
```python
# occurrences: 1 (verified: grep -c 'from .functions import build_scheduler_callback' manager.py)
# AFTER — insert below `from .functions import build_scheduler_callback` (verified: manager.py:55)
from . import jobs
```

### `manager.py` (MODIFY): scheduler_status
```python
# occurrences: 1 (verified: grep -c '        print(event)' manager.py)
# REPLACE line `        print(event)` (verified: manager.py:457) with nothing — delete the line; keep the two logger calls below it.
```

### `manager.py` (MODIFY): job_status
```python
# occurrences: 2 for `        job = self.scheduler.get_job(job_id)` (483 in job_status, 524 in job_success) — disambiguate:
# INSIDE `def job_status(self, event: JobExecutionEvent):` (verified: manager.py:471) replace:
#         job = self.scheduler.get_job(job_id)
#         job_name = job.name
# with:
        job = self.scheduler.get_job(job_id)
        # FEAT-631: one-shot / already-removed jobs are gone by the time this listener runs.
        job_name = job.name if job is not None else str(job_id)
```

### `manager.py` (MODIFY): job_success SKIPPED short-circuit
```python
# occurrences: 1 (verified: grep -c '        result = getattr(event, "retval", None)' manager.py)
# AFTER — insert below `        result = getattr(event, "retval", None)` (verified: manager.py:585)
        if result is jobs.SKIPPED:
            # FEAT-631: an intentionally skipped fire (row gone/disabled/rescheduled) is not a success.
            self._job_context.pop(schedule_id, None)
            return True
```
Note: `context = self._job_context.pop(schedule_id, {})` already ran at line 566, so the extra pop is a harmless safety net.

### `manager.py` (MODIFY): `_update_schedule_run` next_run
```python
# occurrences: 1 (verified: grep -c '                schedule.run_count += 1' manager.py)
# AFTER — insert below `                schedule.run_count += 1` (verified: manager.py:898)
                with contextlib.suppress(Exception):
                    local_job = self.scheduler.get_job(str(schedule_id))
                    if local_job is not None and local_job.next_run_time:
                        schedule.next_run = local_job.next_run_time
```

### `manager.py` (MODIFY): load_schedules_from_db next_run stamp
```python
# occurrences: 1 (verified: grep -c '                        loaded += 1' manager.py)
# BEFORE `                        loaded += 1` (verified: manager.py:1290) — capture the add_job return value
# FILL IN: change `self.scheduler.add_job(` at line 1271 to `job = self.scheduler.add_job(`, then before `loaded += 1`
#          stamp next_run on the row when job.next_run_time is set (e.g. `schedule_data.next_run = job.next_run_time;
#          await schedule_data.update()` under the same `AgentSchedule.Meta.connection = conn`), wrapped so a stamp failure
#          logs a warning but still counts the schedule as loaded — bounded by AC1; must not abort loading other rows
```

### `manager.py` (MODIFY): on_startup
```python
# occurrences: 1 (verified: grep -c '        await self.start_headless(use_redis=True, register_listeners=False)' manager.py)
# REPLACE the comment block at lines 1840-1852 and the call at 1853 with:
        # Delegate the transport-free bootstrap (jobstores, scheduler start, schedule loading) to
        # start_headless(). FEAT-631: listeners are wired here too, so success stamping, send_result
        # and callbacks run on the aiohttp path exactly as on the headless/agentd path (issue #1573).
        await self.start_headless(use_redis=True, register_listeners=True)
```

### `tests/scheduler/test_headless.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'mock_start.assert_awaited_once_with(use_redis=True, register_listeners=False)' test_headless.py)
# REPLACE that assertion with:
        mock_start.assert_awaited_once_with(use_redis=True, register_listeners=True)
# AND rename test_on_startup_never_wires_listeners_end_to_end → test_on_startup_wires_listeners_end_to_end,
# rewrite its docstring to cite FEAT-631, and replace `mock_define.assert_not_called()` with `mock_define.assert_called_once()`.
```

### `tests/scheduler/test_listeners.py` (CREATE)
```python
"""Listener behaviour on the aiohttp path (FEAT-631 TASK-4063)."""
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from apscheduler.events import EVENT_JOB_ERROR, EVENT_JOB_EXECUTED

from parrot.scheduler import jobs
from parrot.scheduler.manager import AgentSchedulerManager


@pytest.fixture
def manager():
    return AgentSchedulerManager()

# FILL IN: test_job_status_tolerates_missing_job — SimpleNamespace(job_id="gone", code=EVENT_JOB_ERROR, scheduled_run_time=None,
#          traceback=None, exception=RuntimeError("x")) → manager.job_status(event) does not raise
# FILL IN: test_job_success_ignores_skipped — patch manager.scheduler.get_job → SimpleNamespace(name="n", kwargs={"schedule_id": "s1"});
#          event retval=jobs.SKIPPED → returns True and _process_job_success is never scheduled (patch it with AsyncMock and assert not awaited/called)
# FILL IN: test_success_stamps_next_run — fake pool/AgentSchedule.get (copy _FakePool pattern from test_run_now.py:100-106),
#          local job with next_run_time → schedule.next_run equals it after _update_schedule_run(success=True)
# FILL IN: test_scheduler_status_does_not_print — capsys shows no stdout
```

### FILL IN checklist
- [ ] `load_schedules_from_db` captures `job` and stamps `next_run` without aborting the loop; bounded by AC1
- [ ] the 4 tests in `test_listeners.py`; bounded by spec §4 M4 rows

---

## Acceptance Criteria

- [ ] `on_startup` awaits `start_headless(use_redis=True, register_listeners=True)` (AC1).
- [ ] `grep -n "print(" packages/ai-parrot-server/src/parrot/scheduler/manager.py` returns nothing (AC8).
- [ ] `job_status` does not raise when the job is gone (AC8).
- [ ] A `SKIPPED` retval causes no DB stamp or callbacks.
- [ ] `next_run` is refreshed after a fire and on load.
- [ ] Existing `test_headless.py` (with the two inverted tests) and `test_run_now.py` pass; `ruff check` is clean on the changed files.

---

## Validation Commands

- `pytest packages/ai-parrot-server/tests/scheduler/test_listeners.py -q`
- `pytest packages/ai-parrot-server/tests/scheduler/test_headless.py -q`
- `pytest packages/ai-parrot-server/tests/scheduler/test_run_now.py -q`

---

## Test Specification

See the blocks above.

---

## Agent Instructions

1. Work in the feature worktree (`python -m scripts.sdd.ensure_worktree --slug scheduler-multiworker-correctness --feature-id FEAT-631 --spec sdd/specs/scheduler-multiworker-correctness.spec.md --index sdd/tasks/index/scheduler-multiworker-correctness.json`). TASK-4061 must be `done`.
2. Re-run each anchor's `grep -c`. A count of 0 means drift: stop and report.
3. Implement and validate with `PYTHONPATH=packages/ai-parrot-server/src:packages/ai-parrot/src`.
4. Commit only the listed files: `feat(scheduler-multiworker-correctness): TASK-4063 — listeners on aiohttp`.
5. Run `scripts/sdd/close_task.sh TASK-4063 scheduler-multiworker-correctness verified`, fill in the Completion Note, commit, and push.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none
