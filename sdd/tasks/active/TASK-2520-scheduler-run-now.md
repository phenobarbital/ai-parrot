# TASK-2520: Scheduler run-now action + last-execution result

**Feature**: FEAT-467 — Agent Studio — Management API
**Spec**: `sdd/specs/agentstudio-management.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 12. Resolved in brainstorm: scheduler management is CRUD
(exists) **+ run-now/test with last execution result** (new). Extends the
existing `SchedulerJobsHandler` rather than adding a parallel handler.
Touches only scheduler files — independent of the studio package
(`parallel: true`).

---

## Scope

- Extend `SchedulerJobsHandler.patch` with `action="run_now"`:
  - Trigger the job immediately, once, WITHOUT changing its schedule
    state (a paused/disabled job may still be run-now — it runs once and
    stays paused).
  - Guard against concurrent run-now on the same `schedule_id` → 409.
- Add last-execution-result read:
  `GET /api/v1/parrot/scheduler/schedules/{schedule_id}/last-result` —
  returns `last_run`, `next_run`, `run_count`, and result/error metadata
  from the `navigator.agents_scheduler` row (verify at implementation how
  execution results are recorded in `AgentSchedulerManager` — likely
  `metadata`/`send_result` columns; extend the manager's job-completion
  callback to stamp a `last_result` entry into `metadata` if nothing
  suitable exists).
- Unit tests with a mocked/ephemeral APScheduler.

**NOT in scope**: scheduler CRUD (exists); Studio routes (this endpoint
stays under `/api/v1/parrot/scheduler/`); the global `POST /restart`.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-server/src/parrot/handlers/scheduler.py` | MODIFY | run_now action + last-result GET |
| `packages/ai-parrot-server/src/parrot/scheduler/manager.py` | MODIFY | run-now trigger + last-result stamping + route |
| `packages/ai-parrot-server/tests/scheduler/test_run_now.py` | CREATE | run-now + last-result tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from navigator.views import BaseHandler, BaseView   # handlers/scheduler.py:8
# ScheduleType from ..scheduler; list_supported_callbacks from ..scheduler.functions;
# SchedulerConfigError from ..scheduler.sanitize   (handlers/scheduler.py:10-12)
```

### Existing Signatures to Use
```python
# packages/ai-parrot-server/src/parrot/handlers/scheduler.py
class SchedulerJobsHandler(BaseView):  # :53
    @property
    def manager(self): ...  # :61-66 → request.app["scheduler_manager"];
                            #   RuntimeError when unconfigured
    def _error_response(self, message: str, status: int = 400) -> web.Response: ...  # :68
    async def get(self) -> web.Response: ...    # :71  ({schedule_id} optional)
    async def post(self) -> web.Response: ...   # :91
    async def patch(self) -> web.Response: ...  # :123
        # action ∈ {"pause","resume","update"} dispatch at :132-139 — ADD "run_now" here
    async def delete(self) -> web.Response: ... # :148
# APScheduler access: manager.scheduler.get_job(schedule_id)  (:75);
#   jobstores: manager.scheduler._jobstores.keys()  (:27)

# packages/ai-parrot-server/src/parrot/scheduler/manager.py
# class AgentSchedulerManager (74KB file):
#   setup(app=...) registers app['scheduler_manager'] and routes :1703-1719:
#     /api/v1/parrot/scheduler/schedules[,/{schedule_id}], /callbacks,
#     POST /restart (:1716-1719) — add the last-result route beside these
#   DB registered as "agentdb": self.db.configure(app, register="agentdb") (:1694)

# packages/ai-parrot-server/src/parrot/scheduler/models.py:7
class AgentSchedule(Model):
    # columns (docstring DDL :11-36): schedule_id UUID PK, agent_id, agent_name,
    # prompt, method_name, schedule_type, schedule_config JSONB, enabled,
    # created_by, created_email, created_at, updated_at, last_run, next_run,
    # run_count, metadata JSONB, is_crew, send_result JSONB, scheduler_type,
    # callbacks JSONB
    class Meta: driver='pg'; name="agents_scheduler"; schema="navigator"  # :59-64
```

### Does NOT Exist
- ~~`action="run_now"` in patch~~ — THIS task adds it (today only
  pause/resume/update).
- ~~A per-job immediate trigger or last-result endpoint~~ — only the
  global `POST /api/v1/parrot/scheduler/restart` exists.
- ~~A `last_result` column~~ — not in the DDL; stamp into `metadata`
  JSONB (or verify an existing result-recording path in
  `AgentSchedulerManager` before adding one).
- ~~Studio-package involvement~~ — no imports from `handlers/studio/`.

---

## Implementation Notes

### Pattern to Follow
APScheduler immediate trigger: fetch the job
(`manager.scheduler.get_job(schedule_id)`) and either
`job.modify(next_run_time=datetime.now(tz))` on a one-shot clone or invoke
the manager's own execution coroutine directly (grep
`AgentSchedulerManager` for the function APScheduler jobs call — reuse it
so run-now takes the SAME code path as scheduled runs, callbacks included).

### Key Constraints
- Run-now must not mutate `schedule_config`, `enabled`, or the stored
  trigger; `run_count`/`last_run` update as a normal run does.
- Concurrency guard: in-memory `set[schedule_id]` (or Redis if the manager
  already tracks running jobs — verify) → 409 while active.
- Sanitize inputs through the existing `SchedulerConfigError` machinery.

### References in Codebase
- `packages/ai-parrot-server/tests/scheduler/test_manager_sanitization.py`
  — existing scheduler test setup to mirror.

---

## Acceptance Criteria

- [ ] `PATCH action="run_now"` triggers exactly one execution via the same
      code path as scheduled runs; schedule state unchanged.
- [ ] Concurrent run-now on the same job → 409.
- [ ] Last-result endpoint returns `last_run`/`run_count` + stamped result
      metadata after a run-now.
- [ ] Existing pause/resume/update behavior untouched (regression test).
- [ ] `pytest packages/ai-parrot-server/tests/scheduler/test_run_now.py -v` passes.
- [ ] `ruff check packages/ai-parrot-server/src/parrot/handlers/scheduler.py packages/ai-parrot-server/src/parrot/scheduler/` clean.

---

## Test Specification

```python
# packages/ai-parrot-server/tests/scheduler/test_run_now.py
class TestRunNow:
    async def test_run_now_executes_once(self, scheduler_app): ...
    async def test_run_now_preserves_schedule_state(self, scheduler_app): ...
    async def test_run_now_on_paused_job(self, scheduler_app): ...
    async def test_concurrent_run_now_409(self, scheduler_app): ...
    async def test_last_result_populated(self, scheduler_app): ...
    async def test_existing_actions_unchanged(self, scheduler_app): ...
```

---

## Agent Instructions

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — none (parallel-safe: scheduler files only)
3. **Verify the Codebase Contract** — grep `AgentSchedulerManager` for the
   job-execution coroutine and any existing result recording BEFORE coding
4. **Update status** in `sdd/tasks/index/agentstudio-management.json` → `"in-progress"`
5. **Implement**, **verify** acceptance criteria
6. **Move this file** to `sdd/tasks/completed/`
7. **Update index** → `"done"`, fill Completion Note

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none
