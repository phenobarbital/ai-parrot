# F004 — Existing metadata stamping pattern (no DDL needed)
- query: read _update_schedule_run, _on_coordination_unavailable, models.py
- citations:
  - packages/ai-parrot-server/src/parrot/scheduler/manager.py:891-950 `_update_schedule_run(schedule_id, success, error, result)`: stamps `metadata.last_status|last_error|last_error_time|last_result|last_result_time`, via `AgentSchedule.get` + `.update()` inside `self._pool.acquire()`.
  - same file :952-975 `_on_coordination_unavailable`: second, independent metadata stamp (`last_status='lock_unavailable'`) — the pattern to copy for a post-callback delivery stamp.
  - packages/ai-parrot-server/src/parrot/scheduler/models.py `AgentSchedule.metadata: dict` (JSONB), `callbacks: list` (JSONB).
