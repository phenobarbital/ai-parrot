# F001 — Listeners are explicitly disabled on the aiohttp path
- query: grep register_listeners / read on_startup + start_headless
- citations:
  - packages/ai-parrot-server/src/parrot/scheduler/manager.py:1720-1768 `AgentSchedulerManager.start_headless(register_listeners=True)`, which calls `define_listeners()` only when it is True (1759)
  - packages/ai-parrot-server/src/parrot/scheduler/manager.py:1831-1853 `on_startup`, which calls `start_headless(use_redis=True, register_listeners=False)`. Its comment says this was deliberately "behaviour-preserving" for FEAT-422.
  - packages/ai-parrot-server/src/parrot/scheduler/manager.py:447-453 `define_listeners`, which wires job_success (EVENT_JOB_EXECUTED), job_status (ERROR|MISSED), job_added and scheduler status
  - packages/ai-parrot-server/src/parrot/scheduler/manager.py:609-702 `_execute_agent_job` only *stashes* context in `_job_context` on success. The DB stamp, callbacks and send_result all run from `job_success` → `_process_job_success` (791-835).
- Consequence: on aiohttp, success never stamps last_run/run_count/last_result, never sends send_result, never runs callbacks. `_job_context` entries also leak forever (they are never popped without the listener). The failure path still stamps the DB (the except clause in _execute_agent_job calls `_update_schedule_run(success=False)`), so the DB shows errors but no successes.
- Latent bugs that wiring exposes: `job_status` (471-513) does `job.name` while `get_job` may return None (one-shot or removed job), which raises AttributeError. `scheduler_status` calls `print(event)` (457), which is banned. `next_run` is never refreshed after a fire or on load.
