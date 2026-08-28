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

**Completed by**: sdd-worker (autonomous)
**Date**: 2026-08-27
**Notes**:
- `SchedulerJobsHandler.patch()` gained `action="run_now"` (409 on
  conflict via the new `SchedulerRunNowConflictError`); new
  `SchedulerLastResultHandler` (`GET .../schedules/{schedule_id}/
  last-result`) registered alongside the existing `{schedule_id}` route
  (different path-segment count — no aiohttp ordering trap).
- `AgentSchedulerManager.run_schedule_now()` schedules a one-shot
  APScheduler `DateTrigger("now")` job (deterministic id
  `"run_now:{schedule_id}"`) whose target is `_run_now_wrapper()` — a
  thin pass-through that calls the SAME `_execute_agent_job()` coroutine
  scheduled runs use (transparent return/exception propagation) and
  releases the new in-memory `_run_now_active: set[str]` concurrency
  guard in a `finally`. Never touches `enabled`/`schedule_config`/the
  stored trigger — a paused job stays paused after running once.
- **Two pre-existing bugs fixed, both directly blocking this feature's
  acceptance criteria** (grepped `AgentSchedulerManager` per the task's
  own instruction before writing code, per Codebase Contract step 3):
  1. `_update_schedule_run()`'s `schedule = AgentSchedule.get(...)` was
     missing `await` — `schedule` was a bare coroutine object, so every
     attribute write below it (and `.update()`) was silently a no-op
     (swallowed by the surrounding `except Exception`). This means
     `last_run`/`run_count` have **never** actually persisted in
     production for ANY schedule, scheduled or run-now. Fixed by adding
     the missing `await`.
  2. `job_success()` (the `EVENT_JOB_EXECUTED` listener) crashed with
     `AttributeError: 'NoneType' object has no attribute 'name'` for
     ANY one-shot (`DateTrigger`) job — APScheduler removes a one-shot
     job from the jobstore as part of firing it, so `scheduler.get_job
     (job_id)` already returns `None` by the time the listener runs.
     APScheduler swallows this as "Error notifying listener" and drops
     the entire success path silently (no DB update, no callbacks, no
     `send_result` email) — discovered because `on_startup()`'s
     `register_listeners=False` (a deliberate FEAT-422 decision, see
     `start_headless()`'s docstring) meant this code path had never
     actually run with listeners wired before. Fixed by having
     `job_success()` fall back to recovering `schedule_id` from the
     deterministic `"run_now:"` job-id prefix when the `Job` object is
     gone, instead of crashing.
- Extended `_update_schedule_run(..., result=...)` to stamp
  `metadata['last_result']` (formatted via the existing
  `_format_result()`, capped at `_LAST_RESULT_MAX_CHARS=10_000`) and
  `metadata['last_status']` on EVERY successful run (scheduled or
  run-now — there is no separate "run-now only" completion path to
  hook, by design); the failure branch got the matching
  `metadata['last_status'] = 'error'` for symmetry.
  `_process_job_success()` now passes `result=result` through.
- Tests (15, all passing): `TestManagerRunNow` — a REAL
  `AgentSchedulerManager` + real in-memory APScheduler
  (`start_headless(register_listeners=True)`, the same path the
  standalone daemon uses) + a fake agent/bot_manager + a mocked DB layer
  (`get_schedule`/`AgentSchedule.get` patched, no real Postgres) —
  proves run-now genuinely executes once, preserves schedule state,
  runs on a paused job, rejects a concurrent run-now with 409, and
  populates `last_result`/`last_status` on both success and failure.
  `TestHandlerDispatch` — mocked-manager unit tests proving the PATCH
  action dispatch (including the pre-existing pause/resume/update
  actions are unchanged — explicit regression coverage) and the
  last-result handler's GET. Full `packages/ai-parrot-server/tests/
  scheduler/` suite (167 tests) passes.
- `ruff check handlers/scheduler.py scheduler/` — `manager.py` is a
  74KB pre-existing file with ~150 pre-existing findings (legacy
  `Dict`/`Optional` typing style, tz-naive `datetime.now()` throughout,
  blind `except Exception`, unused `# noqa` comments) entirely unrelated
  to this change; ran `ruff --fix` once, found it had mechanically
  "modernized" ~370 lines of PRE-EXISTING code across the whole file,
  reverted that (`git checkout --`), and reapplied only the intended
  edits by hand instead — new code deliberately matches the file's
  existing conventions (`Dict[str, Any]`, tz-naive `datetime.now()`) for
  local consistency rather than introducing a mixed style. `handlers/
  scheduler.py`'s new `SchedulerLastResultHandler.get()` also matches
  its siblings' established `self.logger.error(..., exc_info=True)`
  pattern (flagged G201 by ruff, same as every other method in that
  file) rather than diverging to `.exception()`. No NEW category of
  ruff finding was introduced by this task's code.

**Deviations from spec**:
- The two bugfixes above (`_update_schedule_run`'s missing `await`,
  `job_success`'s one-shot-job crash) were not explicitly listed in the
  task's Scope, but were direct, unavoidable blockers for its own
  acceptance criteria ("last_run/run_count update as a normal run
  does", "Last-result endpoint returns last_run/run_count + stamped
  result metadata") — without them, run-now would execute the agent but
  the last-result endpoint would never reflect it. Both are documented
  inline at the fix site.
- **Known limitation, explicitly NOT fixed** (out of scope — high
  blast radius, a prior task's deliberate decision): the default
  aiohttp `on_startup()` path still calls
  `start_headless(use_redis=True, register_listeners=False)`, per an
  explicit FEAT-422 decision (`define_listeners()`/`job_success`/
  `job_status` were "never called anywhere on this path before... out
  of scope for this feature"). This means in a live aiohttp-served
  deployment using the DEFAULT startup path, `run_schedule_now()` will
  correctly trigger the agent execution (verified: the failure-path
  `_update_schedule_run` call inside `_execute_agent_job` itself is
  NOT listener-dependent and works regardless), but the SUCCESS path's
  `last_result`/`run_count` stamping (which runs via `job_success` ->
  `_process_job_success`) will only fire once an operator also flips
  `register_listeners=True` for the aiohttp path — a separate,
  cross-cutting decision (it also turns on notification emails/
  callbacks for every existing scheduled job) that belongs to a
  follow-up task, not this one. Tests prove correctness via
  `start_headless(register_listeners=True)` (the standalone daemon's
  own path) rather than silently reversing that FEAT-422 decision.
