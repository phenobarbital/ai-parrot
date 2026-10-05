# TASK-4066: Multi-worker integration tests and operator docs for the scheduler

**Feature**: FEAT-631 — Scheduler multi-worker correctness
**Spec**: `sdd/specs/scheduler-multiworker-correctness.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-4065
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 5 / AC2, AC3, AC9, AC11. TASK-4061 to TASK-4065 deliver the mechanism with unit tests. This task proves the
end-to-end claims of issue #1573 with two real `AgentSchedulerManager` instances (two real `AsyncIOScheduler`s) over one shared
fake Redis and one shared fake row store, and documents the operator-facing behaviour, including the release note for the
listener behaviour change.

---

## Scope

- Write `tests/scheduler/test_multiworker.py`:
  - `test_two_workers_one_fire`: both managers load the same interval row, and one due fire calls the agent once, bumps `run_count` once and runs the success callback once.
  - `test_auto_job_one_fire`: the same for a decorator `@schedule` job.
  - `test_delete_in_one_worker_stops_other`: worker A deletes; B's next fire returns `SKIPPED` and B drops its local job.
  - `test_redis_down_fails_closed`: no execution in either worker, and the row ends up with `lock_unavailable`.
- Write `docs/scheduler/multi-worker.md`: coordination modes and config keys (`SCHEDULER_COORDINATION`,
  `SCHEDULER_FIRE_LOCK_TTL`, `SCHEDULER_RUN_NOW_LOCK_TTL`), the Redis key layout, fail-closed semantics, the fact that the
  `redis` jobstore gives persistence but **not** coordination, how delete/pause/update propagate (at the next fire), the agentd
  default (`none`), and a "Behaviour change in ai-parrot-server 0.28.0" section (listeners on: `send_result` emails and callbacks
  now fire for existing DB schedules on aiohttp).
- Add a one-line link to the new page at the end of `docs/agentd.md`'s `## Scheduler modes` section (verified: docs/agentd.md:178).

**NOT in scope**: code changes in `manager.py`/`coordination.py`/`jobs.py`. If a test exposes a bug, stop and report it in the
Completion Note (status `done-with-issues`), and do not patch production code here.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-server/tests/scheduler/test_multiworker.py` | CREATE | two-manager integration tests |
| `docs/scheduler/multi-worker.md` | CREATE | operator documentation + release note |
| `docs/agentd.md` | MODIFY | link to the new page under `## Scheduler modes` |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.scheduler import jobs                                       # TASK-4061
from parrot.scheduler.coordination import RedisFireCoordinator, CoordinatedAsyncIOExecutor   # TASK-4062
from parrot.scheduler.manager import AgentSchedulerManager, schedule, ScheduleType   # schedule decorator verified: manager.py:90; ScheduleType: manager.py:62
from parrot.scheduler import manager as manager_module                  # verified: test_run_now.py:30
from apscheduler.triggers.interval import IntervalTrigger                # verified: manager.py:35
```

### Existing Signatures to Use
```python
# manager.py after TASK-4065 (re-grep; names fixed by spec §3):
#   AgentSchedulerManager(bot_manager=None, registered_name=...)   — registered_name via kwargs (manager.py:355 at base)
#   start_headless(*, dsn=None, use_redis=False, register_listeners=True, coordination=None)
#   _fire_coordinator (attribute), _run_db_schedule(schedule_id, fingerprint, *, run_now=False), _job_kwargs_from_schedule(schedule)
#   load_schedules_from_db()  — needs self._pool; tests use a fake pool whose conn.query returns ([row_dict], None)
#   delete_schedule(schedule_id) / get_schedule(schedule_id) — monkeypatch get_schedule/AgentSchedule.get as test_run_now.py does (lines 137-230)
# test doubles to copy (not import): _FakeBot (test_run_now.py:67), _FakeBotManager (:80), _FakePoolAcquireCtx (:89), _FakePool (:100)
```

### Does NOT Exist
- ~~a real Redis/Postgres in unit CI~~: use the dict-backed `FakeRedis` (copy it from `test_coordination.py`) and fake pools.
- ~~`docs/scheduler/`~~: the directory does not exist yet; this task creates it.
- ~~a shared conftest fixture for scheduler doubles~~: none. Keep the doubles local to the file; do not add a `conftest.py`.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot-server/tests/scheduler/test_multiworker.py", "action": "CREATE"},
    {"path": "docs/scheduler/multi-worker.md", "action": "CREATE"},
    {"path": "docs/agentd.md", "action": "MODIFY"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-server/src/parrot/scheduler/manager.py#AgentSchedulerManager",
    "sym:packages/ai-parrot-server/src/parrot/scheduler/manager.py#schedule"
  ]
}
```

---

## Implementation Blueprint

### Steps (in order)
1. Build the fixtures: one `FakeRedis`, one in-memory row dict, two managers with distinct `registered_name`, each given
   `RedisFireCoordinator(fake_redis, worker_id="w1"/"w2")` via `manager._fire_coordinator = …` plus `executor.set_coordinator(…)`.
   *Why*: this reproduces two gunicorn workers deterministically.
2. Drive one fire per manager **with the same `run_times`**. Call each manager's executor `_do_submit_job(job, [run_time])`
   directly (or `executor.submit_job`), then await the pending futures. *Why*: waiting on wall-clock triggers makes tests flaky.
3. Assert the side effects with counters on the fake bot and the fake row.
4. Write the docs page.

### `packages/ai-parrot-server/tests/scheduler/test_multiworker.py` (CREATE)
```python
"""Two-worker behaviour of the agent scheduler (FEAT-631 TASK-4066, issue #1573)."""
import asyncio
from datetime import datetime, timezone

import pytest

from parrot.scheduler import jobs
from parrot.scheduler.coordination import RedisFireCoordinator
from parrot.scheduler.manager import AgentSchedulerManager

# FILL IN: FakeRedis (copy from test_coordination.py), fake bot/bot_manager/pool (copy `_FakeBot`/`_FakeBotManager`/`_FakePoolAcquireCtx`/`_FakePool` from test_run_now.py:67-106)
# FILL IN: fixture two_managers(fake_redis, rows) → (m1, m2), started with start_headless(coordination="none") then
#          coordinators swapped to RedisFireCoordinator(fake_redis, worker_id=...) on both manager and executor; teardown stop_headless
# FILL IN: helper fire_once(manager, job_id, run_time) → executor._do_submit_job(job, [run_time]); await asyncio.gather(*executor._pending_futures)
# FILL IN: test_two_workers_one_fire (AC2), test_auto_job_one_fire (AC2), test_delete_in_one_worker_stops_other (AC3),
#          test_redis_down_fails_closed (AC6, FakeRedis(raise_on=True))
```

### `docs/scheduler/multi-worker.md` (CREATE)
```markdown
# Agent scheduler in multi-worker deployments

<!-- FILL IN: sections — Overview (issue #1573 symptoms), Coordination modes, Configuration (table of the 3 keys + defaults),
     How a fire is claimed (key `parrot:scheduler:fire:{job_id}:{iso_run_time}`, TTL), Fail-closed behaviour (`lock_unavailable`),
     Propagation of delete/pause/update (next fire), Run-now across workers (409), `scheduler_type="redis"` (persistence ≠ coordination),
     agentd (single process → `none` by default), Behaviour change in 0.28.0 (listeners on aiohttp) — bounded by AC11; every key/name
     must match the code, no invented settings -->
```

### `docs/agentd.md` (MODIFY)
```markdown
<!-- occurrences: 1 (verified: grep -c '^## Scheduler modes' docs/agentd.md) — section starts at docs/agentd.md:178.
     Append as the LAST line of that section (just before the next `## ` heading): -->
Multi-worker coordination, fail-closed behaviour and the 0.28.0 listener change: see [scheduler/multi-worker.md](scheduler/multi-worker.md).
```
**Why**: agentd is single-process (coordination `none` by default), but operators running it beside the aiohttp server must know the two share the same schedule table.

### FILL IN checklist
- [ ] the 4 integration tests; bounded by AC2/AC3/AC6
- [ ] all docs sections; bounded by AC11 and the "no invented settings" rule

---

## Acceptance Criteria

- [ ] All four integration tests pass, and they are deterministic (no wall-clock sleeps beyond awaiting pending futures).
- [ ] `docs/scheduler/multi-worker.md` exists and covers every AC11 item; its config names match `coordination.py` exactly.
- [ ] No production code changed by this task.
- [ ] `ruff check packages/ai-parrot-server/tests/scheduler/test_multiworker.py` is clean.

---

## Validation Commands

- `pytest packages/ai-parrot-server/tests/scheduler/test_multiworker.py -q`

---

## Test Specification

See the `test_multiworker.py` block above.

---

## Agent Instructions

1. Work in the feature worktree (`python -m scripts.sdd.ensure_worktree --slug scheduler-multiworker-correctness --feature-id FEAT-631 --spec sdd/specs/scheduler-multiworker-correctness.spec.md --index sdd/tasks/index/scheduler-multiworker-correctness.json`). TASK-4065 must be `done`.
2. Verify the names the docs cite against `coordination.py`, `jobs.py` and `manager.py` as merged.
3. Validate with `PYTHONPATH=packages/ai-parrot-server/src:packages/ai-parrot/src`.
4. Commit only the listed files: `feat(scheduler-multiworker-correctness): TASK-4066 — multi-worker tests + docs`.
5. Run `scripts/sdd/close_task.sh TASK-4066 scheduler-multiworker-correctness verified`, fill in the Completion Note, commit, and push.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: gpt-5.6-terra (codex), orchestrated by sdd-worker
**Date**: 2026-10-05
**Notes**: 4 multiworker tests + docs delivered; merge validation green. Closed via close_task.sh.

**Deviations from spec**: none
