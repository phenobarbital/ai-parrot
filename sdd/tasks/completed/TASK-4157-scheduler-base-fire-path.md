# TASK-4157: SchedulerManager fire path: _execute_job, run-state stamping, auto-disable + alert, listeners, run-now, last-result

**Feature**: FEAT-644 — SchedulerManager base (db | redis | code backends)
**Spec**: `sdd/specs/scheduler-manager-base.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: XL (> 8h)
**Depends-on**: TASK-4156, TASK-4153
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 3, last slice: everything that happens when a job fires. Moves `packages/ai-parrot-server/src/parrot/scheduler/manager.py:470-976` (listeners, success
handling, delivery callbacks, `_send_result_email`, `_format_result`), `:1038-1062` (`_on_coordination_unavailable`),
`:1486-1550` (`_run_db_schedule`, `_run_auto_task`), `:1739-1838` (`run_schedule_now`, `get_last_result`) and replaces
`_execute_agent_job` / `_execute_agent_task` / `_update_schedule_run` / `_stamp_delivery_outcome` with one
`_execute_job(definition, fire)` plus `RunStateStore` calls. It closes three ledger issues: `aa813ccc1927` (fire_id ==
claim key), `37f02d3c2474` (raising `success_callback` no longer skips deliveries), `7b5d75d2c81d` (run-now coordination
outage → typed `SchedulerUnavailableError`, and the unavailable hook only stamps UUID ids).

---

## Scope

- Add `_execute_job(definition, fire, *, success_callback=None)`: resolver lookup (unknown kind or `resolve()` None/raises ⇒ `TargetMissingError`, WARNING without traceback), `build_call`, `getattr(target, method_name)` (or `target.chat(prompt)` fallback is the AGENT resolver's concern — base only calls `method_name`), `inject_fire_context`, await; store `_job_context[schedule_id] = {definition, fire, success_callback, backend}`.
- Add `_run_db_schedule(schedule_id, fingerprint, *, run_now=False)` (move of manager.py:1486-1536 for `ServiceSchedule`), `_run_redis_job(schedule_id, *, run_now=False, definition_version=None, definition=None)` (version mismatch ⇒ stamp `incompatible`, `pause_job`, WARNING once, return `jobs.SKIPPED`; hash `enabled='0'` ⇒ SKIPPED), `_run_auto_task(job_id, *, run_now=False)`.
- Wrap each `_run_*` so an exception from `_execute_job` stamps `stamp_failure(status='target_missing'|'error', threshold=self._max_failures)` and, when `crossed_threshold`, disables the job (db: `enabled=False` already set by the store + remove job; redis: `pause_job`; code: `pause_job`) and calls `_alert_disabled`; then re-raises so APScheduler emits EVENT_JOB_ERROR.
- Move listeners (`define_listeners`, `scheduler_status`, `scheduler_shutdown`, `job_added`, `job_status`, `job_success`) — `job_success` pops `_job_context`, ignores `jobs.SKIPPED`, schedules `_process_job_success(definition, fire, result, success_callback)`.
- Move `_process_job_success` → `stamp_success` then `_handle_job_success` then `stamp_delivery`; in `_handle_job_success` run the user `success_callback` INSIDE try/except recording a `failed` outcome named `success_callback`; callbacks get `target_name=definition.target_name`.
- Move `_callback_outcome`, `_send_result_email`, `_format_result`; add `_alert_disabled(definition, state)` (recipients: `send_result` recipients → `self._alert_recipients` → log only; never raises).
- Move `_on_coordination_unavailable` (stamp `lock_unavailable` via the db store only for UUID ids; never raises) replacing the TASK-4155 stub.
- Move `run_schedule_now` (per-backend trampoline; `FireCoordinationError` ⇒ `SchedulerUnavailableError`; code/external ⇒ code allowed via `run_auto_schedule(run_now=True)`, external ⇒ `NotEditableError`) and `get_last_result` (returns `RunState`; external ⇒ `NoDataFound`).
- Write `tests/scheduler/test_base_fire.py`.

**NOT in scope**: AgentResolver/CrewResolver and `chat(prompt)` fallback (TASK-4158); HTTP status mapping (TASK-4161); closing the ledger issues in the ledger DB (TASK-4165).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-server/src/parrot/scheduler/base.py` | MODIFY | Fire path, run-state stamping, auto-disable, alerts, listeners, run-now, last-result |
| `packages/ai-parrot-server/tests/scheduler/test_base_fire.py` | CREATE | Fire-path, threshold, alert and ledger-regression unit tests |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: This section contains VERIFIED code references from the actual codebase (verified on `dev` @ `3555841e9`, 2026-10-08).
> The implementing agent MUST use these exact imports, class names, and method signatures.
> **DO NOT** invent, guess, or assume any import, attribute, or method not listed here.
> If you need something not listed, VERIFY it exists first with `grep` or `read`.

### Verified Imports
```python
from apscheduler.events import (EVENT_JOB_ADDED, EVENT_JOB_ERROR, EVENT_JOB_EXECUTED, EVENT_JOB_MAX_INSTANCES,
                                EVENT_JOB_MISSED, EVENT_SCHEDULER_SHUTDOWN, EVENT_SCHEDULER_STARTED, JobExecutionEvent)  # manager.py:19-28
from .functions import build_scheduler_callback               # manager.py:56
from ..notifications import NotificationMixin                 # manager.py:54
from ..conf import ENVIRONMENT                                # manager.py:55
from .coordination import FireCoordinationError              # coordination.py:29
from .runstate import truncate                                # TASK-4148
from .coordination import CURRENT_RUN_TIME                    # TASK-4151
```

### Existing Signatures to Use
```python
# packages/ai-parrot-server/src/parrot/scheduler/manager.py:342 — notifier helper to move
class _SchedulerNotification(NotificationMixin):
    def __init__(self, logger): ...
# packages/ai-parrot-server/src/parrot/scheduler/manager.py:538-635 job_success (one-shot run-now id recovery via _RUN_NOW_JOB_PREFIX; SKIPPED → no-op)
# packages/ai-parrot-server/src/parrot/scheduler/manager.py:761-801 _handle_job_success — success_callback currently OUTSIDE try (ledger 37f02d3c2474)
# packages/ai-parrot-server/src/parrot/scheduler/manager.py:803-865 _send_result_email(schedule_id, agent_name, result, send_result) — recipients keys: recipients|emails|email|to
# packages/ai-parrot-server/src/parrot/scheduler/manager.py:1038-1062 _on_coordination_unavailable — skips "auto_" ids; strips _RUN_NOW_JOB_PREFIX
# packages/ai-parrot-server/src/parrot/scheduler/manager.py:1486-1536 _run_db_schedule — NoDataFound → remove local job + SKIPPED; disabled → SKIPPED; fingerprint change → reschedule + SKIPPED
# packages/ai-parrot-server/src/parrot/scheduler/manager.py:1739-1800 run_schedule_now — try_acquire_running; FireCoordinationError → RuntimeError (change to SchedulerUnavailableError);
#   job id f"{_RUN_NOW_JOB_PREFIX}{schedule_id}", DateTrigger(run_date=datetime.now()) → utcnow()
# NotificationMixin.send_notification(self, recipients, provider=NotificationProvider.EMAIL, ...)  # notifications/__init__.py:442
# NotificationMixin.send_email(self, recipients=None, ...)                                          # notifications/__init__.py:1521
# BaseSchedulerCallback.__call__(result, *, schedule_id, target_name, **kwargs)                     # after TASK-4153
```

### Does NOT Exist
- ~~`_execute_agent_job`, `_execute_agent_task`, `_update_schedule_run`, `_stamp_delivery_outcome`, `_prepare_call_arguments` in base~~ — replaced; do not recreate.
- ~~a `chat()` call in base~~ — only `AgentResolver` (TASK-4158) maps `prompt`-only agent schedules to `chat`.

- ~~`BotManager`, `parrot.manager`, `parrot.bots`, `parrot.registry` imports in `base.py`~~ — forbidden (spec AC1); agent/crew resolution lives in `manager.py` (TASK-4158).
- ~~`from .manager import ...` in `base.py`~~ — circular (manager imports base). `ScheduleType`, `SchedulerRunNowConflictError` and `_RUN_NOW_JOB_PREFIX` are defined in `base.py` (TASK-4154); `manager.py` re-exports them in TASK-4158.
- ~~`AgentSchedule` in `base.py`~~ — base uses `ServiceSchedule` only.
- ~~`datetime.now()` in `base.py`~~ — use `utcnow()` everywhere (AC7).

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot-server/src/parrot/scheduler/base.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot-server/tests/scheduler/test_base_fire.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-server/src/parrot/scheduler/manager.py#AgentSchedulerManager.job_success",
    "sym:packages/ai-parrot-server/src/parrot/scheduler/manager.py#AgentSchedulerManager.job_status",
    "sym:packages/ai-parrot-server/src/parrot/scheduler/manager.py#AgentSchedulerManager._handle_job_success",
    "sym:packages/ai-parrot-server/src/parrot/scheduler/manager.py#AgentSchedulerManager._process_job_success",
    "sym:packages/ai-parrot-server/src/parrot/scheduler/manager.py#AgentSchedulerManager._send_result_email",
    "sym:packages/ai-parrot-server/src/parrot/scheduler/manager.py#AgentSchedulerManager._format_result",
    "sym:packages/ai-parrot-server/src/parrot/scheduler/manager.py#AgentSchedulerManager._callback_outcome",
    "sym:packages/ai-parrot-server/src/parrot/scheduler/manager.py#AgentSchedulerManager._on_coordination_unavailable",
    "sym:packages/ai-parrot-server/src/parrot/scheduler/manager.py#AgentSchedulerManager._run_db_schedule",
    "sym:packages/ai-parrot-server/src/parrot/scheduler/manager.py#AgentSchedulerManager._run_auto_task",
    "sym:packages/ai-parrot-server/src/parrot/scheduler/manager.py#AgentSchedulerManager.run_schedule_now",
    "sym:packages/ai-parrot-server/src/parrot/scheduler/manager.py#AgentSchedulerManager.get_last_result",
    "sym:packages/ai-parrot-server/src/parrot/scheduler/functions/__init__.py#build_scheduler_callback"
  ]
}
```

---

## Implementation Notes

### Fire flow per backend
`_run_db_schedule` → re-read row (as today) → `definition = row.to_definition()`; `_run_redis_job` →
`JobDefinition(**definition)` from the trampoline kwargs (or from the job's kwargs when called for run-now);
`_run_auto_task` → `record.to_definition()`. Then
`fire = FireContext.for_fire(schedule_id, CURRENT_RUN_TIME.get() or utcnow(), run_now=run_now)` — `CURRENT_RUN_TIME`
(TASK-4151, `coordination.py`) holds the exact run time `CoordinatedAsyncIOExecutor` claimed, so `fire_id` equals the
claim key suffix `f"{job_id}:{run_time.isoformat()}"` (ledger `aa813ccc1927`). `utcnow()` is only the fallback when a
job runs outside the coordinated executor (direct calls in tests).

### Failure stamping wrapper
```
try:
    return await self._execute_job(definition, fire, success_callback=...)
except TargetMissingError as exc:   status = "target_missing"; self.logger.warning(...)   # no traceback
except Exception as exc:            status = "error"                                      # APScheduler logs traceback
state, crossed = await store.stamp_failure(job_id, status=status, error=str(exc), fire=fire, threshold=self._max_failures)
if crossed: await self._disable_after_threshold(definition, state)
raise
```
`_disable_after_threshold`: db → remove APScheduler job (the store already set `enabled=False`); redis → `pause_job`;
code → `pause_job` + `record.enabled=False`; then `await self._alert_disabled(definition, state)`.

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
1. Move the listeners and the success/delivery helpers first, renaming `agent_name` → `definition.target_name` — *why*: they are pure moves and the rest builds on them.
2. Fix `_handle_job_success` so `success_callback` runs inside try/except — *why*: ledger 37f02d3c2474 / AC17.
3. Add `_execute_job` and the three `_run_*` with the failure-stamping wrapper — *why*: AC11, AC12.
4. Add `_disable_after_threshold` and `_alert_disabled` — *why*: single alert from the crossing caller (S4, S6).
5. Move `_on_coordination_unavailable`, `run_schedule_now` (typed 503 error), `get_last_result` (RunState).
6. Write the tests and run them together with the earlier base test files.

### `packages/ai-parrot-server/src/parrot/scheduler/base.py` (MODIFY)
```python
# occurrences: 1 (verified after TASK-4156: grep -c '    def register_object_schedules(self, obj: Any, name: str) -> int:' packages/ai-parrot-server/src/parrot/scheduler/base.py)
# AFTER `register_object_schedules` — insert into class SchedulerManager (signatures fixed; bodies are moves + FILL IN):
    def define_listeners(self) -> None: ...                                 # FILL IN: move manager.py:470-477
    def scheduler_status(self, event: Any) -> None: ...                     # FILL IN: move (utcnow)
    def scheduler_shutdown(self, event: Any) -> None: ...                   # FILL IN: move (utcnow)
    def job_added(self, event: JobExecutionEvent, *args: Any, **kwargs: Any) -> None: ...   # FILL IN: move
    def job_status(self, event: JobExecutionEvent) -> None: ...             # FILL IN: move manager.py:493-536
    def job_success(self, event: JobExecutionEvent) -> bool:
        """Pop ``_job_context`` (run-now ids via _RUN_NOW_JOB_PREFIX), ignore SKIPPED, schedule _process_job_success."""
        # FILL IN: move manager.py:538-635 using the new context keys.

    async def _execute_job(self, definition: JobDefinition, fire: FireContext, *,
                           success_callback: Callable[..., Any] | None = None) -> Any:
        """Resolve → build_call → inject fire context → await. Raises TargetMissingError / ValueError."""
        # FILL IN

    async def _run_db_schedule(self, schedule_id: str, fingerprint: str | None, *, run_now: bool = False) -> Any: ...
    async def _run_redis_job(self, schedule_id: str, *, run_now: bool = False,
                             definition_version: int | None = None, definition: dict[str, Any] | None = None) -> Any: ...
    async def _run_auto_task(self, job_id: str, *, run_now: bool = False) -> Any: ...
    # FILL IN: the three bodies + shared failure wrapper (Implementation Notes).

    async def _disable_after_threshold(self, definition: JobDefinition, state: RunState) -> None: ...   # FILL IN
    async def _alert_disabled(self, definition: JobDefinition, state: RunState) -> None:
        """Notify that a schedule was auto-disabled; recipients send_result → SCHEDULER_ALERT_RECIPIENTS → log. Never raises."""
        # FILL IN
```
```python
# (continued)
    async def _process_job_success(self, definition: JobDefinition, fire: FireContext, result: Any,
                                   success_callback: Callable[..., Any] | None) -> None:
        """stamp_success → _handle_job_success → stamp_delivery; never raises."""
        # FILL IN: move manager.py:867-922 shape; next_run from self.scheduler.get_job(...).

    async def _handle_job_success(self, definition: JobDefinition, result: Any,
                                  success_callback: Callable[..., Any] | None) -> list[dict[str, Any]]:
        """success_callback (isolated — 37f02d3c2474), registry callbacks, send_result; returns outcomes."""
        # FILL IN: move manager.py:761-801; callback(result, schedule_id=..., target_name=definition.target_name).

    @staticmethod
    def _callback_outcome(name: str, response: Any = None, error: Any = None) -> dict[str, Any]: ...  # FILL IN: move :733-748
    async def _send_result_email(self, definition: JobDefinition, result: Any,
                                 send_result: dict[str, Any]) -> dict[str, Any] | None: ...       # FILL IN: move :803-865
    def _format_result(self, result: Any) -> str: ...                                             # FILL IN: move :924-943
    async def _on_coordination_unavailable(self, job_id: str, exc: BaseException) -> None: ...    # FILL IN: move :1038-1062
    async def run_schedule_now(self, schedule_id: str) -> JobDefinition: ...                      # FILL IN: move :1739-1800
    async def get_last_result(self, schedule_id: str) -> RunState: ...                            # FILL IN: via _locate + store.read
```
**Why**: the success path stays listener-driven (FEAT-631 behaviour the multi-worker suite relies on); the failure
path is stamped inside the trampoline wrapper because only there do we still hold the `definition` of a Redis job.

### FILL IN checklist
- [ ] Listeners — moved; `job_success` uses new context keys.
- [ ] `_execute_job` — TargetMissingError semantics (AC12).
- [ ] `_run_db_schedule` / `_run_redis_job` (incompatible version) / `_run_auto_task` + failure wrapper (AC11).
- [ ] `_disable_after_threshold` / `_alert_disabled` — one alert, never raises (S6).
- [ ] `_process_job_success` / `_handle_job_success` — success_callback isolated (37f02d3c2474).
- [ ] `run_schedule_now` — `SchedulerUnavailableError` (7b5d75d2c81d); `get_last_result` → RunState.
- [ ] fire_id from `CURRENT_RUN_TIME.get() or utcnow()` (aa813ccc1927).

---

## Acceptance Criteria

- [ ] A target that resolves to `None` stamps `target_missing`, logs one WARNING without traceback and never reaches the success listener (AC12).
- [ ] With threshold 3, mixed `error`/`target_missing` failures disable the schedule on the third, exactly one alert is sent, and a later success or `enabled=True` resets the counter (AC11).
- [ ] A raising `success_callback` is recorded as a failed outcome and `send_result` + registry callbacks still run (ledger 37f02d3c2474).
- [ ] `run_schedule_now` on a coordination outage raises `SchedulerUnavailableError` (ledger 7b5d75d2c81d); a non-UUID id never reaches the DB stamp.
- [ ] A Redis job whose `definition_version` != 1 is paused and stamped `incompatible`.
- [ ] `get_last_result` returns `RunState` for db, redis and code jobs; external → `NoDataFound`.

---

## Validation Commands

> File-level pytest only — no directories, no package roots. Run every command from the feature worktree with `PYTHONPATH=packages/ai-parrot-server/src:packages/ai-parrot/src:packages/ai-parrot-integrations/src` — the shared `.venv` is editable-installed against the main checkout, so a bare `pytest` imports the wrong branch.

- `pytest packages/ai-parrot-server/tests/scheduler/test_base_fire.py -q`

---

## Test Specification

```python
# packages/ai-parrot-server/tests/scheduler/test_base_fire.py
async def test_target_missing_raises_not_skipped(...): ...
async def test_resolver_exception_is_target_missing(...): ...
async def test_auto_disable_after_threshold_and_single_alert(...): ...
async def test_alert_failure_never_raises(...): ...
async def test_success_callback_raise_does_not_skip_delivery(...): ...       # 37f02d3c2474
async def test_run_now_coordination_outage_is_unavailable_error(...): ...     # 7b5d75d2c81d
async def test_unavailable_hook_skips_non_uuid_ids(...): ...
async def test_redis_job_incompatible_version_pauses(...): ...
async def test_fire_context_injected_into_target(...): ...
async def test_metadata_never_contains_run_state(...): ...                    # AC6
async def test_get_last_result_per_backend(...): ...
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
   `feat(scheduler-manager-base): TASK-4157 — SchedulerManager fire path: _execute_job, run-state stamping, auto-disable + alert, listeners, run-now, last-result`
9. **Close the task** with `scripts/sdd/close_task.sh TASK-4157 scheduler-manager-base verified` (never move the file by hand)
10. **Fill in the Completion Note** below, then commit the staged SDD state: `sdd: complete TASK-4157 — SchedulerManager fire path: _execute_job, run-state stamping, auto-disable + alert, listeners, run-now, last-result`

---

## Completion Note

**Completed by**: sdd-worker (coder seat: gpt-5.6-luna)
**Date**: 2026-10-08
**Notes**: Implemented as specified and merged into the feature branch. Direct run of packages/ai-parrot-server/tests/scheduler passed. The merge-tier validation was red only because of an unrelated pre-existing studio test collection error (ledger issue:d5a7c625fbe7); closed on direct test evidence.

**Deviations from spec**: none
