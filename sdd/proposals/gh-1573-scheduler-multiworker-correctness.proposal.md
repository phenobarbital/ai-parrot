---
id: GH-1573  # provisional; /sdd-spec reserves the real FEAT-<NNN> via reserve_ids.py
title: "Scheduler correctness under multi-worker aiohttp: wire the listeners, dedupe each fire with a Redis lock, re-check the row at fire time, picklable job entrypoints"
slug: gh-1573-scheduler-multiworker-correctness
type: feature
mode: investigation
status: review
source:
  kind: github_issue
  github_issue: phenobarbital/ai-parrot#1573
  url: https://github.com/phenobarbital/ai-parrot/issues/1573
  fetched_at: 2026-10-05
  summary_oneline: "Scheduler on aiohttp: listeners never wired, every worker fires every job, redis jobstore cannot pickle jobs"
overall_confidence: medium
base_branch: dev
projects: [ai-parrot-server, ai-parrot-integrations]
tags: [scheduler, apscheduler, multi-worker, redis-lock, listeners, gunicorn]
research_state: sdd/state/GH-1573/
created: 2026-10-05
updated: 2026-10-05
---

# GH-1573: Scheduler correctness under multi-worker aiohttp

> **Mode**: investigation
> **Confidence**: medium. Localization is high (direct citations plus a reproduced pickling failure); the coordination hook point is medium (it relies on an APScheduler 3.x executor internal).
> **Source**: [phenobarbital/ai-parrot#1573](https://github.com/phenobarbital/ai-parrot/issues/1573)
> **Audit**: [`sdd/state/GH-1573/`](../state/GH-1573/)

---

## 0. Origin

> 1. **Listeners are off.** The aiohttp `on_startup` calls `start_headless(use_redis=True, register_listeners=False)`. For DB schedules, success therefore never updates `last_run`/`run_count`/`last_result`/`next_run`, and `send_result` and `CALLBACK_REGISTRY` callbacks never run. This differs from the headless/agentd path.
> 2. **Duplicate firing with multiple workers.** Every process loads every schedule and fires it: two workers deliver twice. `delete_schedule` in one worker does not stop the job in another. `_execute_agent_job` does not re-check that the row still exists and is enabled.
> 3. **Redis jobstore.** `scheduler_type="redis"` fails for DB schedules because the bound method `self._execute_agent_job` cannot be pickled. A module-level trampoline would fix it.
>
> **Suggested fixes:** wire the listeners consistently (or document why not); leader election or a distributed lock per fire; re-check the row before executing; a picklable job function.

**Initial signals**
- Kind: bug report, labelled `bug`, from an external integrator (reportbuilder). Versions: ai-parrot-server 0.27.1, apscheduler 3.11.2.
- Named entities: `on_startup`, `start_headless`, `register_listeners`, `_execute_agent_job`, `delete_schedule`, `scheduler_type="redis"`, `CALLBACK_REGISTRY`.
- The reporter already proposes fix directions. No acceptance criteria are given.

---

## 1. Synthesis Summary

All three defects are real and live in `packages/ai-parrot-server/src/parrot/scheduler/manager.py`. The aiohttp `on_startup` deliberately passes `register_listeners=False` [F001]. As a result, the success half of every DB job (DB stamping, `send_result`, callbacks) is dead code in production, while the failure half still writes to the DB. Each gunicorn worker builds its own `AsyncIOScheduler` and loads every row, and none of them re-reads the row at fire time [F002]. Every job function is a bound method of the manager, and APScheduler 3.11 serializes it by pickling the manager itself; this fails with `TypeError: Schedulers cannot be serialized` (reproduced) [F003].

The recommended fix has four parts, and they reinforce each other:
- **Picklable entrypoints.** Module-level trampolines that carry only `schedule_id` and re-read the row when they fire. This fixes Redis serialization and gives the row re-check at the same time.
- **Per-fire Redis claim.** A `SET NX` keyed by `(job_id, scheduled_run_time)` and taken inside a thin executor subclass, so exactly one worker runs each fire. It fails closed when Redis is unavailable.
- **Listeners on by default** on the aiohttp path.
- **Fixes for the latent listener bugs** that turning them on would expose.

---

## 2. Codebase Findings

### 2.1 Localization

| Location | Role | Evidence |
|---|---|---|
| `scheduler/manager.py:1831-1853` `AgentSchedulerManager.on_startup` | Passes `register_listeners=False`. A comment justifies it as "behaviour-preserving" (FEAT-422). | F001 |
| `scheduler/manager.py:1720-1768` `start_headless` | Wires `define_listeners()` only when the flag is set | F001 |
| `scheduler/manager.py:447-453` `define_listeners` | job_success / job_status / job_added / status listeners | F001 |
| `scheduler/manager.py:515-607` `job_success` → `_process_job_success` (791-835) | The only path that stamps success, runs callbacks and sends `send_result` | F001 |
| `scheduler/manager.py:471-513` `job_status` | `job.name` crashes when `get_job()` returns `None` (latent; exposed once wired) | F001 |
| `scheduler/manager.py:456-459` `scheduler_status` | `print(event)`, which is banned by conventions | F001 |
| `scheduler/manager.py:609-702` `_execute_agent_job` | Bound-method job func; no row re-check; stashes context in `_job_context` | F001, F002, F003 |
| `scheduler/manager.py:338-377` `__init__` | Per-process scheduler; `max_instances=2` is per process | F002 |
| `scheduler/manager.py:1237-1300` `load_schedules_from_db` | Every worker loads every enabled row; passes the bound method | F002, F003 |
| `scheduler/manager.py:1146-1217` `register_bot_schedules` | `auto_*` decorator jobs are also per worker, have no DB row, and pass a bound `method` in kwargs | F002 |
| `scheduler/manager.py:1431-1519` `pause/update/delete_schedule` | Change only the local scheduler | F002 |
| `scheduler/manager.py:1521-1601` `run_schedule_now` / `_run_now_wrapper` | `_run_now_active` 409-guard is per process; bound-method func | F002, F003 |
| `scheduler/manager.py:975-1096` `add_schedule` | Bound-method func plus an arbitrary `success_callback` callable in job kwargs | F003 |
| `integrations/agentd/service.py:526` | Headless caller: single process, listeners on, optional redis | F004 |
| `integrations/slack/dedup.py:168` `RedisEventDeduplicator.is_duplicate` | Existing `SET NX EX` idiom to reuse | F004 |

### 2.2 Constraints

- `_update_schedule_run` and the listeners must behave identically on the aiohttp and headless paths; agentd adds its own listeners on top [F004].
- APScheduler is 3.11.2. Version 3.x does **not** support sharing one jobstore across scheduler processes, so a shared `RedisJobStore` is not a coordination mechanism [F002].
- Job kwargs placed in a persistent jobstore must be picklable. In practice that means JSON-able: no callables and no `self` [F003].
- `job_success` already recovers `schedule_id` from the `run_now:` job-id prefix for one-shot jobs that have removed themselves. Any new entrypoint must keep that contract [F001].
- Convention: aiohttp only, `self.logger` instead of `print`, and Redis access through the existing async client idiom [F004].

### 2.3 Recent History

- `af9e3cde70` FEAT-467 TASK-2520 added run-now and last-result. It fixed the missing `await` in `_update_schedule_run`, which means success stamping has *never* worked in production on any path that lacked listeners.
- `2017c501f4` FEAT-422 TASK-2209 extracted `start_headless`. That commit introduced `register_listeners=False` for aiohttp, intentionally keeping the old dead-code behaviour.
- `21b5fa6e82` sanitized env and DB inputs before they reach APScheduler.

---

## 3. Hypothesis / Scope

### Module 1: Picklable job entrypoints (fixes #3, enables the re-check)

- Add a new module, `parrot/scheduler/jobs.py`, with module-level coroutines:
  - `run_db_schedule(manager_name: str, schedule_id: str)`
  - `run_db_schedule_now(manager_name: str, schedule_id: str)`
  - `run_auto_schedule(manager_name: str, job_id: str)`
- Each one resolves its manager from a process-local registry, `_MANAGERS: dict[str, AgentSchedulerManager]`, which is populated in `__init__` and keyed by `registered_name`. APScheduler stores a textual `module:function` reference.
- Job kwargs for DB jobs shrink to `{manager_name, schedule_id}`. At fire time the trampoline re-reads the row, and `agent_name`, `prompt`, `method_name`, `metadata`, `is_crew`, `send_result` and `callbacks` all come from that row. Edits made in another worker (prompt, callbacks, recipients) are therefore picked up automatically.
- `success_callback` (a code-only callable from `add_schedule`) moves out of job kwargs into a process-local `_local_callbacks[schedule_id]`. That is acceptable because it was never persistable anyway.
- `auto_*` jobs look up their bound method on the live bot via `bot_manager` and the method name stored in the job.

### Module 2: Row re-check at fire time (fixes the second half of #2)

- In `_execute_agent_job` (now called from the trampoline): fetch the row.
  - If the row is **missing or `enabled=False`**: remove the local job, log, and return a `SKIPPED` sentinel.
  - If `schedule_type`/`schedule_config` **differ from the trigger the local job was built from**: rebuild the local trigger (`reschedule_job`) and skip this fire.
- The job kwargs carry a cheap `config_hash`; comparing against it is how the trampoline detects the change.
- As a result, `delete`, `pause` and `update` made in worker A take effect in worker B at B's next fire, with no pub/sub.

### Module 3: Per-fire coordination (fixes the first half of #2)

- Add a `FireCoordinator` protocol with two implementations:
  - `RedisFireCoordinator`: `SET parrot:scheduler:fire:{job_id}:{scheduled_run_time_iso} <worker-id> NX EX <ttl>`. The TTL defaults to 24 h; it only has to outlive clock skew and the misfire grace.
  - `NullFireCoordinator`: used when `SCHEDULER_COORDINATION=none` and by default on the single-process agentd path unless it enables Redis.
- **Hook point.** Add a `CoordinatedAsyncIOExecutor(AsyncIOExecutor)` that overrides `_do_submit_job(job, run_times)`. That is the only place where APScheduler 3.x exposes the *scheduled* run time, which every worker computes identically from the trigger. It wraps the coroutine as "claim → `run_coroutine_job` → dispatch event". Verified against 3.11.2: the wrapper coroutine returns `[]` when the claim is lost, so `_run_job_success(job.id, [])` dispatches nothing. Workers that lose the claim therefore emit **no** `EVENT_JOB_EXECUTED`, so listeners, emails and DB stamps happen exactly once.
- With `coalesce=True`, the claim key uses `run_times[-1]`.
- **Fail closed:** if Redis errors, skip the fire, log an error, and stamp `metadata.last_status="lock_unavailable"` on DB-backed rows.
- The run-now 409-guard also moves to Redis (`parrot:scheduler:running:{schedule_id}`, NX with TTL, released in `finally`), so it holds across workers.

### Module 4: Listeners on, and the bugs that exposes (fixes #1)

- `on_startup` calls `start_headless(use_redis=True, register_listeners=True)`. Update the comment and add a release note: existing DB schedules **will start** sending `send_result` emails and running callbacks.
- Fixes needed once the listeners run:
  - `job_status`: guard against `get_job()` returning `None`, as `job_success` already does.
  - `scheduler_status`: replace `print(event)` with logging.
  - `_update_schedule_run(success=True)`: refresh `next_run` from the local job's `next_run_time`, and set it on load too.
  - `_job_context`: pop it on the skip and claim-lost paths so it does not leak.

### Explicitly NOT in scope

- Migrating to APScheduler 4.x (whose data-store layer has native multi-node coordination). That is worth a separate brainstorm.
- Leader election (rejected by the user in favour of per-fire locks).
- A pub/sub invalidation channel or a periodic reconcile loop. The fire-time re-check covers delete, pause and update. A schedule added in worker A runs only in A until other workers restart, which is correct because A still fires it under the lock.

### Test plan sketch

Unit tests with fakeredis or an `AsyncMock` Redis:
- Two managers sharing one coordinator, one fire time: exactly one executes, and listeners fire once.
- Redis raising: no execution, and `lock_unavailable` is stamped.
- The trampoline job pickles: `pickle.dumps(job.__getstate__())`.
- A deleted or disabled row is skipped and its local job removed.
- A changed `config_hash` triggers a reschedule and a skip.
- `on_startup` registers the listeners.
- `job_status` survives `get_job() is None`.

Existing `test_run_now.py` and `test_headless.py` must keep passing.

---

## 4. Confidence Map

- ✓ [high] aiohttp never wires the listeners, so success stamping, callbacks and `send_result` are dead on that path (F001)
- ✓ [high] Every worker loads and fires every job, and nothing re-checks the row (F002)
- ✓ [high] Redis serialization fails because the bound method pickles the manager. Reproduced: `TypeError: Schedulers cannot be serialized` (F003)
- ✓ [high] Turning the listeners on exposes `job_status` crashing on `None` and the `print` call (F001)
- ◐ [medium] `CoordinatedAsyncIOExecutor._do_submit_job` is a stable enough hook. It is a private method in APScheduler 3.x, so pin `apscheduler<4` and add a test that fails loudly if the signature changes.
- ◐ [medium] Re-reading the row at every fire costs one indexed PK lookup per fire, which is negligible next to an LLM call.
- ◌ [low] Exact TTL and key-prefix naming, and whether `RedisFireCoordinator` should reuse the slack dedup client factory or `sanitize_redis_settings(db=6)`.

---

## 5. Open Questions

### Resolved (2026-10-05)

- [x] **How should workers be deduplicated?** Per-fire Redis lock (`SET NX` on job_id + scheduled_run_time). Covers `auto_*` jobs too. Leader election and a Postgres claim column were rejected.
- [x] **Should the aiohttp listeners be on?** Yes, on by default, called out in the release notes. No feature flag.
- [x] **What happens when Redis is unreachable at fire time?** Fail closed: skip, log an error, and stamp `last_status=lock_unavailable`. `SCHEDULER_COORDINATION=none` is the explicit opt-out for single-process deployments.

### Unresolved

- [ ] Should `scheduler_type="redis"` stay supported? Once it pickles, it gives persistence but not coordination, and APScheduler 3 warns against sharing it across processes. The options are to keep it with a docs warning, or to deprecate it in favour of MemoryJobStore + DB rows + lock.
- [ ] Should `/api/v1/parrot/scheduler/restart` restart all workers (via a Redis broadcast) or remain per-worker? Today it only restarts the worker that receives the request.

---

## 6. Recommended Next Step

**→ `/sdd-spec sdd/proposals/gh-1573-scheduler-multiworker-correctness.proposal.md`**

Localization is high-confidence, and the three design decisions that matter most are already resolved. The work splits naturally into about four tasks (entrypoints + re-check, coordinator + executor, listeners + latent fixes, tests + docs/release note), all in one package. `/sdd-spec` will reserve the real FEAT-ID; this proposal uses the provisional `GH-1573`.

---

## 7. Research Audit

- State: `sdd/state/GH-1573/` (source.md, findings F001–F004, state.json, synthesis.json)
- Budget: default profile. About 12 file reads (manager.py read in 6 ranges, models.py, agentd/service.py, dedup.py, the APScheduler source), 6 greps, 2 git log calls, 2 Python repros. Not truncated.
- The FEAT-ID was not reserved: the shared checkout had another session's uncommitted files, and `reserve_ids.py` refuses to run from a worktree.
