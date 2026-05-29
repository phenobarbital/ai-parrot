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
}


def __getattr__(name: str):
    if name in _SERVER_CLASSES:
        module_path, cls_name = _SERVER_CLASSES[name]
        try:
            import importlib
            mod = importlib.import_module(module_path)
            return getattr(mod, cls_name)
        except ImportError:
            raise ImportError(
                f"{name!r} requires the ai-parrot-server package with the scheduler extra. "
                f"Install it with: pip install ai-parrot-server[scheduler]"
            ) from None
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    "ScheduleType",
    "schedule",
    "schedule_daily_report",
    "schedule_weekly_report",
    "AgentSchedulerManager",
]
