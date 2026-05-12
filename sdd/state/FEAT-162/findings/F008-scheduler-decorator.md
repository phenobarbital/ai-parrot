---
id: F008
query_id: Q008
type: grep
intent: Locate the schedule decorator + ScheduleType enum to confirm WEEKLY / MONTHLY enum members and parameter names.
executed_at: 2026-05-12T00:00:00Z
duration_ms: 0
parent_id: null
depth: 0
---

# F008 — ScheduleType has WEEKLY and MONTHLY; `@schedule` accepts ARBITRARY kwargs (no parameter validation)

## Summary

`ScheduleType` is an `Enum` defined at `parrot/scheduler/__init__.py:41` with
members `ONCE`, `DAILY`, `WEEKLY`, `MONTHLY`, `INTERVAL`, `CRON`, `CRONTAB`. The
`@schedule(schedule_type=..., **schedule_config)` decorator captures **all
keyword arguments** into `wrapper._schedule_config["schedule_config"]`. There is
**no validation of `day_of_week`, `day`, `hour`, `minute`** at decoration time —
the kwargs are passed verbatim to APScheduler's `add_job` at registration time.
The brainstorm's `day_of_week=0, hour=6, minute=0` and `day=1, hour=6, minute=0`
will be forwarded as-is.

## Citations

- path: `packages/ai-parrot/src/parrot/scheduler/__init__.py`
  lines: 41-50
  symbol: ScheduleType enum
  excerpt: |
    class ScheduleType(Enum):
        ONCE = "once"
        DAILY = "daily"
        WEEKLY = "weekly"
        MONTHLY = "monthly"
        INTERVAL = "interval"
        CRON = "cron"
        CRONTAB = "crontab"

- path: `packages/ai-parrot/src/parrot/scheduler/__init__.py`
  lines: 53-96
  symbol: schedule decorator
  excerpt: |
    def schedule(
        schedule_type: ScheduleType = ScheduleType.DAILY,
        *,
        success_callback: Optional[Callable] = None,
        send_result: Optional[Dict[str, Any]] = None,
        callbacks: Optional[List[Dict[str, Any]]] = None,
        **schedule_config
    ):
        def decorator(func):
            wrapper._schedule_config = {
                'schedule_type': schedule_type.value,
                'schedule_config': schedule_config,    # <— captures day_of_week, day, hour, minute, etc.
                'method_name': func.__name__,
            }
            return wrapper
        return decorator

- path: `agents/security.py`
  lines: 445
  symbol: existing WEEKLY usage in SecurityAgent (already in the partially-implemented stub)
  excerpt: |
    @schedule(schedule_type=ScheduleType.WEEKLY, day_of_week=0, hour=6, minute=0)
    async def consolidate_weekly_security_summary(self) -> dict:

## Notes

- Confirmed: the brainstorm's `@schedule(ScheduleType.WEEKLY, day_of_week=0, hour=6, minute=0)`
  and `@schedule(ScheduleType.MONTHLY, day=1, hour=6, minute=0)` calls are
  syntactically valid for the decorator. Actual cron semantics come from
  APScheduler at job-registration time (downstream of the decorator).
- The actual scheduler that consumes `_schedule_config` lives later in the same
  file (lines 442+); not inspected here as it doesn't affect the spec.
