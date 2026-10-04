# F002 — Each worker owns an independent scheduler that fires every job
- citations:
  - packages/ai-parrot-server/src/parrot/scheduler/manager.py:338-377 `__init__` creates a per-process AsyncIOScheduler (MemoryJobStore 'default'). job_defaults max_instances=2, which is per process anyway.
  - packages/ai-parrot-server/src/parrot/scheduler/manager.py:1237-1300 `load_schedules_from_db`: every process loads every enabled row with replace_existing=True
  - packages/ai-parrot-server/src/parrot/scheduler/manager.py:1146-1217 `register_bot_schedules`: decorator jobs `auto_<bot>_<method>` are also registered per process and have no DB row
  - packages/ai-parrot-server/src/parrot/scheduler/manager.py:1509-1519 `delete_schedule` and 1431-1441 `pause_schedule` / 1443-1507 `update_schedule` only mutate the *local* scheduler
  - packages/ai-parrot-server/src/parrot/scheduler/manager.py:609-650 `_execute_agent_job` never re-reads the row (no exists/enabled check)
  - packages/ai-parrot-server/src/parrot/scheduler/manager.py:1521-1580 run-now guard `_run_now_active` is an in-memory set, so it is per-process too
- A shared RedisJobStore does NOT fix this. APScheduler 3.x does not support one jobstore shared across scheduler processes: each process polls due jobs and runs them, and processes do not wake on each other's changes.
