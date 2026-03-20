# Feature Specification: New Scheduler Decorators

**Feature ID**: FEAT-028
**Date**: 2026-03-06
**Author**: Jesus Lara
**Status**: approved
**Target version**: next
**Depends on**: None (extends `parrot/scheduler/__init__.py`)

---

## 1. Motivation & Business Requirements

### Problem Statement

The existing `@schedule(schedule_type=ScheduleType.DAILY, hour=8, minute=0)` decorator is general-purpose but requires the developer to supply timing values explicitly and inline. For the two most common recurring report patterns — **daily reports** and **weekly digests** — the desired schedule should be operator-configurable via environment variables so that deployment environments (staging, prod, local) can each use different times without code changes.

There is currently no way to say:

> "Register this method to run daily at whatever time is configured in the environment for this agent, defaulting to 8 AM."

The result: every bot that needs a daily or weekly report must hardcode `hour=` and `minute=` in the decorator, making schedule tuning a deployment-time code change.

### Goals

- Add `@schedule_daily_report` decorator: marks a method to run **daily** at a time read from `{AGENT_ID}_DAILY_REPORT` env var, defaulting to `08:00 UTC`
- Add `@schedule_weekly_report` decorator: marks a method to run **weekly** (Monday by default) at a time read from `{AGENT_ID}_WEEKLY_REPORT` env var, defaulting to `Mon 09:00 UTC`
- Both decorators integrate transparently with the existing `register_bot_schedules()` machinery
- Env var is resolved at **registration time** (when the bot instance is available and its `agent_id` / `name` is known), not at decoration time
- Config is read via `from navconfig import config` → `config.get(key)`

### Non-Goals

- Changing `AgentSchedulerManager.add_schedule()` (DB-backed scheduling)
- Changing the general `@schedule()` decorator
- Validating or normalising env var contents beyond what is needed to extract `hour`, `minute`, and `day_of_week`
- Supporting time zones other than UTC (the existing scheduler uses `timezone='UTC'`)

---

## 2. Architectural Design

### Overview

```
@schedule_daily_report          @schedule_weekly_report
         │                               │
 stores _schedule_report_type='daily'   stores _schedule_report_type='weekly'
 (no timing values at decoration time)
         │                               │
         └───────────────┬───────────────┘
                         ▼
           register_bot_schedules(bot)
                         │
           ┌─────────────┴──────────────────┐
           │  detect _schedule_report_type  │
           │  resolve agent_id from bot     │
           │  read env var via config.get() │
           │  parse → hour / minute / dow   │
           │  fall back to defaults         │
           └─────────────┬──────────────────┘
                         ▼
               _create_trigger(schedule_type, config)
                         │
               scheduler.add_job(...)
```

### New Decorators

Both decorators are thin factories in `parrot/scheduler/__init__.py`. They attach a `_schedule_report_type` attribute to the wrapped function so that `register_bot_schedules()` can detect and handle them.

```python
# parrot/scheduler/__init__.py (additions)

def schedule_daily_report(func: Callable) -> Callable:
    """Mark a method for daily report scheduling.

    Timing is read from `{AGENT_ID}_DAILY_REPORT` env var at registration time.
    Format: "HH:MM" (24-hour, UTC). Defaults to "08:00".

    Usage:
        @schedule_daily_report
        async def generate_daily_report(self):
            ...
    """
    @wraps(func)
    async def wrapper(*args, **kwargs):
        return await func(*args, **kwargs)

    wrapper._schedule_report_type = "daily"
    wrapper._schedule_config = {
        'schedule_type': ScheduleType.DAILY.value,
        'schedule_config': {},          # resolved at register time
        'method_name': func.__name__,
    }
    return wrapper


def schedule_weekly_report(func: Callable) -> Callable:
    """Mark a method for weekly report scheduling.

    Timing is read from `{AGENT_ID}_WEEKLY_REPORT` env var at registration time.
    Format: "DDD HH:MM" (e.g. "MON 09:00", 24-hour, UTC).
    Defaults to "MON 09:00".

    Usage:
        @schedule_weekly_report
        async def generate_weekly_digest(self):
            ...
    """
    @wraps(func)
    async def wrapper(*args, **kwargs):
        return await func(*args, **kwargs)

    wrapper._schedule_report_type = "weekly"
    wrapper._schedule_config = {
        'schedule_type': ScheduleType.WEEKLY.value,
        'schedule_config': {},          # resolved at register time
        'method_name': func.__name__,
    }
    return wrapper
```

### Env Var Resolution

`register_bot_schedules()` is extended to detect `_schedule_report_type` and resolve the env var **before** calling `_create_trigger()`.

```python
# Inside register_bot_schedules(), for each method with _schedule_config:

if hasattr(method, '_schedule_report_type'):
    report_type = method._schedule_report_type     # "daily" | "weekly"
    agent_id = (
        getattr(bot, 'chatbot_id', None)
        or getattr(bot, 'agent_id', None)
        or getattr(bot, 'name', 'unknown')
    )
    schedule_config = _resolve_report_schedule(agent_id, report_type)
else:
    schedule_config = config.get('schedule_config', {})
```

### `_resolve_report_schedule()` Helper

A new private helper in `parrot/scheduler/__init__.py`:

```python
def _resolve_report_schedule(agent_id: str, report_type: str) -> dict:
    """Resolve schedule config from env var or defaults.

    Args:
        agent_id: Agent identifier (used to build the env var key).
        report_type: "daily" or "weekly".

    Returns:
        Dict suitable for _create_trigger(schedule_type, config).
    """
    from navconfig import config as nav_config

    key = f"{agent_id.upper()}_{report_type.upper()}_REPORT"
    raw = nav_config.get(key)           # e.g. "08:30" or "FRI 17:00"

    if report_type == "daily":
        return _parse_daily_schedule(raw)
    else:
        return _parse_weekly_schedule(raw)


def _parse_daily_schedule(raw: Optional[str]) -> dict:
    """Parse "HH:MM" → {hour, minute}. Defaults to 08:00."""
    if raw:
        try:
            h, m = (int(x) for x in raw.strip().split(":"))
            return {"hour": h, "minute": m}
        except (ValueError, AttributeError):
            pass
    return {"hour": 8, "minute": 0}     # default: 08:00 UTC


def _parse_weekly_schedule(raw: Optional[str]) -> dict:
    """Parse "DDD HH:MM" → {day_of_week, hour, minute}. Defaults to mon 09:00."""
    if raw:
        try:
            parts = raw.strip().split()
            dow = parts[0].lower()[:3]  # "monday" → "mon", "MON" → "mon"
            h, m = (int(x) for x in parts[1].split(":"))
            return {"day_of_week": dow, "hour": h, "minute": m}
        except (ValueError, IndexError, AttributeError):
            pass
    return {"day_of_week": "mon", "hour": 9, "minute": 0}  # default: Mon 09:00 UTC
```

### Env Var Format

| Env var | Format | Example | Meaning |
|---|---|---|---|
| `{AGENT_ID}_DAILY_REPORT` | `HH:MM` | `08:30` | Run daily at 08:30 UTC |
| `{AGENT_ID}_WEEKLY_REPORT` | `DDD HH:MM` | `FRI 17:00` | Run every Friday at 17:00 UTC |

`DDD` accepts full names (`monday`, `MONDAY`) or 3-letter abbreviations (`mon`, `MON`). The first 3 characters are taken and lowercased for APScheduler compatibility.

### Integration with `register_bot_schedules()`

The method already calls `_create_trigger(schedule_type, schedule_config)`. The only change is that for report-type decorators, `schedule_config` is populated from env var resolution instead of from the decorator-time dict (which is `{}`).

```
Before (general @schedule):
  method._schedule_config['schedule_config'] → {hour: 8, minute: 0}
  → passed directly to _create_trigger()

After (report decorators):
  method._schedule_config['schedule_config'] → {}  (empty, deferred)
  method._schedule_report_type              → "daily" | "weekly"
  → _resolve_report_schedule(agent_id, report_type) called first
  → result passed to _create_trigger()
```

### Integration Points

| Component | Change Type | Notes |
|---|---|---|
| `parrot/scheduler/__init__.py` | add | `schedule_daily_report`, `schedule_weekly_report` decorators |
| `parrot/scheduler/__init__.py` | add | `_resolve_report_schedule`, `_parse_daily_schedule`, `_parse_weekly_schedule` helpers |
| `parrot/scheduler/__init__.py` | modify | `register_bot_schedules()` — detect `_schedule_report_type`, call resolver |
| `parrot/scheduler/__init__.py` | modify | module `__all__` — export new decorators |

---

## 3. Module Breakdown

### Module 1: New Decorators

- **Path**: `parrot/scheduler/__init__.py` (modify)
- **Responsibility**:
  - Add `schedule_daily_report(func)` decorator
  - Add `schedule_weekly_report(func)` decorator
  - Both attach `_schedule_report_type` and a skeleton `_schedule_config` (with empty `schedule_config` dict and `schedule_type` set)
  - Both preserve the wrapped function's signature via `@wraps`
  - Both remain awaitable
- **Depends on**: None (within same module)

### Module 2: Env Var Resolution Helpers

- **Path**: `parrot/scheduler/__init__.py` (modify)
- **Responsibility**:
  - `_resolve_report_schedule(agent_id, report_type) -> dict`
  - `_parse_daily_schedule(raw: Optional[str]) -> dict`
  - `_parse_weekly_schedule(raw: Optional[str]) -> dict`
  - Parse format: `HH:MM` for daily, `DDD HH:MM` for weekly
  - Silently fall back to defaults on malformed input (log a warning)
- **Depends on**: `navconfig` (already used in this module)

### Module 3: `register_bot_schedules()` Enhancement

- **Path**: `parrot/scheduler/__init__.py` (modify)
- **Responsibility**:
  - After reading `_schedule_config` from a method, check for `_schedule_report_type`
  - If present: resolve agent_id from bot instance (`chatbot_id` → `agent_id` → `name`), call `_resolve_report_schedule()`
  - Pass resolved config to `_create_trigger()`
  - Log which env var key was consulted and whether the default was used
- **Depends on**: Modules 1, 2

### Module 4: Exports

- **Path**: `parrot/scheduler/__init__.py` (modify)
- **Responsibility**:
  - Add `schedule_daily_report` and `schedule_weekly_report` to `__all__`
- **Depends on**: Module 1

---

## 4. Test Specification

### Unit Tests

| Test | Module | Description |
|---|---|---|
| `test_daily_decorator_attaches_report_type` | 1 | `@schedule_daily_report` → method has `_schedule_report_type == "daily"` |
| `test_weekly_decorator_attaches_report_type` | 1 | `@schedule_weekly_report` → method has `_schedule_report_type == "weekly"` |
| `test_daily_decorator_attaches_schedule_config` | 1 | `_schedule_config["schedule_type"] == "daily"` |
| `test_weekly_decorator_attaches_schedule_config` | 1 | `_schedule_config["schedule_type"] == "weekly"` |
| `test_daily_decorator_preserves_awaitable` | 1 | Decorated async method still awaitable |
| `test_weekly_decorator_preserves_awaitable` | 1 | Decorated async method still awaitable |
| `test_parse_daily_valid` | 2 | `_parse_daily_schedule("08:30")` → `{hour:8, minute:30}` |
| `test_parse_daily_default` | 2 | `_parse_daily_schedule(None)` → `{hour:8, minute:0}` |
| `test_parse_daily_malformed` | 2 | `_parse_daily_schedule("bad")` → default `{hour:8, minute:0}` |
| `test_parse_weekly_valid` | 2 | `_parse_weekly_schedule("FRI 17:00")` → `{day_of_week:"fri", hour:17, minute:0}` |
| `test_parse_weekly_full_name` | 2 | `_parse_weekly_schedule("monday 09:30")` → `{day_of_week:"mon", hour:9, minute:30}` |
| `test_parse_weekly_default` | 2 | `_parse_weekly_schedule(None)` → `{day_of_week:"mon", hour:9, minute:0}` |
| `test_parse_weekly_malformed` | 2 | `_parse_weekly_schedule("bad")` → default `{day_of_week:"mon", hour:9, minute:0}` |
| `test_register_daily_reads_env_var` | 3 | Bot with `@schedule_daily_report`; env var `MYBOT_DAILY_REPORT=10:15` → job trigger hour=10, minute=15 |
| `test_register_daily_uses_default_when_no_env_var` | 3 | No env var set → job trigger hour=8, minute=0 |
| `test_register_weekly_reads_env_var` | 3 | `MYBOT_WEEKLY_REPORT=FRI 17:00` → trigger day_of_week=fri, hour=17 |
| `test_register_weekly_uses_default_when_no_env_var` | 3 | No env var → trigger day_of_week=mon, hour=9 |
| `test_register_uses_chatbot_id_for_env_key` | 3 | `bot.chatbot_id = "analytics_bot"` → key `ANALYTICS_BOT_DAILY_REPORT` consulted |
| `test_register_falls_back_to_name_for_env_key` | 3 | No `chatbot_id`; `bot.name = "ReportBot"` → key `REPORTBOT_DAILY_REPORT` consulted |
| `test_general_schedule_unaffected` | 3 | `@schedule(ScheduleType.DAILY, hour=6)` still works unchanged |
| `test_mixed_bot_registers_all` | 3 | Bot with one `@schedule`, one `@schedule_daily_report`, one `@schedule_weekly_report` → 3 jobs registered |

### Verification Script Update

Add a Section 5 to `examples/verify_scheduler.py`:

```python
# Section 5 – @schedule_daily_report / @schedule_weekly_report

def test_report_decorators() -> None:
    from parrot.scheduler import schedule_daily_report, schedule_weekly_report

    class ReportBot:
        name = "ReportBot"
        chatbot_id = "report_bot"

        @schedule_daily_report
        async def daily_summary(self):
            pass

        @schedule_weekly_report
        async def weekly_digest(self):
            pass

    bot = ReportBot()

    # Decorator metadata
    check("daily_summary has _schedule_report_type=='daily'",
          bot.daily_summary._schedule_report_type == "daily")
    check("weekly_digest has _schedule_report_type=='weekly'",
          bot.weekly_digest._schedule_report_type == "weekly")

    # Registration with env var override
    import os
    os.environ["REPORT_BOT_DAILY_REPORT"] = "10:15"
    os.environ["REPORT_BOT_WEEKLY_REPORT"] = "FRI 17:00"

    mgr = AgentSchedulerManager(bot_manager=None)
    registered = mgr.register_bot_schedules(bot)
    check("register_bot_schedules returns 2", registered == 2)

    jobs = {j.id: j for j in mgr.scheduler.get_jobs()}
    daily_trigger = jobs["auto_report_bot_daily_summary"].trigger
    weekly_trigger = jobs["auto_report_bot_weekly_digest"].trigger

    check("daily_summary → CronTrigger", isinstance(daily_trigger, CronTrigger))
    check("weekly_digest → CronTrigger", isinstance(weekly_trigger, CronTrigger))
```

### Verification Commands

```bash
source .venv/bin/activate

# Decorator metadata check
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
print('Decorator metadata: OK')
"

# Env var resolution check
MYAGENT_DAILY_REPORT=10:30 python -c "
import os
from parrot.scheduler import _parse_daily_schedule, _parse_weekly_schedule
print('daily 10:30 ->', _parse_daily_schedule('10:30'))
print('weekly FRI 17:00 ->', _parse_weekly_schedule('FRI 17:00'))
print('daily default ->', _parse_daily_schedule(None))
print('weekly default ->', _parse_weekly_schedule(None))
"

# Registration check
python -c "
import os; os.environ['MYBOT_DAILY_REPORT'] = '09:00'
from parrot.scheduler import AgentSchedulerManager, schedule_daily_report, schedule_weekly_report

class MyBot:
    name = 'mybot'
    @schedule_daily_report
    async def daily_report(self): pass
    @schedule_weekly_report
    async def weekly_report(self): pass

mgr = AgentSchedulerManager(bot_manager=None)
n = mgr.register_bot_schedules(MyBot())
print(f'Registered {n} jobs:')
for j in mgr.scheduler.get_jobs():
    print(f'  {j.name}: {j.trigger}')
"

# Full test run
pytest tests/ -k "scheduler_decorators or daily_report or weekly_report" -v --no-header 2>&1 | head -60
```

---

## 5. Acceptance Criteria

- [ ] `schedule_daily_report` is importable from `parrot.scheduler`
- [ ] `schedule_weekly_report` is importable from `parrot.scheduler`
- [ ] Both decorators attach `_schedule_report_type` (`"daily"` / `"weekly"`) to the wrapped method
- [ ] Both decorators attach `_schedule_config` with the correct `schedule_type` value
- [ ] Both decorated methods remain awaitable
- [ ] `_parse_daily_schedule("HH:MM")` returns `{hour, minute}` correctly
- [ ] `_parse_weekly_schedule("DDD HH:MM")` returns `{day_of_week, hour, minute}` correctly
- [ ] Both parsers accept full day names (`"monday"`) and normalise to 3-letter lowercase
- [ ] Both parsers return defaults (`{hour:8, minute:0}` / `{day_of_week:"mon", hour:9, minute:0}`) when input is `None` or malformed
- [ ] `register_bot_schedules()` detects `_schedule_report_type` and calls `_resolve_report_schedule()`
- [ ] `_resolve_report_schedule()` reads `{AGENT_ID}_DAILY_REPORT` / `{AGENT_ID}_WEEKLY_REPORT` using `navconfig.config.get()`
- [ ] Agent ID resolution priority: `chatbot_id` → `agent_id` → `name`
- [ ] When env var is set, that time is used for the APScheduler trigger
- [ ] When env var is absent or malformed, the default is used and a warning is logged
- [ ] `@schedule()` (general decorator) is completely unaffected
- [ ] `examples/verify_scheduler.py` extended with report-decorator section, all checks passing
- [ ] All existing tests pass

---

## 6. Implementation Notes & Constraints

### Env Var Key Construction

The key is `f"{agent_id.upper()}_{report_type.upper()}_REPORT"`.
- `agent_id = "analytics_bot"` + `report_type = "daily"` → `ANALYTICS_BOT_DAILY_REPORT`
- `agent_id = "MyAgent"` → uppercased to `MYAGENT`

Spaces and hyphens in `agent_id` should be replaced with `_` before uppercasing to avoid invalid env var names:
```python
key = f"{agent_id.upper().replace('-', '_').replace(' ', '_')}_{report_type.upper()}_REPORT"
```

### Malformed Env Var Handling

Log a warning and fall back to the default; do **not** raise an exception. Scheduler registration should never fail due to a bad env var value.

```python
self.logger.warning(
    "Could not parse %s=%r; using default %s schedule",
    key, raw, report_type
)
```

### Why Deferred Resolution (not at decoration time)

The decorator is evaluated at class definition time, before any bot instance exists. `agent_id` is instance-level data. Reading the env var at decoration time would require passing `agent_id` explicitly to the decorator, breaking the no-arg usage pattern. Deferring to `register_bot_schedules()` keeps the decorator API clean:

```python
# Target API — no arguments needed:
@schedule_daily_report
async def daily_report(self): ...

# vs. the more verbose alternative we want to avoid:
@schedule_daily_report(agent_id="my_agent")
async def daily_report(self): ...
```

### `navconfig` Import

`from navconfig import config` is already used elsewhere in `parrot.scheduler` (via `CACHE_HOST`, `CACHE_PORT`). Add the import inside `_resolve_report_schedule()` to avoid circular imports (consistent with existing patterns in the codebase).

### APScheduler Trigger

Both decorators result in a `CronTrigger` via `_create_trigger()`:
- Daily: `CronTrigger(hour=H, minute=M)` — runs every day at H:M UTC
- Weekly: `CronTrigger(day_of_week=D, hour=H, minute=M)` — runs every week on day D at H:M UTC

This is identical to the existing `ScheduleType.DAILY` and `ScheduleType.WEEKLY` paths in `_create_trigger()`.

---

## 7. Open Questions

- [ ] Should `_parse_weekly_schedule` also support multiple days (e.g. `"MON,WED 09:00"` → run twice a week)? — *Default: no, single day only for now; can be extended later*
- [ ] Should the env var format support full ISO times with seconds (`HH:MM:SS`)? — *Default: no, `HH:MM` is sufficient*
- [ ] Should a malformed env var trigger a hard error in strict environments? — *Default: no, always warn + fall back*

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-03-06 | Jesus Lara | Initial draft |
