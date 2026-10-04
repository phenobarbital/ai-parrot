# F003 — Redis jobstore cannot serialize bound-method jobs (reproduced)
- citations:
  - packages/ai-parrot-server/src/parrot/scheduler/manager.py:1071-1082 add_schedule, 1271-1288 load_schedules_from_db, 1493-1501 update_schedule and 1567-1575 run_schedule_now all pass the bound method `self._execute_agent_job` / `self._run_now_wrapper` as func
  - APScheduler 3.11.2 `Job.__getstate__`: for an instance method it prepends `func.__self__` to args, which pickles the whole manager
- Repro (venv, 2026-10-05): `pickle.dumps(AgentSchedulerManager())` raises `TypeError: Schedulers cannot be serialized ... scheduling an instance method where the instance contains a scheduler as an attribute.`
- Also: add_schedule puts `success_callback` (an arbitrary callable) into job kwargs, which is unpicklable for lambdas and closures. A redis job must carry only JSON-able kwargs (schedule_id is enough; everything else can be re-read from the row).
- Effect: add_schedule(scheduler_type='redis') hits the rollback branch ("Failed to add schedule to jobstore"); load_schedules_from_db logs a per-row failure.
