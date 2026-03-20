# TASK-199: Env Var Resolution Helpers

**Feature**: New Scheduler Decorators (FEAT-028)
**Spec**: `sdd/specs/new-scheduler-decorators.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: S (1h)
**Depends-on**: TASK-198
**Assigned-to**: claude-session

---

## Context

> Add three private helper functions to `parrot/scheduler/__init__.py` that resolve the
> APScheduler trigger config from environment variables (via `navconfig.config.get()`),
> with safe fallbacks to defaults.

This is Module 2 from the spec.

---

## Scope

- `_resolve_report_schedule(agent_id: str, report_type: str) -> dict`
  - Builds env var key: `{agent_id.upper().replace('-','_').replace(' ','_')}_{report_type.upper()}_REPORT`
  - Reads value via `from navconfig import config as nav_config; nav_config.get(key)`
  - Dispatches to `_parse_daily_schedule` or `_parse_weekly_schedule`
- `_parse_daily_schedule(raw: Optional[str]) -> dict`
  - Parses `"HH:MM"` → `{"hour": H, "minute": M}`
  - Returns `{"hour": 8, "minute": 0}` on `None` or malformed input
- `_parse_weekly_schedule(raw: Optional[str]) -> dict`
  - Parses `"DDD HH:MM"` → `{"day_of_week": "ddd", "hour": H, "minute": M}`
  - Accepts full day names (`"monday"`) — takes first 3 chars and lowercases
  - Returns `{"day_of_week": "mon", "hour": 9, "minute": 0}` on `None` or malformed input
- Malformed input: log a `self.logger.warning(...)` (use module-level logger, not self) and return default

**NOT in scope**: calling these helpers from `register_bot_schedules()` (that is TASK-200).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/scheduler/__init__.py` | modify | Add three private helper functions |

---

## Implementation Guidance

Place helpers as module-level functions (not methods) just before `AgentSchedulerManager`,
or after the decorators added in TASK-198. Use the module-level logger:

```python
_scheduler_logger = logging.getLogger('Parrot.Scheduler')
```

Or, since they are module-level, use:
```python
import logging as _logging
_log = _logging.getLogger('Parrot.Scheduler')
```

Key implementation notes from spec §6:

1. **Key construction** — sanitise agent_id before uppercasing:
   ```python
   safe_id = agent_id.upper().replace('-', '_').replace(' ', '_')
   key = f"{safe_id}_{report_type.upper()}_REPORT"
   ```

2. **navconfig import** — do it inside `_resolve_report_schedule` to avoid circular imports:
   ```python
   def _resolve_report_schedule(agent_id: str, report_type: str) -> dict:
       from navconfig import config as nav_config
       ...
   ```

3. **Parser fallbacks** — swallow `ValueError`, `IndexError`, `AttributeError`; log warning:
   ```python
   except (ValueError, IndexError, AttributeError):
       _log.warning("Could not parse %s=%r; using default %s schedule", key, raw, report_type)
       # fall through to default return
   ```

---

## Acceptance Criteria

- [ ] `_parse_daily_schedule("08:30")` → `{"hour": 8, "minute": 30}`
- [ ] `_parse_daily_schedule("10:15")` → `{"hour": 10, "minute": 15}`
- [ ] `_parse_daily_schedule(None)` → `{"hour": 8, "minute": 0}`
- [ ] `_parse_daily_schedule("bad")` → `{"hour": 8, "minute": 0}` (no exception)
- [ ] `_parse_weekly_schedule("FRI 17:00")` → `{"day_of_week": "fri", "hour": 17, "minute": 0}`
- [ ] `_parse_weekly_schedule("monday 09:30")` → `{"day_of_week": "mon", "hour": 9, "minute": 30}`
- [ ] `_parse_weekly_schedule("MONDAY 09:30")` → `{"day_of_week": "mon", ...}` (uppercase accepted)
- [ ] `_parse_weekly_schedule(None)` → `{"day_of_week": "mon", "hour": 9, "minute": 0}`
- [ ] `_parse_weekly_schedule("bad")` → `{"day_of_week": "mon", "hour": 9, "minute": 0}` (no exception)
- [ ] `_resolve_report_schedule("my-bot", "daily")` constructs key `MY_BOT_DAILY_REPORT`
- [ ] `_resolve_report_schedule("MyAgent", "weekly")` constructs key `MYAGENT_WEEKLY_REPORT`

---

## Agent Instructions

1. Read `parrot/scheduler/__init__.py` (focus on the imports section and area after `schedule()`)
2. Add the three helper functions as described
3. Quick smoke test:
   ```bash
   source .venv/bin/activate
   python -c "
   from parrot.scheduler import _parse_daily_schedule, _parse_weekly_schedule
   assert _parse_daily_schedule('08:30') == {'hour': 8, 'minute': 30}
   assert _parse_daily_schedule(None) == {'hour': 8, 'minute': 0}
   assert _parse_weekly_schedule('FRI 17:00') == {'day_of_week': 'fri', 'hour': 17, 'minute': 0}
   assert _parse_weekly_schedule(None) == {'day_of_week': 'mon', 'hour': 9, 'minute': 0}
   print('OK')
   "
   ```
4. Run regression check:
   ```bash
   pytest tests/test_agent_service.py -x -q --no-header 2>&1 | tail -5
   ```
