# TASK-201: Unit Tests + Verify Script — Report Scheduler Decorators

**Feature**: New Scheduler Decorators (FEAT-028)
**Spec**: `sdd/specs/new-scheduler-decorators.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: M (2h)
**Depends-on**: TASK-198, TASK-199, TASK-200
**Assigned-to**: claude-session

---

## Context

> Write the full pytest unit test suite for FEAT-028 and extend the existing
> `examples/verify_scheduler.py` sample script with a Section 5 covering the
> new report decorators.

---

## Scope

- Create `tests/test_scheduler_report_decorators.py` with all 21 tests from spec §4
- Extend `examples/verify_scheduler.py` with `test_report_decorators()` (Section 5)

**NOT in scope**: integration tests that start a full bot stack.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `tests/test_scheduler_report_decorators.py` | CREATE | Full unit test suite |
| `examples/verify_scheduler.py` | modify | Add Section 5 for report decorators |

---

## Test Cases

### Decorator Metadata (Module 1)

| Test | Description |
|---|---|
| `test_daily_decorator_attaches_report_type` | `_schedule_report_type == "daily"` |
| `test_weekly_decorator_attaches_report_type` | `_schedule_report_type == "weekly"` |
| `test_daily_decorator_schedule_type_value` | `_schedule_config["schedule_type"] == "daily"` |
| `test_weekly_decorator_schedule_type_value` | `_schedule_config["schedule_type"] == "weekly"` |
| `test_daily_decorator_schedule_config_empty` | `_schedule_config["schedule_config"] == {}` |
| `test_weekly_decorator_schedule_config_empty` | `_schedule_config["schedule_config"] == {}` |
| `test_daily_decorator_preserves_name` | `method.__name__ == "daily_report"` |
| `test_weekly_decorator_preserves_name` | `method.__name__ == "weekly_report"` |
| `test_daily_decorator_awaitable` | `asyncio.run(bot.daily())` completes without error |
| `test_weekly_decorator_awaitable` | `asyncio.run(bot.weekly())` completes without error |

### Env Var Parsers (Module 2)

| Test | Description |
|---|---|
| `test_parse_daily_valid` | `_parse_daily_schedule("08:30")` → `{"hour": 8, "minute": 30}` |
| `test_parse_daily_single_digit` | `_parse_daily_schedule("9:05")` → `{"hour": 9, "minute": 5}` |
| `test_parse_daily_default_on_none` | `_parse_daily_schedule(None)` → `{"hour": 8, "minute": 0}` |
| `test_parse_daily_default_on_malformed` | `_parse_daily_schedule("bad")` → `{"hour": 8, "minute": 0}` |
| `test_parse_weekly_valid_abbrev` | `_parse_weekly_schedule("FRI 17:00")` → `{"day_of_week": "fri", "hour": 17, "minute": 0}` |
| `test_parse_weekly_full_name` | `_parse_weekly_schedule("monday 09:30")` → `{"day_of_week": "mon", "hour": 9, "minute": 30}` |
| `test_parse_weekly_uppercase` | `_parse_weekly_schedule("WEDNESDAY 12:00")` → `{"day_of_week": "wed", ...}` |
| `test_parse_weekly_default_on_none` | `_parse_weekly_schedule(None)` → `{"day_of_week": "mon", "hour": 9, "minute": 0}` |
| `test_parse_weekly_default_on_malformed` | `_parse_weekly_schedule("bad")` → default |

### `register_bot_schedules()` Integration (Module 3)

| Test | Description |
|---|---|
| `test_register_daily_reads_env_var` | env `MYBOT_DAILY_REPORT=10:15` → CronTrigger hour=10, minute=15 |
| `test_register_daily_default_no_env_var` | no env var → CronTrigger hour=8, minute=0 |
| `test_register_weekly_reads_env_var` | env `MYBOT_WEEKLY_REPORT=FRI 17:00` → CronTrigger day_of_week=fri |
| `test_register_weekly_default_no_env_var` | no env var → CronTrigger day_of_week=mon, hour=9 |
| `test_register_uses_chatbot_id` | `bot.chatbot_id="analytics_bot"` → key `ANALYTICS_BOT_DAILY_REPORT` |
| `test_register_falls_back_to_name` | no `chatbot_id`, `bot.name="ReportBot"` → key `REPORTBOT_DAILY_REPORT` |
| `test_general_schedule_unaffected` | `@schedule(ScheduleType.DAILY, hour=6)` → trigger hour=6 (unchanged) |
| `test_mixed_bot_all_three_registered` | bot with `@schedule` + `@schedule_daily_report` + `@schedule_weekly_report` → 3 jobs |

---

## Test File Structure

```python
# tests/test_scheduler_report_decorators.py
"""Unit tests for @schedule_daily_report and @schedule_weekly_report (FEAT-028)."""
import asyncio
import os
import pytest
from unittest.mock import MagicMock, patch
from apscheduler.jobstores.memory import MemoryJobStore
from apscheduler.triggers.cron import CronTrigger

# Patch infrastructure before import (same pattern as verify_scheduler.py)
_patches = [
    patch("apscheduler.jobstores.redis.RedisJobStore",
          side_effect=lambda **_kw: MemoryJobStore()),
    patch("navconfig.logging.logging", MagicMock()),
    patch("asyncdb.AsyncDB", MagicMock()),
    patch("navigator.conf.CACHE_HOST", "localhost"),
    patch("navigator.conf.CACHE_PORT", 6379),
    patch("navigator.connections.PostgresPool", MagicMock()),
    patch("querysource.conf.default_dsn", "postgresql://localhost/test"),
    patch("parrot.notifications.NotificationMixin", MagicMock()),
    patch("parrot.conf.ENVIRONMENT", "test"),
]
for p in _patches:
    p.start()

from parrot.scheduler import (
    AgentSchedulerManager,
    ScheduleType,
    schedule,
    schedule_daily_report,
    schedule_weekly_report,
    _parse_daily_schedule,
    _parse_weekly_schedule,
)
```

Use `monkeypatch` or `os.environ` + cleanup for env var tests. Mock `navconfig.config.get` inside `_resolve_report_schedule` to avoid needing real navconfig:

```python
@pytest.fixture
def mock_nav_config(monkeypatch):
    """Patch navconfig.get inside _resolve_report_schedule."""
    with patch("parrot.scheduler._resolve_report_schedule") as mock_resolve:
        # Or patch at navconfig level:
        import navconfig
        monkeypatch.setattr(navconfig, "config", MagicMock())
        yield navconfig.config
```

For trigger inspection after `register_bot_schedules()`, check:
```python
jobs = {j.id: j for j in mgr.scheduler.get_jobs()}
trigger = jobs["auto_mybot_daily"].trigger
assert isinstance(trigger, CronTrigger)
# Inspect cron fields: trigger.fields[5].expressions[0].first == expected_hour
```

---

## Section 5 for `examples/verify_scheduler.py`

Add `test_report_decorators()` as described in spec §4 "Verification Script Update". Call it from `main()` after Section 3.

```python
def test_report_decorators() -> None:
    print("\n=== 5. @schedule_daily_report / @schedule_weekly_report ===\n")

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

    check("  daily_summary._schedule_report_type == 'daily'",
          bot.daily_summary._schedule_report_type == "daily")
    check("  weekly_digest._schedule_report_type == 'weekly'",
          bot.weekly_digest._schedule_report_type == "weekly")
    check("  daily _schedule_config['schedule_type'] == 'daily'",
          bot.daily_summary._schedule_config['schedule_type'] == ScheduleType.DAILY.value)

    # Registration with env var override
    import os
    os.environ["REPORT_BOT_DAILY_REPORT"] = "10:15"
    os.environ["REPORT_BOT_WEEKLY_REPORT"] = "FRI 17:00"

    mgr = AgentSchedulerManager(bot_manager=None)
    registered = mgr.register_bot_schedules(bot)
    check("  register_bot_schedules returns 2", registered == 2, str(registered))

    jobs = {j.id: j for j in mgr.scheduler.get_jobs()}
    check("  job auto_report_bot_daily_summary present",
          "auto_report_bot_daily_summary" in jobs)
    check("  job auto_report_bot_weekly_digest present",
          "auto_report_bot_weekly_digest" in jobs)
    check("  daily_summary → CronTrigger",
          isinstance(jobs.get("auto_report_bot_daily_summary", MagicMock()).trigger, CronTrigger))
    check("  weekly_digest → CronTrigger",
          isinstance(jobs.get("auto_report_bot_weekly_digest", MagicMock()).trigger, CronTrigger))
```

---

## Acceptance Criteria

- [ ] `tests/test_scheduler_report_decorators.py` created with all test cases
- [ ] All 21+ tests pass: `pytest tests/test_scheduler_report_decorators.py -v --no-header`
- [ ] `examples/verify_scheduler.py` extended with Section 5
- [ ] `python examples/verify_scheduler.py` exits 0 with all checks passing (including Section 5)
- [ ] All existing tests continue to pass

---

## Agent Instructions

1. Create `tests/test_scheduler_report_decorators.py` following the structure above
2. Use the same infrastructure-patching pattern as `examples/verify_scheduler.py` (RedisJobStore → MemoryJobStore)
3. For env var tests, use `monkeypatch.setenv` from pytest or mock `navconfig.config.get`
4. Extend `examples/verify_scheduler.py` — add `test_report_decorators()` and call it from `main()`
5. Run full suite:
   ```bash
   source .venv/bin/activate
   pytest tests/test_scheduler_report_decorators.py -v --no-header 2>&1 | tail -30
   python examples/verify_scheduler.py 2>&1 | tail -15
   ```
6. All must pass before marking complete
