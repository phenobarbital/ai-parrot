# F003 — Manager discards callback outcomes and stamps success first
- query: grep callback in scheduler/manager.py; read 585-640, 730-870
- citations:
  - packages/ai-parrot-server/src/parrot/scheduler/manager.py:733-754 `_handle_job_success`: `await callback(result, ...)` return value discarded; loop has no per-callback try, so a raising callback aborts later callbacks and `send_result`.
  - same file :756-818 `_send_result_email`: `await notifier.send_email(...)` result discarded (uses `_SchedulerNotification(NotificationMixin)` at :342-346).
  - same file :820-865 `_process_job_success`: `_update_schedule_run(success=True)` runs BEFORE callbacks; callback exceptions only `logger.error`'d ("pragma: no cover - safety net").
  - same file :621-634 job_success schedules `_process_job_success` as a fire-and-forget task in `_pending_success_tasks`.
