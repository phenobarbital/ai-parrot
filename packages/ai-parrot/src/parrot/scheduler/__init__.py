"""
Agent Scheduler Module for AI-Parrot.

This module provides scheduling capabilities for agents using APScheduler,
allowing agents to execute operations at specified intervals.

APScheduler is an optional dependency — install with: pip install ai-parrot[scheduler]
"""
from __future__ import annotations
import asyncio
import contextlib
import inspect
import json
from typing import Any, Dict, Optional, Callable, List, Tuple, Set, TYPE_CHECKING
from datetime import datetime
import uuid
from enum import Enum
from functools import wraps
from aiohttp import web
from aiohttp_cors import CorsViewMixin
from navconfig.logging import logging
from asyncdb import AsyncDB
from navigator.connections import PostgresPool
from parrot._imports import lazy_import
from parrot.conf import default_dsn, CACHE_HOST, CACHE_PORT
from .models import AgentSchedule
from ..notifications import NotificationMixin
from ..conf import ENVIRONMENT
from .functions import build_scheduler_callback

if TYPE_CHECKING:
    from apscheduler.events import JobExecutionEvent


# Suppress APScheduler logging noise when the package is installed
with contextlib.suppress(Exception):
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
    if raw:
        try:
            parts = raw.strip().split(":")
            return {"hour": int(parts[0]), "minute": int(parts[1])}
        except (ValueError, IndexError, AttributeError):
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
    if raw:
        try:
            parts = raw.strip().split()
            dow = parts[0].lower()[:3]          # "monday" → "mon", "FRI" → "fri"
            time_parts = parts[1].split(":")
            return {
                "day_of_week": dow,
                "hour": int(time_parts[0]),
                "minute": int(time_parts[1]),
            }
        except (ValueError, IndexError, AttributeError):
            _log.warning("Could not parse weekly schedule %r; using default mon 09:00", raw)
    return {"day_of_week": "mon", "hour": 9, "minute": 0}


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

    def __init__(self, bot_manager=None):
        self.logger = logging.getLogger('Parrot.Scheduler')
        self.bot_manager = bot_manager
        self.app: Optional[web.Application] = None
        self.db: Optional[AsyncDB] = None
        self._pool: Optional[AsyncDB] = None  # Database connection pool
        self._job_context: Dict[str, Dict[str, Any]] = {}
        self._pending_success_tasks: Set[asyncio.Task] = set()

        # Lazy-import APScheduler components (optional dep: pip install ai-parrot[scheduler])
        _aps_sched = lazy_import(
            "apscheduler.schedulers.asyncio", package_name="apscheduler", extra="scheduler"
        )
        _aps_mem = lazy_import(
            "apscheduler.jobstores.memory", package_name="apscheduler", extra="scheduler"
        )
        _aps_redis = lazy_import(
            "apscheduler.jobstores.redis", package_name="apscheduler", extra="scheduler"
        )
        _aps_exec = lazy_import(
            "apscheduler.executors.asyncio", package_name="apscheduler", extra="scheduler"
        )
        AsyncIOScheduler = _aps_sched.AsyncIOScheduler
        MemoryJobStore = _aps_mem.MemoryJobStore
        RedisJobStore = _aps_redis.RedisJobStore
        AsyncIOExecutor = _aps_exec.AsyncIOExecutor

        # Configure APScheduler with AsyncIO
        jobstores = {
            'default': MemoryJobStore(),
            "redis": RedisJobStore(
                db=6,
                jobs_key="apscheduler.jobs",
                run_times_key="apscheduler.run_times",
                host=CACHE_HOST,
                port=CACHE_PORT,
            ),
        }
        executors = {
            'default': AsyncIOExecutor()
        }
        job_defaults = {
            'coalesce': True,  # Combine multiple missed runs into one
            'max_instances': 2,  # Maximum concurrent instances of each job
            'misfire_grace_time': 300  # 5 minutes grace period
        }

        self.scheduler = AsyncIOScheduler(
            jobstores=jobstores,
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
        _ev = lazy_import(
            "apscheduler.events", package_name="apscheduler", extra="scheduler"
        )
        # Asyncio Scheduler
        self.scheduler.add_listener(
            self.scheduler_status,
            _ev.EVENT_SCHEDULER_STARTED
        )
        self.scheduler.add_listener(
            self.scheduler_shutdown,
            _ev.EVENT_SCHEDULER_SHUTDOWN
        )
        self.scheduler.add_listener(self.job_success, _ev.EVENT_JOB_EXECUTED)
        self.scheduler.add_listener(self.job_status, _ev.EVENT_JOB_ERROR | _ev.EVENT_JOB_MISSED)
        # a new job was added:
        self.scheduler.add_listener(self.job_added, _ev.EVENT_JOB_ADDED)

    def scheduler_status(self, event):
        print(event)
        self.logger.debug(f"[{ENVIRONMENT} - NAV Scheduler] :: Started.")
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
        _ev = lazy_import(
            "apscheduler.events", package_name="apscheduler", extra="scheduler"
        )
        EVENT_JOB_MISSED = _ev.EVENT_JOB_MISSED
        EVENT_JOB_ERROR = _ev.EVENT_JOB_ERROR
        EVENT_JOB_MAX_INSTANCES = _ev.EVENT_JOB_MAX_INSTANCES
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
        _base = lazy_import(
            "apscheduler.jobstores.base", package_name="apscheduler", extra="scheduler"
        )
        JobLookupError = _base.JobLookupError
        job_id = event.job_id
        try:
            job = self.scheduler.get_job(job_id)
        except JobLookupError as err:
            self.logger.warning(f"Error found a Job with ID: {err}")
            return False
        job_name = job.name
        self.logger.info(
            f"[Scheduler - {ENVIRONMENT}]: {job_name} with id {event.job_id!s} \
            was queued/executed successfully @ {event.scheduled_run_time!s}"
        )

        job_kwargs = getattr(job, "kwargs", {}) or {}
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
                await self._update_schedule_run(schedule_id, success=True)
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

    async def _update_schedule_run(
        self,
        schedule_id: str,
        success: bool = True,
        error: Optional[str] = None
    ):
        """Update schedule record after execution."""
        try:
            async with await self._pool.acquire() as conn:  # pylint: disable=no-member # noqa
                AgentSchedule.Meta.connection = conn
                schedule = AgentSchedule.get(schedule_id=schedule_id)

                schedule.last_run = datetime.now()
                schedule.run_count += 1

                if error:
                    if not schedule.metadata:
                        schedule.metadata = {}
                    schedule.metadata['last_error'] = error
                    schedule.metadata['last_error_time'] = datetime.now().isoformat()

                await schedule.update()

        except Exception as e:
            self.logger.error(f"Failed to update schedule run: {e}")

    def _create_trigger(self, schedule_type: str, config: Dict[str, Any]):
        """
        Create APScheduler trigger based on schedule type and configuration.

        Args:
            schedule_type: Type of schedule (daily, weekly, monthly, interval, cron)
            config: Configuration dictionary for the trigger

        Returns:
            APScheduler trigger instance
        """
        _cron_mod = lazy_import(
            "apscheduler.triggers.cron", package_name="apscheduler", extra="scheduler"
        )
        _interval_mod = lazy_import(
            "apscheduler.triggers.interval", package_name="apscheduler", extra="scheduler"
        )
        _date_mod = lazy_import(
            "apscheduler.triggers.date", package_name="apscheduler", extra="scheduler"
        )
        CronTrigger = _cron_mod.CronTrigger
        IntervalTrigger = _interval_mod.IntervalTrigger
        DateTrigger = _date_mod.DateTrigger

        schedule_type = schedule_type.lower()

        if schedule_type == ScheduleType.ONCE.value:
            run_date = config.get('run_date', datetime.now())
            return DateTrigger(run_date=run_date)

        elif schedule_type == ScheduleType.DAILY.value:
            hour = config.get('hour', 0)
            minute = config.get('minute', 0)
            return CronTrigger(hour=hour, minute=minute)

        elif schedule_type == ScheduleType.WEEKLY.value:
            day_of_week = config.get('day_of_week', 'mon')
            hour = config.get('hour', 0)
            minute = config.get('minute', 0)
            return CronTrigger(day_of_week=day_of_week, hour=hour, minute=minute)

        elif schedule_type == ScheduleType.MONTHLY.value:
            day = config.get('day', 1)
            hour = config.get('hour', 0)
            minute = config.get('minute', 0)
            return CronTrigger(day=day, hour=hour, minute=minute)

        elif schedule_type == ScheduleType.INTERVAL.value:
            return IntervalTrigger(
                weeks=config.get('weeks', 0),
                days=config.get('days', 0),
                hours=config.get('hours', 0),
                minutes=config.get('minutes', 0),
                seconds=config.get('seconds', 0)
            )

        elif schedule_type == ScheduleType.CRON.value:
            # Full cron expression support
            return CronTrigger(**config)

        elif schedule_type == ScheduleType.CRONTAB.value:
            # Support for crontab syntax (same as cron but more user-friendly)
            return CronTrigger.from_crontab(**config, timezone='UTC')

        else:
            raise ValueError(
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
                self.logger.error(f"Error saving schedule object: {e}")
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
            self.logger.error(f"Error removing schedule {schedule_id}: {e}")
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
                    self.logger.warning(f"Error querying schedules: {error}")
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
                            jobstore=schedule_data.scheduler_type or 'default',
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
            self.logger.error(f"Error loading schedules from database: {e}")
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
            self.logger.error(f"Error restarting scheduler: {e}")
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
        payload = dict(schedule)
        job = self.scheduler.get_job(str(schedule.schedule_id))
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
        for key, value in updates.items():
            if key in editable_fields:
                setattr(schedule, key, value)
        schedule.updated_at = datetime.now()
        async with await pool.acquire() as conn:  # pylint: disable=no-member # noqa
            AgentSchedule.Meta.connection = conn
            await schedule.update()
        job_id = str(schedule.schedule_id)
        with contextlib.suppress(Exception):
            self.scheduler.remove_job(job_id, jobstore=old_scheduler_type)
        if schedule.enabled:
            trigger = self._create_trigger(schedule.schedule_type, schedule.schedule_config)
            job = self.scheduler.add_job(
                self._execute_agent_job,
                trigger=trigger,
                id=job_id,
                name=f"{schedule.agent_name}_{schedule.schedule_type}",
                kwargs=self._job_kwargs_from_schedule(schedule),
                jobstore=schedule.scheduler_type,
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
        _base = lazy_import(
            "apscheduler.jobstores.base", package_name="apscheduler", extra="scheduler"
        )
        with contextlib.suppress(_base.JobLookupError):
            self.scheduler.remove_job(str(schedule.schedule_id), jobstore=schedule.scheduler_type)
        pool = await self._get_connection_pool()
        async with await pool.acquire() as conn:  # pylint: disable=no-member # noqa
            AgentSchedule.Meta.connection = conn
            await schedule.delete()

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
        self.app['scheduler_manager'] = self

        # Configure routes
        router = self.app.router
        from ..handlers.scheduler import SchedulerCallbacksHandler, SchedulerJobsHandler  # pylint: disable=import-outside-toplevel
        router.add_view('/api/v1/parrot/scheduler/schedules', SchedulerJobsHandler)
        router.add_view('/api/v1/parrot/scheduler/schedules/{schedule_id}', SchedulerJobsHandler)
        router.add_view('/api/v1/parrot/scheduler/callbacks', SchedulerCallbacksHandler)
        router.add_post('/api/v1/parrot/scheduler/restart', self.restart_handler)

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

        # Load schedules from database
        await self.load_schedules_from_db()

        # Start scheduler
        self.scheduler.start()

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
            total_auto = 0
            for bot_name, bot in self.bot_manager.get_bots().items():
                total_auto += self.register_bot_schedules(bot)

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

        if self.scheduler.running:
            self.scheduler.shutdown(wait=True)

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
