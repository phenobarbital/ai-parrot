"""
Agent Scheduler Module for AI-Parrot.

This module provides scheduling capabilities for agents using APScheduler,
allowing agents to execute operations at specified intervals.
"""
import asyncio
import contextlib
import inspect
import json
from typing import Any, Dict, Optional, Callable, List, Tuple, Set
from datetime import datetime
import uuid
from enum import Enum
from functools import wraps
from aiohttp import web
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.jobstores.memory import MemoryJobStore
from apscheduler.jobstores.redis import RedisJobStore
from apscheduler.executors.asyncio import AsyncIOExecutor
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from apscheduler.triggers.date import DateTrigger
from apscheduler.events import (
    EVENT_JOB_ADDED,
    EVENT_JOB_ERROR,
    EVENT_JOB_EXECUTED,
    EVENT_JOB_MAX_INSTANCES,
    EVENT_JOB_MISSED,
    EVENT_JOB_SUBMITTED,
    EVENT_SCHEDULER_SHUTDOWN,
    EVENT_SCHEDULER_STARTED,
    JobExecutionEvent,
)
from apscheduler.jobstores.base import JobLookupError
from navconfig.logging import logging
from asyncdb import AsyncDB
from navigator.conf import CACHE_HOST, CACHE_PORT
from navigator.connections import PostgresPool
from querysource.conf import default_dsn
from .models import AgentSchedule
from ..notifications import NotificationMixin
from ..conf import ENVIRONMENT


# disable logging of APScheduler
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
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def wrapper(*args, **kwargs):
            return await func(*args, **kwargs)

        # Add scheduling metadata to the function
        wrapper._schedule_config = {
            'schedule_type': schedule_type.value,
            'schedule_config': schedule_config,
            'method_name': func.__name__
        }
        return wrapper
    return decorator


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
        send_result: Optional[Dict[str, Any]] = None
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
    ) -> None:
        """Execute success callback or fallback notification."""
        if success_callback:
            callback_result = success_callback(result)
            if inspect.isawaitable(callback_result):
                await callback_result
            return

        if not send_result:
            return

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
    ) -> None:
        """Finalize processing for successful job executions."""
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
        success_callback: Optional[Callable] = None
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
                    'schedule_id': str(schedule.schedule_id),
                    'agent_name': agent_name,
                    'prompt': prompt,
                    'method_name': method_name,
                    'metadata': dict(metadata or {}),
                    'is_crew': is_crew,
                    'success_callback': success_callback,
                    'send_result': dict(send_result or {}),
                },
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
                            },
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
        router.add_view(
            '/api/v1/parrot/scheduler/schedules',
            SchedulerHandler
        )
        router.add_view(
            '/api/v1/parrot/scheduler/schedules/{schedule_id}',
            SchedulerHandler
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

        # Load schedules from database
        await self.load_schedules_from_db()

        # Start scheduler
        self.scheduler.start()

        self.logger.notice(
            "Agent Scheduler started successfully"
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


class SchedulerHandler(web.View):
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
