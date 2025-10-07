"""
Agent Scheduler Module for AI-Parrot.

This module provides scheduling capabilities for agents using APScheduler,
allowing agents to execute operations at specified intervals.
"""
from typing import Any, Dict, Optional, Callable, List
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
from navconfig.logging import logging
from asyncdb import AsyncDB
from navigator.conf import CACHE_HOST, CACHE_PORT
from navigator.connections import PostgresPool
from querysource.conf import default_dsn
from .models import AgentSchedule

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

    async def _execute_agent_job(
        self,
        schedule_id: str,
        agent_name: str,
        prompt: Optional[str] = None,
        method_name: Optional[str] = None,
        metadata: Optional[Dict] = None
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

            # Get agent instance from bot manager
            if not self.bot_manager:
                raise RuntimeError("Bot manager not available")

            agent = self.bot_manager._bots.get(agent_name)
            if not agent:
                # Try to get from registry
                agent = await self.bot_manager.registry.get_instance(agent_name)

            if not agent:
                raise ValueError(f"Agent {agent_name} not found")

            # Execute based on type
            if method_name:
                # Call specific method
                if not hasattr(agent, method_name):
                    raise AttributeError(
                        f"Agent {agent_name} has no method {method_name}"
                    )
                method = getattr(agent, method_name)
                if not callable(method):
                    raise TypeError(f"{method_name} is not callable")

                result = await method()
            elif prompt:
                # Send prompt to agent
                result = await agent.chat(prompt)
            else:
                raise ValueError("Either prompt or method_name must be provided")

            # Update schedule record
            await self._update_schedule_run(schedule_id, success=True)

            self.logger.info(
                f"Successfully executed job {schedule_id} for agent {agent_name}"
            )

            return result

        except Exception as e:
            self.logger.error(
                f"Error executing scheduled job {schedule_id}: {e}",
                exc_info=True
            )
            await self._update_schedule_run(schedule_id, success=False, error=str(e))
            raise

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
        agent_id: Optional[str] = None
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
            metadata: Additional metadata
            agent_id: Optional agent ID

        Returns:
            Created AgentSchedule instance
        """
        # Validate agent exists
        if self.bot_manager:
            agent = self.bot_manager._bots.get(agent_name)
            if not agent:
                agent = await self.bot_manager.registry.get_instance(agent_name)
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
                    metadata=metadata or {}
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
                    'metadata': metadata
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
            raise RuntimeError(f"Failed to add schedule to jobstore: {e}")

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
                                'metadata': schedule_data.metadata
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
                metadata=data.get('metadata', {})
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
                            'metadata': schedule.metadata
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
