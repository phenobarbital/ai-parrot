# Agent scheduler in multi-worker deployments

## Overview

When more than one aiohttp or gunicorn worker loads the same database schedule, each local APScheduler sees the same due fire. Without coordination this can execute an agent, callback, or `send_result` email more than once. Issue #1573 is addressed by making one worker claim each fire before it runs.

## Coordination modes

Set `SCHEDULER_COORDINATION` to `redis` for multi-worker deployments. The `none` mode is the single-process default and lets every local fire run. Only `redis` and `none` are valid values.

## Configuration

| Key | Purpose | Default |
| --- | --- | --- |
| `SCHEDULER_COORDINATION` | Fire-coordination mode: `redis` or `none`. | `none`, unless the legacy Redis-jobstore option is enabled |
| `SCHEDULER_FIRE_LOCK_TTL` | Redis TTL, in seconds, for a scheduled-fire claim. | `86400` |
| `SCHEDULER_RUN_NOW_LOCK_TTL` | Redis TTL, in seconds, for a run-now guard. | `3600` |

## How a fire is claimed

Before running a coroutine job, a Redis-coordinated worker atomically writes `parrot:scheduler:fire:{job_id}:{iso_run_time}` with `SET NX EX`. The worker that creates that key runs the job; other workers skip that same due time. The fire-lock TTL is controlled by `SCHEDULER_FIRE_LOCK_TTL`.

## Fail-closed behaviour

If Redis cannot answer the claim, the scheduler does not run the job uncoordinated. DB-backed schedules retain their existing run count and are stamped with `metadata.last_status = "lock_unavailable"` and an error describing the coordination failure. Decorator schedules are also skipped, but have no DB row to stamp.

## Propagation of schedule changes

Delete, pause, and update requests change the shared database schedule immediately. Other workers re-read the row at their next fire: a deleted or paused row returns a skipped result and removes the local job; an updated schedule refreshes its local trigger instead of executing stale fields.

## Run-now across workers

Run-now uses `parrot:scheduler:running:{schedule_id}` with `SCHEDULER_RUN_NOW_LOCK_TTL`. A concurrent request from another worker is rejected as HTTP 409 while the first run-now execution holds the guard.

## Redis jobstore is not coordination

Using `scheduler_type="redis"` persists APScheduler jobs in a Redis jobstore. That persistence does not coordinate execution between workers. Multi-worker deployments still need `SCHEDULER_COORDINATION=redis` for single-fire claims.

## agentd

agentd is a single process and therefore uses coordination mode `none` by default. Configure Redis coordination when agentd shares schedule rows with a multi-worker aiohttp deployment.

## Behaviour change in ai-parrot-server 0.28.0

For existing DB schedules running on aiohttp, scheduler listeners now process `send_result` emails and callbacks after successful execution. This is a listener behaviour change in ai-parrot-server 0.28.0.
