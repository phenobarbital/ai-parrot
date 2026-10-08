# TASK-4156: SchedulerManager add_schedule and the CRUD x backend matrix (db | redis | code | external)

**Feature**: FEAT-644 — SchedulerManager base (db | redis | code backends)
**Spec**: `sdd/specs/scheduler-manager-base.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-4155
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 3, third slice, and the spec §2 CRUD × backend matrix (design research S2, S9). Today every CRUD method
assumes a Postgres `AgentSchedule` row (`packages/ai-parrot-server/src/parrot/scheduler/manager.py:1637-1838`) and code jobs are only a `list_jobs` fallback that parses
`job.name` (`packages/ai-parrot-server/src/parrot/scheduler/manager.py:1585`). This slice gives every operation explicit per-backend semantics, adds Redis-only jobs whose
data-only versioned definition lives in the job kwargs (S8), and replaces `_auto_tasks` with `CodeJobRecord`.

---

## Scope

- Add `add_schedule(target_kind, target_name, schedule_type, schedule_config, *, backend='db', ...)` exactly as spec §2: sanitize (`normalize_schedule_type`, `sanitize_schedule_config`, `normalize_backend(strict=True)`, `clean_method_name`, `clean_misfire_grace_time`), unknown kind → `ValueError`, `await resolver.resolve()` → `None` ⇒ `ValueError(target not found)`, validate the call with `resolver.build_call(target, definition, probe_fire)`, derive `target_id`, reject `success_callback` for `redis`; `db` → insert `ServiceSchedule` + add `jobs.run_db_schedule` job (rollback row on add failure); `redis` → add `jobs.run_redis_job` job to the `redis` jobstore with kwargs `{manager_name, schedule_id, definition_version: 1, definition}`, `misfire_grace_time=definition.misfire_grace_time`, `coalesce=True`. Returns `JobDefinition`.
- Add `_locate(schedule_id) -> tuple[str, JobDefinition | None, Any]` resolving code → redis job → db row → foreign job (`'external'`).
- Add `get_schedule`, `list_schedules`, `list_jobs` (+ `_serialize_job(definition)` with `source` ∈ db/redis/code/external and the `job` sub-dict as today), `update_schedule`, `pause_schedule`, `delete_schedule`, `remove_schedule` (alias of delete) per the spec matrix; code/external mutations raise `NotEditableError`; `update_schedule(enabled=True)` calls `RunStateStore.set_enabled(True)` (counter reset).
- Add `load_schedules_from_db()` (move of manager.py:1378-1443 for `ServiceSchedule` rows, `default` jobstore, `misfire_grace_time=300`).
- Add `register_object_schedules(obj, name)` building `CodeJobRecord`s (move of the scan loop of manager.py:1290-1358 minus report/env logic) and `jobs.run_auto_schedule` jobs with ids `auto_<name>_<method>`.
- Write `tests/scheduler/test_base_crud.py` (parametrized CRUD matrix).

**NOT in scope**: executing jobs, run-state stamping on fire, alerts, `run_schedule_now`, `get_last_result` (TASK-4157); agent/crew resolvers (TASK-4158).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-server/src/parrot/scheduler/base.py` | MODIFY | add_schedule, _locate, CRUD matrix, list/serialize, load_schedules_from_db, register_object_schedules |
| `packages/ai-parrot-server/tests/scheduler/test_base_crud.py` | CREATE | CRUD x backend matrix tests |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: This section contains VERIFIED code references from the actual codebase (verified on `dev` @ `3555841e9`, 2026-10-08).
> The implementing agent MUST use these exact imports, class names, and method signatures.
> **DO NOT** invent, guess, or assume any import, attribute, or method not listed here.
> If you need something not listed, VERIFY it exists first with `grep` or `read`.

### Verified Imports
```python
import uuid
from apscheduler.jobstores.base import JobLookupError          # manager.py:29
from asyncdb.exceptions import NoDataFound                     # manager.py:40
from .models import ServiceSchedule, JobDefinition, CodeJobRecord, JOB_DEFINITION_VERSION, schedule_fingerprint, FireContext, utcnow  # TASK-4147
from .sanitize import clean_method_name, clean_misfire_grace_time, normalize_backend, SchedulerConfigError  # TASK-4150
from . import jobs   # run_db_schedule (jobs.py:60), run_redis_job (TASK-4152), run_auto_schedule (jobs.py:74)
```

### Existing Signatures to Use
```python
# packages/ai-parrot-server/src/parrot/scheduler/manager.py:1119-1240 add_schedule — the sanitize-before-persist ordering, the DB insert idiom
#   (`async with await self._pool.acquire() as conn: Model.Meta.connection = conn; await row.save()`) and the
#   rollback-on-add_job-failure (`await schedule.delete(); raise RuntimeError(...) from e`) to keep.
# packages/ai-parrot-server/src/parrot/scheduler/manager.py:1478 _job_kwargs_from_schedule → for db: {"manager_name", "schedule_id", "fingerprint"} (fingerprint now from models.schedule_fingerprint(definition))
# packages/ai-parrot-server/src/parrot/scheduler/manager.py:1562-1576 _serialize_job payload["job"] keys: id, name, next_run, paused, pending, jobstore — keep the shape, add "source" and "backend"
# packages/ai-parrot-server/src/parrot/scheduler/manager.py:1661-1725 update_schedule — validate trigger BEFORE persisting; remove old job then re-add
# packages/ai-parrot-server/src/parrot/scheduler/manager.py:1302-1306 decorator scan: inspect.getmembers(bot, predicate=inspect.ismethod); hasattr(method, "_schedule_config");
#   config keys schedule_type, schedule_config, method_name, success_callback, send_result, callbacks
# APScheduler 3.11.2: scheduler.get_job(id, jobstore=None), get_jobs(jobstore=None), add_job(func, trigger=, id=, name=,
#   kwargs=, jobstore=, replace_existing=, misfire_grace_time=, coalesce=), modify_job(id, jobstore, **changes),
#   reschedule_job(id, jobstore, trigger=), pause_job(id, jobstore), resume_job(id, jobstore), remove_job(id, jobstore)
```

### Does NOT Exist
- ~~`AgentSchedule` / `scheduler_type`~~ in the new code — db rows are `ServiceSchedule` in the `default` jobstore.
- ~~`self._auto_tasks`~~ — replaced by `self._code_jobs: dict[str, CodeJobRecord]` (TASK-4155 init).
- ~~report-decorator env resolution in the base~~ — `register_bot_schedules` in TASK-4158 does that, then calls `register_object_schedules`.

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
      "path": "packages/ai-parrot-server/tests/scheduler/test_base_crud.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-server/src/parrot/scheduler/manager.py#AgentSchedulerManager.add_schedule",
    "sym:packages/ai-parrot-server/src/parrot/scheduler/manager.py#AgentSchedulerManager.update_schedule",
    "sym:packages/ai-parrot-server/src/parrot/scheduler/manager.py#AgentSchedulerManager.pause_schedule",
    "sym:packages/ai-parrot-server/src/parrot/scheduler/manager.py#AgentSchedulerManager.delete_schedule",
    "sym:packages/ai-parrot-server/src/parrot/scheduler/manager.py#AgentSchedulerManager.list_jobs",
    "sym:packages/ai-parrot-server/src/parrot/scheduler/manager.py#AgentSchedulerManager._serialize_job",
    "sym:packages/ai-parrot-server/src/parrot/scheduler/manager.py#AgentSchedulerManager.load_schedules_from_db",
    "sym:packages/ai-parrot-server/src/parrot/scheduler/manager.py#AgentSchedulerManager.register_bot_schedules"
  ]
}
```

---

## Implementation Notes

### `_locate` order (spec §2 matrix)
1. `schedule_id in self._code_jobs` → `("code", record.to_definition(), record)`.
2. `self.scheduler.get_job(schedule_id, jobstore="redis")` whose `func` is `jobs.run_redis_job` (compare
   `job.func_ref == "parrot.scheduler.jobs:run_redis_job"`) → `("redis", JobDefinition(**job.kwargs["definition"]), job)`.
3. DB row by UUID (only when `schedule_id` parses as a UUID and a pool exists) → `("db", row.to_definition(), row)`.
4. Any other APScheduler job with that id → `("external", None, job)` (e.g. ReminderToolkit `reminder-<uuid>` jobs).
5. Nothing → raise `NoDataFound` (handler maps to 404).

### Redis `update_schedule`
Merge editable fields into a new `JobDefinition` (validate!), rebuild the trigger, then
`modify_job(id, jobstore="redis", kwargs={..., "definition": new.model_dump(mode="json")}, misfire_grace_time=...)`
and `reschedule_job(id, jobstore="redis", trigger=trigger)`. Editable fields: `target_kind, target_name, target_id,
prompt, method_name, schedule_type, schedule_config, metadata, send_result, callbacks, misfire_grace_time, enabled`.
`backend` is NOT editable (409 via `NotEditableError("backend cannot change; delete and re-create")`).

### Serialization (`_serialize_job(definition, job=None, *, source)`)
`definition.model_dump(mode="json")` + `source` + `backend` + the legacy `job` sub-dict. External jobs:
`{"source": "external", "schedule_id": job.id, "enabled": job.next_run_time is not None, "job": {...}}` — never
expose foreign kwargs (they may carry tokens' ids).

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
1. Add `_locate` first — *why*: every CRUD method dispatches on its result (S2).
2. Add `add_schedule` with sanitize-before-persist and per-backend job creation — *why*: AC3, AC8.
3. Add get/list/serialize — *why*: one payload shape for all sources (integration test `test_three_backends_same_list_payload`).
4. Add update/pause/delete/remove per the matrix — *why*: AC10.
5. Move `load_schedules_from_db` and add `register_object_schedules` — *why*: startup reload of db rows and code jobs.
6. Write the parametrized matrix tests (db via a fake pool, redis via the conftest fixtures, code via an object with `@schedule` methods).

### `packages/ai-parrot-server/src/parrot/scheduler/base.py` (MODIFY)
```python
# occurrences: 1 (verified after TASK-4155: grep -c '    def _run_state_for(self, backend: str) -> RunStateStore:' packages/ai-parrot-server/src/parrot/scheduler/base.py)
# AFTER `_run_state_for` — insert into class SchedulerManager:
    async def add_schedule(
        self, target_kind: str, target_name: str, schedule_type: str, schedule_config: dict[str, Any], *,
        backend: str = "db", target_id: str | None = None, tenant: str | None = None,
        prompt: str | None = None, method_name: str | None = None,
        created_by: int | None = None, created_email: str | None = None,
        metadata: dict[str, Any] | None = None, send_result: dict[str, Any] | None = None,
        success_callback: Callable[..., Any] | None = None,
        callbacks: list[dict[str, Any]] | None = None,
        misfire_grace_time: int | None = None,
    ) -> JobDefinition:
        """Validate, persist (db) or store in the Redis jobstore (redis), and schedule.

        Raises:
            SchedulerConfigError: bad schedule_type/config/backend/method_name/misfire_grace_time.
            ValueError: unknown target_kind, target not found, success_callback with backend='redis'.
        """
        # FILL IN: Scope bullet 1, in this order: sanitize → resolve+build_call validation → definition → persist/schedule.

    async def _locate(self, schedule_id: str) -> tuple[str, JobDefinition | None, Any]:
        """Find a job by id across code → redis → db → external (Implementation Notes)."""
        # FILL IN

    async def get_schedule(self, schedule_id: str) -> JobDefinition:
        """Definition for db/redis/code jobs; raises NoDataFound for unknown ids and for external jobs (they have none)."""
        # FILL IN: via _locate.

    async def list_schedules(self) -> list[JobDefinition]:
        """All definitions: db rows + redis jobs + code records."""
        # FILL IN

    async def list_jobs(self) -> list[dict[str, Any]]:
        """Every APScheduler job plus db rows missing from APScheduler (drift), serialized uniformly."""
        # FILL IN: keep the drift behaviour of manager.py:1608-1635.
```
```python
# (continued)
    def _serialize_job(self, definition: JobDefinition | None, job: Any = None, *, source: str) -> dict[str, Any]:
        """Uniform payload (Implementation Notes → Serialization)."""
        # FILL IN

    async def update_schedule(self, schedule_id: str, updates: dict[str, Any]) -> JobDefinition:
        """db: row + reschedule; redis: rewrite kwargs.definition + reschedule; code/external: NotEditableError
        (except ``{'enabled': bool}`` on code jobs → resume/pause). ``enabled=True`` resets consecutive_failures."""
        # FILL IN

    async def pause_schedule(self, schedule_id: str) -> JobDefinition:
        """db: enabled=False + remove job; redis: pause_job + set_enabled(False); code: pause_job; external: NotEditableError."""
        # FILL IN

    async def delete_schedule(self, schedule_id: str) -> None:
        """db: row + job; redis: job + RunStateStore.clear; code/external: NotEditableError."""
        # FILL IN

    async def remove_schedule(self, schedule_id: str) -> None:
        """Backward-compatible alias of :meth:`delete_schedule`."""
        await self.delete_schedule(schedule_id)

    async def load_schedules_from_db(self) -> None:
        """Load enabled ``service_scheduler`` rows into the default jobstore (moved from manager.py:1378)."""
        # FILL IN: SELECT * FROM navigator.service_scheduler WHERE enabled = TRUE ORDER BY created_at

    def register_object_schedules(self, obj: Any, name: str) -> int:
        """Scan ``@schedule`` methods of ``obj`` into CodeJobRecords + ``jobs.run_auto_schedule`` jobs."""
        # FILL IN: job_id f"auto_{name}_{method_name}", job name f"{name}.{method_name}" (dots allowed — never parsed back).
```

### FILL IN checklist
- [ ] `add_schedule` — full validation order; redis kwargs exactly `{manager_name, schedule_id, definition_version, definition}` (S8).
- [ ] `_locate` — 5-step order.
- [ ] `get_schedule` / `list_schedules` / `list_jobs` / `_serialize_job`.
- [ ] `update_schedule` / `pause_schedule` / `delete_schedule` — the spec matrix (AC10).
- [ ] `load_schedules_from_db` — ServiceSchedule rows.
- [ ] `register_object_schedules` — CodeJobRecord.

---

## Acceptance Criteria

- [ ] `add_schedule(target_kind='service', ...)` after `register_target` works with no BotManager (AC3); missing/private/non-allow-listed `method_name` raises.
- [ ] `backend='redis'`: no DB call is made; the job is in the `redis` jobstore with exactly the 4 data-only kwargs; `success_callback` raises `ValueError` (AC8).
- [ ] `backend='redis'` without a Redis jobstore raises `SchedulerConfigError`.
- [ ] The parametrized `(backend, operation)` matrix of spec §2 holds, including `NotEditableError` for code/external (AC10).
- [ ] `register_object_schedules(obj, 'a.b')` lists `target_name == 'a.b'` (no name parsing).

---

## Validation Commands

> File-level pytest only — no directories, no package roots. Run every command from the feature worktree with `PYTHONPATH=packages/ai-parrot-server/src:packages/ai-parrot/src:packages/ai-parrot-integrations/src` — the shared `.venv` is editable-installed against the main checkout, so a bare `pytest` imports the wrong branch.

- `pytest packages/ai-parrot-server/tests/scheduler/test_base_crud.py -q`

---

## Test Specification

```python
# packages/ai-parrot-server/tests/scheduler/test_base_crud.py
async def test_add_service_schedule_db_backend(fake_pool_manager): ...
async def test_add_redis_schedule_has_data_only_kwargs(redis_manager): ...
async def test_add_redis_rejects_success_callback(redis_manager): ...
async def test_add_redis_without_jobstore_fails_closed(memory_manager): ...
@pytest.mark.parametrize("backend,op,expected", [...])   # spec §2 CRUD matrix
async def test_crud_matrix_per_backend(backend, op, expected, ...): ...
async def test_code_job_record_replaces_name_parsing(memory_manager): ...
async def test_external_job_listed_readonly(redis_manager): ...      # foreign job added straight to the redis jobstore
async def test_update_enabled_resets_counter(redis_manager): ...
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
   `feat(scheduler-manager-base): TASK-4156 — SchedulerManager add_schedule and the CRUD x backend matrix (db | redis | code | external)`
9. **Close the task** with `scripts/sdd/close_task.sh TASK-4156 scheduler-manager-base verified` (never move the file by hand)
10. **Fill in the Completion Note** below, then commit the staged SDD state: `sdd: complete TASK-4156 — SchedulerManager add_schedule and the CRUD x backend matrix (db | redis | code | external)`

---

## Completion Note

**Completed by**: sdd-worker (coder seat: gpt-5.6-terra)
**Date**: 2026-10-08
**Notes**: Implemented as specified and merged into the feature branch. Direct run of packages/ai-parrot-server/tests/scheduler passed. The merge-tier validation was red only because of an unrelated pre-existing studio test collection error (ledger issue:d5a7c625fbe7); closed on direct test evidence.

**Deviations from spec**: none
