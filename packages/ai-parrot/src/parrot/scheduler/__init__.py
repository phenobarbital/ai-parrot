"""Agent Scheduler for AI-Parrot.

The scheduler implementation (AgentSchedulerManager, decorators, ScheduleType)
is part of the server layer (ai-parrot-server satellite).

Use: pip install ai-parrot-server[scheduler]
"""
from pkgutil import extend_path
__path__ = extend_path(__path__, __name__)

# Server-side exports (move to satellite in TASK-1374 — lazy via __getattr__)
_SERVER_CLASSES = {
    "ScheduleType": ("parrot.scheduler.manager", "ScheduleType"),
    "schedule": ("parrot.scheduler.manager", "schedule"),
    "schedule_daily_report": ("parrot.scheduler.manager", "schedule_daily_report"),
    "schedule_weekly_report": ("parrot.scheduler.manager", "schedule_weekly_report"),
    "AgentSchedulerManager": ("parrot.scheduler.manager", "AgentSchedulerManager"),
    # Private env-var parsers — re-exported so the report-decorator test suite
    # can reach them through the namespace shim.
    "_parse_daily_schedule": ("parrot.scheduler.manager", "_parse_daily_schedule"),
    "_parse_weekly_schedule": ("parrot.scheduler.manager", "_parse_weekly_schedule"),
    "_resolve_report_schedule": ("parrot.scheduler.manager", "_resolve_report_schedule"),
}


def __getattr__(name: str):
    if name in _SERVER_CLASSES:
        from parrot._imports import load_satellite_attr

        module_path, cls_name = _SERVER_CLASSES[name]
        return load_satellite_attr(
            name, module_path, install="ai-parrot-server[scheduler]", attr=cls_name
        )
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    "ScheduleType",
    "schedule",
    "schedule_daily_report",
    "schedule_weekly_report",
    "AgentSchedulerManager",
]
