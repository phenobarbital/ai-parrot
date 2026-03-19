# TASK-200: register_bot_schedules() Enhancement

**Feature**: New Scheduler Decorators (FEAT-028)
**Spec**: `sdd/specs/new-scheduler-decorators.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: M (1-2h)
**Depends-on**: TASK-198, TASK-199
**Assigned-to**: claude-session

---

## Context

> Extend `AgentSchedulerManager.register_bot_schedules()` to detect methods decorated
> with `@schedule_daily_report` / `@schedule_weekly_report` (identified by the
> `_schedule_report_type` attribute) and resolve their trigger config via the env var
> helpers from TASK-199 before passing to `_create_trigger()`.

This is Module 3 from the spec.

---

## Scope

- Modify `register_bot_schedules(self, bot)` in `AgentSchedulerManager`
- After reading `config = method._schedule_config`, check `hasattr(method, '_schedule_report_type')`
- If present:
  1. Resolve `agent_id` from bot: `chatbot_id` → `agent_id` → `name` (in priority order)
  2. Call `_resolve_report_schedule(agent_id, method._schedule_report_type)`
  3. Use the returned dict as `schedule_config` for `_create_trigger()`
- If absent: use `config.get('schedule_config', {})` as before (general `@schedule` path — unchanged)
- Log: `self.logger.debug("Resolving %s report schedule for %s via env var %s", report_type, agent_id, key)` — the key is logged inside `_resolve_report_schedule`

**NOT in scope**: changes to `add_schedule()`, `_create_trigger()`, or any other method.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/scheduler/__init__.py` | modify | `register_bot_schedules()` — add branch for `_schedule_report_type` |

---

## Implementation Guidance

Current loop in `register_bot_schedules()` (around line 857–894):

```python
for name, method in inspect.getmembers(bot, predicate=inspect.ismethod):
    if not hasattr(method, '_schedule_config'):
        continue

    config = method._schedule_config
    schedule_type = config.get('schedule_type')
    schedule_config = config.get('schedule_config', {})
    method_name = config.get('method_name', name)

    try:
        trigger = self._create_trigger(schedule_type, schedule_config)
        ...
```

Change the `schedule_config` resolution line to:

```python
    config = method._schedule_config
    schedule_type = config.get('schedule_type')
    method_name = config.get('method_name', name)

    # Report decorators defer timing resolution to registration time
    if hasattr(method, '_schedule_report_type'):
        report_type = method._schedule_report_type
        agent_id = (
            getattr(bot, 'chatbot_id', None)
            or getattr(bot, 'agent_id', None)
            or getattr(bot, 'name', 'unknown')
        )
        schedule_config = _resolve_report_schedule(agent_id, report_type)
    else:
        schedule_config = config.get('schedule_config', {})

    try:
        trigger = self._create_trigger(schedule_type, schedule_config)
        ...
```

The rest of the loop (job_id, job_name, `scheduler.add_job(...)`) remains unchanged.

---

## Acceptance Criteria

- [ ] A bot with `@schedule_daily_report` method: `register_bot_schedules()` reads env var `{AGENT_ID}_DAILY_REPORT` and creates a `CronTrigger` with the parsed hour/minute
- [ ] A bot with `@schedule_weekly_report` method: `register_bot_schedules()` reads env var `{AGENT_ID}_WEEKLY_REPORT` and creates a `CronTrigger` with day_of_week/hour/minute
- [ ] When no env var is set, defaults are used (hour=8/minute=0 for daily; mon/9/0 for weekly)
- [ ] Agent ID is taken from `bot.chatbot_id` first, then `bot.agent_id`, then `bot.name`
- [ ] A bot with `@schedule(ScheduleType.DAILY, hour=6)` method still uses inline config unchanged
- [ ] A mixed bot (one of each decorator type) registers all 3 jobs successfully
- [ ] `register_bot_schedules()` return count is correct for all three types

---

## Agent Instructions

1. Read `parrot/scheduler/__init__.py` — focus on `register_bot_schedules()` method
2. Apply the diff described in Implementation Guidance
3. Quick integration check:
   ```bash
   source .venv/bin/activate
   python -c "
   import os
   os.environ['MYBOT_DAILY_REPORT'] = '10:30'
   os.environ['MYBOT_WEEKLY_REPORT'] = 'FRI 17:00'
   from parrot.scheduler import AgentSchedulerManager, schedule_daily_report, schedule_weekly_report, schedule, ScheduleType

   class MyBot:
       name = 'mybot'
       @schedule_daily_report
       async def daily(self): pass
       @schedule_weekly_report
       async def weekly(self): pass
       @schedule(schedule_type=ScheduleType.INTERVAL, minutes=15)
       async def poll(self): pass

   mgr = AgentSchedulerManager(bot_manager=None)
   n = mgr.register_bot_schedules(MyBot())
   assert n == 3, f'Expected 3, got {n}'
   jobs = {j.id: j for j in mgr.scheduler.get_jobs()}
   print('Jobs:', list(jobs.keys()))
   print('OK')
   "
   ```
4. Run regression tests:
   ```bash
   pytest tests/test_agent_service.py tests/test_decision_node.py -x -q --no-header 2>&1 | tail -10
   ```
