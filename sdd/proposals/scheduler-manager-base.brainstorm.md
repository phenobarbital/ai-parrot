---
# SDD flow type and base branch (FEAT-145).
# - type: feature  (default)  → base_branch: dev (or any non-main branch)
# - type: hotfix              → base_branch MUST be: main
type: feature
base_branch: dev
# projects: parts of the codebase this doc concerns. Use `packages/*` dir names
#   (ai-parrot, ai-parrot-server, parrot-formdesigner, …) or an area
#   (sdd-tooling, dev-loop, admin-ui, docs, ci). Unknown values warn, not fail.
projects: [ai-parrot-server, ai-parrot-integrations, ai-parrot]
# tags: free-form kebab-case keywords for organizing specs (e.g. memory, mcp).
tags: [scheduler, apscheduler, target-registry, service-scheduler, hard-cut, run-state]
---

# Brainstorm: SchedulerManager base — target-agnostic scheduler with AgentSchedulerManager as a subclass

**Date**: 2026-10-08
**Author**: Jesus Lara (brainstorm drafted by Claude)
**Status**: exploration
**Recommended Option**: A
**Source**: GitHub issue [phenobarbital/ai-parrot#1572](https://github.com/phenobarbital/ai-parrot/issues/1572) — "scheduler: first-class non-agent job targets, and keep run state out of job metadata"
**Target version**: ai-parrot-server 1.3.0 (breaking — current `parrot.server.version.__version__` is `1.2.0`)

---

## Problem Statement

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

**Why now:** the table `navigator.agents_scheduler` is barely used in deployments, so a hard-cut
(new table, new columns, no row migration) is cheap today and gets more expensive with every
schedule written. FEAT-631 and FEAT-635 both landed in the last week and are closed, so the
scheduler is quiescent — no in-flight spec touches `manager.py`.

## Constraints & Requirements

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
- **Missing-target policy**: `last_status = 'target_missing'`, a `consecutive_failures` counter;
  after N consecutive misses (default 3, env-configurable) the schedule is set `enabled = false`,
  the APScheduler job removed, and an alert is sent through `NotificationMixin`. One WARNING per
  tick, no traceback.
- **`@schedule` scanning generalised**: `SchedulerManager.register_object_schedules(obj, name)`
  scans any object; `AgentSchedulerManager.register_bot_schedules(bot)` wraps it and adds the
  `chatbot_id` / report env-var resolution.
- Existing invariants that must survive: picklable `jobs.py` trampolines keyed by
  `registered_name` (FEAT-631), fire-time row re-check + fingerprint reschedule, Redis fire
  coordination, delivery-outcome persistence (FEAT-635), `run_schedule_now` semantics
  (FEAT-467), `start_headless`/`stop_headless` (TASK-2209), sanitisation of
  `schedule_type`/`schedule_config`/jobstore alias (`sanitize.py`).
- Conventions: aiohttp only, `asyncdb` models, `self.logger`, no LangChain, Google docstrings,
  120 columns; tests under `packages/ai-parrot-server/tests/scheduler/`.

---

## Options Explored

### Option A: `SchedulerManager` base + kind-keyed `TargetResolver` table; `AgentSchedulerManager` subclasses it

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

### Option B: Pure composition — one `SchedulerManager`, no subclass; agent/crew are just two resolvers

Same split of concerns as Option A, but there is **no** `AgentSchedulerManager` class at all.
`SchedulerManager` is the only manager; `parrot/scheduler/agents.py` ships `AgentResolver`,
`CrewResolver` and a `register_bot_schedules(manager, bot)` function. `BotManager.setup()` (or the
app bootstrap) calls `manager.register_resolver("agent", AgentResolver(bot_manager))`. A
`make_agent_scheduler(bot_manager)` factory returns a pre-wired `SchedulerManager` for one-liner
setups. `AgentSchedulerManager` survives only as a one-release alias of that factory, or is removed
outright under the hard-cut.

✅ **Pros:**
- Cleanest dependency direction: the scheduler never imports anything from `parrot.manager` or
  `parrot.bots`; agent support is a plug-in installed by whoever owns `BotManager`.
- One class to test; `register_resolver` is the single extension point for every kind.
- Easiest story for external packages: "instantiate `SchedulerManager`, register your resolvers".

❌ **Cons:**
- Loses the `AgentSchedulerManager` type that five callers, two docs pages (`docs/agentd.md`,
  `docs/guides/cli-agent-daemon.md`) and the `_SERVER_CLASSES` lazy export reference by name.
  Either keep an alias (which the hard-cut decision rules out) or rename across the repo.
- `on_startup`'s "find `app['bot_manager']` and scan its bots" convenience becomes bootstrap glue
  that lives outside the scheduler package — easy to forget in a new app.
- The report decorators (`schedule_daily_report`/`schedule_weekly_report`) depend on
  `chatbot_id`-based env vars; as free functions they are less discoverable than today's methods.
- Equal blast radius to A, plus a rename wave.

📊 **Effort:** High

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| same as Option A | — | no new dependency |

🔗 **Existing Code to Reuse:**
- Identical to Option A; the agent/crew code moves to `parrot/scheduler/agents.py` instead of a
  subclass.

---

### Option C: Minimal bolt-on inside the existing class (what the issue literally asks for)

Keep `AgentSchedulerManager` as the single class and the existing table. Add
`register_target(name, obj)` and a `targets: Dict[str, Any]` consulted **before** `bot_manager` in
both `add_schedule` and `_execute_agent_job`; `agent_name` is reinterpreted as "target name".
Run state moves under a reserved `metadata["_run"]` sub-key that `_execution_fields()` strips
before building call kwargs; timestamps become UTC-aware; `last_error` is popped on success;
missing targets increment `metadata["_run"]["consecutive_failures"]` and disable at N.

✅ **Pros:**
- Smallest diff by far; no schema change, no migration, no new module.
- Fixes every bullet of issue #1572 as filed.
- Zero API breakage for existing callers.

❌ **Cons:**
- Leaves the smell in place: `agent_name`/`agent_id` NOT NULL columns and `is_crew` must now
  describe non-agent jobs; `BotManagement.get` still 400s for them.
- `bot_manager._bots` private access stays.
- `SingleAgentManager` in agentd stays (it could switch to `register_target`, but the class would
  still exist for `get_crew`).
- Run state under a reserved JSON key is a convention, not a schema — the next contributor can
  break it silently, which is exactly how the current bug appeared.
- Contradicts the discovery decisions (hard-cut, dedicated columns).

📊 **Effort:** Low

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| none new | — | — |

🔗 **Existing Code to Reuse:**
- `manager.py:1168` and `manager.py:681` — the two resolution blocks gain a registry lookup.
- `manager.py:977` `_update_schedule_run` — rewritten to the reserved key.

---

## Recommendation

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
- Option C is cheap but preserves the two root causes (private `BotManager` access and run state as
  JSON convention). Given the table is barely populated, paying the migration cost now is the whole
  point of the hard-cut.

**What we trade off:** one large, breaking PR instead of a series of small ones, and a required
call-site update for every external consumer of `add_schedule`. That is acceptable because the
API surface is small (one method plus three HTTP/RPC payload fields), the table is nearly empty,
and the server package is already at a major version where breaking changes are expected.

---

## Feature Description

### User-Facing Behavior

- **Python API (base)** — `SchedulerManager(**kwargs)`; `register_target(name, obj, *, kind="service")`;
  `register_resolver(kind, resolver)`; `register_object_schedules(obj, name)`;
  `add_schedule(target_kind, target_name, schedule_type, schedule_config, *, target_id=None, prompt=None,
  method_name=None, created_by=None, created_email=None, metadata=None, send_result=None,
  success_callback=None, scheduler_type="default", callbacks=None)`; the existing
  `remove_schedule`, `pause_schedule`, `update_schedule`, `delete_schedule`, `run_schedule_now`,
  `get_last_result`, `list_jobs`, `list_schedules`, `get_schedule`, `restart_scheduler`,
  `start_headless`, `stop_headless`, `setup`, `on_startup`, `on_shutdown` unchanged in semantics.
- **Python API (subclass)** — `AgentSchedulerManager(bot_manager=None, **kwargs)` adds the
  `agent`/`crew` resolvers and `register_bot_schedules(bot)`; `on_startup` keeps falling back to
  `app["bot_manager"]`. The `@schedule`, `@schedule_daily_report`, `@schedule_weekly_report`
  decorators and `ScheduleType` stay exported from `parrot.scheduler.manager` and lazily from
  `parrot.scheduler`.
- **HTTP** (`handlers/scheduler.py::SchedulerJobsHandler.post` and the legacy `SchedulerHandler`
  view in `manager.py`) — request body uses `target_kind` (required, one of `agent|crew|service`),
  `target_name` (required) and optional `target_id`; `agent_name`, `agent_id`, `is_crew` are
  rejected with 400 "unknown field". Serialized jobs (`_serialize_job`) expose `target_kind`,
  `target_name`, `target_id`, `last_status`, `last_error`, `last_error_at`, `last_result_at`,
  `consecutive_failures`. `SchedulerLastResultHandler` reads the new columns instead of `metadata`.
- **agentd RPC** — `schedules.add` passes `**params` straight to `add_schedule`, so clients send
  `target_kind`/`target_name`; `SingleAgentManager` is deleted and `AgentDaemon` registers its
  single agent explicitly.
- **Operators** — a schedule whose target cannot be resolved logs one WARNING per tick (no
  traceback), increments `consecutive_failures`, and after `PARROT_SCHEDULER_MAX_TARGET_MISSES`
  (default 3) consecutive misses is disabled, removed from APScheduler and reported through the
  configured notification channel. A later `PATCH enabled=true` re-arms it and resets the counter.
- **Targets** — any method may opt into idempotency by declaring `fire_id: str` and/or
  `scheduled_at: datetime` (or `**kwargs`); nothing else about the call changes.

### Internal Behavior

1. **Module layout** (ai-parrot-server, `parrot/scheduler/`):
   `base.py` (`SchedulerManager`, `TargetRegistry`, `TargetResolver` protocol, `RegistryResolver`,
   `FireContext`, `TargetMissingError`), `models.py` (`ServiceSchedule`, replaces `AgentSchedule`),
   `manager.py` (`AgentSchedulerManager`, `AgentResolver`, `CrewResolver`, decorators,
   `ScheduleType`, `SchedulerHandler`, `_resolve_report_schedule` and the env-var parsers),
   `jobs.py` / `coordination.py` / `sanitize.py` / `functions/` as today with renamed fields.
   Core `parrot/scheduler/__init__.py` adds `SchedulerManager`, `TargetRegistry`, `ServiceSchedule`
   to `_SERVER_CLASSES`.
2. **Schema** — `navigator.service_scheduler`:
   `schedule_id UUID PK`, `target_kind VARCHAR NOT NULL`, `target_name VARCHAR NOT NULL`,
   `target_id VARCHAR NULL`, `prompt TEXT`, `method_name VARCHAR`, `schedule_type VARCHAR NOT NULL`,
   `schedule_config JSONB NOT NULL`, `enabled BOOLEAN DEFAULT TRUE`, `created_by INTEGER`,
   `created_email VARCHAR`, `created_at/updated_at TIMESTAMPTZ DEFAULT NOW()`,
   `last_run TIMESTAMPTZ`, `next_run TIMESTAMPTZ`, `run_count INTEGER DEFAULT 0`,
   `last_status VARCHAR` (`success|error|target_missing|lock_unavailable`), `last_error TEXT`,
   `last_error_at TIMESTAMPTZ`, `last_result TEXT`, `last_result_at TIMESTAMPTZ`,
   `consecutive_failures INTEGER DEFAULT 0`, `last_delivery_status VARCHAR`,
   `last_delivery_at TIMESTAMPTZ`, `last_callbacks JSONB DEFAULT '[]'`, `metadata JSONB DEFAULT '{}'`
   (call kwargs only), `send_result JSONB DEFAULT '{}'`, `scheduler_type VARCHAR DEFAULT 'default'`,
   `callbacks JSONB DEFAULT '[]'`. Indexes on `enabled` and `(target_kind, target_name)`.
   The model's defaults use `datetime.now(timezone.utc)`.
3. **`add_schedule`** — sanitise (`normalize_schedule_type`, `sanitize_schedule_config`,
   `_safe_jobstore`), validate `target_kind` against the installed resolvers, ask the resolver to
   `resolve(target_name)` (missing target → `ValueError`, as today), derive `target_id` from the
   resolver when not supplied (`chatbot_id` / `crew_id` / `None`), reject `service` schedules that
   have no `method_name`, persist, add the `jobs.run_db_schedule` trampoline with the
   fingerprint. The fingerprint (`schedule_fingerprint`, `manager.py:327`) covers the new fields.
4. **Fire path** — `_run_db_schedule` unchanged (re-read row, skip disabled/missing, fingerprint
   reschedule) then `_execute_job(schedule, fire)` where `FireContext(fire_id, scheduled_at,
   run_now)` is built from the APScheduler run time (the same value `FireCoordinator.claim` keys on,
   so claim and `fire_id` agree). The resolver resolves the target and builds the call; the base
   injects `fire_id`/`scheduled_at` via `inspect.signature` only when accepted; the call runs;
   `_job_context` is recorded; `_process_job_success` → `_update_schedule_run` → delivery callbacks
   → `_stamp_delivery_outcome`, as today but writing columns.
5. **Run-state stamping** — success: `last_status='success'`, `last_result`, `last_result_at`,
   `last_error=None`, `last_error_at=None`, `consecutive_failures=0`. Error:
   `last_status='error'`, `last_error`, `last_error_at`, `consecutive_failures += 1`.
   Target missing: `last_status='target_missing'`, same error fields, counter += 1, and when the
   counter reaches the threshold: `enabled=false`, job removed, notification sent.
   `lock_unavailable` keeps its current semantics (`_on_coordination_unavailable`).
6. **Auto schedules** — `register_object_schedules(obj, name)` scans `inspect.getmembers` for
   `_schedule_config` markers and registers `jobs.run_auto_schedule` trampolines exactly as
   `register_bot_schedules` does now, storing `target_name` in `_auto_tasks`.
   `AgentSchedulerManager.register_bot_schedules(bot)` resolves `chatbot_id`/`agent_id`/`name`,
   handles `_schedule_report_type` env-var timing, then delegates.
7. **Callbacks** — `BaseSchedulerCallback.run(result, *, schedule_id, target_name, **kwargs)`;
   `RunInfographicRecipeCallback.run` (`handlers/infographic_recipes.py:349`) and
   `SendEmailReportCallback` updated accordingly.
8. **Callers migrated** — `handlers/scheduler.py` (POST body), `SchedulerHandler` in `manager.py`,
   `handlers/crew/saved_execution_service.py:285` (`target_kind="crew", target_name=crew_name`),
   agentd `service.py` (`SingleAgentManager` removed; `register_target(..., kind="agent")`),
   `tools/reminder.py` and `bots/jira_specialist.py` (doc/type references only — they use
   `.scheduler` and `app["scheduler_manager"]`, not `add_schedule`).

### Edge Cases & Error Handling

- **Unknown `target_kind`** → `ValueError` from `add_schedule` (HTTP 400); a row loaded from DB with
  a kind that has no resolver in this process → `target_missing` path (counts toward auto-disable),
  logged once per tick.
- **`service` without `method_name`** → rejected at `add_schedule`; a legacy row in that state →
  `error` status with a clear message, not a crash.
- **Target resolves but method missing / not callable** → `error` (not `target_missing`): the
  object exists, the schedule is misconfigured; no auto-disable.
- **Resolver raises** (e.g. `registry.get_instance` network error) → treated as `target_missing`
  for that tick; the counter means a transient outage of fewer than N ticks never disables.
- **Signature injection** — methods wrapped by the `@schedule` decorator expose `*args, **kwargs`,
  so injection is attempted; `functools.wraps` preserves `__wrapped__`, and the base inspects the
  innermost signature to avoid passing `fire_id` to a method that cannot take it.
- **Counter reset** — `PATCH enabled=true` and `run_schedule_now` success both reset
  `consecutive_failures`; a run-now on a disabled schedule still executes (today's semantics) but
  does not re-enable.
- **Notification failure** on auto-disable never raises; it is logged and the schedule is still
  disabled.
- **Two managers in one process** (`registered_name`) — unchanged: `jobs.get_manager` dispatches by
  name; resolvers are per-manager.
- **Multi-worker** — the auto-disable `UPDATE` is idempotent, so two workers racing on the same
  miss cannot double-disable; the notification may be sent twice in that race (accepted, documented).
- **Old table present** — nothing reads `navigator.agents_scheduler`; `load_schedules_from_db` reads
  only `service_scheduler`. Operators are told in the migration note to drop the old table.

---

## Capabilities

### New Capabilities
- `scheduler-manager-base`: target-agnostic `SchedulerManager` with `TargetRegistry`, kind-keyed
  `TargetResolver`s, `FireContext` injection, dedicated run-state columns and the missing-target
  auto-disable policy.
- `service-scheduler-schema`: `navigator.service_scheduler` table + `ServiceSchedule` model
  (hard-cut replacement of `agents_scheduler` / `AgentSchedule`).

### Modified Capabilities
- `agent-scheduler` (FEAT-467 run-now / `new-scheduler-decorators` / FEAT-631
  `scheduler-multiworker-correctness` / FEAT-635 `scheduler-callback-delivery-status`):
  `AgentSchedulerManager` becomes a subclass; the behaviours those specs define are preserved but
  their persistence target and field names change.
- `agentd` (TASK-2212): `SingleAgentManager` removed; explicit target registration.
- `agentcrew-saved-crews` (FEAT-307): `SavedExecutionService` schedules crews with
  `target_kind="crew"`.

---

## Impact & Integration

| Affected Component | Impact Type | Notes |
|---|---|---|
| `packages/ai-parrot-server/src/parrot/scheduler/base.py` | **new** | `SchedulerManager`, `TargetRegistry`, `TargetResolver`, `RegistryResolver`, `FireContext` |
| `packages/ai-parrot-server/src/parrot/scheduler/models.py` | **breaking** | `AgentSchedule` → `ServiceSchedule`, new table/columns |
| `packages/ai-parrot-server/src/parrot/scheduler/manager.py` | **breaking refactor** | shrinks to `AgentSchedulerManager(SchedulerManager)` + resolvers + decorators + `SchedulerHandler` |
| `packages/ai-parrot-server/src/parrot/scheduler/jobs.py` | modifies | type hints → `SchedulerManager`; behaviour unchanged |
| `packages/ai-parrot-server/src/parrot/scheduler/sanitize.py` | modifies | docstring/table name; no logic change |
| `packages/ai-parrot-server/src/parrot/scheduler/functions/__init__.py` | **breaking** | callback `run(..., target_name=...)` replaces `agent_name` |
| `packages/ai-parrot-server/src/parrot/handlers/scheduler.py` | **breaking** | POST/PATCH payload fields; last-result handler reads columns |
| `packages/ai-parrot-server/src/parrot/handlers/infographic_recipes.py` | modifies | callback signature |
| `packages/ai-parrot-server/src/parrot/handlers/crew/saved_execution_service.py` | modifies | `add_schedule(target_kind="crew", target_name=...)` |
| `packages/ai-parrot-integrations/src/parrot/integrations/agentd/service.py` | **breaking** | `SingleAgentManager` deleted; RPC `schedules.add` payload |
| `packages/ai-parrot/src/parrot/scheduler/__init__.py` | extends | lazy exports for the new names |
| `packages/ai-parrot/src/parrot/tools/reminder.py`, `bots/jira_specialist.py` | docs only | reference `AgentSchedulerManager` by name; no call-site change |
| `packages/ai-parrot-server/tests/scheduler/*` (13 modules), `packages/ai-parrot/tests/test_schedules.py` | **rewrite** | field renames + new base-class tests |
| `docs/scheduler/multi-worker.md`, `docs/agentd.md`, `docs/guides/cli-agent-daemon.md` | modifies | new API + migration note (drop old table) |
| `sdd/proposals/dashboard-scheduled-notifications-canvas.proposal.md` (FEAT-430, in review) | depends on | describes `navigator.agents_scheduler`; must be rebased on `service_scheduler` |
| `examples/database/agents_scheduler_market_analysis.sql` | stale | example SQL against the old table |
| Admin UI (`packages/ai-parrot-server/ui/`) | none | the only `scheduler.ts` is an A2UI linked-surface component unrelated to this manager |
| Deployment | **manual DDL** | create `navigator.service_scheduler`; optional `DROP TABLE navigator.agents_scheduler` |
| `ai-parrot-server` version | bump | 1.2.0 → 1.3.0 |

---

## Code Context

### User-Provided Code

None — the user supplied design direction only (hard-cut rename to `navigator.service_scheduler`,
`target_kind` + `target_name` policy, base class + subclass).

### Verified Codebase References

#### Classes & Signatures
```python
# From packages/ai-parrot-server/src/parrot/scheduler/manager.py
class ScheduleType(Enum):                                   # line 71  — ONCE/DAILY/WEEKLY/MONTHLY/INTERVAL/CRON/CRONTAB
class SchedulerRunNowConflictError(Exception):              # line 83
def _resolve_report_schedule(agent_id: str, report_type: str) -> Dict[str, Any]:  # line 294
def schedule_fingerprint(schedule: AgentSchedule) -> str:   # line 327
class _SchedulerNotification(NotificationMixin):            # line 342
class AgentSchedulerManager:                                # line 349
    registered_name: str = "scheduler_manager"              # line 360
    def __init__(self, bot_manager: Any = None, **kwargs):  # line 362
    def _prepare_call_arguments(self, method, prompt, metadata, *, is_crew, method_name) -> Tuple[List, Dict]:  # line 402
    def _apply_prompt_signature(self, method, call_args, call_kwargs, prompt):  # line 441
    def define_listeners(self):                             # line 470
    def job_success(self, event: JobExecutionEvent):        # line 538
    async def _execute_agent_job(self, schedule_id, agent_name, prompt=None, method_name=None, metadata=None, *,
                                 is_crew=False, success_callback=None, send_result=None, callbacks=None):  # line 637
    async def _handle_job_success(self, schedule_id, agent_name, result, ...):  # line 761
    async def _process_job_success(self, schedule_id, agent_name, result, ..., persist: bool = True):  # line 867
    def _format_result(self, result: Any) -> str:           # line 924
    _LAST_RESULT_MAX_CHARS                                   # line ~945 (class constant)
    async def _stamp_delivery_outcome(self, schedule_id: str, outcomes: List[Dict[str, Any]]) -> None:  # line 950
    async def _update_schedule_run(self, schedule_id, success=True, error=None, result=None):  # line 977
    async def _on_coordination_unavailable(self, job_id: str, exc: BaseException) -> None:  # line 1038
    def _create_trigger(self, schedule_type: str, config: Dict[str, Any]):  # line 1064
    async def add_schedule(self, agent_name, schedule_type, schedule_config, prompt=None, method_name=None,
                           created_by=None, created_email=None, metadata=None, agent_id=None, *,
                           is_crew=False, send_result=None, success_callback=None,
                           scheduler_type="default", callbacks=None) -> AgentSchedule:  # line 1119
    async def _execute_agent_task(self, job_id, agent_name, method, *, success_callback=None, send_result=None, callbacks=None):  # line 1242
    def register_bot_schedules(self, bot: Any) -> int:      # line 1290
    async def remove_schedule(self, schedule_id: str):      # line 1360
    async def load_schedules_from_db(self):                 # line 1378
    async def restart_scheduler(self):                      # line 1445
    def _execution_fields(self, schedule: AgentSchedule) -> Dict[str, Any]:  # line 1465  (passes dict(schedule.metadata) as call metadata)
    def _job_kwargs_from_schedule(self, schedule: AgentSchedule) -> Dict[str, Any]:  # line 1478
    async def _run_db_schedule(self, schedule_id: str, fingerprint: Optional[str], *, run_now: bool = False) -> Any:  # line 1486
    async def _run_auto_task(self, job_id: str) -> Any:     # line 1538
    def _serialize_job(self, schedule: AgentSchedule) -> Dict[str, Any]:  # line 1562
    async def list_jobs(self) -> List[Dict[str, Any]]:      # line 1608
    async def get_schedule(self, schedule_id: str) -> AgentSchedule:  # line 1637
    async def pause_schedule(self, schedule_id: str) -> AgentSchedule:  # line 1649
    async def update_schedule(self, schedule_id: str, updates: Dict[str, Any]) -> AgentSchedule:  # line 1661
    async def delete_schedule(self, schedule_id: str) -> None:  # line 1727
    async def run_schedule_now(self, schedule_id: str) -> AgentSchedule:  # line 1739
    async def get_last_result(self, schedule_id: str) -> Dict[str, Any]:  # line 1802
    def _build_jobstores(self, use_redis: bool = False) -> Dict[str, Any]:  # line 1875
    async def start_headless(self, ...):                    # line 1919
    async def stop_headless(self, *, wait: bool = True) -> None:  # line 1977
    def setup(self, app: web.Application) -> web.Application:  # line 2005
    async def on_startup(self, app: web.Application, conn: Callable):  # line 2042  (falls back to app.get("bot_manager"), line 2062)
    async def on_shutdown(self, app: web.Application, conn: Callable):  # line 2077
class SchedulerHandler(CorsViewMixin, web.View):            # line 2098  (legacy HTTP view, uses agent_name)

# From packages/ai-parrot-server/src/parrot/scheduler/models.py
class AgentSchedule(Model):                                 # line 7  — table navigator.agents_scheduler (Meta: driver='pg', schema='navigator', strict=True)
    schedule_id: uuid.UUID; agent_id: str; agent_name: str; prompt; method_name; schedule_type; schedule_config
    enabled; created_by; created_email; created_at; updated_at; last_run; next_run; run_count
    metadata: dict; is_crew: bool; send_result: dict; scheduler_type: str; callbacks: list

# From packages/ai-parrot-server/src/parrot/scheduler/jobs.py
_MANAGERS: Dict[str, "AgentSchedulerManager"]              # line 32
def register_manager(manager) -> None:                      # line 35
def unregister_manager(name: str) -> None:                  # line 43
def get_manager(name: str) -> "AgentSchedulerManager":      # line 48
async def run_db_schedule(manager_name: str, schedule_id: str, fingerprint: str) -> Any:  # line 60
async def run_db_schedule_now(manager_name: str, schedule_id: str) -> Any:  # line 65
async def run_auto_schedule(manager_name: str, job_id: str) -> Any:  # line 74
SKIPPED  # module-level _Skipped sentinel, line 21

# From packages/ai-parrot-server/src/parrot/scheduler/coordination.py
class FireCoordinationError(Exception):                     # line 29
class FireCoordinator(Protocol):                            # line 34  — claim(job_id, run_time), try_acquire_running, release_running, close
class NullFireCoordinator:                                  # line 53
class RedisFireCoordinator:                                 # line 81
def build_fire_coordinator(mode=None, *, use_redis=False) -> FireCoordinator:  # line 139
class CoordinatedAsyncIOExecutor(AsyncIOExecutor):          # line 168

# From packages/ai-parrot-server/src/parrot/scheduler/sanitize.py
class SchedulerConfigError(ValueError):                     # line 104
def normalize_jobstore_alias(...)                           # line 275
def normalize_schedule_type(value: Any) -> str:             # line 343
def sanitize_schedule_config(...)                           # line 502

# From packages/ai-parrot-server/src/parrot/scheduler/functions/__init__.py
class BaseSchedulerCallback(NotificationMixin):             # line 17
    async def run(self, result, *, schedule_id: str, agent_name: str, **kwargs) -> Dict[str, Any]:  # line ~97
def build_scheduler_callback(definition: Dict[str, Any], logger=None) -> BaseSchedulerCallback:  # line 253 (uses CALLBACK_REGISTRY)

# From packages/ai-parrot-server/src/parrot/handlers/scheduler.py
class SchedulerCatalogHelper(BaseHandler):                  # line 17
class SchedulerCallbacksHandler(BaseView):                  # line 36
class SchedulerJobsHandler(BaseView):                       # line 55  — post() calls add_schedule(agent_name=..., agent_id=..., is_crew=...) at line 100
class SchedulerLastResultHandler(BaseView):                 # line 172

# From packages/ai-parrot-server/src/parrot/handlers/infographic_recipes.py
class RunInfographicRecipeCallback(BaseSchedulerCallback):  # line 323
    async def run(self, result: Any, *, schedule_id: str, agent_name: str, **kwargs)  # line 349

# From packages/ai-parrot-server/src/parrot/handlers/crew/saved_execution_service.py
class SavedExecutionService:  # __init__(..., scheduler_manager: Any = None, ...) line 87
    # add_schedule(crew_name, schedule_type, schedule_config, prompt=..., method_name=..., ..., is_crew=True, callbacks=...)  line 285

# From packages/ai-parrot-integrations/src/parrot/integrations/agentd/service.py
class SingleAgentManager:                                   # line 240  — fake bot_manager: _bots dict, registry.get_instance(name), get_crew(name) -> None
class AgentDaemon:                                          # line 277
    # from parrot.scheduler.manager import AgentSchedulerManager   line 509
    # manager = AgentSchedulerManager(bot_manager=single_agent_manager)  line 525
    # manager.register_bot_schedules(self.agent)                   line 529
    async def _handle_schedules_add(self, session, params) -> Any:  # line 787 — add_schedule(**params)

# From packages/ai-parrot-server/src/parrot/manager/manager.py
class BotManager:                                           # line 212
    self._bots: Dict[str, AbstractBot] = {}                 # line 245 (private — current scheduler coupling point)
    self.registry: AgentRegistry = agent_registry           # line 254
    def get_bots(self) -> Dict[str, AbstractBot]:           # line 1257 (public)
    async def get_crew(self, identifier: str, as_new: bool = False, tenant: Optional[str] = None
                       ) -> Optional[Tuple[AgentCrew, CrewDefinition]]:  # line 3019 (ASYNC — scheduler currently calls it un-awaited)
    # self.app["bot_manager"] = self                        # lines 2377, 2850

# From packages/ai-parrot/src/parrot/registry/registry.py
    async def get_instance(self, *args, **kwargs) -> AbstractBot:  # line 85 (AgentRegistry)

# From packages/ai-parrot/src/parrot/notifications/__init__.py
class NotificationMixin:                                    # line 83

# From packages/ai-parrot/src/parrot/_imports.py
def load_satellite_attr(name: str, module_path: str, *, install: str, attr: str | None = None) -> object:  # line 183

# From packages/ai-parrot/src/parrot/tools/reminder.py
class ReminderToolkit:  # __init__(self, scheduler_manager: Any, **kwargs) line 179; stores self._sm, uses .scheduler only
```

#### Verified Imports
```python
# These imports have been confirmed to work:
from parrot.scheduler import AgentSchedulerManager, ScheduleType, schedule  # lazy via parrot/scheduler/__init__.py:_SERVER_CLASSES
from parrot.scheduler.manager import AgentSchedulerManager, ScheduleType, schedule_fingerprint
from parrot.scheduler.models import AgentSchedule
from parrot.scheduler import jobs                                   # packages/ai-parrot-server/src/parrot/scheduler/jobs.py
from parrot.scheduler.coordination import FireCoordinator, NullFireCoordinator, CoordinatedAsyncIOExecutor, build_fire_coordinator
from parrot.scheduler.sanitize import SchedulerConfigError, normalize_schedule_type, sanitize_schedule_config, normalize_jobstore_alias
from parrot.scheduler.functions import build_scheduler_callback, BaseSchedulerCallback
from parrot.notifications import NotificationMixin                   # packages/ai-parrot/src/parrot/notifications/__init__.py:83
from parrot._imports import load_satellite_attr
from asyncdb.models import Model, Field
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.jobstores.redis import RedisJobStore
```

#### Key Attributes & Constants
- `AgentSchedulerManager.registered_name` → `str`, default `"scheduler_manager"` (manager.py:360); key for `jobs._MANAGERS`.
- `AgentSchedulerManager._job_context` → `Dict[str, Dict[str, Any]]` (manager.py:371); carries `persist` flag for auto tasks.
- `AgentSchedulerManager._auto_tasks` → `Dict[str, Dict[str, Any]]` (manager.py:376); keys `auto_<bot>_<method>`.
- `AgentSchedulerManager._local_callbacks` → `Dict[str, Callable]` (manager.py:375); process-local `success_callback`s.
- `AgentSchedulerManager._fire_coordinator` → `FireCoordinator` (manager.py:374).
- `AgentSchedulerManager._LAST_RESULT_MAX_CHARS` → cap for `last_result` (manager.py:~945).
- APScheduler `job_defaults`: `coalesce=True`, `max_instances=2`, `misfire_grace_time=300`, `timezone="UTC"` (manager.py:391-400).
- `apscheduler==3.11.2` pinned in `packages/ai-parrot-server/pyproject.toml:42` (extra `scheduler`).
- `parrot.server.version.__version__ == "1.2.0"`.
- Tests: `packages/ai-parrot-server/tests/scheduler/` — `test_callback_delivery.py`, `test_coordination.py`, `test_delivery_outcomes.py`, `test_fire_recheck.py`, `test_headless.py`, `test_jobs.py`, `test_listeners.py`, `test_manager_sanitization.py`, `test_multiworker.py`, `test_run_now.py`, `test_run_now_coordination.py`, `test_sanitize.py`; plus `packages/ai-parrot/tests/test_schedules.py` (imports `AgentSchedule`).
- Open ledger issues on `manager.py` (fold into this work or re-base them): `aa813ccc1927` (major — fire claim key unstable for interval/once triggers), `7b5d75d2c81d` (minor — run_schedule_now bare RuntimeError), `37f02d3c2474` (minor — raising `success_callback` skips delivery callbacks).

### Does NOT Exist (Anti-Hallucination)
- ~~`parrot.scheduler.base`~~ / ~~`SchedulerManager`~~ — does not exist yet; this feature creates it.
- ~~`TargetRegistry`~~, ~~`TargetResolver`~~, ~~`RegistryResolver`~~, ~~`FireContext`~~, ~~`TargetMissingError`~~ — new names, nothing to reuse.
- ~~`ServiceSchedule`~~ / ~~`navigator.service_scheduler`~~ — new model/table.
- ~~`AgentSchedulerManager.register_target()`~~, ~~`.register_resolver()`~~, ~~`.register_object_schedules()`~~ — not present today.
- ~~`BotManager.get_bot(name)`~~ — not verified; only `get_bots()` (manager.py:1257) and the private `_bots` dict were confirmed. Do not reference `get_bot`.
- ~~synchronous `BotManager.get_crew(name)`~~ — it is **async**: `async def get_crew(self, identifier: str, as_new: bool = False, tenant: Optional[str] = None) -> Optional[Tuple[AgentCrew, CrewDefinition]]` (manager/manager.py:3019). The scheduler calls it **without `await`** at manager.py:681 and manager.py:1170, so against a real `BotManager` the walrus/unpack sees a coroutine object (latent bug, see Problem Statement). `CrewResolver` must `await` it.
- ~~`AgentSchedule.last_status` / `.last_error` / `.consecutive_failures`~~ — today these live only inside `metadata`.
- ~~`schedule_fingerprint` in `sanitize.py`~~ — it is defined in `manager.py:327`, not in `sanitize.py`.
- ~~`parrot.scheduler.inprocess.InProcessScheduler` as a base~~ — exists (`packages/ai-parrot/src/parrot/scheduler/inprocess.py:49`) but is a tiny core-side helper unrelated to this manager; not a candidate base class.
- ~~Admin UI scheduler pages~~ — `ui/src/.../a2ui/linked/scheduler.ts` is an A2UI linked-surface component; no admin page sends `agent_name` to this manager.
- ~~tests for `SingleAgentManager`~~ — no test under `packages/ai-parrot-integrations/tests/agentd/` references it.

---

## Parallelism Assessment

- **Internal parallelism**: low. The model/DDL, the base class, the subclass refactor and the caller
  hard-cut form a strict chain: callers cannot compile until `add_schedule`'s new signature exists,
  and the base cannot be tested until `ServiceSchedule` exists. Only the docs/migration-note task
  and the agentd task can run in parallel with the test rewrite once the base + subclass land.
- **Cross-feature independence**: FEAT-631 and FEAT-635 are closed (all tasks `done`), so
  `manager.py` has no in-flight writer. FEAT-430 (`dashboard-scheduled-notifications-canvas`,
  status `review`) *describes* `navigator.agents_scheduler` and must be rebased on the new table
  before it is specced. Shared files with nothing else: `handlers/scheduler.py`,
  `handlers/crew/saved_execution_service.py`, agentd `service.py`.
- **Recommended isolation**: `per-spec`.
- **Rationale**: one worktree, tasks sequential in the order model → base → subclass → callers →
  tests/docs; a single breaking PR is the point of the hard-cut, and splitting it across worktrees
  would leave `dev` in a half-migrated state between merges.

---

## Open Questions

- [x] Flow type and base branch? — *Owner: Jesus Lara*: `feature` on `dev`.
- [x] Where does the base live? — *Owner: Jesus Lara*: ai-parrot-server, `parrot/scheduler/base.py`; core only lazy-exports.
- [x] Postgres migration scope? — *Owner: Jesus Lara*: hard-cut, new table `navigator.service_scheduler`, DDL documented, no row-copy script, old table left for the operator.
- [x] Does the hard-cut reach the Python/HTTP/RPC API? — *Owner: Jesus Lara*: yes, total; `agent_name`/`agent_id`/`is_crew` removed everywhere, all in-repo callers migrated in the same PR, no aliases.
- [x] Name of the registry-resolved kind? — *Owner: Jesus Lara*: `service` (`agent` | `crew` | `service`).
- [x] How is fire context delivered to targets? — *Owner: Jesus Lara*: signature injection of `fire_id` / `scheduled_at` only when declared or `**kwargs`.
- [x] Missing-target policy? — *Owner: Jesus Lara*: disable after N consecutive misses (default 3, env-configurable), WARNING per tick, notification on disable.
- [x] Generalise `@schedule` scanning? — *Owner: Jesus Lara*: yes, `register_object_schedules(obj, name)` in the base; `register_bot_schedules(bot)` wraps it.
- [ ] Should plain `error` runs (target found, call raised) also count toward auto-disable, or only `target_missing`? Brainstorm assumes **only `target_missing`** disables; `error` bumps the counter but never disables. — *Owner: Jesus Lara*
- [ ] agentd RPC `schedules.add` forwards `**params` verbatim: hard-cut the RPC payload in this release (clients must send `target_kind`/`target_name`), or translate in `_handle_schedules_add`? Brainstorm assumes hard-cut. — *Owner: Jesus Lara*
- [ ] Should the three open ledger issues on `manager.py` (`aa813ccc1927`, `7b5d75d2c81d`, `37f02d3c2474`) be closed inside this feature since the code moves to the base, or re-pointed at `base.py` and left for `/sdd-fix`? — *Owner: Jesus Lara*
- [ ] FEAT-430 proposal references `navigator.agents_scheduler`: rebase it on `service_scheduler` now, or leave it to `/sdd-spec` of FEAT-430? — *Owner: Jesus Lara*
- [ ] `examples/database/agents_scheduler_market_analysis.sql` and the `docs/report-builder/inventory/*` pages mention the old table: update, or mark historical? — *Owner: Jesus Lara*
- [ ] The un-awaited `get_crew()` means `SavedExecutionService.schedule_execution` (crew schedules via HTTP) is likely broken on `dev` today. Confirm with a live `BotManager` and decide whether a hotfix lands on `main` before this feature, or the fix rides inside it. — *Owner: Jesus Lara*
- [ ] Name of the env var for the miss threshold: `PARROT_SCHEDULER_MAX_TARGET_MISSES` (assumed) — confirm it goes through `parrot.conf` like `CACHE_HOST`/`CACHE_PORT`. — *Owner: Jesus Lara*
