<!--
  sdd/templates/design_research.prompt.md — neutral design-research brief (FEAT-545).
  Rendered by /sdd-spec section 3b and piped to `codex exec ... --output-schema
  design_research.schema.json`.
  FORBIDDEN INPUTS: never paste the spec draft, the spec author's reasoning, a preferred
  conclusion, or any text written by the model that will author the spec. The brief carries
  ONLY the accepted exploration document (brainstorm/proposal) and verified code anchors.
  Placeholders (double-curly-brace tokens, deliberately NOT written with literal braces in
  this comment — a renderer that does a naive whole-document string replace must not also
  rewrite this sentence): problem_statement, constraints_and_goals,
  recommended_option_or_scope, code_context_paths, open_questions, question.
-->
# Independent design review — read-only

You are an independent design reviewer for **ai-parrot**, an async-first Python
framework for AI agents (aiohttp, Pydantic v2, `uv` workspace under `packages/`).
You have read-only access to the repository in your working directory.

## Rules
1. Read the code you cite. Every `affected_paths` entry must be a repo-relative
   path you actually opened; suggestions with unverifiable paths are discarded.
2. Judge the design intent below against what exists in the repository: what is
   missing, what is risky, what would be simpler, what the codebase already
   provides that the intent re-invents.
3. Do not restate the intent, do not praise it, do not write code. Propose at
   most 12 concrete, falsifiable suggestions, each tagged with a kind
   (`architecture` | `api` | `testing` | `risk` | `alternative`), a risk level and
   your confidence.
4. Output exactly ONE JSON object conforming to the schema you were given — no
   markdown fences, no prose before or after.

## Accepted design intent (verbatim from the exploration document)

### Problem statement
`AgentSchedulerManager` (`packages/ai-parrot-server/src/parrot/scheduler/manager.py`, 2,219 lines)
is the only scheduler in AI-Parrot, and it is hard-wired to `BotManager`:

- `add_schedule()` requires `agent_name` and validates the target through the **private**
  `bot_manager._bots` dict plus `bot_manager.registry.get_instance()` (`manager.py:1168-1184`).
- `_execute_agent_job()` resolves the target the same way at fire time (`manager.py:681-688`).
- `on_startup()` falls back to `app["bot_manager"]` and scans its bots (`manager.py:2062-2066`).

Everything else in the class — APScheduler wiring, jobstores, Redis fire coordination (FEAT-631),
DB persistence, `run_schedule_now`, `start_headless`/`stop_headless`, event listeners, delivery
callbacks (FEAT-635), `_update_schedule_run` — is target-agnostic. Roughly 90% of the class is
reusable by any job, yet nobody can reuse it without faking a `BotManager`.

**Who is affected:**

- **External packages** (issue #1572 was filed while integrating `reportbuilder`): to schedule a
  non-LLM job they must register a fake bot, and `BotManagement.get` then returns 400 for it.
- **agentd** inside this repo already carries the same workaround:
  `SingleAgentManager` in `packages/ai-parrot-integrations/src/parrot/integrations/agentd/service.py:240`
  is a stand-in that exposes exactly `_bots`, `registry.get_instance()` and `get_crew()` so the
  scheduler will accept a single agent.
- **Operators**: a schedule whose target is missing logs an ERROR with a traceback on every tick
  and is never disabled.

**Run state is mixed into the call arguments (confirmed in code):**

- `_execution_fields()` passes `dict(schedule.metadata)` as the `metadata` kwarg
  (`manager.py:1473`), and `_execute_agent_job` → `_prepare_call_arguments` turns that dict into
  the **call kwargs** of the target method (`manager.py:412`).
- `_update_schedule_run()` writes `last_error`, `last_error_time`, `last_status`, `last_result`,
  `last_result_time` into that same `metadata` dict (`manager.py:1022-1031`), and
  `_stamp_delivery_outcome()` adds `last_callbacks`, `last_delivery_status`, `last_delivery_time`
  (`manager.py:970-972`). On the next tick all of them are replayed as kwargs to the target.
- `last_error` is never cleared after a later success (the success branch only sets
  `last_result*`/`last_status`).
- Every timestamp is a naive `datetime.now()` — including `last_run` (`manager.py:1011`), so the
  issue understates it: nothing is timezone-aware, and the `TIMESTAMP WITH TIME ZONE` columns
  take whatever the session timezone is.

**Latent crew bug found during research:** `BotManager.get_crew()` is `async`
(`manager/manager.py:3019`), but both scheduler call sites invoke it without `await`
(`manager.py:681`, `manager.py:1170`). Against a real `BotManager` the walrus test sees a coroutine
object (always truthy) and `crew_entry[0]` / `_, crew_def = crew_entry` raise `TypeError`; only
agentd's `SingleAgentManager.get_crew()` (sync, returns `None`) and test doubles work. The new
`CrewResolver` fixes this by construction.

**Redis persistence is redundant today, and there is no Redis-only path.** `scheduler_type='redis'`
only chooses which APScheduler jobstore holds the job (`_safe_jobstore`, `manager.py:1857`); the
schedule row still lives in Postgres and `load_schedules_from_db()` re-adds every enabled row with
`replace_existing=True` on each start (`manager.py:1378`). A job cannot exist without a Postgres row,
so an API consumer that only has Redis (or does not want a DB row per job) has nothing to call. The
global `misfire_grace_time=300` (`manager.py:398`) also means that a restart longer than five
minutes silently drops the missed fire of every job, whatever its jobstore.

**Why now:** the table `navigator.agents_scheduler` is barely used in deployments, so a hard-cut
(new table, new columns, no row migration) is cheap today and gets more expensive with every
schedule written. FEAT-631 and FEAT-635 both landed in the last week and are closed, so the
scheduler is quiescent — no in-flight spec touches `manager.py`.

### Constraints and goals
Decisions taken during discovery (Rounds 0–2):

- **Flow**: `type: feature`, `base_branch: dev`.
- **Package**: the base lives in **ai-parrot-server** (`parrot/scheduler/base.py`). APScheduler
  (`apscheduler==3.11.2`, extra `scheduler`), `asyncdb` and `navigator` are already server
  dependencies; core only gains a lazy export in `parrot/scheduler/__init__.py::_SERVER_CLASSES`.
- **Hard-cut in Postgres**: new table `navigator.service_scheduler` with a new model; `CREATE TABLE`
  documented in the model docstring as today; **no row-copy script**; the old
  `navigator.agents_scheduler` is left untouched for the operator to drop.
- **Hard-cut in the API**: `add_schedule(target_kind, target_name, …)` on the base; `agent_name`,
  `agent_id` and `is_crew` disappear from the Python API, the HTTP payloads and the agentd RPC.
  All in-repo callers are migrated in the same PR. No compatibility shims, no deprecated aliases.
- **`target_kind` vocabulary**: `agent` | `crew` | `service`. `agent`/`crew` are resolved by
  `AgentSchedulerManager` via `BotManager`; `service` is resolved by the base against
  `TargetRegistry.register_target(name, obj)` and invoked as `obj.<method_name>(…)`.
- **Run state in dedicated columns**: `last_status`, `last_error`, `last_error_at`, `last_result`,
  `last_result_at` (plus delivery outcome columns, see Feature Description), all `TIMESTAMPTZ` and
  written as `datetime.now(timezone.utc)`. `metadata` is **only** call kwargs again.
  `last_error` is cleared on success.
- **Fire context by signature injection**: `fire_id` and `scheduled_at` are passed to the target
  only when its signature declares them or accepts `**kwargs`. `agent.chat(prompt)` and legacy
  methods keep working unchanged.
- **Auto-disable policy**: `last_status = 'target_missing'` or `'error'`, one shared
  `consecutive_failures` counter; after `SCHEDULER_MAX_CONSECUTIVE_FAILURES` consecutive failures
  of **either** kind (default 3, read with `nav_config.get()` like `SCHEDULER_COORDINATION`) the
  schedule is set `enabled = false`, the APScheduler job removed (or paused, for `redis`), and an
  alert is sent through `NotificationMixin`. A missing target logs one WARNING per tick, no
  traceback; a raising target keeps today's ERROR with traceback.
- **`@schedule` scanning generalised**: `SchedulerManager.register_object_schedules(obj, name)`
  scans any object; `AgentSchedulerManager.register_bot_schedules(bot)` wraps it and adds the
  `chatbot_id` / report env-var resolution.
- **Three job backends, one axis** (Round 3): `backend = 'db' | 'redis' | 'code'`.
  `db` → row in `service_scheduler` + `MemoryJobStore`, reloaded from Postgres at start.
  `redis` → **no Postgres row**; the full definition (target_kind, target_name, target_id,
  method_name, prompt, metadata, callbacks, send_result, trigger spec, misfire policy) is pickled
  into the `RedisJobStore` job and APScheduler reloads it by itself at start.
  `code` → `@schedule`-decorated methods, process-local, re-registered from code at start.
  The `scheduler_type` column and the `scheduler_type` API field disappear (hard-cut).
- **Missed fires** (Round 3): `backend='redis'` jobs default to `misfire_grace_time=None` (run any
  missed fire) with `coalesce=True` (one catch-up run however long the outage); the API accepts a
  per-job `misfire_grace_time` in seconds to bound it. `db` jobs keep the current 300 s default.
- **Run state for Redis jobs** (Round 3): a Redis hash `parrot:scheduler:runstate:{job_id}` written
  by the base; `get_last_result` / `list_jobs` / auto-disable work identically for `db` and `redis`
  through a `RunStateStore` abstraction (`pg` columns | `redis` hash | `memory` for `code` jobs).
- **Redis keys and settings** (Round 4): jobstore keys are namespaced per manager —
  `parrot:scheduler:{registered_name}:jobs` / `:run_times` — instead of the global
  `apscheduler.jobs` / `apscheduler.run_times`; the Redis logical db comes from
  `SCHEDULER_REDIS_DB` (default 6) and is shared by the jobstore, the run-state hashes and the fire
  coordinator.
- **Coordination follows the jobstore** (Round 4): when a Redis jobstore is attached, the fire
  coordinator is `redis` — always. `SCHEDULER_COORDINATION=none` is honoured only when no Redis
  jobstore is attached; otherwise it logs a WARNING and is overridden. (Today's
  `build_fire_coordinator` already falls back to `"redis" if use_redis` when the env var is unset,
  `coordination.py:151`; the change makes that the rule rather than the fallback.)
- **agentd RPC is hard-cut too** (Round 4): `schedules.add` keeps forwarding `**params`; clients
  send `target_kind` / `target_name` / `backend`; `agent_name` is an unknown-parameter RPC error.
- **Scope additions** (Round 4): the three open ledger issues on `manager.py` are closed inside
  this feature with their own tests (`aa813ccc1927`, `7b5d75d2c81d`, `37f02d3c2474`); the
  un-awaited `BotManager.get_crew()` bug is fixed by `CrewResolver` inside the feature, not as a
  prior hotfix; `examples/database/agents_scheduler_market_analysis.sql` and
  `docs/report-builder/inventory/*` are updated to the new table.
- **One API surface** (Round 3): the same `add_schedule(...)` and the same
  `POST /api/v1/scheduler/jobs` take a `backend` field; `list_jobs`, `pause`, `update`, `delete`,
  `run_now` and `last-result` behave the same for every backend. `schedule_id` is the APScheduler
  job id (a generated UUID) for `redis` jobs.
- Existing invariants that must survive: picklable `jobs.py` trampolines keyed by
  `registered_name` (FEAT-631), fire-time row re-check + fingerprint reschedule, Redis fire
  coordination, delivery-outcome persistence (FEAT-635), `run_schedule_now` semantics
  (FEAT-467), `start_headless`/`stop_headless` (TASK-2209), sanitisation of
  `schedule_type`/`schedule_config`/jobstore alias (`sanitize.py`).
- Conventions: aiohttp only, `asyncdb` models, `self.logger`, no LangChain, Google docstrings,
  120 columns; tests under `packages/ai-parrot-server/tests/scheduler/`.

---

### Recommended option / probable scope
**Option A** is recommended because:

- It is the only option that satisfies all discovery decisions at once: a real base class
  (`SchedulerManager`) that external packages instantiate directly, a kind-keyed resolver so the
  issue's `register_target()` is first-class rather than bolted on, and `AgentSchedulerManager`
  surviving as a thin subclass so every in-repo import path keeps working.
- Option B is architecturally slightly purer, but under the hard-cut rule it forces a repo-wide
  rename of `AgentSchedulerManager` for no functional gain; the subclass in A costs ~300 lines
  and buys import stability for `jira_specialist.py`, `reminder.py`, `saved_execution_service.py`,
  agentd and two docs pages. A also keeps the "auto-wire from `app['bot_manager']`" behaviour where
  it is today.
- Only A and B can carry the `backend` axis; C is structurally unable to run a job without a
  Postgres row.
- Option C is cheap but preserves the two root causes (private `BotManager` access and run state as
  JSON convention). Given the table is barely populated, paying the migration cost now is the whole
  point of the hard-cut.

**What we trade off:** one large, breaking PR instead of a series of small ones, and a required
call-site update for every external consumer of `add_schedule`. That is acceptable because the
API surface is small (one method plus three HTTP/RPC payload fields), the table is nearly empty,
and the server package is already at a major version where breaking changes are expected.

---

Extract everything target-agnostic from `manager.py` into `parrot/scheduler/base.py` as
`SchedulerManager`. The base owns APScheduler, jobstores, coordination, persistence, listeners,
run-now, headless lifecycle, delivery callbacks, run-state stamping, the missing-target policy and
`register_object_schedules()`. Target resolution is delegated to a small per-kind strategy table:

- `TargetResolver` protocol: `resolve(name) -> Any | None` and
  `build_call(target, schedule, fire) -> (args, kwargs)`.
- The base installs one resolver: `service` → `RegistryResolver` backed by `TargetRegistry`
  (`register_target(name, obj, kind="service")`). It requires `method_name`; a `service` schedule
  with only a `prompt` is rejected at `add_schedule` time.
- `AgentSchedulerManager(SchedulerManager)` installs `agent` → `AgentResolver(bot_manager)` and
  `crew` → `CrewResolver(bot_manager)`. `AgentResolver` checks explicit registrations first
  (`register_target(name, agent, kind="agent")`), then `bot_manager.get_bots()` (public, verified
  at `manager/manager.py:1257`), then `bot_manager.registry.get_instance(name)`. It keeps the
  `chat(prompt)` fallback and the crew prompt-mapping (`initial_task`/`query`/`tasks`) that today
  lives in `_prepare_call_arguments`.
- agentd stops needing `SingleAgentManager`: `AgentSchedulerManager()` +
  `register_target(config.name, agent, kind="agent")`.

Persistence is a second, independent axis inside the base: a `backend` per job selects where its
definition lives (`db` row, `redis` jobstore, or `code`) and which `RunStateStore` receives its
run state (Postgres columns, Redis hash, or process memory). The three fire trampolines in
`jobs.py` become `run_db_schedule` (re-reads the row), `run_redis_job` (definition carried in the
pickled kwargs) and `run_auto_schedule` (code-registered), all dispatching through
`registered_name`.

The subclass is therefore ~300 lines: two resolvers, `register_bot_schedules`, the report
decorators' env-var resolution, and `on_startup`'s `app["bot_manager"]` auto-wiring.

✅ **Pros:**
- Matches the user's mental model (base + subclass) and the issue's `register_target()` ask in one
  design.
- The hook surface is tiny and typed (`TargetResolver`), so an external package can add a fourth
  kind (`register_resolver("dagster", …)`) without subclassing.
- `AgentSchedulerManager` keeps its name and import path (`parrot.scheduler.manager`), so
  `jira_specialist.py`, `reminder.py`, `saved_execution_service.py` and agentd only change
  call-site kwargs, not imports.
- The `jobs.py` trampolines already dispatch through `registered_name`, not through the class, so
  they work for both classes unchanged (only type hints move to `SchedulerManager`).
- `backend='redis'` reuses the FEAT-631 groundwork (picklable trampolines, `_ensure_redis_jobstore`,
  fire coordination) — the jobstore is already attached on the aiohttp path
  (`start_headless(use_redis=True)`, `manager.py:2055`); what is new is a job whose definition is
  *only* there.

❌ **Cons:**
- Highest blast radius of the three: a 2.2k-line file is split, a schema is replaced, five
  callers and 13 test modules are touched in one feature.
- Two classes to document and test; the resolver protocol is one more concept.
- Hard-cut means external users (reportbuilder) must change call sites when they upgrade.

📊 **Effort:** High

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `apscheduler==3.11.2` | triggers, jobstores, `AsyncIOScheduler` | already pinned in the `scheduler` extra of ai-parrot-server |
| `asyncdb` (`Model`, `Field`) | new `ServiceSchedule` model | already used by `AgentSchedule` |
| `navigator.connections.PostgresPool` | connection pool in `setup()`/`start_headless()` | unchanged |
| `redis` (via `RedisJobStore`, `RedisFireCoordinator`) | persistent jobstore + fire claims | unchanged (FEAT-631) |
| `typing.Protocol` | `TargetResolver` contract | stdlib |

🔗 **Existing Code to Reuse:**
- `packages/ai-parrot-server/src/parrot/scheduler/manager.py` — everything from `__init__`
  (`manager.py:362`) through `stop_headless` (`manager.py:1977`) moves to the base except the
  agent/crew resolution blocks and `register_bot_schedules`.
- `packages/ai-parrot-server/src/parrot/scheduler/jobs.py` — `register_manager`, `get_manager`,
  `run_db_schedule`, `run_db_schedule_now`, `run_auto_schedule` stay as-is (type hints only).
- `packages/ai-parrot-server/src/parrot/scheduler/coordination.py` — `FireCoordinator`,
  `CoordinatedAsyncIOExecutor`, `build_fire_coordinator` unchanged; `fire_id` is derived from the
  same `run_time` the coordinator claims on.
- `packages/ai-parrot-server/src/parrot/scheduler/sanitize.py` — `normalize_schedule_type`,
  `sanitize_schedule_config`, `normalize_jobstore_alias` reused verbatim; module docstring updated
  to name the new table.
- `packages/ai-parrot-server/src/parrot/scheduler/functions/__init__.py` — `CALLBACK_REGISTRY` +
  `build_scheduler_callback` is the precedent for a name-keyed registry; `BaseSchedulerCallback.run`
  gains `target_name` in place of `agent_name`.
- `packages/ai-parrot/src/parrot/notifications/__init__.py:83` — `NotificationMixin` for the
  auto-disable alert (already wrapped by `_SchedulerNotification`, `manager.py:342`).

---

### Verified code anchors (paths only — open them yourself)
packages/ai-parrot-integrations/src/parrot/integrations/agentd/config.py
packages/ai-parrot-integrations/src/parrot/integrations/agentd/service.py
packages/ai-parrot-server/pyproject.toml
packages/ai-parrot-server/src/parrot/handlers/crew/saved_execution_service.py
packages/ai-parrot-server/src/parrot/handlers/infographic_recipes.py
packages/ai-parrot-server/src/parrot/handlers/scheduler.py
packages/ai-parrot-server/src/parrot/manager/manager.py
packages/ai-parrot-server/src/parrot/scheduler/coordination.py
packages/ai-parrot-server/src/parrot/scheduler/functions/__init__.py
packages/ai-parrot-server/src/parrot/scheduler/jobs.py
packages/ai-parrot-server/src/parrot/scheduler/manager.py
packages/ai-parrot-server/src/parrot/scheduler/models.py
packages/ai-parrot-server/src/parrot/scheduler/sanitize.py
packages/ai-parrot/src/parrot/_imports.py
packages/ai-parrot/src/parrot/notifications/__init__.py
packages/ai-parrot/src/parrot/registry/registry.py
packages/ai-parrot/src/parrot/scheduler/inprocess.py
packages/ai-parrot/src/parrot/tools/reminder.py
packages/ai-parrot/tests/test_schedules.py

### Questions still open in the exploration document
none

## Question
Given this accepted design intent and these verified code anchors, how would you build it? What is missing, risky, or better done another way?
