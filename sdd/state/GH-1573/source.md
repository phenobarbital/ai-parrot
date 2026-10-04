---
kind: github_issue
github_issue: phenobarbital/ai-parrot#1573
url: https://github.com/phenobarbital/ai-parrot/issues/1573
fetched_at: 2026-10-05T01:15:00Z
labels: [bug]
state: open
summary_oneline: Scheduler on aiohttp: listeners never wired, every worker fires every job, redis jobstore cannot pickle jobs
---

# scheduler: listeners disabled on the aiohttp path; duplicate firing with multiple workers; redis jobstore cannot pickle jobs

1. **Listeners are off.** The aiohttp `on_startup` calls `start_headless(use_redis=True, register_listeners=False)`. For DB schedules, success therefore never updates `last_run`/`run_count`/`last_result`/`next_run`, and `send_result` and `CALLBACK_REGISTRY` callbacks never run. This differs from the headless/agentd path.
2. **Duplicate firing with multiple workers.** Every process loads every schedule and fires it: two workers deliver twice. `delete_schedule` in one worker does not stop the job in another. `_execute_agent_job` does not re-check that the row still exists and is enabled.
3. **Redis jobstore.** `scheduler_type="redis"` fails for DB schedules because the bound method `self._execute_agent_job` cannot be pickled. A module-level trampoline would fix it.

**Suggested fixes:** wire the listeners consistently (or document why not); leader election or a distributed lock per fire; re-check the row before executing; a picklable job function.

_Found while integrating ai-parrot-server's scheduler and ai-parrot-visualizations' A2UI renderers into an external package (reportbuilder). Versions: ai-parrot 0.18.9, ai-parrot-server 0.27.1, ai-parrot-visualizations 1.0.7, apscheduler 3.11.2._
