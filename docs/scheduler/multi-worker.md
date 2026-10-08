# Scheduler backends in multi-worker deployments

## Overview

When more than one aiohttp or gunicorn worker loads the same schedule, each
local APScheduler can see the same due fire. The scheduler claims each fire
before it runs so an agent, callback, or `send_result` email is executed once.

## Backends and coordination

Each schedule has one persistence backend:

| Backend | Definition and run state | Restart behaviour |
| --- | --- | --- |
| `db` | `navigator.service_scheduler` and its UTC run-state columns | Reloaded by `load_schedules_from_db()` |
| `redis` | Versioned JSON job definition in the namespaced Redis jobstore and a Redis run-state hash | Reloaded by `RedisJobStore` |
| `code` | In-process `CodeJobRecord` and `MemoryRunState` | Recreated by decorator/object scanning |

The `redis` backend is also the coordinator whenever a Redis jobstore is
attached. In a multi-worker deployment, fire claims are therefore forced to
Redis; `SCHEDULER_COORDINATION=none` applies only when no Redis jobstore is
attached. A single-process deployment without a Redis jobstore may use
`none`.

Every Redis key is namespaced by the manager's `registered_name` (which
defaults to `scheduler_manager`). Jobstore keys, run-state hashes, and fire
coordination keys use the `parrot:scheduler:{registered_name}:` prefix, so
separate managers do not claim one another's fires.

| Key | Purpose | Default |
| --- | --- | --- |
| `SCHEDULER_COORDINATION` | `redis` or `none` fire coordination mode | `none`, unless a Redis jobstore is attached |
| `SCHEDULER_REDIS_DB` | Redis database used by the scheduler jobstore and coordinator | Redis client's configured database |
| `SCHEDULER_FIRE_LOCK_TTL` | Seconds before a scheduled-fire claim expires | `86400` |
| `SCHEDULER_RUN_NOW_LOCK_TTL` | Seconds before a run-now guard expires | `3600` |
| `SCHEDULER_MAX_CONSECUTIVE_FAILURES` | Consecutive `error` or `target_missing` runs before auto-disable | `3` |
| `SCHEDULER_ALERT_RECIPIENTS` | Comma-separated recipients for the single auto-disable alert | unset |

### How a fire is claimed

Before running a coroutine job, a Redis-coordinated worker atomically writes
`parrot:scheduler:{registered_name}:fire:{job_id}:{iso_run_time}` with
`SET NX EX`. The worker that creates that key runs the job; other workers skip
that same due time. The fire-lock TTL is controlled by
`SCHEDULER_FIRE_LOCK_TTL`.

If Redis cannot answer the claim, the scheduler does not run the job
uncoordinated. Database schedules record `last_status = "lock_unavailable"`
in their run-state column. Decorator schedules are skipped because they have
no database row to stamp.

## Missed fires and catch-up

Database and code schedules use their trigger's normal APScheduler misfire
policy. Redis-backed jobs keep their own `misfire_grace_time` in the job
definition; the default is `None`, so a missed fire is eligible for catch-up
after a restart. Redis jobs use `coalesce=True`, meaning multiple missed fire
times are coalesced into one execution. Set a per-job grace time when a job
must expire instead of catching up.

## Propagation of schedule changes

Delete, pause, and update requests change the shared schedule immediately.
Other workers re-read the definition at their next fire: a deleted or paused
row returns a skipped result and removes the local job; an updated schedule
refreshes its local trigger instead of executing stale fields.

## Run-now across workers

Run-now uses `parrot:scheduler:{registered_name}:running:{schedule_id}` with
`SCHEDULER_RUN_NOW_LOCK_TTL`. A concurrent request from another worker is
rejected as HTTP 409 while the first run-now execution holds the guard.

## Migration to ai-parrot-server 1.3.0

The scheduler hard-cut replaces `navigator.agents_scheduler` with
`navigator.service_scheduler`. Create the new table and indexes before
starting the upgraded server:

```sql
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
```

After validating the new table, drop `navigator.agents_scheduler`. Redis keys
also changed to include the registered scheduler name. Existing armed
`ReminderToolkit` reminders use the old key namespace and are not migrated;
re-arm those reminders after upgrading. The `metadata` field now contains
call kwargs only. Run state, including `last_status`, is stored in its own
columns (or the backend's run-state store), not in `metadata`.

## agentd

agentd is a single process and therefore uses coordination mode `none` by
default. Configure Redis when agentd shares schedules with a multi-worker
aiohttp deployment.

## Behaviour change in ai-parrot-server 1.3.0

For existing schedules running on aiohttp, scheduler listeners process
`send_result` emails and callbacks after successful execution. This is a
listener behaviour change in ai-parrot-server 1.3.0.
