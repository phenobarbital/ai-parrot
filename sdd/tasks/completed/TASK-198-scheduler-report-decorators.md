# TASK-198: New Report Scheduler Decorators

**Feature**: New Scheduler Decorators (FEAT-028)
**Spec**: `sdd/specs/new-scheduler-decorators.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: S (1h)
**Depends-on**: —
**Assigned-to**: claude-session

---

## Context

> Add `schedule_daily_report` and `schedule_weekly_report` as new no-arg decorators in
> `parrot/scheduler/__init__.py`. Both attach metadata to the wrapped function so that
> `register_bot_schedules()` can detect and process them. Export both from `__all__`.

This is Module 1 + Module 4 from the spec.

---

## Scope

- Add `schedule_daily_report(func)` decorator
- Add `schedule_weekly_report(func)` decorator
- Each attaches:
  - `_schedule_report_type`: `"daily"` or `"weekly"`
  - `_schedule_config`: `{'schedule_type': <value>, 'schedule_config': {}, 'method_name': func.__name__}`
- Both use `@wraps(func)` and return an awaitable wrapper
- Add both to `__all__` in the module

**NOT in scope**: env var resolution, `register_bot_schedules()` changes (those are TASK-199 / TASK-200).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/scheduler/__init__.py` | modify | Add two decorator functions + update `__all__` |

---

## Implementation Guidance

Place the two functions directly below the existing `schedule()` decorator (around line 93).
Follow the exact signatures in spec §2 "New Decorators":

```python
def schedule_daily_report(func: Callable) -> Callable:
    """Mark a method for daily report scheduling.
    Timing is read from `{AGENT_ID}_DAILY_REPORT` env var at registration time.
    Format: "HH:MM" (24-hour, UTC). Defaults to "08:00".
    """
    @wraps(func)
    async def wrapper(*args, **kwargs):
        return await func(*args, **kwargs)
    wrapper._schedule_report_type = "daily"
    wrapper._schedule_config = {
        'schedule_type': ScheduleType.DAILY.value,
        'schedule_config': {},
        'method_name': func.__name__,
    }
    return wrapper


def schedule_weekly_report(func: Callable) -> Callable:
    """Mark a method for weekly report scheduling.
    Timing is read from `{AGENT_ID}_WEEKLY_REPORT` env var at registration time.
    Format: "DDD HH:MM" (e.g. "MON 09:00", 24-hour, UTC). Defaults to "MON 09:00".
    """
    @wraps(func)
    async def wrapper(*args, **kwargs):
        return await func(*args, **kwargs)
    wrapper._schedule_report_type = "weekly"
    wrapper._schedule_config = {
        'schedule_type': ScheduleType.WEEKLY.value,
        'schedule_config': {},
        'method_name': func.__name__,
    }
    return wrapper
```

For `__all__`, locate the existing list and append:
```python
"schedule_daily_report",
"schedule_weekly_report",
```

---

## Acceptance Criteria

- [ ] `from parrot.scheduler import schedule_daily_report, schedule_weekly_report` works
- [ ] `@schedule_daily_report` on an async method → `method._schedule_report_type == "daily"`
- [ ] `@schedule_weekly_report` on an async method → `method._schedule_report_type == "weekly"`
- [ ] `_schedule_config["schedule_type"]` is `"daily"` / `"weekly"` respectively
- [ ] `_schedule_config["schedule_config"]` is `{}` (empty dict)
- [ ] Both decorated methods remain awaitable (can be `await`ed without error)
- [ ] `@wraps` preserves the original function name (`wrapper.__name__ == func.__name__`)
- [ ] Both names appear in `parrot.scheduler.__all__`

---

## Agent Instructions

1. Read `parrot/scheduler/__init__.py` first (full file)
2. Add the two decorator functions after the existing `schedule()` function (~line 93)
3. Update `__all__` to include both names
4. Quick smoke test:
   ```bash
   source .venv/bin/activate
   python -c "
   from parrot.scheduler import schedule_daily_report, schedule_weekly_report
   class Bot:
       @schedule_daily_report
       async def daily(self): pass
       @schedule_weekly_report
       async def weekly(self): pass
   b = Bot()
   assert b.daily._schedule_report_type == 'daily'
   assert b.weekly._schedule_report_type == 'weekly'
   print('OK')
   "
   ```
5. Run full test suite to confirm no regressions:
   ```bash
   pytest tests/test_agent_service.py tests/test_decision_node.py -x -q --no-header 2>&1 | tail -10
   ```
