"""
Agent Scheduler Module for AI-Parrot.

This module provides scheduling capabilities for agents using APScheduler,
allowing agents to execute operations at specified intervals.
"""
from __future__ import annotations
import asyncio
import contextlib
import inspect
import json
from typing import Any, Dict, Optional, Callable, List, Tuple, Set
from datetime import datetime
import uuid
from enum import Enum
from functools import wraps
from apscheduler.events import (
    EVENT_JOB_ADDED,
    EVENT_JOB_ERROR,
    EVENT_JOB_EXECUTED,
    EVENT_JOB_MAX_INSTANCES,
    EVENT_JOB_MISSED,
    EVENT_SCHEDULER_SHUTDOWN,
    EVENT_SCHEDULER_STARTED,
    JobExecutionEvent,
)
from apscheduler.executors.asyncio import AsyncIOExecutor
from apscheduler.jobstores.base import JobLookupError
from apscheduler.jobstores.memory import MemoryJobStore
from apscheduler.jobstores.redis import RedisJobStore
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.date import DateTrigger
from apscheduler.triggers.interval import IntervalTrigger
from aiohttp import web
from aiohttp_cors import CorsViewMixin
from navconfig.logging import logging
from asyncdb import AsyncDB
from navigator.connections import PostgresPool
from parrot.conf import default_dsn, CACHE_HOST, CACHE_PORT
from .models import AgentSchedule
from .sanitize import (
    WEEKDAYS,
    SchedulerConfigError,
    clean_int,
    clean_str,
    normalize_jobstore_alias,
    normalize_schedule_type,
    sanitize_redis_settings,
    sanitize_schedule_config,
)
from ..notifications import NotificationMixin
from ..conf import ENVIRONMENT
from .functions import build_scheduler_callback


# Suppress APScheduler logging noise.
logging.getLogger("apscheduler").setLevel(logging.WARNING)


# Database Model for Scheduler
class ScheduleType(Enum):
    """Schedule execution types."""
    ONCE = "once"
    DAILY = "daily"
    WEEKLY = "weekly"
    MONTHLY = "monthly"
    INTERVAL = "interval"
    CRON = "cron"
    CRONTAB = "crontab"  # using crontab-syntax (supported by APScheduler)


class SchedulerRunNowConflictError(Exception):
    """Raised by :meth:`AgentSchedulerManager.run_schedule_now` when a
    run-now execution is already active for the target schedule
    (FEAT-467 TASK-2520) — the handler maps this to HTTP 409."""


#: Deterministic APScheduler job-id prefix for run-now one-shot jobs
#: (FEAT-467 TASK-2520). Shared between :meth:`AgentSchedulerManager.
#: run_schedule_now` (job-id construction) and
#: :meth:`AgentSchedulerManager.job_success` (schedule_id recovery when
#: the one-shot job has already self-removed from the jobstore by the
#: time the listener runs — see that method's docstring).
_RUN_NOW_JOB_PREFIX = "run_now:"


# Decorator for scheduling agent methods
def schedule(
    schedule_type: ScheduleType = ScheduleType.DAILY,
    *,
    success_callback: Optional[Callable] = None,
    send_result: Optional[Dict[str, Any]] = None,
    callbacks: Optional[List[Dict[str, Any]]] = None,
    **schedule_config
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
            'schedule_type': schedule_type.value,
            'schedule_config': schedule_config,
            'method_name': func.__name__,
            'success_callback': success_callback,
            'send_result': send_result,
            'callbacks': list(callbacks or []),
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
                'schedule_type': schedule_type_value,
                'schedule_config': {},   # resolved at register time via env var
                'method_name': f.__name__,
                'success_callback': success_callback,
                'send_result': send_result,
                'callbacks': list(callbacks or []),
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

_log = logging.getLogger('Parrot.Scheduler')


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

    dow = parts[0].lower()[:3]          # "monday" → "mon", "FRI" → "fri"
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
        report_type, agent_id, key, raw,
    )

    if report_type == "daily":
        return _parse_daily_schedule(raw)
    return _parse_weekly_schedule(raw)


class _SchedulerNotification(NotificationMixin):
    """Helper to reuse notification mixin capabilities."""

    def __init__(self, logger):
        self.logger = logger


class AgentSchedulerManager:
    """
    Manager for scheduling agent operations using APScheduler.

    This manager handles:
    - Loading schedules from database on startup
    - Adding/removing schedules dynamically
    - Executing scheduled agent operations
    - Safe restart of scheduler
    """
    registered_name: str = 'scheduler_manager'

    def __init__(self, bot_manager: Any = None, **kwargs):
        self.logger = logging.getLogger('Parrot.Scheduler')
        self.bot_manager = bot_manager
        self.app: Optional[web.Application] = None
        self.db: Optional[AsyncDB] = None
        self._pool: Optional[AsyncDB] = None  # Database connection pool
        # True only when start_headless() created self._pool itself (via a
        # `dsn`) — used by stop_headless() to decide whether it owns the
        # pool's lifecycle and should close it.
        self._owns_pool: bool = False
        self._job_context: Dict[str, Dict[str, Any]] = {}
        self._pending_success_tasks: Set[asyncio.Task] = set()
        # In-memory concurrency guard for run-now (FEAT-467 TASK-2520):
        # schedule_ids with an active run-now execution in flight. A
        # second run-now for the same schedule_id while present here is
        # refused (409) rather than queued/stacked.
        self._run_now_active: Set[str] = set()
        self.registered_name = kwargs.get(
            "registered_name", self.registered_name
        )
        self.scheduler: Optional[AsyncIOScheduler] = None

        # Configure APScheduler with AsyncIO.
        # NOTE: RedisJobStore is intentionally NOT constructed here anymore
        # (it used to be built unconditionally, which could attempt a Redis
        # connection even when Redis is never used). Jobstore selection now
        # happens at start time via `_build_jobstores()`/`start_headless()`;
        # `self.scheduler` still exists after `__init__` with the always-on
        # 'default' MemoryJobStore, per existing code that touches it.
        executors = {
            'default': AsyncIOExecutor()
        }
        job_defaults = {
            'coalesce': True,  # Combine multiple missed runs into one
            'max_instances': 2,  # Maximum concurrent instances of each job
            'misfire_grace_time': 300  # 5 minutes grace period
        }

        self.scheduler = AsyncIOScheduler(
            jobstores=self._build_jobstores(use_redis=False),
            executors=executors,
            job_defaults=job_defaults,
            timezone='UTC'
        )

    def _prepare_call_arguments(
        self,
        method: Callable,
        prompt: Optional[Any],
        metadata: Optional[Dict[str, Any]],
        *,
        is_crew: bool,
        method_name: Optional[str]
    ) -> Tuple[List[Any], Dict[str, Any]]:
        """Build positional and keyword arguments for method execution."""
        call_kwargs: Dict[str, Any] = dict(metadata or {})
        call_args: List[Any] = []

        if prompt is None:
            return call_args, call_kwargs

        assigned_prompt = False

        if is_crew:
            crew_prompt_map = {
                'run_flow': 'initial_task',
                'run_loop': 'initial_task',
                'run_sequential': 'query',
                'run_parallel': 'tasks',
            }
            if (param_name := crew_prompt_map.get(method_name or '')):
                if param_name == 'tasks':
                    if param_name not in call_kwargs and isinstance(prompt, list):
                        call_kwargs[param_name] = prompt
                        assigned_prompt = True
                elif param_name not in call_kwargs:
                        call_kwargs[param_name] = prompt
                        assigned_prompt = True

        if not assigned_prompt:
            call_args, call_kwargs = self._apply_prompt_signature(
                method,
                call_args,
                call_kwargs,
                prompt
            )

        return call_args, call_kwargs

    def _apply_prompt_signature(
        self,
        method: Callable,
        call_args: List[Any],
        call_kwargs: Dict[str, Any],
        prompt: Any
    ) -> Tuple[List[Any], Dict[str, Any]]:
        """Inject prompt into call signature when possible."""
        try:
            signature = inspect.signature(method)
        except (TypeError, ValueError):
            return call_args, call_kwargs

        positional_params = [
            param
            for param in signature.parameters.values()
            if param.kind in (
                inspect.Parameter.POSITIONAL_ONLY,
                inspect.Parameter.POSITIONAL_OR_KEYWORD
            )
        ]

        if positional_params:
            first_param = positional_params[0]
            call_kwargs.setdefault(first_param.name, prompt)
            return call_args, call_kwargs

        if any(
            param.kind == inspect.Parameter.VAR_POSITIONAL
            for param in signature.parameters.values()
        ):
            call_args.append(prompt)
            return call_args, call_kwargs

        if any(
            param.kind == inspect.Parameter.VAR_KEYWORD
            for param in signature.parameters.values()
        ):
            call_kwargs.setdefault('prompt', prompt)

        return call_args, call_kwargs

    def define_listeners(self):
        # Asyncio Scheduler
        self.scheduler.add_listener(
            self.scheduler_status,
            EVENT_SCHEDULER_STARTED
        )
        self.scheduler.add_listener(
            self.scheduler_shutdown,
            EVENT_SCHEDULER_SHUTDOWN
        )
        self.scheduler.add_listener(self.job_success, EVENT_JOB_EXECUTED)
        self.scheduler.add_listener(self.job_status, EVENT_JOB_ERROR | EVENT_JOB_MISSED)
        # a new job was added:
        self.scheduler.add_listener(self.job_added, EVENT_JOB_ADDED)

    def scheduler_status(self, event):
        print(event)
        self.logger.debug("[%s - NAV Scheduler] :: Started.", ENVIRONMENT)
        self.logger.notice(
            f"[{ENVIRONMENT} - NAV Scheduler] START time is: {datetime.now()}"
        )

    def scheduler_shutdown(self, event):
        self.logger.notice(
            f"[{ENVIRONMENT}] Scheduler {event} Stopped at: {datetime.now()}"
        )

    def job_added(self, event: JobExecutionEvent, *args, **kwargs):
        with contextlib.suppress(Exception):
            job = self.scheduler.get_job(event.job_id)
            job_name = job.name
            # TODO: using to check if tasks were added
            self.logger.info(
                f"Job Added: {job_name} with args: {args!s}/{kwargs!r}"
            )

    def job_status(self, event: JobExecutionEvent):
        """React on Error events from scheduler.

        :param apscheduler.events.JobExecutionEvent event: job execution event.

        TODO: add the reschedule_job
        scheduler = sched.scheduler #it returns the native apscheduler instance
        scheduler.reschedule_job('my_job_id', trigger='cron', minute='*/5')

        """
        job_id = event.job_id
        self._job_context.pop(str(job_id), None)
        job = self.scheduler.get_job(job_id)
        job_name = job.name
        scheduled = event.scheduled_run_time
        stack = event.traceback
        if event.code == EVENT_JOB_MISSED:
            self.logger.warning(
                f"[{ENVIRONMENT} - NAV Scheduler] Job {job_name} \
                was missed for scheduled run at {scheduled}"
            )
            message = f"⚠️ :: [{ENVIRONMENT} - NAV Scheduler] Job {job_name} was missed \
            for scheduled run at {scheduled}"
        elif event.code == EVENT_JOB_ERROR:
            self.logger.error(
                f"[{ENVIRONMENT} - NAV Scheduler] Job {job_name} scheduled at \
                {scheduled!s} failed with Exception: {event.exception!s}"
            )
            message = f"🛑 :: [{ENVIRONMENT} - NAV Scheduler] Job **{job_name}** \
             scheduled at {scheduled!s} failed with Error {event.exception!s}"
            if stack:
                self.logger.exception(
                    f"[{ENVIRONMENT} - NAV Scheduler] Job {job_name} id: {job_id!s} \
                    StackTrace: {stack!s}"
                )
                message = f"🛑 :: [{ENVIRONMENT} - NAV Scheduler] Job \
                **{job_name}**:**{job_id!s}** failed with Exception {event.exception!s}"
            # send a Notification error from Scheduler
        elif event.code == EVENT_JOB_MAX_INSTANCES:
            self.logger.exception(
                f"[{ENVIRONMENT} - Scheduler] Job {job_name} could not be submitted \
                Maximum number of running instances was reached."
            )
            message = f"⚠️ :: [{ENVIRONMENT} - NAV Scheduler] Job **{job_name}** was \
            missed for scheduled run at {scheduled}"
        else:
            # will be an exception
            message = f"🛑 :: [{ENVIRONMENT} - NAV Scheduler] Job \
            {job_name}:{job_id!s} failed with Exception {stack!s}"
        # send a Notification Exception from Scheduler
        # self._send_notification(message)

    def job_success(self, event: JobExecutionEvent):
        """Job Success.

        Event when a Job was executed successfully.

        :param apscheduler.events.JobExecutionEvent event: job execution event
        """
        job_id = event.job_id
        try:
            job = self.scheduler.get_job(job_id)
        except JobLookupError as err:
            self.logger.warning("Error found a Job with ID: %s", err)
            return False

        job_kwargs: Dict[str, Any] = {}
        if job is not None:
            job_name = job.name
            job_kwargs = getattr(job, "kwargs", {}) or {}
        elif job_id.startswith(_RUN_NOW_JOB_PREFIX):
            # BUGFIX (FEAT-467 TASK-2520): one-shot jobs (DateTrigger,
            # non-recurring) self-remove from the jobstore as part of
            # firing — get_job(job_id) already returns None by the time
            # this listener runs, so `job.name` below used to raise
            # AttributeError, which APScheduler swallows as "Error
            # notifying listener" and silently drops the entire success
            # path (no last_run/run_count/last_result stamping, no
            # callbacks, no send_result email). Not specific to run-now
            # in principle — any one-shot job hits this window — but
            # run-now is the first caller that combines a one-shot
            # trigger with listeners actually registered (see
            # start_headless()'s register_listeners docstring: the
            # default aiohttp on_startup() path still passes
            # register_listeners=False). Recover schedule_id from the
            # deterministic job-id prefix run_schedule_now() uses,
            # since the vanished Job object can't supply job.kwargs.
            job_name = job_id
        else:
            self.logger.warning(
                "job_success: job %s not found in scheduler and is not a "
                "recognized one-shot job id — cannot process.", job_id,
            )
            return False

        self.logger.info(
            f"[Scheduler - {ENVIRONMENT}]: {job_name} with id {event.job_id!s} \
            was queued/executed successfully @ {event.scheduled_run_time!s}"
        )

        if job is None and job_id.startswith(_RUN_NOW_JOB_PREFIX):
            schedule_id = job_id[len(_RUN_NOW_JOB_PREFIX):]
        else:
            schedule_id = str(job_kwargs.get('schedule_id', event.job_id))
        context = self._job_context.pop(schedule_id, {})

        if 'agent_name' in context:
            agent_name = context['agent_name']
        else:
            agent_name = job_kwargs.get('agent_name', job_name)

        if 'success_callback' in context:
            success_callback = context['success_callback']
        else:
            success_callback = job_kwargs.get('success_callback')

        if 'send_result' in context:
            send_result = context['send_result']
        else:
            send_result = job_kwargs.get('send_result')

        callbacks = context.get('callbacks', job_kwargs.get('callbacks'))
        persist = context.get('persist', job_kwargs.get('persist', True))
        result = getattr(event, 'retval', None)

        if not schedule_id:
            self.logger.debug(
                "Job %s executed successfully but no schedule_id was found in context",
                job_id,
            )
            return True

        task = asyncio.create_task(
            self._process_job_success(
                schedule_id,
                agent_name,
                result,
                success_callback,
                send_result if isinstance(send_result, dict) else send_result,
                callbacks,
                persist=persist,
            )
        )
        self._pending_success_tasks.add(task)
        task.add_done_callback(self._pending_success_tasks.discard)
        return True

    async def _execute_agent_job(
        self,
        schedule_id: str,
        agent_name: str,
        prompt: Optional[str] = None,
        method_name: Optional[str] = None,
        metadata: Optional[Dict] = None,
        *,
        is_crew: bool = False,
        success_callback: Optional[Callable] = None,
        send_result: Optional[Dict[str, Any]] = None,
        callbacks: Optional[List[Dict[str, Any]]] = None
    ):
        """
        Execute a scheduled agent operation.

        Args:
            schedule_id: Unique identifier for this schedule
            agent_name: Name of the agent to execute
            prompt: Optional prompt to send to the agent
            method_name: Optional public method to call on the agent
            metadata: Additional metadata for execution context
        """
        try:
            self.logger.info(
                f"Executing scheduled job {schedule_id} for agent {agent_name}"
            )

            if not self.bot_manager:
                raise RuntimeError("Bot manager not available")

            call_metadata: Dict[str, Any] = dict(metadata or {})

            metadata_send_result = call_metadata.pop('send_result', None)
            send_result_config = (
                send_result
                if send_result is not None
                else metadata_send_result
            )

            metadata_success_callback = call_metadata.pop('success_callback', None)
            if success_callback is None and callable(metadata_success_callback):
                success_callback = metadata_success_callback

            metadata_is_crew = call_metadata.pop('is_crew', None)
            if metadata_is_crew is not None:
                is_crew = bool(is_crew or metadata_is_crew)

            agent: Any = None
            if is_crew:
                if (crew_entry := self.bot_manager.get_crew(agent_name)):
                    agent = crew_entry[0]
                else:
                    raise ValueError(f"Crew {agent_name} not found")
            elif not (agent := self.bot_manager._bots.get(agent_name)):
                    agent = await self.bot_manager.registry.get_instance(agent_name)
            if not agent:
                raise ValueError(
                    f"Agent {agent_name} not found"
                )

            if method_name:
                if not hasattr(agent, method_name):
                    raise AttributeError(
                        f"Agent {agent_name} has no method {method_name}"
                    )
                method = getattr(agent, method_name)
                if not callable(method):
                    raise TypeError(f"{method_name} is not callable")

                call_args, call_kwargs = self._prepare_call_arguments(
                    method,
                    prompt,
                    call_metadata,
                    is_crew=is_crew,
                    method_name=method_name,
                )
                result = await method(*call_args, **call_kwargs)
            elif prompt is not None:
                result = await agent.chat(prompt)
            else:
                raise ValueError(
                    "Either prompt or method_name must be provided"
                )

            send_result_payload = (
                dict(send_result_config)
                if isinstance(send_result_config, dict)
                else send_result_config
            )

            self._job_context[str(schedule_id)] = {
                'schedule_id': str(schedule_id),
                'agent_name': agent_name,
                'success_callback': success_callback,
                'send_result': send_result_payload,
                'callbacks': list(callbacks or []),
            }

            self.logger.info(
                f"Successfully executed job {schedule_id} for agent {agent_name}"
            )

            return result

        except Exception as e:
            self.logger.error(
                f"Error executing scheduled job {schedule_id}: {e}",
                exc_info=True
            )
            self._job_context.pop(str(schedule_id), None)
            await self._update_schedule_run(schedule_id, success=False, error=str(e))
            raise

    async def _handle_job_success(
        self,
        schedule_id: str,
        agent_name: str,
        result: Any,
        success_callback: Optional[Callable],
        send_result: Optional[Dict[str, Any]],
        callbacks: Optional[List[Dict[str, Any]]] = None,
    ) -> None:
        """Execute success callback or fallback notification."""
        if success_callback:
            callback_result = success_callback(result)
            if inspect.isawaitable(callback_result):
                await callback_result

        callback_definitions = list(callbacks or [])
        for definition in callback_definitions:
            callback = build_scheduler_callback(definition, logger=self.logger)
            await callback(result, schedule_id=schedule_id, agent_name=agent_name)

        if send_result:
            await self._send_result_email(schedule_id, agent_name, result, send_result)

    async def _send_result_email(
        self,
        schedule_id: str,
        agent_name: str,
        result: Any,
        send_result: Dict[str, Any],
    ) -> None:
        """Send job result via email using the notification system."""
        if not isinstance(send_result, dict):
            self.logger.warning(
                "send_result configuration for schedule %s is not a dictionary", schedule_id
            )
            return

        recipients = (
            send_result.get('recipients')
            or send_result.get('emails')
            or send_result.get('email')
            or send_result.get('to')
        )

        if not recipients:
            self.logger.warning(
                "send_result for schedule %s is missing recipients", schedule_id
            )
            return

        subject = send_result.get(
            'subject',
            f"Scheduled job {agent_name} completed",
        )

        message = send_result.get(
            'message',
            f"Job {agent_name} ({schedule_id}) completed successfully.",
        )

        if (include_result := send_result.get('include_result', True)):
            if (formatted_result := self._format_result(result)):
                message = f"{message}\n\nResult:\n{formatted_result}"

        template = send_result.get('template')
        report = send_result.get('report')

        reserved_keys = {
            'recipients',
            'emails',
            'email',
            'to',
            'subject',
            'message',
            'include_result',
            'template',
            'report',
        }

        extra_kwargs = {
            key: value
            for key, value in send_result.items()
            if key not in reserved_keys
        }

        notifier = _SchedulerNotification(self.logger)
        await notifier.send_email(
            message=message,
            recipients=recipients,
            subject=subject,
            report=report,
            template=template,
            **extra_kwargs,
        )

    async def _process_job_success(
        self,
        schedule_id: str,
        agent_name: str,
        result: Any,
        success_callback: Optional[Callable],
        send_result: Optional[Dict[str, Any]],
        callbacks: Optional[List[Dict[str, Any]]] = None,
        *,
        persist: bool = True,
    ) -> None:
        """Finalize processing for successful job executions.

        Args:
            persist: When False, skip the DB update step. Used by
                decorator-registered tasks that are not backed by an
                ``AgentSchedule`` row.
        """
        if persist:
            try:
                await self._update_schedule_run(schedule_id, success=True, result=result)
            except Exception as update_error:  # pragma: no cover - safety net
                self.logger.error(
                    "Failed to update schedule run for job %s: %s",
                    schedule_id,
                    update_error,
                    exc_info=True,
                )

        try:
            await self._handle_job_success(
                schedule_id,
                agent_name,
                result,
                success_callback,
                send_result,
                callbacks,
            )
        except Exception as callback_error:  # pragma: no cover - safety net
            self.logger.error(
                "Error executing success callback for job %s: %s",
                schedule_id,
                callback_error,
                exc_info=True,
            )

    def _format_result(self, result: Any) -> str:
        """Format execution result for notifications."""
        if result is None:
            return ''

        if isinstance(result, (str, int, float, bool)):
            return str(result)

        if hasattr(result, 'model_dump'):
            with contextlib.suppress(Exception):
                return json.dumps(result.model_dump(), indent=2, default=str)

        if hasattr(result, 'dict'):
            with contextlib.suppress(Exception):
                return json.dumps(result.dict(), indent=2, default=str)

        try:
            return json.dumps(result, indent=2, default=str)
        except TypeError:
            return str(result)

    #: Cap on the serialized ``last_result`` stamped into ``metadata``
    #: (FEAT-467 TASK-2520) — the JSONB column should never grow
    #: unbounded from a single verbose agent response.
    _LAST_RESULT_MAX_CHARS: int = 10_000

    async def _update_schedule_run(
        self,
        schedule_id: str,
        success: bool = True,
        error: Optional[str] = None,
        result: Any = None,
    ):
        """Update schedule record after execution.

        Args:
            schedule_id: The schedule row to update.
            success: Whether the run succeeded.
            error: Error message when ``success`` is ``False``.
            result: The job's return value on success — stamped into
                ``metadata['last_result']`` (FEAT-467 TASK-2520), same
                formatting :meth:`_format_result` uses for notification
                emails, truncated to :attr:`_LAST_RESULT_MAX_CHARS`. This
                runs for EVERY successful execution (scheduled or
                run-now) since both paths call ``_execute_agent_job`` /
                ``_process_job_success`` identically — there is no
                separate "run-now only" code path to hook.
        """
        try:
            async with await self._pool.acquire() as conn:  # pylint: disable=no-member # noqa
                AgentSchedule.Meta.connection = conn
                # BUGFIX (FEAT-467 TASK-2520): this was missing ``await`` —
                # ``schedule`` was a bare coroutine object, so every
                # attribute assignment below (and the ``.update()`` call)
                # silently no-oped inside the surrounding ``except
                # Exception`` — last_run/run_count/metadata were NEVER
                # actually persisted in production. Discovered while
                # extending this method for last_result stamping.
                schedule = await AgentSchedule.get(schedule_id=schedule_id)

                schedule.last_run = datetime.now()
                schedule.run_count += 1

                if not schedule.metadata:
                    schedule.metadata = {}

                if error:
                    schedule.metadata['last_error'] = error
                    schedule.metadata['last_error_time'] = datetime.now().isoformat()
                    schedule.metadata['last_status'] = 'error'
                else:
                    formatted = self._format_result(result)
                    if len(formatted) > self._LAST_RESULT_MAX_CHARS:
                        formatted = formatted[: self._LAST_RESULT_MAX_CHARS] + '…(truncated)'
                    schedule.metadata['last_result'] = formatted
                    schedule.metadata['last_result_time'] = datetime.now().isoformat()
                    schedule.metadata['last_status'] = 'success'

                await schedule.update()

        except Exception as e:
            self.logger.error("Failed to update schedule run: %s", e)

    def _create_trigger(self, schedule_type: str, config: Dict[str, Any]):
        """
        Create APScheduler trigger based on schedule type and configuration.

        Args:
            schedule_type: Type of schedule (daily, weekly, monthly, interval, cron)
            config: Configuration dictionary for the trigger

        Returns:
            APScheduler trigger instance
        """
        # `schedule_type` and `config` come straight off the
        # navigator.agents_scheduler row, so they may carry untrimmed strings,
        # empty values, nulls or unknown keys. Normalize before any of it
        # reaches a trigger — APScheduler fails late and opaquely otherwise
        # (and silently degrades a daily job into an every-minute one when a
        # cron field arrives as None).
        schedule_type = normalize_schedule_type(schedule_type)
        config = sanitize_schedule_config(schedule_type, config)

        if schedule_type == ScheduleType.ONCE.value:
            run_date = config.get('run_date', datetime.now())
            return DateTrigger(run_date=run_date)

        elif schedule_type == ScheduleType.DAILY.value:
            return CronTrigger(hour=config['hour'], minute=config['minute'])

        elif schedule_type == ScheduleType.WEEKLY.value:
            return CronTrigger(
                day_of_week=config['day_of_week'],
                hour=config['hour'],
                minute=config['minute'],
            )

        elif schedule_type == ScheduleType.MONTHLY.value:
            return CronTrigger(
                day=config['day'],
                hour=config['hour'],
                minute=config['minute'],
            )

        elif schedule_type == ScheduleType.INTERVAL.value:
            return IntervalTrigger(**config)

        elif schedule_type == ScheduleType.CRON.value:
            # Full cron expression support
            return CronTrigger(**config)

        elif schedule_type == ScheduleType.CRONTAB.value:
            # Support for crontab syntax (same as cron but more user-friendly)
            return CronTrigger.from_crontab(**config, timezone='UTC')

        else:
            raise SchedulerConfigError(
                f"Unsupported schedule type: {schedule_type}"
            )

    async def add_schedule(
        self,
        agent_name: str,
        schedule_type: str,
        schedule_config: Dict[str, Any],
        prompt: Optional[str] = None,
        method_name: Optional[str] = None,
        created_by: Optional[int] = None,
        created_email: Optional[str] = None,
        metadata: Optional[Dict] = None,
        agent_id: Optional[str] = None,
        *,
        is_crew: bool = False,
        send_result: Optional[Dict[str, Any]] = None,
        success_callback: Optional[Callable] = None,
        scheduler_type: str = 'default',
        callbacks: Optional[List[Dict[str, Any]]] = None
    ) -> AgentSchedule:
        """
        Add a new schedule to both database and APScheduler.

        Args:
            agent_name: Name of the agent
            schedule_type: Type of schedule
            schedule_config: Configuration for the schedule
            prompt: Optional prompt to execute
            method_name: Optional method name to call
            created_by: User ID who created the schedule
            created_email: Email of creator
            metadata: Additional metadata passed to execution method
            agent_id: Optional agent ID
            is_crew: Whether the scheduled target is a crew
            send_result: Optional configuration to email execution results
            success_callback: Optional coroutine/function executed after success

        Returns:
            Created AgentSchedule instance
        """
        # Normalize and validate caller-supplied values BEFORE anything is
        # persisted. Doing it here rather than at trigger-build time matters:
        # the "Add to APScheduler" block below wraps every exception in a
        # RuntimeError after deleting the row, which would both mask the
        # SchedulerConfigError (the API could not map it to a 400) and write a
        # row only to roll it back.
        schedule_type = normalize_schedule_type(schedule_type)
        scheduler_type = self._safe_jobstore(scheduler_type, strict=True)
        schedule_config = sanitize_schedule_config(schedule_type, schedule_config)

        # Validate agent exists
        if self.bot_manager:
            if is_crew:
                crew_entry = self.bot_manager.get_crew(agent_name)
                if not crew_entry:
                    raise ValueError(f"Crew {agent_name} not found")
                _, crew_def = crew_entry
                if not agent_id:
                    agent_id = getattr(crew_def, 'crew_id', agent_name)
            else:
                agent = self.bot_manager._bots.get(
                    agent_name
                ) or await self.bot_manager.registry.get_instance(agent_name)
                if not agent:
                    raise ValueError(f"Agent {agent_name} not found")

                if not agent_id:
                    agent_id = getattr(agent, 'chatbot_id', agent_name)

        # Create database record
        async with await self._pool.acquire() as conn:  # pylint: disable=no-member # noqa
            #  TODO> create the bind method: AgentSchedule.bind(conn)
            AgentSchedule.Meta.connection = conn
            try:
                schedule = AgentSchedule(
                    agent_id=agent_id or agent_name,
                    agent_name=agent_name,
                    prompt=prompt,
                    method_name=method_name,
                    schedule_type=schedule_type,
                    schedule_config=schedule_config,
                    created_by=created_by,
                    created_email=created_email,
                    metadata=dict(metadata or {}),
                    is_crew=is_crew,
                    send_result=dict(send_result or {}),
                    scheduler_type=scheduler_type,
                    callbacks=list(callbacks or []),
                )
                await schedule.save()
            except Exception as e:
                self.logger.error("Error saving schedule object: %s", e)
                raise

        # Add to APScheduler
        try:
            trigger = self._create_trigger(schedule_type, schedule_config)

            job = self.scheduler.add_job(
                self._execute_agent_job,
                trigger=trigger,
                id=str(schedule.schedule_id),
                name=f"{agent_name}_{schedule_type}",
                kwargs={
                    **self._job_kwargs_from_schedule(schedule),
                    'success_callback': success_callback,
                },
                jobstore=scheduler_type,
                replace_existing=True
            )

            # Update next run time
            if job.next_run_time:
                schedule.next_run = job.next_run_time
                await schedule.update()

            self.logger.info(
                f"Added schedule {schedule.schedule_id} for agent {agent_name}"
            )

        except Exception as e:
            # Rollback database record
            await schedule.delete()
            raise RuntimeError(
                f"Failed to add schedule to jobstore: {e}"
            ) from e

        return schedule

    async def _execute_agent_task(
        self,
        job_id: str,
        agent_name: str,
        method: Callable,
        *,
        success_callback: Optional[Callable] = None,
        send_result: Optional[Dict[str, Any]] = None,
        callbacks: Optional[List[Dict[str, Any]]] = None,
    ) -> Any:
        """Execute a decorator-registered agent task.

        Unlike ``_execute_agent_job``, this path is used by
        ``register_bot_schedules`` for code-declared tasks that are NOT
        persisted in ``navigator.agents_scheduler``. It records the
        callback context with ``persist=False`` so that
        ``_process_job_success`` skips the DB update step.

        Args:
            job_id: Stable scheduler job id (``auto_<bot>_<method>``).
            agent_name: Identifier of the owning bot/agent (for logging).
            method: Bound method to invoke (captured at registration time).
            success_callback: Optional coroutine/function invoked with the
                task result after successful execution.
            send_result: Optional configuration to email the task result.
            callbacks: Optional list of callback definitions resolved via
                ``build_scheduler_callback``.
        """
        try:
            self.logger.info(
                f"Executing auto-schedule {job_id} for agent {agent_name}"
            )
            send_result_payload = (
                dict(send_result)
                if isinstance(send_result, dict)
                else send_result
            )
            self._job_context[str(job_id)] = {
                'schedule_id': str(job_id),
                'agent_name': agent_name,
                'persist': False,
                'success_callback': success_callback,
                'send_result': send_result_payload,
                'callbacks': list(callbacks or []),
            }
            return await method()
        except Exception as e:
            self.logger.error(
                f"Error executing auto-schedule {job_id}: {e}",
                exc_info=True,
            )
            self._job_context.pop(str(job_id), None)
            raise

    def register_bot_schedules(self, bot: Any) -> int:
        """
        Scan and register @schedule decorated methods for a bot.

        Args:
            bot: Bot instance to scan

        Returns:
            Number of schedules registered
        """
        registered_count = 0
        bot_name = getattr(bot, 'name', 'Unknown')

        # Scan all methods of the bot
        for name, method in inspect.getmembers(bot, predicate=inspect.ismethod):
            # Check for schedule config
            if not hasattr(method, '_schedule_config'):
                continue

            config = method._schedule_config
            schedule_type = config.get('schedule_type')
            method_name = config.get('method_name', name)
            success_callback = config.get('success_callback')
            send_result = config.get('send_result')
            callbacks = config.get('callbacks') or []

            # Report decorators defer timing to env var resolution at registration time.
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
                # Create trigger
                trigger = self._create_trigger(schedule_type, schedule_config)

                # Construct unique job ID
                job_id = f"auto_{bot_name}_{method_name}"
                job_name = f"{bot_name}.{method_name}"

                # Route through _execute_agent_task so success_callback /
                # send_result / callbacks are honored without requiring a
                # DB-backed AgentSchedule row.
                self.scheduler.add_job(
                    self._execute_agent_task,
                    trigger=trigger,
                    id=job_id,
                    name=job_name,
                    kwargs={
                        'job_id': job_id,
                        'agent_name': bot_name,
                        'method': method,
                        'success_callback': success_callback,
                        'send_result': send_result,
                        'callbacks': callbacks,
                    },
                    replace_existing=True,
                )

                self.logger.info(
                    f"Registered auto-schedule for {job_name} ({schedule_type})"
                )
                registered_count += 1

            except Exception as e:
                self.logger.error(
                    f"Failed to register auto-schedule for {bot_name}.{method_name}: {e}"
                )

        return registered_count

    async def remove_schedule(self, schedule_id: str):
        """Remove a schedule from both database and APScheduler."""
        try:
            # Remove from APScheduler
            self.scheduler.remove_job(schedule_id)

            # Remove from database
            async with await self._pool.acquire() as conn:  # pylint: disable=no-member # noqa
                AgentSchedule.Meta.connection = conn
                schedule = await AgentSchedule.get(schedule_id=uuid.UUID(schedule_id))
                await schedule.delete()

            self.logger.info(
                f"Removed schedule {schedule_id}"
            )

        except Exception as e:
            self.logger.error("Error removing schedule %s: %s", schedule_id, e)
            raise

    async def load_schedules_from_db(self):
        """Load all enabled schedules from database and add to APScheduler."""
        try:
            # Fallback: ensure pool is available
            if self._pool is None:
                if self.app and 'agentdb' in self.app:
                    self._pool = self.app['agentdb']
                else:
                    # Create a new connection pool as fallback
                    self.logger.warning(
                        "Database pool not initialized, creating fallback connection"
                    )
                    self._pool = AsyncDB("pg", dsn=default_dsn)
                    await self._pool.connection()

            # Query all enabled schedules
            query = """
                SELECT * FROM navigator.agents_scheduler
                WHERE enabled = TRUE
                ORDER BY created_at
            """
            async with await self._pool.acquire() as conn:  # pylint: disable=no-member # noqa
                AgentSchedule.Meta.connection = conn
                results, error = await conn.query(query)
                if error:
                    self.logger.warning("Error querying schedules: %s", error)
                    return

                loaded = 0
                failed = 0

                for record in results:
                    try:
                        schedule_data = AgentSchedule(**record)
                        trigger = self._create_trigger(
                            schedule_data.schedule_type,
                            schedule_data.schedule_config
                        )

                        self.scheduler.add_job(
                            self._execute_agent_job,
                            trigger=trigger,
                            id=str(schedule_data.schedule_id),
                            name=f"{schedule_data.agent_name}_{schedule_data.schedule_type}",
                            kwargs={
                                'schedule_id': str(schedule_data.schedule_id),
                                'agent_name': schedule_data.agent_name,
                                'prompt': schedule_data.prompt,
                                'method_name': schedule_data.method_name,
                                'metadata': dict(schedule_data.metadata or {}),
                                'is_crew': schedule_data.is_crew,
                                'send_result': dict(schedule_data.send_result or {}),
                                'callbacks': list(schedule_data.callbacks or []),
                            },
                            jobstore=self._safe_jobstore(
                                schedule_data.scheduler_type
                            ),
                            replace_existing=True
                        )

                        loaded += 1

                    except Exception as e:
                        failed += 1
                        self.logger.error(
                            f"Failed to load schedule {record.get('schedule_id')}: {e}"
                        )

            self.logger.notice(
                f"Loaded {loaded} schedules from database ({failed} failed)"
            )

        except Exception as e:
            self.logger.error("Error loading schedules from database: %s", e)
            raise

    async def restart_scheduler(self):
        """Safely restart the scheduler."""
        try:
            self.logger.info("Restarting scheduler...")

            if self.scheduler.running:
                self.scheduler.shutdown(wait=True)

            # Reload schedules from database
            await self.load_schedules_from_db()

            # Start scheduler
            self.scheduler.start()

            self.logger.notice("Scheduler restarted successfully")

        except Exception as e:
            self.logger.error("Error restarting scheduler: %s", e)
            raise

    def _job_kwargs_from_schedule(self, schedule: AgentSchedule) -> Dict[str, Any]:
        return {
            'schedule_id': str(schedule.schedule_id),
            'agent_name': schedule.agent_name,
            'prompt': schedule.prompt,
            'method_name': schedule.method_name,
            'metadata': dict(schedule.metadata or {}),
            'is_crew': schedule.is_crew,
            'send_result': dict(schedule.send_result or {}),
            'callbacks': list(schedule.callbacks or []),
        }

    async def _get_connection_pool(self):
        if self._pool is not None:
            return self._pool
        if self.app and 'agentdb' in self.app:
            self._pool = self.app['agentdb']
            return self._pool
        self._pool = AsyncDB("pg", dsn=default_dsn)
        await self._pool.connection()
        return self._pool

    def _serialize_job(self, schedule: AgentSchedule) -> Dict[str, Any]:
        payload = schedule.to_dict()
        job = self.scheduler.get_job(str(schedule.schedule_id))
        payload['source'] = 'db'
        payload['jobstore'] = schedule.scheduler_type
        payload['callbacks'] = list(schedule.callbacks or [])
        payload['job'] = {
            'id': str(job.id) if job else None,
            'name': job.name if job else None,
            'next_run': job.next_run_time.isoformat() if job and job.next_run_time else None,
            'paused': bool(job and job.next_run_time is None and schedule.enabled),
            'pending': job is not None,
            'jobstore': getattr(job, '_jobstore_alias', None) if job else schedule.scheduler_type,
        }
        return payload

    def _serialize_auto_job(self, job: Any) -> Dict[str, Any]:
        """Serialize an APScheduler job that has no AgentSchedule row.

        Auto-schedules come from ``@schedule``-decorated bot methods registered
        via :meth:`register_bot_schedules`. They live in APScheduler only, so
        the payload mirrors :meth:`_serialize_job` minus the DB-derived fields.
        """
        bot_name, _, method_name = (job.name or job.id or '').partition('.')
        jobstore = getattr(job, '_jobstore_alias', 'default')
        next_run = job.next_run_time.isoformat() if job.next_run_time else None
        return {
            'source': 'auto',
            'schedule_id': job.id,
            'agent_name': bot_name or job.id,
            'method_name': method_name or None,
            'enabled': job.next_run_time is not None,
            'metadata': {},
            'callbacks': [],
            'scheduler_type': jobstore,
            'jobstore': jobstore,
            'job': {
                'id': job.id,
                'name': job.name,
                'next_run': next_run,
                'paused': job.next_run_time is None,
                'pending': True,
                'jobstore': jobstore,
            },
        }

    async def list_jobs(self) -> List[Dict[str, Any]]:
        """Return every job in the APScheduler JobStore, normalized for the API.

        DB-backed schedules are enriched with their ``AgentSchedule`` row and
        tagged ``source='db'``; jobs without a matching row (auto-schedules
        from ``@schedule``-decorated bot methods) are tagged ``source='auto'``.
        DB rows whose job is missing from APScheduler are still surfaced so
        operators can spot drift.
        """
        try:
            db_schedules = await self.list_schedules()
        except Exception as exc:  # pylint: disable=broad-except
            self.logger.warning(
                "list_jobs: could not load DB schedules (%s); returning JobStore-only view",
                exc,
            )
            db_schedules = []
        db_by_id: Dict[str, AgentSchedule] = {
            str(s.schedule_id): s for s in db_schedules
        }
        payload: List[Dict[str, Any]] = []
        for job in self.scheduler.get_jobs():
            schedule = db_by_id.pop(job.id, None)
            if schedule is not None:
                payload.append(self._serialize_job(schedule))
            else:
                payload.append(self._serialize_auto_job(job))
        for schedule in db_by_id.values():
            payload.append(self._serialize_job(schedule))
        return payload

    async def get_schedule(self, schedule_id: str) -> AgentSchedule:
        pool = await self._get_connection_pool()
        async with await pool.acquire() as conn:  # pylint: disable=no-member # noqa
            AgentSchedule.Meta.connection = conn
            return await AgentSchedule.get(schedule_id=uuid.UUID(str(schedule_id)))

    async def list_schedules(self) -> List[AgentSchedule]:
        pool = await self._get_connection_pool()
        async with await pool.acquire() as conn:  # pylint: disable=no-member # noqa
            AgentSchedule.Meta.connection = conn
            return await AgentSchedule.all()

    async def pause_schedule(self, schedule_id: str) -> AgentSchedule:
        schedule = await self.get_schedule(schedule_id)
        pool = await self._get_connection_pool()
        if self.scheduler.get_job(str(schedule_id)):
            self.scheduler.pause_job(str(schedule_id))
        async with await pool.acquire() as conn:  # pylint: disable=no-member # noqa
            AgentSchedule.Meta.connection = conn
            schedule.enabled = False
            schedule.updated_at = datetime.now()
            await schedule.update()
        return schedule

    async def update_schedule(self, schedule_id: str, updates: Dict[str, Any]) -> AgentSchedule:
        schedule = await self.get_schedule(schedule_id)
        pool = await self._get_connection_pool()
        editable_fields = {
            'agent_name', 'agent_id', 'prompt', 'method_name', 'schedule_type',
            'schedule_config', 'metadata', 'enabled', 'is_crew', 'send_result',
            'scheduler_type', 'callbacks'
        }
        old_scheduler_type = schedule.scheduler_type

        # Normalize the incoming values first. `scheduler_type` is checked
        # strictly because this is an explicit request: silently downgrading it
        # to the in-memory store while persisting 'redis' would leave the row
        # claiming a durability the job does not have.
        updates = dict(updates)
        if 'schedule_type' in updates:
            updates['schedule_type'] = normalize_schedule_type(
                updates['schedule_type']
            )
        if 'scheduler_type' in updates:
            updates['scheduler_type'] = self._safe_jobstore(
                updates['scheduler_type'], strict=True
            )

        for key, value in updates.items():
            if key in editable_fields:
                setattr(schedule, key, value)

        # Prove the merged configuration can actually build a trigger BEFORE
        # persisting it. Validating afterwards would leave the row holding a
        # config that was rejected, with no job scheduled — and
        # load_schedules_from_db() would keep failing on it after a restart.
        trigger = None
        if schedule.enabled:
            trigger = self._create_trigger(
                schedule.schedule_type, schedule.schedule_config
            )

        schedule.updated_at = datetime.now()
        async with await pool.acquire() as conn:  # pylint: disable=no-member # noqa
            AgentSchedule.Meta.connection = conn
            await schedule.update()
        job_id = str(schedule.schedule_id)
        with contextlib.suppress(Exception):
            # Cleanup of the previous placement — fall back rather than raise.
            self.scheduler.remove_job(
                job_id, jobstore=self._safe_jobstore(old_scheduler_type)
            )
        if schedule.enabled:
            job = self.scheduler.add_job(
                self._execute_agent_job,
                trigger=trigger,
                id=job_id,
                name=f"{schedule.agent_name}_{schedule.schedule_type}",
                kwargs=self._job_kwargs_from_schedule(schedule),
                jobstore=self._safe_jobstore(schedule.scheduler_type),
                replace_existing=True
            )
            if job.next_run_time:
                schedule.next_run = job.next_run_time
                async with await pool.acquire() as conn:  # pylint: disable=no-member # noqa
                    AgentSchedule.Meta.connection = conn
                    await schedule.update()
        return schedule

    async def delete_schedule(self, schedule_id: str) -> None:
        schedule = await self.get_schedule(schedule_id)
        with contextlib.suppress(JobLookupError):
            self.scheduler.remove_job(
                str(schedule.schedule_id),
                jobstore=self._safe_jobstore(schedule.scheduler_type),
            )
        pool = await self._get_connection_pool()
        async with await pool.acquire() as conn:  # pylint: disable=no-member # noqa
            AgentSchedule.Meta.connection = conn
            await schedule.delete()

    async def run_schedule_now(self, schedule_id: str) -> AgentSchedule:
        """Trigger ``schedule_id`` for one immediate, out-of-band execution.

        Schedules a one-shot APScheduler job (a ``DateTrigger`` firing
        "now", the same trigger type the ``"once"`` schedule_type already
        uses) that calls :meth:`_run_now_wrapper`, which in turn calls
        the exact same :meth:`_execute_agent_job` coroutine — and
        therefore the exact same ``job_success``/``job_status`` event
        handling, callbacks, ``send_result`` emails, and
        ``last_run``/``run_count``/``last_result`` stamping — as a
        normally scheduled run. Does NOT touch the schedule's
        ``enabled`` flag, trigger, or ``schedule_config`` (FEAT-467
        TASK-2520 Key Constraints); a paused/disabled job still runs
        once and stays paused.

        Args:
            schedule_id: The schedule to run immediately.

        Returns:
            The (unmodified) :class:`AgentSchedule` row, for the caller
            to serialize.

        Raises:
            SchedulerRunNowConflictError: A run-now execution is already
                active for this ``schedule_id`` — the handler maps this
                to HTTP 409.
            Exception: Whatever :meth:`get_schedule` raises for an
                unknown ``schedule_id`` — not special-cased here, same
                behaviour as ``pause_schedule``/``update_schedule``/
                ``delete_schedule``.
        """
        schedule_id = str(schedule_id)
        if schedule_id in self._run_now_active:
            raise SchedulerRunNowConflictError(
                f"A run-now execution is already active for schedule {schedule_id}."
            )

        schedule = await self.get_schedule(schedule_id)
        self._run_now_active.add(schedule_id)

        job_kwargs = self._job_kwargs_from_schedule(schedule)
        # Deterministic (not uuid-suffixed): the concurrency guard above
        # already rules out two simultaneous run-nows for the same
        # schedule_id, and job_success() needs to derive schedule_id
        # back out of this id when the one-shot job has already
        # self-removed by the time the listener runs (see that method).
        job_id = f"{_RUN_NOW_JOB_PREFIX}{schedule_id}"
        try:
            self.scheduler.add_job(
                self._run_now_wrapper,
                trigger=DateTrigger(run_date=datetime.now()),
                id=job_id,
                name=f"{schedule.agent_name}_run_now",
                kwargs=job_kwargs,
                jobstore=self._safe_jobstore(schedule.scheduler_type),
                replace_existing=False,
            )
        except Exception:
            self._run_now_active.discard(schedule_id)
            raise

        return schedule

    async def _run_now_wrapper(self, schedule_id: str, **kwargs) -> Any:
        """Release the run-now concurrency guard once execution finishes.

        A thin pass-through around :meth:`_execute_agent_job` — returns
        the same value / propagates the same exception, so
        ``job_success``/``job_status`` (which key off the job's return
        value / raised exception, not which coroutine APScheduler called)
        behave identically to a normal scheduled run. The ``finally``
        releases :attr:`_run_now_active` on BOTH success and failure.

        Args:
            schedule_id: The schedule this run-now execution belongs to.
            **kwargs: Forwarded verbatim to :meth:`_execute_agent_job`
                (``agent_name``, ``prompt``, ``method_name``,
                ``metadata``, ``is_crew``, ``send_result``, ``callbacks``).
        """
        try:
            return await self._execute_agent_job(schedule_id, **kwargs)
        finally:
            self._run_now_active.discard(str(schedule_id))

    async def get_last_result(self, schedule_id: str) -> Dict[str, Any]:
        """Return last-execution metadata for ``schedule_id`` (FEAT-467 TASK-2520).

        Args:
            schedule_id: The schedule to inspect.

        Returns:
            A dict with ``schedule_id``, ``last_run``, ``next_run``,
            ``run_count``, ``last_status`` (``"success"``/``"error"``/
            ``None``), ``last_result``, ``last_result_time``,
            ``last_error``, ``last_error_time`` — the last two populated
            only from a failed run, the two before them only from a
            successful one.

        Raises:
            Exception: Whatever :meth:`get_schedule` raises for an
                unknown ``schedule_id``.
        """
        schedule = await self.get_schedule(schedule_id)
        metadata = schedule.metadata or {}
        job = self.scheduler.get_job(str(schedule.schedule_id))
        next_run = None
        if job is not None and job.next_run_time:
            next_run = job.next_run_time.isoformat()
        elif schedule.next_run:
            next_run = schedule.next_run.isoformat()
        return {
            'schedule_id': str(schedule.schedule_id),
            'last_run': schedule.last_run.isoformat() if schedule.last_run else None,
            'next_run': next_run,
            'run_count': schedule.run_count,
            'last_status': metadata.get('last_status'),
            'last_result': metadata.get('last_result'),
            'last_result_time': metadata.get('last_result_time'),
            'last_error': metadata.get('last_error'),
            'last_error_time': metadata.get('last_error_time'),
        }

    def _registered_jobstores(self) -> Set[str]:
        """Return the jobstore aliases currently registered on the scheduler.

        Used to normalize a row's ``scheduler_type`` before it reaches
        ``add_job()``/``remove_job()``: APScheduler raises ``KeyError`` for an
        unregistered alias, which is exactly what happens when a schedule says
        ``'redis'`` but the scheduler was started with ``use_redis=False``.

        Returns:
            The set of known aliases; always contains ``'default'``.
        """
        aliases = {'default'}
        scheduler = self.scheduler
        if scheduler is not None:
            aliases.update(getattr(scheduler, '_jobstores', {}) or {})
        return aliases

    def _safe_jobstore(self, value: Any, *, strict: bool = False) -> str:
        """Normalize a ``scheduler_type`` value into a usable jobstore alias.

        Args:
            value: Raw ``scheduler_type`` from a schedule row or API payload.
            strict: Raise instead of falling back to ``'default'`` when the
                alias is not registered. Used for explicit API requests, where
                silently downgrading a caller's durability choice to an
                in-memory store would be worse than an error.

        Returns:
            A trimmed, lowercase alias that is registered on the scheduler.

        Raises:
            SchedulerConfigError: When ``strict`` and the alias is unknown.
        """
        return normalize_jobstore_alias(
            value, available=self._registered_jobstores(), strict=strict
        )

    def _build_jobstores(self, use_redis: bool = False) -> Dict[str, Any]:
        """Build the APScheduler jobstore mapping.

        Args:
            use_redis: When True, also include a Redis-backed jobstore under
                the ``'redis'`` alias (used by schedules whose
                ``scheduler_type`` is ``'redis'``). The ``'default'``
                ``MemoryJobStore`` is always present.

        Returns:
            A jobstore mapping suitable for ``AsyncIOScheduler(jobstores=...)``.
        """
        jobstores: Dict[str, Any] = {'default': MemoryJobStore()}
        if use_redis:
            jobstores['redis'] = self._make_redis_jobstore()
        return jobstores

    def _make_redis_jobstore(self) -> RedisJobStore:
        """Construct a `RedisJobStore` using the shared cache configuration."""
        # CACHE_HOST/CACHE_PORT come from navconfig, whose `fallback=` only
        # applies to *absent* keys — a present-but-empty `CACHE_PORT=` yields
        # ''. redis-py defers int(port) to the first connection, so an unclean
        # value would only surface as a per-tick "Error getting due jobs from
        # job store 'redis'" inside APScheduler's loop. Sanitize here instead.
        settings = sanitize_redis_settings(host=CACHE_HOST, port=CACHE_PORT, db=6)
        return RedisJobStore(
            jobs_key="apscheduler.jobs",
            run_times_key="apscheduler.run_times",
            **settings,
        )

    def _ensure_redis_jobstore(self) -> None:
        """Attach a ``'redis'`` jobstore to the running scheduler if absent.

        Idempotent: safe to call more than once (e.g. if `start_headless()`
        is invoked again) — APScheduler raises `ValueError` when the alias
        is already registered, which is swallowed here.
        """
        try:
            self.scheduler.add_jobstore(self._make_redis_jobstore(), alias='redis')
        except ValueError:
            # Alias already registered — nothing to do.
            pass

    async def start_headless(
        self,
        *,
        dsn: Optional[str] = None,
        use_redis: bool = False,
        register_listeners: bool = True,
    ) -> None:
        """Boot the scheduler without an aiohttp application.

        Only requires a running asyncio event loop. Builds/attaches the
        Redis jobstore only when requested, creates a Postgres connection
        pool only when a `dsn` is given (and none is already set),
        optionally wires the APScheduler event listeners, starts the
        scheduler, and loads persisted schedules from the database only
        when a pool exists.

        Args:
            dsn: Postgres DSN to build a connection pool from. When
                `None` (and no pool is already assigned via `self._pool`),
                the scheduler runs with decorator-registered schedules only.
            use_redis: When True, attach a Redis-backed jobstore under the
                `'redis'` alias. Defaults to `False` (MemoryJobStore only).
            register_listeners: When True (default), call
                `define_listeners()`. `on_startup()` passes `False` to stay
                strictly behaviour-preserving for the aiohttp path, where
                these listeners were never wired before FEAT-422 (this
                param exists so the standalone headless-daemon path — the
                only caller that needs `job_success`/`job_status`/etc.
                actually firing — can still opt in without changing
                aiohttp's existing runtime behaviour).
        """
        if use_redis:
            self._ensure_redis_jobstore()

        if dsn is not None and self._pool is None:
            self._pool = AsyncDB("pg", dsn=dsn)
            await self._pool.connection()
            self._owns_pool = True

        if register_listeners:
            self.define_listeners()

        if not self.scheduler.running:
            self.scheduler.start()

        if self._pool is not None:
            await self.load_schedules_from_db()

        self.logger.notice("Agent Scheduler started (headless)")

    async def stop_headless(self, *, wait: bool = True) -> None:
        """Stop a scheduler previously started via `start_headless()`.

        Tolerant of partial initialization: safe to call even if
        `start_headless()` was never called, or failed partway through.
        Only closes the connection pool when `start_headless()` created it
        itself (via `dsn`) — a pool injected from elsewhere (e.g. the
        aiohttp `on_startup()` path) is left for its owner to close.

        Args:
            wait: Passed through to `AsyncIOScheduler.shutdown(wait=...)`.
        """
        if self.scheduler is not None and self.scheduler.running:
            with contextlib.suppress(Exception):
                self.scheduler.shutdown(wait=wait)

        if self._owns_pool and self._pool is not None:
            with contextlib.suppress(Exception):
                await self._pool.close()
            self._pool = None
            self._owns_pool = False

        self.logger.notice("Agent Scheduler stopped (headless)")

    def setup(self, app: web.Application) -> web.Application:
        """
        Setup scheduler with aiohttp application.

        Similar to BotManager setup pattern.
        """
        # Database Pool:
        self.db = PostgresPool(
            dsn=default_dsn,
            name="Parrot.Scheduler",
            startup=self.on_startup,
            shutdown=self.on_shutdown
        )
        self.db.configure(app, register="agentdb")
        self.app = app

        # Add to app
        self.app[self.registered_name] = self

        # Configure routes
        router = self.app.router
        from ..handlers.scheduler import (  # pylint: disable=import-outside-toplevel
            SchedulerCallbacksHandler,
            SchedulerJobsHandler,
            SchedulerLastResultHandler,
        )
        router.add_view(
            '/api/v1/parrot/scheduler/schedules',
            SchedulerJobsHandler
        )
        router.add_view(
            '/api/v1/parrot/scheduler/schedules/{schedule_id}',
            SchedulerJobsHandler
        )
        # FEAT-467 TASK-2520 — last-execution-result read. Registered
        # alongside (not instead of) the {schedule_id} route above; the
        # extra `/last-result` path segment keeps this unambiguous for
        # aiohttp's UrlDispatcher (different segment count, no ordering
        # trap like the Studio `/skills/resync` vs `/skills/{id}` case).
        router.add_view(
            '/api/v1/parrot/scheduler/schedules/{schedule_id}/last-result',
            SchedulerLastResultHandler
        )
        router.add_view(
            '/api/v1/parrot/scheduler/callbacks',
            SchedulerCallbacksHandler
        )
        router.add_post(
            '/api/v1/parrot/scheduler/restart',
            self.restart_handler
        )

        return self.app

    async def on_startup(self, app: web.Application, conn: Callable):
        """Initialize scheduler on app startup."""
        self.logger.notice("Starting Agent Scheduler...")
        try:
            self._pool = conn
        except Exception as e:
            self.logger.error(
                f"Failed to get database connection pool: {e}"
            )
            self._pool = app['agentdb']

        # Delegate the transport-free bootstrap steps (jobstore(s),
        # scheduler start, schedule loading) to start_headless(). `self.
        # _pool` is already assigned above (owned by aiohttp's PostgresPool
        # via `conn`) so start_headless()'s own dsn-based pool creation is
        # skipped, while schedules are still loaded from it. `use_redis=
        # True` preserves the previous behaviour of always having a Redis
        # jobstore available under aiohttp. `register_listeners=False`
        # keeps this strictly behaviour-preserving: `define_listeners()`
        # was never called anywhere on this path before FEAT-422 (dead
        # code), so wiring it now would be a silent, undocumented change
        # to production aiohttp deployments (job_success/job_status
        # callbacks, notifications, DB updates firing for the first time)
        # — out of scope for this feature.
        await self.start_headless(use_redis=True, register_listeners=False)

        self.logger.notice(
            "Agent Scheduler started successfully"
        )

        # Register code-based schedules from active bots.
        # Fall back to the aiohttp app registry when no bot_manager was
        # injected explicitly at construction time — BotManager.setup()
        # stores itself under ``app['bot_manager']``.
        if self.bot_manager is None:
            self.bot_manager = app.get('bot_manager')

        if self.bot_manager:
            total_auto = sum(
                self.register_bot_schedules(bot)
                for _, bot in self.bot_manager.get_bots().items()
            )

            if total_auto > 0:
                self.logger.notice(
                    f"Registered {total_auto} auto-schedules from active bots"
                )
        else:
            self.logger.warning(
                "No bot_manager available; skipping auto-schedule registration "
                "(set bot_manager on AgentSchedulerManager or register a "
                "BotManager in the aiohttp app before startup)"
            )

    async def on_shutdown(self, app: web.Application, conn: Callable):
        """Cleanup on app shutdown."""
        self.logger.info("Shutting down Agent Scheduler...")

        # Delegate to stop_headless(): since on_startup() never sets
        # `_owns_pool` (the pool is owned by aiohttp's PostgresPool, not by
        # us), stop_headless() will shut the scheduler down but leave pool
        # teardown to its owner — identical to the previous behaviour.
        await self.stop_headless(wait=True)

        self.logger.notice("Agent Scheduler shut down")

    async def restart_handler(self, request: web.Request):
        """HTTP endpoint to restart scheduler."""
        try:
            await self.restart_scheduler()
            return web.json_response({
                'status': 'success',
                'message': 'Scheduler restarted successfully'
            })
        except Exception as e:
            return web.json_response({
                'status': 'error',
                'message': str(e)
            }, status=500)


class SchedulerHandler(CorsViewMixin, web.View):
    """HTTP handler for schedule management."""

    async def get(self):
        """Get schedule(s)."""
        scheduler_manager = self.request.app.get('scheduler_manager')
        schedule_id = self.request.match_info.get('schedule_id')

        try:
            if schedule_id:
                # Get specific schedule
                async with await self._pool.acquire() as conn:  # pylint: disable=no-member # noqa
                    AgentSchedule.Meta.connection = conn
                    schedule = await AgentSchedule.get(schedule_id=uuid.UUID(schedule_id))

                # Get job info from scheduler
                job = scheduler_manager.scheduler.get_job(schedule_id)
                job_info = {
                    'next_run': job.next_run_time.isoformat() if job and job.next_run_time else None,
                    'pending': job is not None
                }

                return web.json_response({
                    'schedule': dict(schedule),
                    'job': job_info
                })
            else:
                # List all schedules
                async with await self._pool.acquire() as conn:  # pylint: disable=no-member # noqa
                    AgentSchedule.Meta.connection = conn
                    results = await AgentSchedule.all()

                return web.json_response({
                    'schedules': [dict(r) for r in results],
                    'count': len(results)
                })

        except Exception as e:
            return web.json_response({
                'status': 'error',
                'message': str(e)
            }, status=500)

    async def post(self):
        """Create new schedule."""
        scheduler_manager = self.request.app.get('scheduler_manager')

        try:
            data = await self.request.json()

            # Extract session info
            session = await self.request.app.get('session_manager').get_session(
                self.request
            )
            created_by = session.get('user_id')
            created_email = session.get('email')

            schedule = await scheduler_manager.add_schedule(
                agent_name=data['agent_name'],
                schedule_type=data['schedule_type'],
                schedule_config=data['schedule_config'],
                prompt=data.get('prompt'),
                method_name=data.get('method_name'),
                created_by=created_by,
                created_email=created_email,
                metadata=data.get('metadata', {}),
                is_crew=data.get('is_crew', False),
                send_result=data.get('send_result'),
            )

            return web.json_response({
                'status': 'success',
                'schedule': dict(schedule)
            }, status=201)

        except Exception as e:
            return web.json_response({
                'status': 'error',
                'message': str(e)
            }, status=500)

    async def delete(self):
        """Delete schedule."""
        scheduler_manager = self.request.app.get('scheduler_manager')
        schedule_id = self.request.match_info.get('schedule_id')

        if not schedule_id:
            return web.json_response({
                'status': 'error',
                'message': 'schedule_id required'
            }, status=400)

        try:
            await scheduler_manager.remove_schedule(schedule_id)

            return web.json_response({
                'status': 'success',
                'message': f'Schedule {schedule_id} deleted'
            })

        except Exception as e:
            return web.json_response({
                'status': 'error',
                'message': str(e)
            }, status=500)

    async def patch(self):
        """Update schedule (enable/disable)."""
        schedule_id = self.request.match_info.get('schedule_id')

        if not schedule_id:
            return web.json_response({
                'status': 'error',
                'message': 'schedule_id required'
            }, status=400)

        try:
            data = await self.request.json()

            async with await self._pool.acquire() as conn:  # pylint: disable=no-member # noqa
                AgentSchedule.Meta.connection = conn
                schedule = await AgentSchedule.get(schedule_id=uuid.UUID(schedule_id))

                # Update fields
                if 'enabled' in data:
                    schedule.enabled = data['enabled']

                schedule.updated_at = datetime.now()
                await schedule.update()

                # If disabled, remove from scheduler
                scheduler_manager = self.request.app.get('scheduler_manager')
                if not schedule.enabled:
                    scheduler_manager.scheduler.remove_job(schedule_id)
                else:
                    # Re-add to scheduler
                    trigger = scheduler_manager._create_trigger(
                        schedule.schedule_type,
                        schedule.schedule_config
                    )
                    scheduler_manager.scheduler.add_job(
                        scheduler_manager._execute_agent_job,
                        trigger=trigger,
                        id=schedule_id,
                        name=f"{schedule.agent_name}_{schedule.schedule_type}",
                        kwargs={
                            'schedule_id': schedule_id,
                            'agent_name': schedule.agent_name,
                            'prompt': schedule.prompt,
                            'method_name': schedule.method_name,
                            'metadata': dict(schedule.metadata or {}),
                            'is_crew': schedule.is_crew,
                            'send_result': dict(schedule.send_result or {}),
                        },
                        replace_existing=True
                    )

                return web.json_response({
                    'status': 'success',
                    'schedule': dict(schedule)
                })

        except Exception as e:
            return web.json_response({
                'status': 'error',
                'message': str(e)
            }, status=500)
