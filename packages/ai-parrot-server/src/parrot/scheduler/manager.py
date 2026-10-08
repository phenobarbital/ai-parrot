"""
Agent scheduler layer for AI-Parrot (FEAT-644).

Target-agnostic scheduling lives in :mod:`parrot.scheduler.base`; this module keeps the agent-specific
pieces: the ``@schedule`` / report decorators, :class:`AgentResolver`, :class:`CrewResolver` and
:class:`AgentSchedulerManager`.
"""

from __future__ import annotations

import inspect
import logging
import types
from typing import Any, Callable, Dict, List, Optional
from functools import wraps

from aiohttp import web

from .base import (
    SchedulerManager,
    SchedulerRunNowConflictError,
    ScheduleType,
    TargetRegistry,
    _RUN_NOW_JOB_PREFIX,
    apply_prompt_signature,
    inject_fire_context,
)
from .models import FireContext, JobDefinition, schedule_fingerprint
from .sanitize import WEEKDAYS, clean_int, clean_str

__all__ = [
    "ScheduleType",
    "SchedulerRunNowConflictError",
    "SchedulerManager",
    "TargetRegistry",
    "AgentResolver",
    "CrewResolver",
    "AgentSchedulerManager",
    "schedule",
    "schedule_daily_report",
    "schedule_weekly_report",
    "schedule_fingerprint",
    "_RUN_NOW_JOB_PREFIX",
]

_log = logging.getLogger("Parrot.Scheduler")

# Decorator for scheduling agent methods
def schedule(
    schedule_type: ScheduleType = ScheduleType.DAILY,
    *,
    success_callback: Optional[Callable] = None,
    send_result: Optional[Dict[str, Any]] = None,
    callbacks: Optional[List[Dict[str, Any]]] = None,
    **schedule_config,
):
    """
    Decorator to mark agent methods for scheduling.

    Usage:
        @schedule(schedule_type=ScheduleType.DAILY, hour=9, minute=0)
        async def generate_daily_report(self):
            ...

        @schedule(schedule_type=ScheduleType.INTERVAL, hours=2)
        async def check_updates(self):
            ...

        @schedule(
            schedule_type=ScheduleType.INTERVAL,
            minutes=30,
            success_callback=my_callback,
        )
        async def poll(self):
            ...
    """

    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def wrapper(*args, **kwargs):
            return await func(*args, **kwargs)

        # Add scheduling metadata to the function
        wrapper._schedule_config = {
            "schedule_type": schedule_type.value,
            "schedule_config": schedule_config,
            "method_name": func.__name__,
            "success_callback": success_callback,
            "send_result": send_result,
            "callbacks": list(callbacks or []),
        }
        return wrapper

    return decorator


def _report_decorator_factory(report_type: str, schedule_type_value: str):
    """Build a dual-mode (@bare / @parameterized) report decorator."""

    def outer(
        func: Optional[Callable] = None,
        *,
        success_callback: Optional[Callable] = None,
        send_result: Optional[Dict[str, Any]] = None,
        callbacks: Optional[List[Dict[str, Any]]] = None,
    ):
        def decorator(f: Callable) -> Callable:
            @wraps(f)
            async def wrapper(*args, **kwargs):
                return await f(*args, **kwargs)

            wrapper._schedule_report_type = report_type
            wrapper._schedule_config = {
                "schedule_type": schedule_type_value,
                "schedule_config": {},  # resolved at register time via env var
                "method_name": f.__name__,
                "success_callback": success_callback,
                "send_result": send_result,
                "callbacks": list(callbacks or []),
            }
            return wrapper

        if func is not None and callable(func):
            # Bare usage: @schedule_daily_report
            return decorator(func)
        # Parameterized: @schedule_daily_report(success_callback=fn)
        return decorator

    return outer


schedule_daily_report = _report_decorator_factory("daily", ScheduleType.DAILY.value)
schedule_daily_report.__doc__ = """Mark a method for daily report scheduling.

Timing is read from ``{AGENT_ID}_DAILY_REPORT`` env var at registration time.
Format: ``HH:MM`` (24-hour, UTC). Defaults to ``08:00``.

The env var key is built from the bot's ``chatbot_id`` (or ``agent_id``, or ``name``)
at the time ``register_bot_schedules()`` is called — NOT at decoration time.

Usage:
    @schedule_daily_report
    async def generate_daily_report(self):
        ...

    @schedule_daily_report(success_callback=notify_team)
    async def generate_daily_report(self):
        ...
"""

schedule_weekly_report = _report_decorator_factory("weekly", ScheduleType.WEEKLY.value)
schedule_weekly_report.__doc__ = """Mark a method for weekly report scheduling.

Timing is read from ``{AGENT_ID}_WEEKLY_REPORT`` env var at registration time.
Format: ``DDD HH:MM`` (e.g. ``MON 09:00``, 24-hour, UTC).
Defaults to ``MON 09:00``.

The env var key is built from the bot's ``chatbot_id`` (or ``agent_id``, or ``name``)
at the time ``register_bot_schedules()`` is called — NOT at decoration time.

Usage:
    @schedule_weekly_report
    async def generate_weekly_digest(self):
        ...

    @schedule_weekly_report(success_callback=notify_team)
    async def generate_weekly_digest(self):
        ...
"""


__all__ = [
    "ScheduleType",
    "schedule",
    "schedule_daily_report",
    "schedule_weekly_report",
    "AgentSchedulerManager",
]

# ---------------------------------------------------------------------------
# Env var resolution helpers for report decorators
# ---------------------------------------------------------------------------



def _parse_daily_schedule(raw: Optional[str]) -> Dict[str, Any]:
    """Parse ``"HH:MM"`` into an APScheduler cron config dict.

    Args:
        raw: String in ``HH:MM`` format (24-hour), or ``None``.

    Returns:
        Dict with keys ``hour`` and ``minute``.
        Falls back to ``{"hour": 8, "minute": 0}`` on ``None`` or malformed input.
    """
    text = clean_str(raw, field="daily report schedule")
    if text:
        try:
            hour_part, minute_part = text.split(":", 1)
        except ValueError:
            _log.warning("Could not parse daily schedule %r; using default 08:00", raw)
        else:
            hour = clean_int(hour_part, default=None, minimum=0, maximum=23, field="hour")
            minute = clean_int(minute_part, default=None, minimum=0, maximum=59, field="minute")
            if hour is not None and minute is not None:
                return {"hour": hour, "minute": minute}
            _log.warning("Could not parse daily schedule %r; using default 08:00", raw)
    return {"hour": 8, "minute": 0}


def _parse_weekly_schedule(raw: Optional[str]) -> Dict[str, Any]:
    """Parse ``"DDD HH:MM"`` into an APScheduler cron config dict.

    Args:
        raw: String in ``DDD HH:MM`` format where ``DDD`` is a 3-letter day abbreviation
             or full day name (case-insensitive), e.g. ``"FRI 17:00"`` or ``"monday 09:30"``.
             May also be ``None``.

    Returns:
        Dict with keys ``day_of_week``, ``hour``, and ``minute``.
        Falls back to ``{"day_of_week": "mon", "hour": 9, "minute": 0}`` on ``None``
        or malformed input.
    """
    default = {"day_of_week": "mon", "hour": 9, "minute": 0}
    text = clean_str(raw, field="weekly report schedule")
    if not text:
        return default
    parts = text.split()
    if len(parts) != 2 or ":" not in parts[1]:
        _log.warning("Could not parse weekly schedule %r; using default mon 09:00", raw)
        return default

    dow = parts[0].lower()[:3]  # "monday" → "mon", "FRI" → "fri"
    hour_part, minute_part = parts[1].split(":", 1)
    hour = clean_int(hour_part, default=None, minimum=0, maximum=23, field="hour")
    minute = clean_int(minute_part, default=None, minimum=0, maximum=59, field="minute")
    if dow not in WEEKDAYS or hour is None or minute is None:
        _log.warning("Could not parse weekly schedule %r; using default mon 09:00", raw)
        return default
    return {"day_of_week": dow, "hour": hour, "minute": minute}


def _resolve_report_schedule(agent_id: str, report_type: str) -> Dict[str, Any]:
    """Resolve APScheduler trigger config from env var or defaults.

    Reads ``{AGENT_ID}_{REPORT_TYPE}_REPORT`` from navconfig.  Falls back to
    parser defaults when the env var is absent or malformed.

    Args:
        agent_id: Bot identifier used to build the env var key.
                  Hyphens and spaces are replaced with ``_`` and uppercased.
        report_type: ``"daily"`` or ``"weekly"``.

    Returns:
        Dict suitable for passing to ``_create_trigger(schedule_type, config)``.
    """
    from navconfig import config as nav_config  # local import — avoids circular import

    safe_id = agent_id.upper().replace("-", "_").replace(" ", "_")
    key = f"{safe_id}_{report_type.upper()}_REPORT"
    raw: Optional[str] = nav_config.get(key)

    _log.debug(
        "Resolving %s report schedule for agent '%s' via env var %s (value=%r)",
        report_type,
        agent_id,
        key,
        raw,
    )

    if report_type == "daily":
        return _parse_daily_schedule(raw)
    return _parse_weekly_schedule(raw)


def _validated_method(target: Any, method_name: str) -> Callable[..., Any]:
    """Return a public, callable ``method_name`` of ``target`` or raise ``ValueError``."""
    if method_name.startswith("_"):
        raise ValueError("method_name must be a public identifier")
    method = getattr(target, method_name, None)
    if not callable(method):
        raise ValueError(f"method {method_name!r} is not callable")
    return method


class AgentResolver:
    """``agent`` kind: registry -> BotManager.get_bots() -> AgentRegistry.get_instance()."""

    kind: str = "agent"
    default_method: str = "chat"

    def __init__(self, registry: TargetRegistry, bot_manager_getter: Callable[[], Any | None]) -> None:
        self._registry = registry
        self._bot_manager_getter = bot_manager_getter

    async def resolve(self, name: str, *, target_id: str | None = None) -> Any | None:
        """Resolve an agent by name; never touches the BotManager's private bot map."""
        registered = self._registry.get(name, kind=self.kind)
        if registered is not None:
            return registered
        bot_manager = self._bot_manager_getter()
        if not bot_manager:
            return None
        bot = bot_manager.get_bots().get(name)
        if bot is not None:
            return bot
        try:
            return await bot_manager.registry.get_instance(name)
        except Exception as exc:  # noqa: BLE001 - a failed lookup is a target miss
            _log.debug("Agent %r could not be instantiated: %s", name, exc)
            return None

    def derive_target_id(self, target: Any) -> str | None:
        """Return the agent's ``chatbot_id`` when it has one."""
        return getattr(target, "chatbot_id", None)

    def build_call(self, target: Any, definition: JobDefinition, fire: FireContext) -> tuple[list[Any], dict[str, Any]]:
        """Build agent call arguments; prompt-only schedules call ``chat(prompt)``."""
        method_name = definition.method_name
        prompt = definition.prompt
        if method_name is None and prompt is None:
            raise ValueError("Either prompt or method_name must be provided")
        call_kwargs: dict[str, Any] = dict(definition.metadata)
        if method_name is None:
            method = _validated_method(target, self.default_method)
            return [prompt], inject_fire_context(method, call_kwargs, fire)
        method = _validated_method(target, method_name)
        call_args: list[Any] = []
        if prompt is not None:
            call_args, call_kwargs = apply_prompt_signature(method, call_args, call_kwargs, prompt)
        return call_args, inject_fire_context(method, call_kwargs, fire)


_CREW_PROMPT_MAP = {
    "run_flow": "initial_task",
    "run_loop": "initial_task",
    "run_sequential": "query",
    "run_parallel": "tasks",
}


class CrewResolver:
    """``crew`` kind: ``await bot_manager.get_crew(name)`` (async)."""

    kind: str = "crew"

    def __init__(self, registry: TargetRegistry, bot_manager_getter: Callable[[], Any | None]) -> None:
        self._registry = registry
        self._bot_manager_getter = bot_manager_getter
        self._definitions: dict[int, Any] = {}

    async def resolve(self, name: str, *, target_id: str | None = None) -> Any | None:
        """Resolve a crew by name and remember its definition for :meth:`derive_target_id`."""
        registered = self._registry.get(name, kind=self.kind)
        if registered is not None:
            return registered
        bot_manager = self._bot_manager_getter()
        if not bot_manager:
            return None
        entry = await bot_manager.get_crew(name)
        if not entry:
            return None
        crew, crew_def = entry[0], entry[1]
        if crew is not None:
            self._definitions[id(crew)] = crew_def
        return crew

    def derive_target_id(self, target: Any) -> str | None:
        """Return the ``crew_id`` of the definition the crew was resolved with."""
        crew_def = self._definitions.get(id(target))
        return getattr(crew_def, "crew_id", None) if crew_def is not None else None

    def build_call(self, target: Any, definition: JobDefinition, fire: FireContext) -> tuple[list[Any], dict[str, Any]]:
        """Map the prompt onto the crew method's parameter, else use the signature."""
        method_name = definition.method_name
        if method_name is None:
            raise ValueError("method_name is required for crew schedules")
        method = _validated_method(target, method_name)
        call_kwargs: dict[str, Any] = dict(definition.metadata)
        call_args: list[Any] = []
        prompt = definition.prompt
        if prompt is not None:
            assigned = False
            param_name = _CREW_PROMPT_MAP.get(method_name)
            if param_name == "tasks":
                if param_name not in call_kwargs and isinstance(prompt, list):
                    call_kwargs[param_name] = prompt
                    assigned = True
            elif param_name is not None and param_name not in call_kwargs:
                call_kwargs[param_name] = prompt
                assigned = True
            if not assigned:
                call_args, call_kwargs = apply_prompt_signature(method, call_args, call_kwargs, prompt)
        return call_args, inject_fire_context(method, call_kwargs, fire)


class AgentSchedulerManager(SchedulerManager):
    """SchedulerManager plus agent/crew resolution, ``@schedule`` bot scanning and BotManager auto-wiring."""

    def __init__(self, bot_manager: Any = None, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.bot_manager = bot_manager
        self.register_resolver(AgentResolver(self.targets, lambda: self.bot_manager))
        self.register_resolver(CrewResolver(self.targets, lambda: self.bot_manager))

    async def _execute_job(
        self,
        definition: JobDefinition,
        fire: FireContext,
        *,
        success_callback: Callable[..., Any] | None = None,
    ) -> Any:
        """Default prompt-only agent schedules to ``chat`` before delegating to the base executor."""
        if definition.target_kind == "agent" and definition.method_name is None and definition.backend != "code":
            definition = definition.model_copy(update={"method_name": AgentResolver.default_method})
        return await super()._execute_job(definition, fire, success_callback=success_callback)

    def register_bot_schedules(self, bot: Any) -> int:
        """Resolve report-decorator env timing, then ``register_object_schedules(bot, bot.name)``.

        Args:
            bot: Bot instance whose ``@schedule`` methods are scanned.

        Returns:
            Number of schedules registered.
        """
        bot_name = getattr(bot, "name", "Unknown")
        members: dict[str, Any] = {}
        for attr, method in inspect.getmembers(bot, predicate=inspect.ismethod):
            config = getattr(method, "_schedule_config", None)
            if config is None:
                continue
            if hasattr(method, "_schedule_report_type"):
                agent_id = (
                    getattr(bot, "chatbot_id", None)
                    or getattr(bot, "agent_id", None)
                    or getattr(bot, "name", "unknown")
                )
                resolved = dict(config)
                resolved["schedule_config"] = _resolve_report_schedule(agent_id, method._schedule_report_type)
                members[attr] = self._with_config(method, resolved)
            else:
                members[attr] = method
        if not members:
            return 0
        return self.register_object_schedules(types.SimpleNamespace(**members), bot_name)

    @staticmethod
    def _with_config(method: Any, config: dict[str, Any]) -> Any:
        """Return a bound proxy of ``method`` carrying a private ``_schedule_config`` copy."""

        @wraps(method.__func__)
        async def proxy(_owner: Any, *args: Any, **kwargs: Any) -> Any:
            return await method(*args, **kwargs)

        proxy._schedule_config = config  # type: ignore[attr-defined]
        return types.MethodType(proxy, method.__self__)

    async def on_startup(self, app: web.Application, conn: Callable[..., Any]) -> None:
        """Base startup, then BotManager fallback (``app['bot_manager']``) and bot schedule registration."""
        await super().on_startup(app, conn)
        if self.bot_manager is None:
            self.bot_manager = app.get("bot_manager")
        if self.bot_manager:
            total_auto = sum(self.register_bot_schedules(bot) for _, bot in self.bot_manager.get_bots().items())
            if total_auto > 0:
                self.logger.info("Registered %d auto-schedules from active bots", total_auto)
        else:
            self.logger.warning(
                "No bot_manager available; skipping auto-schedule registration "
                "(set bot_manager on AgentSchedulerManager or register a "
                "BotManager in the aiohttp app before startup)"
            )
