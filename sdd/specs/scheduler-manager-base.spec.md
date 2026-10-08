---
type: feature
base_branch: dev
projects: [ai-parrot-server, ai-parrot-integrations, ai-parrot]
tags: [scheduler, apscheduler, target-registry, service-scheduler, hard-cut, run-state, redis-jobstore]
---

# Feature Specification: SchedulerManager base — target-agnostic scheduler (db | redis | code backends) with AgentSchedulerManager as a subclass

**Feature ID**: FEAT-644
**Date**: 2026-10-08
**Author**: Jesus Lara (spec drafted by Claude)
**Status**: approved
**Target version**: ai-parrot-server 1.3.0 (breaking; current `parrot.server.version.__version__` is `1.2.0`)
**Source**: GitHub issue [phenobarbital/ai-parrot#1572](https://github.com/phenobarbital/ai-parrot/issues/1572) · brainstorm `sdd/proposals/scheduler-manager-base.brainstorm.md` (accepted) · design research `sdd/state/FEAT-644/design_research/`

---

## 1. Motivation & Business Requirements

### Problem Statement

`AgentSchedulerManager` (`packages/ai-parrot-server/src/parrot/scheduler/manager.py`, 2,219 lines) is the only
scheduler in AI-Parrot and it is hard-wired to `BotManager`:

- `add_schedule()` requires `agent_name` and validates the target through the **private** `bot_manager._bots`
  dict plus `bot_manager.registry.get_instance()` (`manager.py:1168-1184`).
- `_execute_agent_job()` resolves the target the same way at fire time (`manager.py:681-688`).
- `on_startup()` falls back to `app["bot_manager"]` and scans its bots (`manager.py:2062-2066`).

Everything else — APScheduler wiring, jobstores, Redis fire coordination (FEAT-631), DB persistence,
`run_schedule_now`, `start_headless`/`stop_headless`, listeners, delivery callbacks (FEAT-635),
`_update_schedule_run` — is target-agnostic, yet nobody can reuse it without faking a `BotManager`:

- **External packages** (issue #1572, filed while integrating `reportbuilder`) must register a fake bot, and
  `BotManagement.get` then returns 400 for it.
- **agentd** carries the same workaround in-repo: `SingleAgentManager`
  (`packages/ai-parrot-integrations/src/parrot/integrations/agentd/service.py:240`) exposes exactly `_bots`,
  `registry.get_instance()` and `get_crew()` so the scheduler accepts a single agent.
- **Operators**: a schedule whose target is missing logs an ERROR with traceback on every tick and is never disabled.

**Run state is mixed into the call arguments (confirmed).** `_execution_fields()` passes `dict(schedule.metadata)`
as the `metadata` kwarg (`manager.py:1473`), which `_prepare_call_arguments` turns into the target's call kwargs
(`manager.py:412`). `_update_schedule_run()` writes `last_error`, `last_error_time`, `last_status`, `last_result`,
`last_result_time` into that same dict (`manager.py:1022-1031`) and `_stamp_delivery_outcome()` adds
`last_callbacks`, `last_delivery_status`, `last_delivery_time` (`manager.py:970-972`). On the next tick all of them
are replayed as kwargs to the target. `last_error` is never cleared on success. Every timestamp — including
`last_run` (`manager.py:1011`) — is a naive `datetime.now()` written into `TIMESTAMPTZ` columns.

**Redis persistence is redundant and there is no manager-level Redis-only path.** `scheduler_type='redis'` only
picks the APScheduler jobstore (`_safe_jobstore`, `manager.py:1857`); the row still lives in Postgres and
`load_schedules_from_db()` re-adds every enabled row with `replace_existing=True` on each start (`manager.py:1378`).
The one Redis-only job that exists today bypasses the manager entirely: `ReminderToolkit` adds a module-level
`deliver_reminder` to the `redis` jobstore by hand (`packages/ai-parrot/src/parrot/tools/reminder.py:294-300`).
The global `misfire_grace_time=300` (`manager.py:398`) drops the missed fire of every job after a restart longer
than five minutes.

**Latent crew bug.** `BotManager.get_crew()` is `async` (`packages/ai-parrot-server/src/parrot/manager/manager.py:3019`)
but both scheduler call sites invoke it without `await` (`manager.py:681`, `manager.py:1170`): against a real
`BotManager` the walrus sees a coroutine and `crew_entry[0]` / `_, crew_def = crew_entry` raise `TypeError`. The
core test `test_execute_crew_job_uses_registered_crew` hides it with a **sync** `def get_crew` stub
(`packages/ai-parrot/tests/test_schedules.py:53-80`); only agentd's sync `SingleAgentManager.get_crew()` (returns
`None`) works in production. Crew schedules through `SavedExecutionService` are therefore broken on `dev`.

**Why now.** `navigator.agents_scheduler` is barely populated, so a hard-cut (new table, no row migration) is cheap
today and gets more expensive with every schedule written. FEAT-631 and FEAT-635 are closed; nothing in flight
touches `manager.py`.

### Goals

- G1. A target-agnostic `SchedulerManager` that external packages instantiate directly, with
  `register_target(name, obj, kind="service", methods=...)` and a kind-keyed, **async** `TargetResolver` table.
- G2. `AgentSchedulerManager(SchedulerManager)` keeps its name and import path; it only adds the `agent` and
  `crew` resolvers, `register_bot_schedules`, the report decorators and the `app["bot_manager"]` auto-wiring.
  `SingleAgentManager` in agentd is deleted.
- G3. Hard-cut persistence: `navigator.service_scheduler` + `ServiceSchedule` (`target_kind` / `target_name` /
  `target_id`, run state in dedicated UTC columns, `tenant`, no `scheduler_type`); `metadata` is call kwargs only.
- G4. One `backend` axis — `db | redis | code` — with the same CRUD/run-now/last-result API for every backend;
  `redis` jobs have no Postgres row, survive restarts through the `RedisJobStore`, catch up missed fires per their
  own `misfire_grace_time`, and keep run state in a Redis hash.
- G5. Atomic run-state transitions with one shared `consecutive_failures` counter; auto-disable after
  `SCHEDULER_MAX_CONSECUTIVE_FAILURES` (default 3) for `error` **and** `target_missing`; exactly one alert.
- G6. `fire_id` / `scheduled_at` injected into targets by signature so they can be idempotent.
- G7. Hard-cut of the Python, HTTP (`/api/v1/parrot/scheduler/schedules`) and agentd RPC surfaces: `agent_name`,
  `agent_id`, `is_crew`, `scheduler_type` disappear; all in-repo callers migrate in the same PR.
- G8. Close ledger issues `aa813ccc1927`, `7b5d75d2c81d`, `37f02d3c2474` and the un-awaited `get_crew()` bug, each
  with a regression test.

### Non-Goals (explicitly out of scope)

- No row-copy script from `agents_scheduler`; the old table is left for the operator to drop.
- No compatibility aliases (`AgentSchedule`, `agent_name` kwargs, `scheduler_type`, the legacy `SchedulerHandler`
  view in `manager.py`). The brainstorm's Option C (bolt-on inside the existing class) and Option B (no subclass)
  were rejected — see `sdd/proposals/scheduler-manager-base.brainstorm.md`.
- No tenant **enforcement** on list/read/mutate — the `tenant` column and `JobDefinition.tenant` are added, the
  policy is §8 Q1 (design research S11).
- No change to `parrot.scheduler.inprocess.InProcessScheduler` (core helper unrelated to this manager).
- No admin-UI work: the only `scheduler.ts` under `packages/ai-parrot-server/ui/` is an A2UI linked-surface component.
- No change to APScheduler version (`apscheduler==3.11.2`).
- `ReminderToolkit` keeps adding its own jobs to the `redis` jobstore; it is not migrated to `backend='redis'`
  (its jobs surface as `source='external'`, §2).

---

## 2. Architectural Design

### Overview

Everything target-agnostic moves from `manager.py` into `parrot/scheduler/base.py::SchedulerManager`. Two
independent axes live in the base:

1. **Target resolution** — a kind-keyed table of `TargetResolver` strategies (`resolve()` is `async`, design
   research S1). The base ships one resolver, `service` → `RegistryResolver`, backed by a **manager-scoped**
   `TargetRegistry` (`register_target(name, obj, *, kind="service", methods=None)`). `AgentSchedulerManager`
   installs `agent` → `AgentResolver(bot_manager)` and `crew` → `CrewResolver(bot_manager)`; `AgentResolver`
   checks explicit registrations first, then `bot_manager.get_bots()`, then `await bot_manager.registry.get_instance()`;
   `CrewResolver` **awaits** `bot_manager.get_crew()`. Method names starting with `_` are rejected for every kind;
   a `service` registration may carry an explicit `methods` allowlist (S5).
2. **Persistence backend** — `backend = 'db' | 'redis' | 'code'` per job, selecting where the definition lives and
   which `RunStateStore` receives its run state:

| backend | Definition lives in | APScheduler job | Reloaded at start by | Run state |
|---|---|---|---|---|
| `db` | `navigator.service_scheduler` row | `jobs.run_db_schedule` in `default` (memory) jobstore | `load_schedules_from_db()` | `PostgresRunState` (columns) |
| `redis` | the pickled `RedisJobStore` job (`kwargs.definition`, versioned, JSON-only) | `jobs.run_redis_job` in `redis` jobstore, per-job `misfire_grace_time` (default `None`), `coalesce=True` | `RedisJobStore` itself, because the store is attached **before** `scheduler.start()` | `RedisRunState` (hash `parrot:scheduler:{registered_name}:runstate:{job_id}`) |
| `code` | `CodeJobRecord` in process memory (from `@schedule` scanning) | `jobs.run_auto_schedule` in `default` jobstore | `register_object_schedules()` / `register_bot_schedules()` | `MemoryRunState` |
| *external* | a job some other component put in a jobstore (e.g. `ReminderToolkit`) | foreign | its owner | none — listed as `source='external'`, read-only |

Every Redis key is namespaced by `registered_name` (S3): jobstore keys `parrot:scheduler:{name}:jobs` /
`:run_times`, run-state hashes, and the fire-coordination prefix `parrot:scheduler:{name}:fire:` /
`:running:`. The default `registered_name` stays `"scheduler_manager"` so a restart finds its own jobs. A Redis
jobstore attached ⇒ the fire coordinator is `redis`, always; `SCHEDULER_COORDINATION=none` is honoured only
without a Redis jobstore and otherwise overridden with a WARNING.

**Uniform API, explicit per-backend semantics** (S2, S9):

| Operation | `db` | `redis` | `code` | external |
|---|---|---|---|---|
| `add_schedule` | row + job | job only (definition JSON-validated, `success_callback` rejected) | n/a (declared in code) | n/a |
| `get_schedule` / `list_jobs` | row | job kwargs → `JobDefinition` | `CodeJobRecord` → `JobDefinition` | minimal `source='external'` payload |
| `pause_schedule` / resume (`update enabled`) | `enabled` column + remove/add job | `pause_job` / `resume_job` + `enabled` in hash | `pause_job` / `resume_job` + record flag | **409** `not editable` |
| `update_schedule` (other fields) | row + fingerprint reschedule | rewrite `kwargs.definition` + `reschedule_job` | **409** `code-declared` | **409** |
| `delete_schedule` | row + job | job + hash | **409** `code-declared` (pause instead) | **409** |
| `run_schedule_now` | `jobs.run_db_schedule_now` one-shot | `jobs.run_redis_job_now` one-shot | `jobs.run_auto_schedule` one-shot | **409** |
| `get_last_result` | `PostgresRunState.read` | `RedisRunState.read` | `MemoryRunState.read` | **404** |

Resetting `enabled=true` through `update_schedule` also resets `consecutive_failures`.

**Fire path.** `jobs.run_*` trampolines dispatch by `registered_name` as today; the base builds a
`FireContext(fire_id, scheduled_at, run_now)` from the APScheduler run time (the same value the coordinator claims
on, so `fire_id` and the claim key agree — closes `aa813ccc1927`), resolves the target through the kind's resolver,
builds the call, injects `fire_id`/`scheduled_at` only when the innermost signature declares them or accepts
`**kwargs`, runs the target, then `_process_job_success` → `RunStateStore.stamp_success` → delivery callbacks
(user `success_callback` **inside** the same try/except as the registry callbacks — closes `37f02d3c2474`) →
`stamp_delivery`. A missing target raises `TargetMissingError`; it is a job failure, never `jobs.SKIPPED` (S4).

**Run-state transitions are atomic** (S4): `PostgresRunState` uses one `UPDATE … SET consecutive_failures =
consecutive_failures + 1, enabled = CASE … RETURNING`; `RedisRunState` uses a `WATCH`/`MULTI` pipeline on the hash.
Both return `crossed_threshold: bool`, true for exactly one caller, and only that caller sends the alert. Alerts go
to the schedule's own `send_result` recipients when configured, else `SCHEDULER_ALERT_RECIPIENTS`, else log only;
they never raise (S6). All timestamps go through one `utcnow()` helper and are serialized as ISO-8601 with offset (S7).

**Legacy surface removed** (S10): the mounted HTTP surface is `handlers/scheduler.py`
(`/api/v1/parrot/scheduler/schedules`, `/{id}/last-result`); the duplicate `SchedulerHandler` view at
`manager.py:2098` is deleted.

### Component Diagram
```
                 ┌────────────────────────── parrot.scheduler.base.SchedulerManager ──────────────────────────┐
                 │  AsyncIOScheduler ── jobstores{default: Memory, redis: RedisJobStore(ns=registered_name)}   │
                 │  CoordinatedAsyncIOExecutor ── FireCoordinator(prefix ns=registered_name)                   │
 HTTP / RPC ───► │  add_schedule / update / pause / delete / run_now / get_last_result / list_jobs             │
                 │       │                                                                                     │
                 │       ▼                                                                                     │
                 │  JobDefinition(backend) ──► db:    ServiceSchedule row  + jobs.run_db_schedule              │
                 │                         ──► redis: kwargs.definition    + jobs.run_redis_job                │
                 │                         ──► code:  CodeJobRecord        + jobs.run_auto_schedule            │
                 │       fire ▼                                                                                │
                 │  _execute_job(definition, FireContext) ── resolvers[kind].resolve()/build_call()            │
                 │       │                     ├─ service → RegistryResolver(TargetRegistry)   (base)          │
                 │       │                     ├─ agent   → AgentResolver(bot_manager)         (subclass)      │
                 │       │                     └─ crew    → CrewResolver(bot_manager)          (subclass)      │
                 │       ▼                                                                                     │
                 │  RunStateStore[backend] ── PostgresRunState | RedisRunState | MemoryRunState                 │
                 │       └─ stamp_success / stamp_failure(crossed_threshold) ─► alert (NotificationMixin)      │
                 └─────────────────────────────────────────────────────────────────────────────────────────────┘
                                          ▲ extends
                 parrot.scheduler.manager.AgentSchedulerManager(bot_manager) — register_bot_schedules, @schedule_*_report
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `parrot/scheduler/manager.py::AgentSchedulerManager` | **refactored** into subclass | keeps name, module, `registered_name`; loses target/persistence code |
| `parrot/scheduler/models.py::AgentSchedule` | **replaced** by `ServiceSchedule` | new table `navigator.service_scheduler`; `AgentSchedule` removed |
| `parrot/scheduler/jobs.py` | extends | `run_redis_job`, `run_redis_job_now`; type hints → `SchedulerManager` |
| `parrot/scheduler/coordination.py` | modifies | prefix namespaced by `registered_name`; coordinator forced to `redis` when the jobstore is attached; `SCHEDULER_REDIS_DB` |
| `parrot/scheduler/sanitize.py` | modifies | `normalize_jobstore_alias` → `normalize_backend`; `clean_misfire_grace_time`; `clean_method_name` |
| `parrot/scheduler/functions/__init__.py` (5 callbacks) + `handlers/infographic_recipes.py::RunInfographicRecipeCallback` | **breaking** | `run(result, *, schedule_id, target_name, **kwargs)` |
| `parrot/handlers/scheduler.py` (`SchedulerJobsHandler`, `SchedulerLastResultHandler`, `SchedulerCatalogHelper`) | **breaking** | `target_kind`/`target_name`/`target_id`/`backend`/`misfire_grace_time` payload; `list_scheduler_types` → `list_backends`; last-result from columns; 409/503 mappings |
| `parrot/handlers/crew/saved_execution_service.py::SavedExecutionService.schedule_execution` | modifies | `add_schedule(target_kind="crew", target_name=crew_name, ...)` as keywords |
| `parrot/integrations/agentd/service.py` | **breaking** | `SingleAgentManager` deleted; `register_target(name, agent, kind="agent")`; RPC `schedules.add` payload hard-cut |
| `parrot/integrations/agentd/config.py::SchedulerConfig`, `cli.py` | modifies | `redis: bool` keeps meaning "attach the Redis jobstore"; CLI `--redis/--no-redis` unchanged; no `scheduler_type` |
| `parrot/scheduler/__init__.py` (core lazy exports) | extends | `SchedulerManager`, `TargetRegistry`, `ServiceSchedule`, `JobDefinition` |
| `parrot/tools/reminder.py::ReminderToolkit`, `parrot/bots/jira_specialist.py` | docs only | still use `.scheduler` / `app["scheduler_manager"]`; reminder jobs appear as `source='external'` |
| `parrot/notifications/__init__.py::NotificationMixin` | uses | auto-disable alert via `send_notification(recipients=..., provider=...)` |
| `docs/scheduler/multi-worker.md`, `docs/agentd.md`, `docs/guides/cli-agent-daemon.md`, `examples/database/agents_scheduler_market_analysis.sql`, `docs/report-builder/inventory/*.md` | modifies | new API, backends, catch-up semantics, migration note (DDL + drop old table) |
| `sdd/proposals/dashboard-scheduled-notifications-canvas.proposal.md` (FEAT-430) | depends on | dependency note already added; rebased when FEAT-430 is specced |

### Data Models
```python
# packages/ai-parrot-server/src/parrot/scheduler/models.py  (replaces AgentSchedule)
class ServiceSchedule(Model):
    """asyncdb model for ``navigator.service_scheduler`` (backend='db' rows only).

    CREATE TABLE IF NOT EXISTS navigator.service_scheduler (
        schedule_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
        target_kind VARCHAR NOT NULL,                 -- agent | crew | service
        target_name VARCHAR NOT NULL,
        target_id VARCHAR,
        tenant VARCHAR,                               -- reserved; enforcement is §8 Q1
        prompt TEXT,
        method_name VARCHAR,
        schedule_type VARCHAR NOT NULL,
        schedule_config JSONB NOT NULL,
        enabled BOOLEAN DEFAULT TRUE,
        created_by INTEGER,
        created_email VARCHAR,
        created_at TIMESTAMPTZ DEFAULT NOW(),
        updated_at TIMESTAMPTZ DEFAULT NOW(),
        last_run TIMESTAMPTZ,
        next_run TIMESTAMPTZ,
        run_count INTEGER DEFAULT 0,
        last_status VARCHAR,                          -- success | error | target_missing | lock_unavailable
        last_error TEXT,
        last_error_at TIMESTAMPTZ,
        last_result TEXT,                             -- _format_result(), truncated to _LAST_RESULT_MAX_CHARS
        last_result_at TIMESTAMPTZ,
        consecutive_failures INTEGER DEFAULT 0,
        last_delivery_status VARCHAR,
        last_delivery_at TIMESTAMPTZ,
        last_callbacks JSONB DEFAULT '[]'::JSONB,
        metadata JSONB DEFAULT '{}'::JSONB,           -- call kwargs ONLY
        send_result JSONB DEFAULT '{}'::JSONB,
        callbacks JSONB DEFAULT '[]'::JSONB
    );
    CREATE INDEX idx_service_scheduler_enabled ON navigator.service_scheduler(enabled);
    CREATE INDEX idx_service_scheduler_target ON navigator.service_scheduler(target_kind, target_name);
    """
    schedule_id: uuid.UUID = Field(primary_key=True, default_factory=uuid.uuid4)
    target_kind: str = Field(required=True)
    target_name: str = Field(required=True)
    target_id: Optional[str] = Field(required=False)
    tenant: Optional[str] = Field(required=False)
    prompt: Optional[str] = Field(required=False)
    method_name: Optional[str] = Field(required=False)
    schedule_type: str = Field(required=True)
    schedule_config: dict = Field(required=True, default_factory=dict)
    enabled: bool = Field(required=False, default=True)
    created_by: Optional[int] = Field(required=False)
    created_email: Optional[str] = Field(required=False)
    created_at: datetime = Field(required=False, default_factory=utcnow)
    updated_at: datetime = Field(required=False, default_factory=utcnow)
    last_run: Optional[datetime] = Field(required=False)
    next_run: Optional[datetime] = Field(required=False)
    run_count: int = Field(required=False, default=0)
    last_status: Optional[str] = Field(required=False)
    last_error: Optional[str] = Field(required=False)
    last_error_at: Optional[datetime] = Field(required=False)
    last_result: Optional[str] = Field(required=False)
    last_result_at: Optional[datetime] = Field(required=False)
    consecutive_failures: int = Field(required=False, default=0)
    last_delivery_status: Optional[str] = Field(required=False)
    last_delivery_at: Optional[datetime] = Field(required=False)
    last_callbacks: list = Field(required=False, default_factory=list)
    metadata: dict = Field(required=False, default_factory=dict)
    send_result: dict = Field(required=False, default_factory=dict)
    callbacks: list = Field(required=False, default_factory=list)

    class Meta:
        driver = "pg"; name = "service_scheduler"; schema = "navigator"; strict = True; frozen = False


class JobDefinition(BaseModel):
    """Backend-independent, JSON-serializable job definition (Pydantic v2).

    Carried in Redis job kwargs (``definition_version`` = JOB_DEFINITION_VERSION = 1), converted
    from/to ``ServiceSchedule`` for ``db`` rows and built from ``CodeJobRecord`` for ``code`` jobs.
    ``extra='forbid'``; ``metadata``/``schedule_config``/``send_result``/``callbacks`` must survive
    ``json.dumps`` (validated at ``add_schedule``).
    """
    schedule_id: str
    backend: Literal["db", "redis", "code"]
    target_kind: str
    target_name: str
    target_id: Optional[str] = None
    tenant: Optional[str] = None
    prompt: Optional[str] = None
    method_name: Optional[str] = None
    schedule_type: str
    schedule_config: dict[str, Any]
    metadata: dict[str, Any] = {}
    send_result: dict[str, Any] = {}
    callbacks: list[dict[str, Any]] = []
    misfire_grace_time: Optional[int] = None   # None = always catch up (redis default); db default 300
    created_by: Optional[int] = None
    created_email: Optional[str] = None
    created_at: datetime


@dataclass(frozen=True)
class FireContext:
    """Per-fire context: ``fire_id = f"{schedule_id}:{scheduled_at.isoformat()}"`` (same value the
    coordinator claims on), ``scheduled_at`` (UTC-aware APScheduler run time), ``run_now``."""
    fire_id: str
    scheduled_at: datetime
    run_now: bool = False


@dataclass
class CodeJobRecord:
    """Process-local record for a ``@schedule``-declared job (replaces the ``_auto_tasks`` dict)."""
    job_id: str                   # auto_<target_name>_<method_name>
    target_name: str
    method_name: str
    method: Callable[..., Awaitable[Any]]
    schedule_type: str
    schedule_config: dict[str, Any]
    send_result: Optional[dict[str, Any]] = None
    callbacks: list[dict[str, Any]] = field(default_factory=list)
    success_callback: Optional[Callable[..., Any]] = None
    enabled: bool = True


class RunState(BaseModel):
    """What every ``RunStateStore.read()`` returns and ``get_last_result`` serializes (ISO-8601 with offset)."""
    schedule_id: str
    backend: str
    enabled: bool
    last_run: Optional[datetime] = None
    next_run: Optional[datetime] = None
    run_count: int = 0
    last_status: Optional[str] = None
    last_error: Optional[str] = None
    last_error_at: Optional[datetime] = None
    last_result: Optional[str] = None
    last_result_at: Optional[datetime] = None
    consecutive_failures: int = 0
    last_delivery_status: Optional[str] = None
    last_delivery_at: Optional[datetime] = None
    last_callbacks: list[dict[str, Any]] = []
```

Redis layout (all under `SCHEDULER_REDIS_DB`, default 6):

| Key | Type | Owner |
|---|---|---|
| `parrot:scheduler:{registered_name}:jobs` / `:run_times` | APScheduler `RedisJobStore` | base |
| `parrot:scheduler:{registered_name}:runstate:{job_id}` | hash, fields = `RunState` minus `schedule_id`/`backend` (ISO strings, ints) | `RedisRunState` |
| `parrot:scheduler:{registered_name}:fire:{job_id}:{iso_run_time}` / `:running:{schedule_id}` | `SET NX EX` | `RedisFireCoordinator` |

Redis job kwargs (pickled by APScheduler, data-only — S8):
`{"manager_name": str, "schedule_id": str, "definition_version": 1, "definition": JobDefinition.model_dump(mode="json")}`.

### New Public Interfaces
```python
# packages/ai-parrot-server/src/parrot/scheduler/base.py
def utcnow() -> datetime: ...                       # datetime.now(timezone.utc) — the ONLY clock in the package

class TargetMissingError(LookupError): ...          # raised by _execute_job when a resolver returns None / raises
class SchedulerUnavailableError(RuntimeError): ...  # coordination/jobstore unavailable → HTTP 503 (closes 7b5d75d2c81d)
class NotEditableError(ValueError): ...             # code/external job mutation → HTTP 409

class TargetResolver(Protocol):
    kind: str
    async def resolve(self, name: str, *, target_id: str | None = None) -> Any | None: ...
    def derive_target_id(self, target: Any) -> str | None: ...
    def build_call(self, target: Any, definition: JobDefinition, fire: FireContext) -> tuple[list[Any], dict[str, Any]]: ...

class TargetRegistry:
    def register(self, name: str, obj: Any, *, kind: str = "service", methods: Sequence[str] | None = None) -> None: ...
    def unregister(self, name: str, *, kind: str = "service") -> None: ...
    def get(self, name: str, *, kind: str = "service") -> Any | None: ...
    def allowed_methods(self, name: str, *, kind: str = "service") -> frozenset[str] | None: ...

class RegistryResolver:                              # kind = "service"
    def __init__(self, registry: TargetRegistry) -> None: ...

class SchedulerManager:
    registered_name: str = "scheduler_manager"
    def __init__(self, **kwargs: Any) -> None: ...
    def register_resolver(self, resolver: TargetResolver) -> None: ...
    def register_target(self, name: str, obj: Any, *, kind: str = "service", methods: Sequence[str] | None = None) -> None: ...
    def register_object_schedules(self, obj: Any, name: str) -> int: ...
    async def add_schedule(self, target_kind: str, target_name: str, schedule_type: str, schedule_config: dict[str, Any], *,
                           backend: str = "db", target_id: str | None = None, tenant: str | None = None,
                           prompt: str | None = None, method_name: str | None = None,
                           created_by: int | None = None, created_email: str | None = None,
                           metadata: dict[str, Any] | None = None, send_result: dict[str, Any] | None = None,
                           success_callback: Callable[..., Any] | None = None,
                           callbacks: list[dict[str, Any]] | None = None,
                           misfire_grace_time: int | None = None) -> JobDefinition: ...
    async def get_schedule(self, schedule_id: str) -> JobDefinition: ...
    async def list_schedules(self) -> list[JobDefinition]: ...
    async def list_jobs(self) -> list[dict[str, Any]]: ...
    async def update_schedule(self, schedule_id: str, updates: dict[str, Any]) -> JobDefinition: ...
    async def pause_schedule(self, schedule_id: str) -> JobDefinition: ...
    async def delete_schedule(self, schedule_id: str) -> None: ...
    async def run_schedule_now(self, schedule_id: str) -> JobDefinition: ...
    async def get_last_result(self, schedule_id: str) -> RunState: ...
    # unchanged in semantics: remove_schedule, restart_scheduler, start_headless, stop_headless, setup, on_startup, on_shutdown

# packages/ai-parrot-server/src/parrot/scheduler/runstate.py
class RunStateStore(Protocol):
    async def stamp_success(self, job_id: str, *, result_text: str | None, fire: FireContext, next_run: datetime | None) -> RunState: ...
    async def stamp_failure(self, job_id: str, *, status: str, error: str, fire: FireContext, threshold: int) -> tuple[RunState, bool]: ...
    async def stamp_delivery(self, job_id: str, outcomes: list[dict[str, Any]]) -> None: ...
    async def read(self, job_id: str) -> RunState | None: ...
    async def set_enabled(self, job_id: str, enabled: bool) -> None: ...   # enabled=True also resets consecutive_failures
    async def clear(self, job_id: str) -> None: ...

# packages/ai-parrot-server/src/parrot/scheduler/manager.py
class AgentResolver: ...   # kind = "agent"
class CrewResolver: ...    # kind = "crew"
class AgentSchedulerManager(SchedulerManager):
    def __init__(self, bot_manager: Any = None, **kwargs: Any) -> None: ...
    def register_bot_schedules(self, bot: Any) -> int: ...
```

---

## 3. Module Breakdown

#### Delegation-eligible modules

| Module | Eligible? | Decided patterns / exact contracts | Why not (if no) |
|---|---|---|---|
| M1: Models + DDL | yes | `ServiceSchedule` fields and DDL fixed in §2; `JobDefinition`/`RunState`/`FireContext`/`CodeJobRecord` fixed; `utcnow()` | — |
| M2: RunStateStore | yes | protocol + 3 impls in §2/§3; Postgres single-statement UPDATE; Redis WATCH/MULTI; `crossed_threshold` contract | — |
| M3: SchedulerManager base | no | the extraction of a 2.2k-line class and the exact seam with M5 need the thinking model | seam decisions during extraction |
| M4: jobs / coordination / sanitize | yes | trampoline signatures, key namespacing, `normalize_backend`, `clean_misfire_grace_time`, `clean_method_name`, coordinator rule | — |
| M5: AgentSchedulerManager + resolvers | no | depends on M3's seam; crew/agent resolution + report decorators | same as M3 |
| M6: Callbacks `target_name` | yes | mechanical rename on 6 `run()` signatures + `_job_context` | — |
| M7: HTTP handlers + SavedExecutionService | yes | payload fields, error mappings (400/404/409/503), catalog helper | — |
| M8: agentd | yes | delete `SingleAgentManager`, `register_target(kind="agent")`, RPC passthrough, config/cli | — |
| M9: Exports, docs, SQL example, inventory, version bump | yes | lists in §2 Integration Points; version 1.3.0 | — |
| M10: Ledger regression tests + parity test matrix | yes | test names and fakes fixed in §4 | — |

### Module 1: Models, definitions and the clock
- **Path**: `packages/ai-parrot-server/src/parrot/scheduler/models.py` (modify), `packages/ai-parrot-server/src/parrot/scheduler/base.py` (new, `utcnow`, `FireContext`, errors — the dataclasses live in `models.py`)
- **Responsibility**: `ServiceSchedule` (replaces `AgentSchedule`), `JobDefinition`, `RunState`, `CodeJobRecord`, `JOB_DEFINITION_VERSION = 1`, conversions `ServiceSchedule ↔ JobDefinition`, `schedule_fingerprint(definition)` (moved here from `manager.py:327`).
- **Depends on**: `asyncdb.models`, `pydantic`.
- **Interface Skeleton**:
  ```python
  # packages/ai-parrot-server/src/parrot/scheduler/models.py  (modifies models.py:7 — class AgentSchedule(Model) is REPLACED)
  JOB_DEFINITION_VERSION: int = 1
  def utcnow() -> datetime:
      """Return ``datetime.now(timezone.utc)``; the only clock used by the scheduler package."""
  class ServiceSchedule(Model):          # fields/DDL exactly as §2 Data Models
      def to_definition(self) -> "JobDefinition":
          """Map a db row to a ``JobDefinition(backend='db', misfire_grace_time=300)``."""
      @classmethod
      def from_definition(cls, definition: "JobDefinition") -> "ServiceSchedule":
          """Build a row (run-state columns untouched) from a definition."""
  class JobDefinition(BaseModel): ...    # §2
  class RunState(BaseModel): ...         # §2
  @dataclass(frozen=True)
  class FireContext: ...                 # §2
  @dataclass
  class CodeJobRecord: ...               # §2
  def schedule_fingerprint(definition: JobDefinition) -> str:   # moved from manager.py:327
      """sha256 over target_kind, target_name, target_id, prompt, method_name, schedule_type, schedule_config, metadata, send_result, callbacks, misfire_grace_time."""
  ```

### Module 2: RunStateStore
- **Path**: `packages/ai-parrot-server/src/parrot/scheduler/runstate.py` (new)
- **Responsibility**: the protocol in §2 plus `PostgresRunState(pool_getter)`, `RedisRunState(client, prefix)`, `MemoryRunState()`. Atomic failure transition: Postgres —
  `UPDATE navigator.service_scheduler SET last_run=$1, run_count=run_count+1, last_status=$2, last_error=$3, last_error_at=$1, consecutive_failures=consecutive_failures+1, enabled=(consecutive_failures+1 < $4 AND enabled) WHERE schedule_id=$5 RETURNING consecutive_failures, enabled` → `crossed = (row.consecutive_failures == threshold)`; Redis — `WATCH key; MULTI; HINCRBY/HSET…; EXEC` with retry on `WatchError`, `crossed` computed from the pre-read value `+1 == threshold`. `stamp_success` resets `consecutive_failures=0`, clears `last_error`/`last_error_at`. `stamp_failure(status='lock_unavailable')` stamps but does not touch the counter.
- **Depends on**: M1; `redis.asyncio` (same client type `RedisFireCoordinator` takes, `coordination.py:86`); asyncdb pool.
- **Interface Skeleton**:
  ```python
  # packages/ai-parrot-server/src/parrot/scheduler/runstate.py  (new)
  class RunStateStore(Protocol): ...                    # §2 New Public Interfaces
  class PostgresRunState:
      def __init__(self, acquire: Callable[[], Awaitable[Any]]) -> None:
          """``acquire`` returns the ``async with`` connection context the manager already uses (manager.py:999)."""
  class RedisRunState:
      def __init__(self, client: "aioredis.Redis", *, prefix: str) -> None:
          """``prefix`` = ``parrot:scheduler:{registered_name}:runstate:``."""
  class MemoryRunState:
      def __init__(self) -> None: ...
  ```

### Module 3: SchedulerManager base
- **Path**: `packages/ai-parrot-server/src/parrot/scheduler/base.py` (new)
- **Responsibility**: everything from `AgentSchedulerManager.__init__` (`manager.py:362`) through `on_shutdown` (`manager.py:2077`) that is not agent/crew specific: scheduler + jobstores (namespaced), coordinator (forced `redis` with a jobstore), listeners, `_job_context`, `_local_callbacks` (db only), `_code_jobs: dict[str, CodeJobRecord]` (replaces `_auto_tasks`), `TargetRegistry` instance + `self._resolvers: dict[str, TargetResolver]` with `RegistryResolver` pre-installed, `register_object_schedules`, the CRUD matrix of §2, `_execute_job(definition, fire)` (signature injection via `inspect.signature(inspect.unwrap(method))`; underscore-prefixed `method_name` → `ValueError` at add time and `error` at fire; `methods` allowlist enforced for `service`), `_process_job_success` (user `success_callback` inside the try/except — `37f02d3c2474`), alerts (`_alert_disabled(definition, state)` → recipients from `send_result` → `SCHEDULER_ALERT_RECIPIENTS` → log), `start_headless`/`stop_headless`/`setup`/`on_startup`/`on_shutdown`, `run_schedule_now` raising `SchedulerUnavailableError` on `FireCoordinationError` (`7b5d75d2c81d`), settings read once via `nav_config.get()`.
- **Depends on**: M1, M2, M4.
- **Interface Skeleton**:
  ```python
  # packages/ai-parrot-server/src/parrot/scheduler/base.py  (new)
  class TargetMissingError(LookupError): ...
  class SchedulerUnavailableError(RuntimeError): ...
  class NotEditableError(ValueError): ...
  class TargetResolver(Protocol): ...            # §2
  class TargetRegistry: ...                      # §2
  class RegistryResolver:
      kind: str = "service"
      def __init__(self, registry: TargetRegistry) -> None: ...
      async def resolve(self, name: str, *, target_id: str | None = None) -> Any | None:
          """Return the registered object or None; never raises."""
      def derive_target_id(self, target: Any) -> str | None:
          """Always None for services."""
      def build_call(self, target: Any, definition: JobDefinition, fire: FireContext) -> tuple[list[Any], dict[str, Any]]:
          """kwargs = dict(definition.metadata); prompt is passed through the same signature rules as agents
          (first positional / *args / **kwargs) — see manager.py:441 _apply_prompt_signature, moved here."""
  class SchedulerManager:
      registered_name: str = "scheduler_manager"   # verified: manager.py:360
      def __init__(self, **kwargs: Any) -> None:
          """Builds AsyncIOScheduler with job_defaults coalesce=True, max_instances=2, misfire_grace_time=300, tz UTC (verified: manager.py:391-400); registers with jobs.register_manager (verified: jobs.py:35)."""
      def register_resolver(self, resolver: TargetResolver) -> None:
          """Install/replace the resolver for ``resolver.kind``."""
      def register_target(self, name: str, obj: Any, *, kind: str = "service", methods: Sequence[str] | None = None) -> None:
          """Explicit registration consulted first by every resolver; ``methods`` is the allowlist for ``service``."""
      def register_object_schedules(self, obj: Any, name: str) -> int:
          """Scan ``inspect.getmembers(obj, inspect.ismethod)`` for ``_schedule_config`` (verified: manager.py:1302-1306) and add ``jobs.run_auto_schedule`` jobs backed by ``CodeJobRecord``."""
      async def add_schedule(...) -> JobDefinition: ...          # §2 signature
      async def _execute_job(self, definition: JobDefinition, fire: FireContext, *, success_callback: Callable[..., Any] | None = None) -> Any:
          """Resolve → build_call → inject fire_id/scheduled_at by signature → await. Raises TargetMissingError, ValueError (private/unlisted method)."""
      async def _run_db_schedule(self, schedule_id: str, fingerprint: str | None, *, run_now: bool = False) -> Any: ...   # verified: manager.py:1486, semantics kept
      async def _run_redis_job(self, schedule_id: str, *, run_now: bool = False) -> Any:
          """Read kwargs from the APScheduler job; definition_version mismatch → stamp 'incompatible', pause_job, WARNING once, return jobs.SKIPPED."""
      async def _run_auto_task(self, job_id: str, *, run_now: bool = False) -> Any: ...   # verified: manager.py:1538
      def _run_state_for(self, backend: str) -> RunStateStore: ...
      async def _alert_disabled(self, definition: JobDefinition, state: RunState) -> None:
          """NotificationMixin.send_notification (verified: notifications/__init__.py:442); never raises."""
  ```

### Module 4: Trampolines, coordination keys, sanitisation
- **Path**: `packages/ai-parrot-server/src/parrot/scheduler/jobs.py`, `coordination.py`, `sanitize.py` (modify)
- **Responsibility**: `run_redis_job(manager_name, schedule_id, definition_version, definition)` and `run_redis_job_now(manager_name, schedule_id)`; `_MANAGERS` typed to `SchedulerManager`; `build_fire_coordinator(mode, *, use_redis, prefix)` forcing `redis` when `use_redis` and warning on explicit `none`; `DEFAULT_PREFIX` → `f"parrot:scheduler:{registered_name}:"`; `DEFAULT_REDIS_JOBSTORE_DB` read from `SCHEDULER_REDIS_DB`; `normalize_backend(value, *, redis_available, strict)` replacing `normalize_jobstore_alias` (`sanitize.py:275`); `clean_misfire_grace_time(value) -> int | None`; `clean_method_name(value) -> str | None` (rejects `_`-prefixed, non-identifier).
- **Depends on**: M1.
- **Interface Skeleton**:
  ```python
  # packages/ai-parrot-server/src/parrot/scheduler/jobs.py  (modifies jobs.py:32-76)
  async def run_redis_job(manager_name: str, schedule_id: str, definition_version: int, definition: dict[str, Any]) -> Any:
      """Entrypoint for backend='redis' jobs; delegates to ``_run_redis_job``."""
  async def run_redis_job_now(manager_name: str, schedule_id: str) -> Any:
      """Run-now one-shot for a redis job; always releases the run-now guard (mirror of run_db_schedule_now, verified: jobs.py:65-71)."""
  # packages/ai-parrot-server/src/parrot/scheduler/coordination.py  (modifies coordination.py:24, :139)
  def build_fire_coordinator(mode: Optional[str] = None, *, use_redis: bool = False, prefix: str = DEFAULT_PREFIX) -> FireCoordinator:
      """use_redis=True ⇒ RedisFireCoordinator regardless of SCHEDULER_COORDINATION (WARNING if it says 'none')."""
  # packages/ai-parrot-server/src/parrot/scheduler/sanitize.py  (modifies sanitize.py:275 normalize_jobstore_alias → REPLACED)
  def normalize_backend(value: Any, *, redis_available: bool, strict: bool = False) -> str:
      """'db' | 'redis'; 'redis' without an attached jobstore → SchedulerConfigError (strict) — never a downgrade to 'db'."""
  def clean_misfire_grace_time(value: Any) -> Optional[int]:
      """None or int >= 0; anything else → SchedulerConfigError."""
  def clean_method_name(value: Any) -> Optional[str]:
      """Identifier not starting with '_' or None; anything else → SchedulerConfigError."""
  ```

### Module 5: AgentSchedulerManager, AgentResolver, CrewResolver
- **Path**: `packages/ai-parrot-server/src/parrot/scheduler/manager.py` (modify — shrinks)
- **Responsibility**: keeps `ScheduleType`, the `@schedule` / `schedule_daily_report` / `schedule_weekly_report` decorators and env-var parsers (`manager.py:120-325`), `SchedulerRunNowConflictError`; adds `AgentResolver` (registry first → `bot_manager.get_bots().get(name)` → `await bot_manager.registry.get_instance(name)`; `derive_target_id` = `chatbot_id`; `build_call` keeps the `chat(prompt)` fallback when `method_name` is None), `CrewResolver` (`crew_entry = await bot_manager.get_crew(name)`; `derive_target_id` = `crew_id`; crew prompt mapping `run_flow`/`run_loop` → `initial_task`, `run_sequential` → `query`, `run_parallel` → `tasks`, verified `manager.py:421-427`), `AgentSchedulerManager(SchedulerManager)` with `bot_manager` kwarg, `register_bot_schedules(bot)` (resolves `chatbot_id`/`agent_id`/`name` and `_schedule_report_type` env timing, then `register_object_schedules`), `on_startup` fallback to `app.get("bot_manager")`. **Deletes** `SchedulerHandler` (`manager.py:2098-2219`), `_execute_agent_job`, `_execute_agent_task`, `_prepare_call_arguments`, `_apply_prompt_signature` (moved), `_update_schedule_run`, `_stamp_delivery_outcome`, `_serialize_auto_job`, `_auto_tasks`.
- **Depends on**: M3, M1.
- **Interface Skeleton**:
  ```python
  # packages/ai-parrot-server/src/parrot/scheduler/manager.py  (modifies manager.py:349 class AgentSchedulerManager)
  class AgentResolver:
      kind: str = "agent"
      def __init__(self, registry: TargetRegistry, bot_manager_getter: Callable[[], Any | None]) -> None: ...
      async def resolve(self, name: str, *, target_id: str | None = None) -> Any | None:
          """registry → bot_manager.get_bots() (verified: manager/manager.py:1257) → await bot_manager.registry.get_instance(name) (verified: registry.py:85)."""
  class CrewResolver:
      kind: str = "crew"
      async def resolve(self, name: str, *, target_id: str | None = None) -> Any | None:
          """``await bot_manager.get_crew(name)`` (verified async: manager/manager.py:3019) → crew or None."""
  class AgentSchedulerManager(SchedulerManager):
      def __init__(self, bot_manager: Any = None, **kwargs: Any) -> None:
          """Installs AgentResolver + CrewResolver; keeps ``registered_name`` kwarg."""
      def register_bot_schedules(self, bot: Any) -> int:
          """Report decorators → _resolve_report_schedule (verified: manager.py:294); then register_object_schedules(bot, bot.name)."""
      async def on_startup(self, app: web.Application, conn: Callable) -> None:
          """super().on_startup; bot_manager fallback to app.get('bot_manager') (verified: manager.py:2062); register_bot_schedules for get_bots()."""
  ```

### Module 6: Callbacks take `target_name`
- **Path**: `packages/ai-parrot-server/src/parrot/scheduler/functions/__init__.py` (5 `run()` signatures at lines 97, 108, 155, 169, 215 and `__call__`), `packages/ai-parrot-server/src/parrot/handlers/infographic_recipes.py:348`
- **Responsibility**: rename the keyword `agent_name` → `target_name` on `BaseSchedulerCallback.run/__call__` and every subclass; `_job_context` carries `target_kind`/`target_name`.
- **Depends on**: M3.
- **Interface Skeleton**:
  ```python
  # packages/ai-parrot-server/src/parrot/scheduler/functions/__init__.py  (modifies :97, :108, :155, :169, :215)
  class BaseSchedulerCallback(NotificationMixin):
      async def run(self, result: Any, *, schedule_id: str, target_name: str, **kwargs: Any) -> Dict[str, Any]: ...
      async def __call__(self, result: Any, *, schedule_id: str, target_name: str, **kwargs: Any) -> Dict[str, Any]: ...
  ```

### Module 7: HTTP handlers and SavedExecutionService
- **Path**: `packages/ai-parrot-server/src/parrot/handlers/scheduler.py`, `packages/ai-parrot-server/src/parrot/handlers/crew/saved_execution_service.py`
- **Responsibility**: POST body `target_kind`* `target_name`* `schedule_type`* `schedule_config`* + `backend` `target_id` `tenant` `prompt` `method_name` `created_by` `created_email` `metadata` `send_result` `callbacks` `misfire_grace_time`; unknown fields (incl. `agent_name`, `agent_id`, `is_crew`, `scheduler_type`) → 400 `unknown field`; `SchedulerConfigError` → 400; `TargetMissingError`/`NoDataFound` → 404; `NotEditableError`/`SchedulerRunNowConflictError` → 409; `SchedulerUnavailableError` → 503. `SchedulerCatalogHelper.list_scheduler_types` → `list_backends(app)` (`["db"]` + `"redis"` when attached). `SchedulerLastResultHandler` returns `RunState.model_dump(mode="json")`. `SavedExecutionService.schedule_execution` calls `add_schedule(target_kind="crew", target_name=crew_name, schedule_type=..., schedule_config=..., prompt=..., method_name=..., created_by=..., created_email=..., metadata=..., callbacks=...)`.
- **Depends on**: M3, M5.
- **Interface Skeleton**:
  ```python
  # packages/ai-parrot-server/src/parrot/handlers/scheduler.py  (modifies :25 list_scheduler_types, :93-125 post, :127-160 patch, :198 get)
  class SchedulerCatalogHelper(BaseHandler):
      @staticmethod
      def list_backends(app: web.Application) -> list[str]:
          """['db'] plus 'redis' when the manager's scheduler has the 'redis' jobstore."""
  class SchedulerJobsHandler(BaseView):
      async def post(self) -> web.Response:
          """201 with manager._serialize_job(definition); error mapping as above."""
  ```

### Module 8: agentd
- **Path**: `packages/ai-parrot-integrations/src/parrot/integrations/agentd/service.py`, `config.py`, `cli.py`
- **Responsibility**: delete `SingleAgentManager` (`service.py:240-275`) and its `__all__` entry (`service.py:58`); boot `AgentSchedulerManager()` then `manager.register_target(self.config.name, self.agent, kind="agent")` and `manager.register_bot_schedules(self.agent)` (`service.py:509-529`); `_handle_schedules_add` keeps `add_schedule(**params)` (payload hard-cut; unknown kwargs → `RpcHandlerError` invalid params); `SchedulerConfig.redis` unchanged in meaning; docstrings in `config.py:115-125` and `cli.py` updated; `docs/agentd.md`, `docs/guides/cli-agent-daemon.md` examples use `target_kind`/`target_name`.
- **Depends on**: M5.
- **Interface Skeleton**:
  ```python
  # packages/ai-parrot-integrations/src/parrot/integrations/agentd/service.py  (modifies :509-529; deletes :240-275)
  class AgentDaemon:
      async def _boot_scheduler(self) -> Any:
          """AgentSchedulerManager(); register_target(name, agent, kind='agent'); register_bot_schedules(agent); start_headless(dsn=cfg.dsn, use_redis=cfg.redis)."""
  ```

### Module 9: Exports, docs, SQL example, inventory, version
- **Path**: `packages/ai-parrot/src/parrot/scheduler/__init__.py` (`_SERVER_CLASSES` + `__all__`), `docs/scheduler/multi-worker.md` (rewrite "Redis jobstore is not coordination", line 35, into "Backends and coordination"; add catch-up semantics and the migration note with the DDL and `DROP TABLE navigator.agents_scheduler`), `docs/agentd.md`, `docs/guides/cli-agent-daemon.md`, `examples/database/agents_scheduler_market_analysis.sql`, `docs/report-builder/inventory/{_admin_bots,P1-parrot-endpoints,P2-parrot-components-models}.md`, `docs/report-builder/inventory-and-analysis.md`, `packages/ai-parrot-server/src/parrot/server/version.py` (`1.3.0`).
- **Depends on**: M1–M8 names.
- **Interface Skeleton**:
  ```python
  # packages/ai-parrot/src/parrot/scheduler/__init__.py  (modifies :17 — _SERVER_CLASSES)
  _SERVER_CLASSES = {
      ...,
      "SchedulerManager": ("parrot.scheduler.base", "SchedulerManager"),
      "TargetRegistry": ("parrot.scheduler.base", "TargetRegistry"),
      "ServiceSchedule": ("parrot.scheduler.models", "ServiceSchedule"),
      "JobDefinition": ("parrot.scheduler.models", "JobDefinition"),
  }
  ```

### Module 10: Tests — ledger regressions and the backend-parity matrix
- **Path**: `packages/ai-parrot-server/tests/scheduler/` (rewrite the 13 modules for the new names; add `test_base_parity.py`, `test_runstate.py`, `test_redis_backend.py`, `test_resolvers.py`, `test_ledger_regressions.py`), `packages/ai-parrot/tests/test_schedules.py` (rewrite; `get_crew` stub becomes `async`), agentd tests touching the scheduler.
- **Responsibility**: see §4.
- **Depends on**: all.

---

## 4. Test Specification

### Unit Tests
| Test | Module | Description |
|---|---|---|
| `test_service_schedule_roundtrip_definition` | M1 | `ServiceSchedule.to_definition()` / `from_definition()` preserve every field; run-state columns untouched |
| `test_definition_rejects_non_json_metadata` | M1 | `JobDefinition` with a callable/`datetime` in `metadata` fails validation |
| `test_fingerprint_covers_misfire_and_target_fields` | M1 | changing any covered field changes `schedule_fingerprint` |
| `test_utcnow_is_aware` | M1 | `utcnow().tzinfo is timezone.utc` |
| `test_pg_stamp_failure_single_statement_threshold` | M2 | three `stamp_failure` calls on a fake pool: `crossed_threshold` true exactly on the third; `enabled` flips once |
| `test_pg_stamp_success_resets_counter_and_clears_error` | M2 | after a failure, success leaves `last_error=None`, `consecutive_failures=0` |
| `test_redis_stamp_failure_watch_multi_race` | M2 | two concurrent `stamp_failure` on `fakeredis` crossing the threshold → exactly one `crossed_threshold=True` |
| `test_lock_unavailable_does_not_count` | M2 | `status='lock_unavailable'` leaves `consecutive_failures` unchanged (pg, redis, memory) |
| `test_runstate_parity_matrix` | M2 | parametrized over the three stores: same `RunState` after the same stamp sequence (ISO offsets, ints) |
| `test_register_target_and_resolve_service` | M3 | `register_target` + `add_schedule(target_kind='service', method_name=...)` resolves and calls `obj.method` |
| `test_service_requires_method_name` | M3 | `service` without `method_name` → `ValueError` at `add_schedule` |
| `test_private_method_rejected_all_kinds` | M3 | `method_name='_x'` / `'__dunder__'` → `ValueError` for agent, crew, service |
| `test_service_methods_allowlist` | M3 | `register_target(..., methods=['run'])` then `method_name='other'` → `ValueError` at add; at fire → `error` |
| `test_fire_context_injected_by_signature` | M3 | method with `fire_id`, with `**kwargs`, with neither: injected / injected / not injected; `@schedule`-wrapped method unwrapped before inspection |
| `test_fire_id_matches_coordinator_claim_key` | M3/M4 | `fire_id` equals `f"{job_id}:{run_time.isoformat()}"` used by `RedisFireCoordinator.claim` (closes `aa813ccc1927`) |
| `test_target_missing_raises_not_skipped` | M3 | resolver returns `None` → `TargetMissingError`, `last_status='target_missing'`, counter +1; the job_success listener never runs |
| `test_resolver_exception_is_target_missing` | M3 | resolver raising → `target_missing`, WARNING without traceback |
| `test_auto_disable_after_threshold_and_single_alert` | M3 | with `SCHEDULER_MAX_CONSECUTIVE_FAILURES=3`, mixed `error`/`target_missing` → disabled on the third, one `send_notification` call, recipients from `send_result` then `SCHEDULER_ALERT_RECIPIENTS` |
| `test_alert_failure_never_raises` | M3 | `send_notification` raising → logged, schedule still disabled |
| `test_update_enabled_resets_counter` | M3 | `update_schedule(id, {'enabled': True})` → `consecutive_failures=0`, job re-added |
| `test_success_callback_raise_does_not_skip_delivery` | M3 | raising `success_callback` → recorded as failed outcome, `send_result` + callbacks still run (closes `37f02d3c2474`) |
| `test_run_now_coordination_outage_is_unavailable_error` | M3 | `FireCoordinationError` → `SchedulerUnavailableError`; handler → 503 (closes `7b5d75d2c81d`) |
| `test_crud_matrix_per_backend` | M3 | parametrized `(backend, op)` over the §2 matrix: expected result or `NotEditableError` |
| `test_code_job_record_replaces_name_parsing` | M3 | `register_object_schedules(obj, 'a.b')` with a dotted name → `list_jobs` reports `target_name='a.b'`, `method_name` exact |
| `test_external_job_listed_readonly` | M3 | a foreign job added straight to the `redis` jobstore (ReminderToolkit style) → `source='external'`; `delete_schedule` → `NotEditableError`; `get_last_result` → `None` |
| `test_redis_job_kwargs_are_json_only_and_versioned` | M4 | `add_schedule(backend='redis')` job kwargs == `{manager_name, schedule_id, definition_version: 1, definition}`; `success_callback` → `ValueError` |
| `test_redis_job_incompatible_version_pauses` | M3/M4 | kwargs with `definition_version=99` → `last_status='incompatible'`, job paused, one WARNING |
| `test_redis_job_survives_restart` | M3/M4 | add `redis` job on manager A (fakeredis jobstore), `stop_headless`, new manager B same `registered_name`, `start_headless(use_redis=True)` → job listed, fires, run state readable |
| `test_redis_job_catchup_once_after_outage` | M3/M4 | `misfire_grace_time=None` + `coalesce=True`: three missed run times → one execution with `scheduled_at` = the last due time; `misfire_grace_time=600` + 2 h gap → none |
| `test_jobstore_and_coordinator_keys_namespaced` | M4 | two managers with different `registered_name` on one fakeredis: no cross-listing, independent fire claims |
| `test_coordinator_forced_redis_with_jobstore` | M4 | `use_redis=True` + `SCHEDULER_COORDINATION=none` → `RedisFireCoordinator` + WARNING |
| `test_normalize_backend_strict_503_path` | M4 | `'redis'` with `redis_available=False, strict=True` → `SchedulerConfigError`; handler → 503 |
| `test_clean_misfire_grace_time` / `test_clean_method_name` | M4 | accepted/rejected values |
| `test_crew_resolver_awaits_get_crew` | M5 | `bot_manager.get_crew` is `async def` → crew resolved (the regression for the un-awaited call) |
| `test_agent_resolver_order` | M5 | registry → `get_bots()` → `registry.get_instance()`; `_bots` never touched |
| `test_report_decorators_still_register` | M5 | `schedule_daily_report` on a bot with `chatbot_id` → env-var timing resolved, `code` job registered |
| `test_callbacks_receive_target_name` | M6 | every `CALLBACK_REGISTRY` entry accepts `target_name=`; `agent_name=` → `TypeError` |
| `test_post_rejects_legacy_fields` | M7 | `agent_name` / `is_crew` / `scheduler_type` in body → 400 `unknown field` |
| `test_post_redis_backend_without_jobstore_503` | M7 | — |
| `test_last_result_from_columns` | M7 | response carries `last_error_at`, `consecutive_failures`, ISO offsets |
| `test_saved_execution_schedules_crew_by_keyword` | M7 | `SavedExecutionService.schedule_execution` → `add_schedule(target_kind='crew', target_name=...)` |
| `test_agentd_boots_without_single_agent_manager` | M8 | `SingleAgentManager` absent; `register_target(kind='agent')` called; RPC `schedules.add` with `agent_name` → invalid params |
| `test_lazy_exports_resolve` | M9 | `from parrot.scheduler import SchedulerManager, TargetRegistry, ServiceSchedule, JobDefinition` |

### Integration Tests
| Test | Description |
|---|---|
| `test_db_schedule_end_to_end` | fake pool + memory jobstore: add → fire → columns stamped (UTC) → delivery outcomes stamped → `get_last_result` |
| `test_redis_schedule_end_to_end` | fakeredis jobstore + `RedisRunState`: add → restart → fire → hash stamped → pause/update/delete |
| `test_three_backends_same_list_payload` | `list_jobs()` with one job per backend (+ one external) returns the same keys, `source` ∈ {db, redis, code, external} |
| `test_multiworker_threshold_race` | two managers, same `registered_name`, fakeredis coordinator + `RedisRunState`: three failing fires → one disable, one alert |
| `test_headless_startup_order` | jobstores attached → coordinator → `scheduler.start()` → `load_schedules_from_db` → code jobs; redis jobs present before DB load |

### Test Data / Fixtures
```python
@pytest.fixture
async def fake_redis():            # fakeredis.aioredis.FakeRedis — already used by tests/test_suspended_store.py
    ...
@pytest.fixture
def fake_pool():                   # records executed SQL; returns rows for RETURNING
    ...
@pytest.fixture
async def manager(fake_pool):      # SchedulerManager(registered_name=f"t-{uuid4().hex}") with MemoryJobStore; stop_headless on teardown
    ...
@pytest.fixture
def service_obj():                 # object with `async def run(self, prompt=None, *, fire_id=None, scheduled_at=None)` and `async def _private(self)`
    ...
def _definition(**overrides) -> JobDefinition: ...
```
Existing fixtures/helpers to keep: `_schedule(**overrides)` and `manager()` in `tests/scheduler/test_fire_recheck.py:17-44` (renamed to the new model).

---

## 5. Acceptance Criteria

> This feature is complete when ALL of the following are true:

- [ ] AC1. `SchedulerManager` is importable from `parrot.scheduler.base` and lazily from `parrot.scheduler`; it has no import of `parrot.manager`, `parrot.bots` or `parrot.registry` (`grep` in `base.py` returns nothing).
- [ ] AC2. `AgentSchedulerManager` is a subclass of `SchedulerManager`, keeps its module and `registered_name` default, and `SingleAgentManager` no longer exists anywhere in the repo.
- [ ] AC3. `register_target(name, obj, kind="service", methods=[...])` + `add_schedule(target_kind="service", ...)` schedules and executes `obj.<method_name>` without a `BotManager`; a `service` schedule without `method_name`, with a `_`-prefixed name, or with a name outside `methods` is rejected at `add_schedule`.
- [ ] AC4. `TargetResolver.resolve` is `async`; `CrewResolver` awaits `BotManager.get_crew()`; the core crew test uses an `async def get_crew` stub and passes.
- [ ] AC5. `navigator.service_scheduler` DDL in `ServiceSchedule.__doc__` matches §2 exactly (incl. `tenant`, run-state columns, no `scheduler_type`); `AgentSchedule` and the string `agents_scheduler` no longer appear under `packages/*/src`.
- [ ] AC6. `metadata` never contains run state: after a success and a failure, `_execute_job` receives call kwargs equal to the original `metadata`; `last_error`/`last_error_at` are `None` after a success.
- [ ] AC7. Every persisted timestamp is UTC-aware (`utcnow()`), and every API/RPC timestamp is ISO-8601 with offset.
- [ ] AC8. `backend='redis'` jobs: no Postgres row; job kwargs are JSON-only and carry `definition_version=1`; `success_callback` is rejected; the job is listed and fires after `stop_headless` + new manager + `start_headless(use_redis=True)`; default `misfire_grace_time=None` + `coalesce=True` yields exactly one catch-up run after an outage; a per-job `misfire_grace_time` bounds it.
- [ ] AC9. Run state for `redis` jobs lives in `parrot:scheduler:{registered_name}:runstate:{job_id}` and `get_last_result` / `list_jobs` return the same `RunState` shape as for `db` jobs.
- [ ] AC10. The CRUD × backend matrix of §2 holds: `code` and external jobs raise `NotEditableError` (HTTP 409) on update/delete, `code` jobs can be paused/resumed/run-now, external jobs are read-only `source='external'`.
- [ ] AC11. `consecutive_failures` is shared by `error` and `target_missing`, reset by success and by `enabled=true`, untouched by `lock_unavailable`; crossing `SCHEDULER_MAX_CONSECUTIVE_FAILURES` (default 3) disables the schedule, removes/pauses the job and sends exactly one alert even with two concurrent workers (Postgres single-statement UPDATE; Redis WATCH/MULTI).
- [ ] AC12. A missing target logs one WARNING per tick without traceback and is stamped `target_missing`; it is never reported through the success listener.
- [ ] AC13. `fire_id`/`scheduled_at` are injected only when the innermost signature declares them or accepts `**kwargs`; `fire_id` equals the coordinator claim key suffix.
- [ ] AC14. All Redis keys (jobstore, run state, fire/running) are prefixed `parrot:scheduler:{registered_name}:`; `SCHEDULER_REDIS_DB` (default 6) selects the logical db; attaching a Redis jobstore forces the `redis` coordinator and logs a WARNING when `SCHEDULER_COORDINATION=none`.
- [ ] AC15. HTTP `POST /api/v1/parrot/scheduler/schedules` accepts `target_kind`/`target_name`/`backend`/`misfire_grace_time`/`tenant` and rejects `agent_name`/`agent_id`/`is_crew`/`scheduler_type` with 400; `backend='redis'` without a jobstore → 503; `NotEditableError` → 409; `SchedulerUnavailableError` → 503. The `SchedulerHandler` view in `manager.py` is gone.
- [ ] AC16. agentd RPC `schedules.add` with `agent_name` fails with an invalid-params error; with `target_kind`/`target_name` it succeeds.
- [ ] AC17. Ledger issues `aa813ccc1927`, `7b5d75d2c81d`, `37f02d3c2474` are closed (`wikitoolkit ledger close --resolved-by`) with the regression tests of §4 passing.
- [ ] AC18. `ruff check` passes (TID251 included) on every touched file; the 13 existing scheduler test modules, `packages/ai-parrot/tests/test_schedules.py`, `tests/tools/test_reminder_toolkit.py` and the agentd suite pass under `PYTHONPATH=packages/ai-parrot-server/src:packages/ai-parrot/src:packages/ai-parrot-integrations/src`.
- [ ] AC19. Docs updated: `docs/scheduler/multi-worker.md` (backends, catch-up, migration note with DDL + drop), `docs/agentd.md`, `docs/guides/cli-agent-daemon.md`, `examples/database/agents_scheduler_market_analysis.sql`, the four `docs/report-builder` pages; `ai-parrot-server` version is `1.3.0`.
- [ ] AC20. `ReminderToolkit` tests still pass and its jobs are listed as `source='external'` (its jobstore keys move with the namespace; documented in the migration note).

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor.** Verified against `dev` @ `c9b5f4a44` (2026-10-08). The scheduler files are
> unchanged between the brainstorm's verification and this commit (`git diff --stat` empty).

### Verified Imports
```python
from parrot.scheduler import AgentSchedulerManager, ScheduleType, schedule           # verified: packages/ai-parrot/src/parrot/scheduler/__init__.py:12-23 (lazy _SERVER_CLASSES)
from parrot.scheduler.manager import AgentSchedulerManager, ScheduleType, schedule_fingerprint, _resolve_report_schedule  # manager.py:71, :349, :327, :294
from parrot.scheduler.models import AgentSchedule                                     # verified: packages/ai-parrot-server/src/parrot/scheduler/models.py:7 (to be REPLACED)
from parrot.scheduler import jobs                                                     # verified: packages/ai-parrot-server/src/parrot/scheduler/jobs.py
from parrot.scheduler.coordination import FireCoordinator, FireCoordinationError, NullFireCoordinator, RedisFireCoordinator, CoordinatedAsyncIOExecutor, build_fire_coordinator  # coordination.py:29,34,53,81,168,139
from parrot.scheduler.sanitize import SchedulerConfigError, normalize_schedule_type, sanitize_schedule_config, normalize_jobstore_alias, sanitize_redis_settings  # sanitize.py:104,343,502,275,236
from parrot.scheduler.functions import BaseSchedulerCallback, CALLBACK_REGISTRY, build_scheduler_callback, list_supported_callbacks  # functions/__init__.py:17,238,253,249
from parrot.notifications import NotificationMixin                                    # verified: packages/ai-parrot/src/parrot/notifications/__init__.py:83
from parrot._imports import load_satellite_attr                                       # verified: packages/ai-parrot/src/parrot/_imports.py:183
from parrot.conf import default_dsn, CACHE_HOST, CACHE_PORT                          # verified: manager.py:42; conf.py:81
from navconfig import config as nav_config                                            # verified: coordination.py:149
from asyncdb.models import Model, Field                                               # verified: models.py:4
from asyncdb.exceptions import NoDataFound                                            # verified: manager.py:40
import redis.asyncio as aioredis                                                      # verified: coordination.py:13
from apscheduler.schedulers.asyncio import AsyncIOScheduler                           # verified: manager.py:32
from apscheduler.jobstores.memory import MemoryJobStore                               # verified: manager.py:30
from apscheduler.jobstores.redis import RedisJobStore                                 # verified: manager.py:31
from apscheduler.jobstores.base import JobLookupError                                 # verified: manager.py:29
from apscheduler.triggers.date import DateTrigger                                     # verified: manager.py:34
```

### Existing Class Signatures
```python
# packages/ai-parrot-server/src/parrot/scheduler/manager.py
class ScheduleType(Enum):                                   # line 71  — ONCE/DAILY/WEEKLY/MONTHLY/INTERVAL/CRON/CRONTAB
class SchedulerRunNowConflictError(Exception):              # line 83
def schedule(...) / _report_decorator_factory(...)          # lines 120-186 — set wrapper._schedule_config / wrapper._schedule_report_type
def _resolve_report_schedule(agent_id: str, report_type: str) -> Dict[str, Any]:  # line 294
def schedule_fingerprint(schedule: AgentSchedule) -> str:   # line 327 (moves to models.py)
class _SchedulerNotification(NotificationMixin):            # line 342
class AgentSchedulerManager:                                # line 349
    registered_name: str = "scheduler_manager"              # line 360
    def __init__(self, bot_manager: Any = None, **kwargs):  # line 362 — jobs.register_manager(self) line 377; job_defaults lines 391-400
    def _prepare_call_arguments(self, method, prompt, metadata, *, is_crew, method_name) -> Tuple[List, Dict]:  # line 402 (crew map lines 421-427)
    def _apply_prompt_signature(self, method, call_args, call_kwargs, prompt):  # line 441
    def define_listeners(self):                             # line 470
    def job_success(self, event: JobExecutionEvent):        # line 538 — treats jobs.SKIPPED as no-op
    async def _execute_agent_job(self, schedule_id, agent_name, prompt=None, method_name=None, metadata=None, *, is_crew=False, success_callback=None, send_result=None, callbacks=None):  # line 637 (get_crew un-awaited line 681; getattr line 691)
    async def _handle_job_success(self, schedule_id, agent_name, result, ...):  # line 761 (success_callback outside try — ledger 37f02d3c2474)
    async def _process_job_success(self, schedule_id, agent_name, result, ..., persist: bool = True):  # line 867
    def _format_result(self, result: Any) -> str:           # line 924 ; _LAST_RESULT_MAX_CHARS ~line 945
    async def _stamp_delivery_outcome(self, schedule_id: str, outcomes: List[Dict[str, Any]]) -> None:  # line 950 (writes metadata 970-972)
    async def _update_schedule_run(self, schedule_id, success=True, error=None, result=None):  # line 977 (naive now 1011; metadata 1022-1031)
    async def _on_coordination_unavailable(self, job_id: str, exc: BaseException) -> None:  # line 1038
    def _create_trigger(self, schedule_type: str, config: Dict[str, Any]):  # line 1064
    async def add_schedule(self, agent_name, schedule_type, schedule_config, prompt=None, method_name=None, created_by=None, created_email=None, metadata=None, agent_id=None, *, is_crew=False, send_result=None, success_callback=None, scheduler_type="default", callbacks=None) -> AgentSchedule:  # line 1119 (get_crew un-awaited line 1170; _bots line 1177)
    async def _execute_agent_task(self, job_id, agent_name, method, *, success_callback=None, send_result=None, callbacks=None):  # line 1242
    def register_bot_schedules(self, bot: Any) -> int:      # line 1290 (_auto_tasks dict line 1335)
    async def remove_schedule(self, schedule_id: str):      # line 1360
    async def load_schedules_from_db(self):                 # line 1378 (SELECT navigator.agents_scheduler line 1392)
    async def restart_scheduler(self):                      # line 1445
    def _execution_fields(self, schedule: AgentSchedule) -> Dict[str, Any]:  # line 1465 (metadata → call kwargs line 1473)
    def _job_kwargs_from_schedule(self, schedule: AgentSchedule) -> Dict[str, Any]:  # line 1478
    async def _run_db_schedule(self, schedule_id: str, fingerprint: Optional[str], *, run_now: bool = False) -> Any:  # line 1486
    async def _run_auto_task(self, job_id: str) -> Any:     # line 1538
    def _serialize_job(self, schedule: AgentSchedule) -> Dict[str, Any]:  # line 1562 (payload["source"]="db", ["jobstore"])
    def _serialize_auto_job(self, job: Any) -> Dict[str, Any]:  # line 1578 (partitions job.name on "." line 1585)
    async def list_jobs(self) -> List[Dict[str, Any]]:      # line 1608
    async def get_schedule(self, schedule_id: str) -> AgentSchedule:  # line 1637
    async def pause_schedule(self, schedule_id: str) -> AgentSchedule:  # line 1649
    async def update_schedule(self, schedule_id: str, updates: Dict[str, Any]) -> AgentSchedule:  # line 1661 (editable_fields 1664-1677)
    async def delete_schedule(self, schedule_id: str) -> None:  # line 1727
    async def run_schedule_now(self, schedule_id: str) -> AgentSchedule:  # line 1739 (DateTrigger(datetime.now()) line 1789)
    async def get_last_result(self, schedule_id: str) -> Dict[str, Any]:  # line 1802 (reads metadata 1826-1838)
    def _registered_jobstores(self) -> Set[str]:            # line 1840
    def _safe_jobstore(self, value: Any, *, strict: bool = False) -> str:  # line 1857
    def _build_jobstores(self, use_redis: bool = False) -> Dict[str, Any]:  # line 1875
    def _make_redis_jobstore(self) -> RedisJobStore:        # line 1892 (jobs_key="apscheduler.jobs", run_times_key="apscheduler.run_times", db=6)
    def _ensure_redis_jobstore(self) -> None:               # line 1906
    async def start_headless(self, *, dsn=None, use_redis=False, ..., coordination=None):  # line 1919 (jobstore attached BEFORE start)
    async def stop_headless(self, *, wait: bool = True) -> None:  # line 1977
    def setup(self, app: web.Application) -> web.Application:  # line 2005
    async def on_startup(self, app: web.Application, conn: Callable):  # line 2042 (start_headless(use_redis=True, register_listeners=True) line 2055; bot_manager fallback 2062)
    async def on_shutdown(self, app: web.Application, conn: Callable):  # line 2077
class SchedulerHandler(CorsViewMixin, web.View):            # line 2098 — DELETED by M5

# packages/ai-parrot-server/src/parrot/scheduler/models.py
class AgentSchedule(Model):                                 # line 7 — REPLACED by ServiceSchedule (M1)

# packages/ai-parrot-server/src/parrot/scheduler/jobs.py
class _Skipped / SKIPPED                                    # line 21
_MANAGERS: Dict[str, "AgentSchedulerManager"] = {}          # line 32
def register_manager(manager) -> None:                      # line 35
def unregister_manager(name: str) -> None:                  # line 43
def get_manager(name: str) -> "AgentSchedulerManager":      # line 48
async def run_db_schedule(manager_name: str, schedule_id: str, fingerprint: str) -> Any:  # line 60
async def run_db_schedule_now(manager_name: str, schedule_id: str) -> Any:  # line 65
async def run_auto_schedule(manager_name: str, job_id: str) -> Any:  # line 74

# packages/ai-parrot-server/src/parrot/scheduler/coordination.py
DEFAULT_PREFIX = "parrot:scheduler:"                        # line 24
DEFAULT_FIRE_TTL = 86400 ; DEFAULT_RUN_NOW_TTL = 3600       # lines 25-26
class FireCoordinationError(Exception):                     # line 29
class FireCoordinator(Protocol):                            # line 34 — claim(job_id, run_time) / try_acquire_running / release_running / close
class NullFireCoordinator:                                  # line 53
class RedisFireCoordinator:                                 # line 81 — __init__(client: aioredis.Redis, ..., prefix) line 84-99
def build_fire_coordinator(mode=None, *, use_redis=False) -> FireCoordinator:  # line 139 — mode = nav_config SCHEDULER_COORDINATION or ("redis" if use_redis else "none") line 151; TTLs lines 156-157; DEFAULT_REDIS_JOBSTORE_DB line 159
class CoordinatedAsyncIOExecutor(AsyncIOExecutor):          # line 168

# packages/ai-parrot-server/src/parrot/scheduler/sanitize.py
class SchedulerConfigError(ValueError):                     # line 104
def sanitize_redis_settings(host, port, db=DEFAULT_REDIS_JOBSTORE_DB) -> Dict[str, Any]:  # line 236
def normalize_jobstore_alias(...)                           # line 275 — REPLACED by normalize_backend (M4)
def normalize_schedule_type(value: Any) -> str:             # line 343
def sanitize_schedule_config(...)                           # line 502

# packages/ai-parrot-server/src/parrot/scheduler/functions/__init__.py
class BaseSchedulerCallback(NotificationMixin):             # line 17 — run(result, *, schedule_id, agent_name, **kwargs) line 97
class SendEmailReportCallback                               # line 104 (run line 108)
class CreateFileCallback                                    # line 151 (run line 155)
class SaveDataCallback                                      # line 165 (run line 169)
class SendNotifyReportCallback                              # line 211 (run line 215)
CALLBACK_REGISTRY: Dict[str, Type[BaseSchedulerCallback]]  # line 238
def list_supported_callbacks() -> List[Dict[str, Any]]:     # line 249
def build_scheduler_callback(definition: Dict[str, Any], logger=None) -> BaseSchedulerCallback:  # line 253

# packages/ai-parrot-server/src/parrot/handlers/scheduler.py
class SchedulerCatalogHelper(BaseHandler):                  # line 17 — list_schedule_types :21, list_scheduler_types(app) :25, list_callbacks :32
class SchedulerCallbacksHandler(BaseView):                  # line 36
class SchedulerJobsHandler(BaseView):                       # line 55 — post() line 93 (add_schedule(agent_name=...) line 100-112); patch() line 127
class SchedulerLastResultHandler(BaseView):                 # line 172 — route docstring "/api/v1/parrot/scheduler/schedules/{schedule_id}/last-result" line 173

# packages/ai-parrot-server/src/parrot/handlers/infographic_recipes.py
class RunInfographicRecipeCallback(BaseSchedulerCallback):  # line 323 — run(self, result, *, schedule_id, agent_name, **kwargs) line 348-349

# packages/ai-parrot-server/src/parrot/handlers/crew/saved_execution_service.py
class SchedulerUnavailableError(SavedExecutionError):       # line 66 (service-level; distinct from the new parrot.scheduler.base one)
class SavedExecutionService:                                # __init__(..., scheduler_manager: Any = None, ...) line 87; add_schedule(crew_name, ..., is_crew=True, ...) lines 285-296

# packages/ai-parrot-integrations/src/parrot/integrations/agentd/service.py
"SingleAgentManager" in __all__                             # line 58
class SingleAgentManager:                                   # line 240-275 — DELETED by M8
class AgentDaemon:                                          # line 277 — AgentSchedulerManager import 509; construct with bot_manager=single_agent_manager 525; register_bot_schedules 529
    async def _handle_schedules_add(self, session, params) -> Any:  # line 787 — add_schedule(**params)

# packages/ai-parrot-integrations/src/parrot/integrations/agentd/config.py
class SchedulerConfig(BaseModel):                           # line 115 — enabled: bool = True; dsn: str | None = None; redis: bool = False
# packages/ai-parrot-integrations/src/parrot/integrations/agentd/cli.py — "--redis/--no-redis" → use_redis (lines 54-55, 118-119)

# packages/ai-parrot-server/src/parrot/manager/manager.py
class BotManager:                                           # line 212
    self._bots: Dict[str, AbstractBot]                      # line 245 (private — never referenced by the new code)
    self.registry: AgentRegistry                            # line 254
    def get_bots(self) -> Dict[str, AbstractBot]:           # line 1257
    async def get_crew(self, identifier: str, as_new: bool = False, tenant: Optional[str] = None) -> Optional[Tuple[AgentCrew, CrewDefinition]]:  # line 3019 (ASYNC)
    # app["bot_manager"] = self                             # lines 2377, 2850

# packages/ai-parrot/src/parrot/registry/registry.py
    async def get_instance(self, *args, **kwargs) -> AbstractBot:  # line 85 (AgentRegistry)

# packages/ai-parrot/src/parrot/notifications/__init__.py
class NotificationMixin:                                    # line 83
    def notification_succeeded(result) -> bool              # line 304
    async def send_notification(self, recipients: Union[List[Actor], Actor, Channel, Chat, str, List[str]], provider: Union[str, NotificationProvider] = NotificationProvider.EMAIL, ...)  # line 442-446
    async def send_email(self, recipients=None, ...)        # line 1521-1524

# packages/ai-parrot/src/parrot/tools/reminder.py
async def deliver_reminder(...)                             # line 90 — module-level, picklable
class ReminderToolkit(AbstractToolkit):                     # line 158 — __init__(scheduler_manager) :179 stores self._sm; add_job(..., jobstore="redis") :294-300; get_jobs(jobstore="redis") :340; remove_job(..., jobstore="redis") :388

# packages/ai-parrot/src/parrot/scheduler/__init__.py
_SERVER_CLASSES = {"ScheduleType": ..., "AgentSchedulerManager": ("parrot.scheduler.manager", "AgentSchedulerManager"), ...}  # lines 12-23; __getattr__ via load_satellite_attr line 26-34

# packages/ai-parrot/src/parrot/_imports.py
def load_satellite_attr(name: str, module_path: str, *, install: str, attr: str | None = None) -> object:  # line 183
```

### Integration Points
| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `SchedulerManager.__init__` | `jobs.register_manager` | call | `jobs.py:35` |
| `SchedulerManager._make_redis_jobstore` | `RedisJobStore(jobs_key=..., run_times_key=..., **sanitize_redis_settings(...))` | constructor | `manager.py:1892-1904`, `sanitize.py:236` |
| `SchedulerManager.start_headless` | `build_fire_coordinator(..., prefix=...)` → `CoordinatedAsyncIOExecutor.set_coordinator` | call | `manager.py:1919-1977`, `coordination.py:139,180` |
| `AgentResolver.resolve` | `BotManager.get_bots()`, `AgentRegistry.get_instance()` | await | `manager/manager.py:1257`, `registry.py:85` |
| `CrewResolver.resolve` | `BotManager.get_crew()` | **await** | `manager/manager.py:3019` |
| `SchedulerManager._alert_disabled` | `NotificationMixin.send_notification(recipients=..., provider=...)` | await, wrapped | `notifications/__init__.py:442` |
| `SchedulerManager._process_job_success` | `build_scheduler_callback(definition)` → `callback(result, schedule_id=..., target_name=...)` | await | `functions/__init__.py:253`, `:97` |
| `RedisRunState` | `aioredis.Redis` (`WATCH`/`MULTI` pipeline) | await | `coordination.py:13,86` |
| `PostgresRunState` | `self._pool.acquire()` connection context | `async with` | `manager.py:999` |
| `SchedulerJobsHandler.post` | `SchedulerManager.add_schedule(...)` | await | `handlers/scheduler.py:100` |
| `AgentDaemon._boot_scheduler` | `AgentSchedulerManager.register_target(..., kind="agent")`, `register_bot_schedules`, `start_headless` | call | `agentd/service.py:509-529` |
| core lazy export | `load_satellite_attr(name, module_path, install=..., attr=...)` | `__getattr__` | `parrot/scheduler/__init__.py:26-34` |

### Configuration References
| Setting | Read via | Default | Used by |
|---|---|---|---|
| `SCHEDULER_COORDINATION` | `nav_config.get` | `none` (forced `redis` with a Redis jobstore) | M4 |
| `SCHEDULER_FIRE_LOCK_TTL` / `SCHEDULER_RUN_NOW_LOCK_TTL` | `nav_config.get` | 86400 / 3600 | M4 (existing) |
| `SCHEDULER_REDIS_DB` (new) | `nav_config.get` | 6 | jobstore, `RedisRunState`, coordinator |
| `SCHEDULER_MAX_CONSECUTIVE_FAILURES` (new) | `nav_config.get` | 3 | M2/M3 |
| `SCHEDULER_ALERT_RECIPIENTS` (new) | `nav_config.get`, comma-separated | unset → log only | M3 `_alert_disabled` |
| `CACHE_HOST` / `CACHE_PORT` | `parrot.conf` | — | `sanitize_redis_settings` (existing) |

### Does NOT Exist (Anti-Hallucination)
- ~~`parrot.scheduler.base`~~, ~~`SchedulerManager`~~, ~~`TargetRegistry`~~, ~~`TargetResolver`~~, ~~`RegistryResolver`~~, ~~`FireContext`~~, ~~`TargetMissingError`~~, ~~`SchedulerUnavailableError` in `parrot.scheduler`~~ (only the `SavedExecutionError` subclass at `saved_execution_service.py:66` exists), ~~`NotEditableError`~~ — all created by this feature.
- ~~`parrot.scheduler.runstate`~~, ~~`RunStateStore`~~, ~~`PostgresRunState`~~, ~~`RedisRunState`~~, ~~`MemoryRunState`~~, ~~`RunState`~~ — new.
- ~~`ServiceSchedule`~~, ~~`JobDefinition`~~, ~~`CodeJobRecord`~~, ~~`JOB_DEFINITION_VERSION`~~, ~~`utcnow()`~~, ~~`navigator.service_scheduler`~~ — new.
- ~~`AgentSchedulerManager.register_target()` / `.register_resolver()` / `.register_object_schedules()` / `._execute_job()` / `._run_redis_job()` / `._run_state_for()` / `._alert_disabled()` / `._code_jobs`~~ — not present today.
- ~~`jobs.run_redis_job` / `jobs.run_redis_job_now`~~, ~~`normalize_backend`~~, ~~`clean_misfire_grace_time`~~, ~~`clean_method_name`~~ — new.
- ~~`SCHEDULER_REDIS_DB`, `SCHEDULER_MAX_CONSECUTIVE_FAILURES`, `SCHEDULER_ALERT_RECIPIENTS`~~ — not read anywhere today.
- ~~`BotManager.get_bot(name)`~~ — not verified; use `get_bots()` (`manager/manager.py:1257`).
- ~~a synchronous `BotManager.get_crew()`~~ — it is `async` (`manager/manager.py:3019`).
- ~~`AgentSchedule.last_status` / `.last_error` / `.consecutive_failures` / `.tenant` / `.target_kind`~~ — today run state lives only in `metadata`.
- ~~`schedule_fingerprint` in `sanitize.py`~~ — it is in `manager.py:327` (moves to `models.py`).
- ~~a manager-level Redis-only job path~~ — only `ReminderToolkit` writes to the `redis` jobstore directly (`tools/reminder.py:294-300`); every manager trampoline except `run_auto_schedule` re-reads a Postgres row.
- ~~per-job `misfire_grace_time` in `add_schedule` / HTTP~~ — only `job_defaults` (`manager.py:398`).
- ~~`parrot:scheduler:*:runstate:*` keys~~ — only `apscheduler.jobs`, `apscheduler.run_times`, `parrot:scheduler:fire:*`, `parrot:scheduler:running:*` exist.
- ~~`/api/v1/scheduler/jobs`~~ — the mounted route is `/api/v1/parrot/scheduler/schedules` (`handlers/scheduler.py:173`); route registration lives in the host app, not in this package (unverified where — check before use).
- ~~admin UI scheduler pages~~, ~~tests for `SingleAgentManager`~~, ~~`fakeredis` declared in a `pyproject.toml`~~ (it is importable in the test env: `tests/test_suspended_store.py` uses it — guard with `pytest.importorskip("fakeredis")`).

### Edit Sites (Blueprint Anchors)

Verified against: `c9b5f4a44` (`dev`, 2026-10-08). `/sdd-task` MUST re-run `grep -c` for every row it uses.

| File | Action | Verbatim anchor line | Verified at | Occurrences |
|---|---|---|---|---|
| `packages/ai-parrot-server/src/parrot/scheduler/base.py` | CREATE | — | — | — |
| `packages/ai-parrot-server/src/parrot/scheduler/runstate.py` | CREATE | — | — | — |
| `packages/ai-parrot-server/src/parrot/scheduler/models.py` | MODIFY | `class AgentSchedule(Model):` | `models.py:7` | 1 |
| `packages/ai-parrot-server/src/parrot/scheduler/manager.py` | MODIFY | `def schedule_fingerprint(schedule: AgentSchedule) -> str:` | `manager.py:327` | 1 |
| `packages/ai-parrot-server/src/parrot/scheduler/manager.py` | MODIFY | `class AgentSchedulerManager:` | `manager.py:349` | 1 |
| `packages/ai-parrot-server/src/parrot/scheduler/manager.py` | MODIFY | `    def __init__(self, bot_manager: Any = None, **kwargs):` | `manager.py:362` | 1 |
| `packages/ai-parrot-server/src/parrot/scheduler/manager.py` | MODIFY | `    def _prepare_call_arguments(` | `manager.py:402` | 1 |
| `packages/ai-parrot-server/src/parrot/scheduler/manager.py` | MODIFY | `    async def _execute_agent_job(` | `manager.py:637` | 1 |
| `packages/ai-parrot-server/src/parrot/scheduler/manager.py` | MODIFY | `    async def _update_schedule_run(` | `manager.py:977` | 1 |
| `packages/ai-parrot-server/src/parrot/scheduler/manager.py` | MODIFY | `    async def add_schedule(` | `manager.py:1119` | 1 |
| `packages/ai-parrot-server/src/parrot/scheduler/manager.py` | MODIFY | `    def register_bot_schedules(self, bot: Any) -> int:` | `manager.py:1290` | 1 |
| `packages/ai-parrot-server/src/parrot/scheduler/manager.py` | MODIFY | `    async def load_schedules_from_db(self):` | `manager.py:1378` | 1 |
| `packages/ai-parrot-server/src/parrot/scheduler/manager.py` | MODIFY | `    def _execution_fields(self, schedule: AgentSchedule) -> Dict[str, Any]:` | `manager.py:1465` | 1 |
| `packages/ai-parrot-server/src/parrot/scheduler/manager.py` | MODIFY | `    async def _run_db_schedule(` | `manager.py:1486` | 1 |
| `packages/ai-parrot-server/src/parrot/scheduler/manager.py` | MODIFY | `    def _make_redis_jobstore(self) -> RedisJobStore:` | `manager.py:1892` | 1 |
| `packages/ai-parrot-server/src/parrot/scheduler/manager.py` | MODIFY | `    async def start_headless(` | `manager.py:1919` | 1 |
| `packages/ai-parrot-server/src/parrot/scheduler/manager.py` | MODIFY | `    async def on_startup(self, app: web.Application, conn: Callable):` | `manager.py:2042` | 1 |
| `packages/ai-parrot-server/src/parrot/scheduler/manager.py` | DELETE block | `class SchedulerHandler(CorsViewMixin, web.View):` | `manager.py:2098` | 1 |
| `packages/ai-parrot-server/src/parrot/scheduler/jobs.py` | MODIFY | `_MANAGERS: Dict[str, "AgentSchedulerManager"] = {}` | `jobs.py:32` | 1 |
| `packages/ai-parrot-server/src/parrot/scheduler/jobs.py` | MODIFY | `async def run_auto_schedule(manager_name: str, job_id: str) -> Any:` | `jobs.py:74` | 1 |
| `packages/ai-parrot-server/src/parrot/scheduler/coordination.py` | MODIFY | `DEFAULT_PREFIX = "parrot:scheduler:"` | `coordination.py:24` | 1 |
| `packages/ai-parrot-server/src/parrot/scheduler/coordination.py` | MODIFY | `def build_fire_coordinator(mode: Optional[str] = None, *, use_redis: bool = False) -> FireCoordinator:` | `coordination.py:139` | 1 |
| `packages/ai-parrot-server/src/parrot/scheduler/sanitize.py` | MODIFY | `def normalize_jobstore_alias(` | `sanitize.py:275` | 1 |
| `packages/ai-parrot-server/src/parrot/scheduler/sanitize.py` | MODIFY | `def sanitize_schedule_config(` | `sanitize.py:502` | 1 |
| `packages/ai-parrot-server/src/parrot/scheduler/functions/__init__.py` | MODIFY | `    async def run(self, result: Any, *, schedule_id: str, agent_name: str, **kwargs) -> Dict[str, Any]:` | `functions/__init__.py:97,108,155,169,215` | **5** — one per class: `BaseSchedulerCallback` (:17), `SendEmailReportCallback` (:104), `CreateFileCallback` (:151), `SaveDataCallback` (:165), `SendNotifyReportCallback` (:211) |
| `packages/ai-parrot-server/src/parrot/handlers/infographic_recipes.py` | MODIFY | `    async def run(` (inside `class RunInfographicRecipeCallback`, :323) | `infographic_recipes.py:348` | 1 |
| `packages/ai-parrot-server/src/parrot/handlers/scheduler.py` | MODIFY | `    def list_scheduler_types(app: web.Application) -> list[str]:` | `handlers/scheduler.py:25` | 1 |
| `packages/ai-parrot-server/src/parrot/handlers/scheduler.py` | MODIFY | `                agent_name=data["agent_name"],` | `handlers/scheduler.py:101` | 1 |
| `packages/ai-parrot-server/src/parrot/handlers/crew/saved_execution_service.py` | MODIFY | `            is_crew=True,` | `saved_execution_service.py:294` | 1 |
| `packages/ai-parrot-integrations/src/parrot/integrations/agentd/service.py` | DELETE block | `class SingleAgentManager:` | `agentd/service.py:240` | 1 |
| `packages/ai-parrot-integrations/src/parrot/integrations/agentd/service.py` | MODIFY | `        manager = AgentSchedulerManager(bot_manager=single_agent_manager)` | `agentd/service.py:525` | 1 |
| `packages/ai-parrot-integrations/src/parrot/integrations/agentd/service.py` | MODIFY | `    async def _handle_schedules_add(self, session: Session, params: dict[str, Any]) -> Any:` | `agentd/service.py:787` | 1 |
| `packages/ai-parrot-integrations/src/parrot/integrations/agentd/config.py` | MODIFY | `class SchedulerConfig(BaseModel):` | `agentd/config.py:115` | 1 |
| `packages/ai-parrot/src/parrot/scheduler/__init__.py` | MODIFY | `    "AgentSchedulerManager": ("parrot.scheduler.manager", "AgentSchedulerManager"),` | `scheduler/__init__.py:17` | 1 |
| `packages/ai-parrot-server/src/parrot/server/version.py` | MODIFY | `__version__ = "1.2.0"` | `version.py:3` | 1 |
| `docs/scheduler/multi-worker.md` | MODIFY | `## Redis jobstore is not coordination` | `multi-worker.md:35` | 1 |
| `packages/ai-parrot/tests/test_schedules.py` | MODIFY | `async def test_execute_crew_job_uses_registered_crew(monkeypatch):` | `test_schedules.py:53` | 1 |
| `packages/ai-parrot-server/tests/scheduler/test_base_parity.py`, `test_runstate.py`, `test_redis_backend.py`, `test_resolvers.py`, `test_ledger_regressions.py` | CREATE | — | — | — |

---

## 7. Implementation Notes & Constraints

### Patterns to Follow
- Async-first everywhere; `redis.asyncio` for run state and coordination (never sync redis in the event loop); the sync `RedisJobStore` client is APScheduler's own and stays as today.
- `nav_config.get()` for every `SCHEDULER_*` setting, read once in `SchedulerManager.__init__`/`start_headless` (pattern: `coordination.py:149-157`).
- Picklable-trampoline rule from FEAT-631: APScheduler `func` is always a module-level function in `jobs.py`; kwargs are JSON-safe data (strings, ints, dicts) — never bound methods, callables or model instances.
- Keep the fire-time row re-check / fingerprint reschedule for `db` jobs exactly as `_run_db_schedule` does today; for `redis` jobs the definition in the job kwargs *is* the source of truth, so no re-check is needed.
- `_LAST_RESULT_MAX_CHARS` truncation and `_format_result` stay in the base.
- Pydantic v2 for `JobDefinition`/`RunState` (`extra="forbid"`); dataclasses for `FireContext`/`CodeJobRecord`.
- Google docstrings, `self.logger`, 120 columns; `ruff check` with TID251.
- Tests run with `PYTHONPATH=packages/ai-parrot-server/src:packages/ai-parrot/src:packages/ai-parrot-integrations/src` from the worktree; `pytest.importorskip("apscheduler")` / `("fakeredis")` guards as in `test_schedules.py:7`.

### Known Risks / Gotchas
- **Extraction seam**: `manager.py` is 2,219 lines; M3 must move code *verbatim* first (behaviour-preserving), then apply the §2 changes, so the 13 existing suites can be rewritten incrementally.
- **Un-awaited `get_crew()`** hid behind a sync stub; every new test double for `BotManager` must be `async` (AC4).
- **`jobs.SKIPPED` vs failure**: `job_success` treats `SKIPPED` as a no-op; `TargetMissingError` must propagate as an exception so the error listener stamps it (S4).
- **Redis key rename is a hard-cut**: jobs pickled under `apscheduler.jobs` (including armed `ReminderToolkit` reminders) are not visible after upgrade; the migration note says so and tells operators to re-arm.
- **Shared `RedisJobStore` across workers**: `next_run_time` updates are last-writer-wins on equal values; execution dedupe relies on the forced `redis` coordinator. Alert dedupe relies on `crossed_threshold` being true for one caller only (single-statement UPDATE / WATCH-MULTI).
- **`fakeredis` and Lua**: the Redis transition deliberately uses `WATCH/MULTI` rather than `EVAL` so `fakeredis` can exercise it without `lupa`.
- **Signature injection through decorators**: `@schedule` wraps with `functools.wraps`; inspect `inspect.unwrap(method)`; a wrapper without `__wrapped__` is treated as "accepts nothing extra".
- **`misfire_grace_time=None` + `coalesce=True`** on APScheduler 3.11.2 means "run the latest missed fire once" — tests must assert one run, not N.
- **Alert recipients**: `send_result` may be an email config dict (`manager.py:803-866`); extract its recipients the same way `_send_result_email` does; never raise from `_alert_disabled`.
- **Resolver outages**: a transient `registry.get_instance` failure counts as `target_missing`; with threshold 3 an outage shorter than three ticks never disables — document the tradeoff next to `SCHEDULER_MAX_CONSECUTIVE_FAILURES`.
- **Route registration** of `handlers/scheduler.py` lives in the host application (not located in this package); do not add a router here.
- **`tenant`** is persisted but not enforced (§8 Q1); handlers must not pretend otherwise.

### External Dependencies
| Package | Version | Reason |
|---|---|---|
| `apscheduler` | `==3.11.2` (extra `scheduler`, `packages/ai-parrot-server/pyproject.toml:42-43`) | triggers, `RedisJobStore`, `AsyncIOScheduler` — unchanged |
| `redis` (`redis.asyncio`) | existing | `RedisRunState`, `RedisFireCoordinator` |
| `asyncdb` | existing | `ServiceSchedule` model, pool |
| `navigator` / `navconfig` | existing | `PostgresPool`, `nav_config` |
| `pydantic` | v2 (existing) | `JobDefinition`, `RunState` |
| `fakeredis` | test env only (already imported by `tests/test_suspended_store.py`) | Redis backend tests |

---

## 8. Open Questions

- [ ] Q1. Tenant scoping / authorization on list, read, update, pause, delete and run-now (design research S11): the schema gains `tenant` now; who may act on a schedule, and whether `created_by` or `tenant` is the scope key, is a cross-cutting authz decision. — *Owner: Jesus Lara*
- [x] Flow type and base branch? — *Resolved in brainstorm*: `feature` on `dev`.
- [x] Where does the base live? — *Resolved in brainstorm*: ai-parrot-server, `parrot/scheduler/base.py`; core only lazy-exports.
- [x] Postgres migration scope? — *Resolved in brainstorm*: hard-cut, new table `navigator.service_scheduler`, DDL documented, no row-copy script, old table left for the operator.
- [x] Does the hard-cut reach the Python/HTTP/RPC API? — *Resolved in brainstorm*: yes, total; `agent_name`/`agent_id`/`is_crew` removed everywhere, all in-repo callers migrated in the same PR, no aliases.
- [x] Name of the registry-resolved kind? — *Resolved in brainstorm*: `service` (`agent` | `crew` | `service`).
- [x] How is fire context delivered to targets? — *Resolved in brainstorm*: signature injection of `fire_id` / `scheduled_at` only when declared or `**kwargs`.
- [x] Missing-target policy? — *Resolved in brainstorm*: disable after N consecutive misses (default 3, env-configurable), WARNING per tick, notification on disable.
- [x] Generalise `@schedule` scanning? — *Resolved in brainstorm*: yes, `register_object_schedules(obj, name)` in the base; `register_bot_schedules(bot)` wraps it.
- [x] How do Redis-only jobs fit? — *Resolved in brainstorm*: one `backend` axis (`db | redis | code`); `redis` jobs have no Postgres row, their definition is pickled in the `RedisJobStore`; the `scheduler_type` column/field is removed.
- [x] Missed-fire policy on restart? — *Resolved in brainstorm*: `redis` jobs default to `misfire_grace_time=None` + `coalesce=True` (always one catch-up run), per-job override in seconds via the API; `db` jobs keep 300 s.
- [x] Run state for Redis-only jobs? — *Resolved in brainstorm*: Redis hash `parrot:scheduler:runstate:{job_id}` behind a `RunStateStore` abstraction (pg | redis | memory). *(Spec refinement: the hash is namespaced by `registered_name`, per the key-namespacing resolution below.)*
- [x] API surface for Redis jobs? — *Resolved in brainstorm*: same `add_schedule` and same `POST /api/v1/scheduler/jobs` with a `backend` field; all CRUD/run-now/last-result endpoints work for every backend. *(Spec correction, design research S10: the mounted route is `/api/v1/parrot/scheduler/schedules`.)*
- [x] Namespace the Redis jobstore keys by `registered_name`? — *Resolved in brainstorm*: yes — `parrot:scheduler:{registered_name}:jobs` / `:run_times`; the global `apscheduler.*` keys are dropped (hard-cut). *(Extended to the coordinator prefix, S3.)*
- [x] `backend='redis'` with coordination `none` on multi-worker? — *Resolved in brainstorm*: coordination is activated automatically — a Redis jobstore always implies the `redis` fire coordinator; an explicit `SCHEDULER_COORDINATION=none` is overridden with a WARNING.
- [x] Expose the Redis jobstore db? — *Resolved in brainstorm*: yes — `SCHEDULER_REDIS_DB`, default 6, shared by jobstore, run-state hashes and coordinator.
- [x] Do `error` runs count toward auto-disable? — *Resolved in brainstorm*: yes — `error` and `target_missing` share one counter and one threshold; any success resets it; `lock_unavailable` does not count.
- [x] agentd RPC `schedules.add` payload? — *Resolved in brainstorm*: hard-cut — clients send `target_kind` / `target_name` / `backend`; `agent_name` is an unknown-parameter error.
- [x] Open ledger issues on `manager.py`? — *Resolved in brainstorm*: close all three inside the feature (`aa813ccc1927` via run_time-derived `fire_id`, `37f02d3c2474` via `_execute_job` wrapping `success_callback`, `7b5d75d2c81d` via a typed `SchedulerUnavailableError` → 503), each with a regression test.
- [x] FEAT-430 proposal? — *Resolved in brainstorm*: add a dependency note pointing at this brainstorm now; rebase its table/field names when FEAT-430 goes through `/sdd-spec`. *(Note added in commit `fbc12fb54`.)*
- [x] Old table references in `examples/database/agents_scheduler_market_analysis.sql` and `docs/report-builder/inventory/*`? — *Resolved in brainstorm*: update both to `navigator.service_scheduler` and the new field names.
- [x] Un-awaited `BotManager.get_crew()` (manager.py:681, :1170)? — *Resolved in brainstorm*: fixed inside the feature by `CrewResolver` (which awaits it); no prior hotfix to `main`. Until the feature merges, crew schedules via `SavedExecutionService` stay broken on `dev`.
- [x] Auto-disable threshold setting? — *Resolved in brainstorm*: `SCHEDULER_MAX_CONSECUTIVE_FAILURES`, default 3, read with `nav_config.get()` next to `SCHEDULER_COORDINATION` (no `PARROT_` prefix, not a `parrot.conf` constant).

---

## 9. Design Research Cross-Check

> Independent design opinion from the `codex` seat over the **accepted exploration doc** (never over this spec).
> Model: `gpt-5.6-luna` (codex-cli 0.159.2, reasoning high, 2026-10-08 15:44:30Z → 15:47:24Z, exit 0) · Status: completed
> · Transcript: `sdd/state/FEAT-644/design_research/`
> All 19 cited `affected_paths` passed repository containment and `test -e`.

| # | Suggestion (kind) | Disposition | Reason | Landed in |
|---|---|---|---|---|
| S1 | Make target resolution explicitly asynchronous; registry manager-scoped (architecture) | CONFIRM | `BotManager.get_crew()` and `AgentRegistry.get_instance()` are `async`; brainstorm's `resolve()` was sync. `TargetRegistry` is an instance attribute. | §2 New Public Interfaces, §3 M3 |
| S2 | Specify CRUD semantics per backend (api) | CONFIRM | All CRUD/run-now/last-result assume a Postgres row today (`manager.py:1637-1838`); matrix with explicit 409s added. | §2 CRUD matrix, §3 M3, AC10 |
| S3 | Namespace coordinator keys too; keep default name stable; direct Redis consumers (risk) | CONFIRM | `DEFAULT_PREFIX` has no manager name; `ReminderToolkit` is the existing Redis-only path and keeps working through the default `registered_name`. | §2 Overview, §3 M4, §7 |
| S4 | Atomic failure-count state machine; `SKIPPED` ≠ success (architecture) | CONFIRM | `_update_schedule_run` is read-modify-write; multi-worker is normal. Single-statement UPDATE / WATCH-MULTI; `TargetMissingError` raised. | §2 Data Models, §3 M2, AC11-12 |
| S5 | Restrict callable methods for service targets; reject private names (risk) | CONFIRM | unfiltered `getattr` at `manager.py:689-693`; `methods` allowlist + `_` rejection for every kind. Authz itself → S11. | §3 M3/M4, AC3 |
| S6 | Define the auto-disable alert destination and delivery contract (api) | CONFIRM | `send_notification` needs recipients; order `send_result` → `SCHEDULER_ALERT_RECIPIENTS` → log; never raises; single sender. | §3 M3, §6 Configuration, §7 |
| S7 | Freeze run-state schema and one UTC rule (architecture) | CONFIRM | every stamp is naive today; `utcnow()` + fixed DDL/`RunState`. | §2 Data Models, AC7 |
| S8 | Versioned, data-only Redis job definitions (risk) | CONFIRM | FEAT-631 precedent; `definition_version`, JSON validation, `success_callback` rejected, `incompatible` status. | §3 M4, §7, AC8 |
| S9 | First-class record for code jobs (api) | CONFIRM | `_serialize_auto_job` parses `job.name`; `CodeJobRecord`; external jobs as `source='external'`. | §2 Data Models, §3 M3, AC10 |
| S10 | Resolve the duplicate legacy HTTP surface; fix route name; keyword callers (api) | CONFIRM | mounted route is `/api/v1/parrot/scheduler/schedules`; legacy `SchedulerHandler` deleted; `SavedExecutionService` keywords. | §2 Integration Points, §3 M5/M7, AC15 |
| S11 | Tenant and authorization semantics (risk) | ESCALATE | correct concern; `tenant` column + `JobDefinition.tenant` added now, enforcement is the human's call. | §8 Q1 |
| S12 | Backend-parity and restart test matrix (testing) | CONFIRM | existing suites are DB-centred; parity matrix, restart, key-collision and threshold-race tests defined. | §4 |

Summary: **11** confirmed · **0** rejected · **1** escalated.

---

## Worktree Strategy

- **Isolation**: one feature worktree `feat-FEAT-644-scheduler-manager-base` (per-spec); the `sdd-coder` engine gives each task its own sub-worktree inside it.
- **Module dependency graph** (evidence in parentheses):
  - M2 → M1 (imports `RunState`, `FireContext`, `utcnow`).
  - M3 → M1, M2, M4 (imports `JobDefinition`, `RunStateStore`, `jobs.run_redis_job`, `normalize_backend`, `build_fire_coordinator(prefix=)`).
  - M4 → M1 (`jobs.run_redis_job` signature carries a `JobDefinition` dict; `schedule_fingerprint` moved to `models.py`).
  - M5 → M3 (subclass), M1.
  - M6 → M3 (`_job_context` keys) — but the rename itself only needs the new keyword, so M6 can start after M1.
  - M7 → M3, M5 (`SchedulerManager.add_schedule` signature, error types).
  - M8 → M5 (`AgentSchedulerManager.register_target`).
  - M9 → names from M1–M8 (docs/exports/version can be drafted in parallel and finalized last).
  - M10 → all; the parity/runstate tests (M1/M2/M4 scope) can run as soon as those modules land.
  - No edge between M2 and M4, M6 and M7, M8 and M9: expected to run concurrently.
- **Shared files** (tasks serialized): `packages/ai-parrot-server/src/parrot/scheduler/manager.py` (M1 moves `schedule_fingerprint` out; M3 moves the base out; M5 rewrites what stays), `packages/ai-parrot-server/src/parrot/scheduler/jobs.py` (M3/M4), `packages/ai-parrot-server/tests/scheduler/*` (M10 vs rewrites per module).
- **Exclusive resources**: none (no extension rebuild, no lockfile change, no automatic migration — the DDL is documentation).
- **Cross-feature dependencies**: none to merge first. FEAT-430 (`dashboard-scheduled-notifications-canvas`, proposal in review) depends on this spec's table and must be rebased when specced.

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-10-08 | Jesus Lara (Claude) | Initial draft from the accepted brainstorm + codex design research (11 confirmed, 1 escalated) |
