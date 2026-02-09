"""
AgentService: Standalone asyncio runtime for autonomous AI agents.

This service runs independently from the web server (aiohttp) and provides:
- Heartbeat scheduler: agents "wake up" periodically to check for pending work
- Cron scheduler: scheduled task execution with cron expressions
- Worker pool: asyncio workers consuming tasks from queues
- Redis IPC: communication bridge with the web server via Redis Streams/Pub-Sub
- Task persistence: jobs survive restarts via Redis

Architecture:
    ┌─────────────────────────────────────────────────────┐
    │                   AgentService                       │
    │                                                      │
    │  ┌──────────────┐  ┌──────────────┐  ┌───────────┐ │
    │  │  Heartbeat    │  │    Cron      │  │  Redis    │ │
    │  │  Scheduler    │  │  Scheduler   │  │  Listener │ │
    │  └──────┬───────┘  └──────┬───────┘  └─────┬─────┘ │
    │         │                  │                 │       │
    │         └──────────┬───────┘                 │       │
    │                    ▼                         │       │
    │            ┌───────────────┐                 │       │
    │            │  Task Queue   │◄────────────────┘       │
    │            │ (asyncio.Queue│                         │
    │            │  + Redis)     │                         │
    │            └───────┬───────┘                         │
    │                    │                                  │
    │         ┌──────────┼──────────┐                      │
    │         ▼          ▼          ▼                       │
    │    ┌─────────┐┌─────────┐┌─────────┐               │
    │    │ Worker 1 ││ Worker 2 ││ Worker N │              │
    │    │ (agent   ││ (agent   ││ (agent   │              │
    │    │  exec)   ││  exec)   ││  exec)   │              │
    │    └─────────┘└─────────┘└─────────┘               │
    └─────────────────────────────────────────────────────┘
             │                          ▲
             │ Results/Notifications     │ Task Requests
             ▼                          │
    ┌─────────────────┐      ┌──────────────────┐
    │  Redis Streams   │      │  aiohttp Server  │
    │  (IPC channel)   │      │  (REST/WebSocket) │
    └─────────────────┘      └──────────────────┘

Usage:
    # Standalone process:
    python -m parrot.services.agent_service --config agents.yaml

    # Programmatic:
    service = AgentService(config=AgentServiceConfig(...))
    asyncio.run(service.run())

    # Or embed alongside web server in same process (shared event loop):
    loop = asyncio.get_event_loop()
    loop.create_task(service.start())
"""
from __future__ import annotations

import asyncio
import json
import signal
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, TYPE_CHECKING

from navconfig.logging import logging

try:
    from croniter import croniter
    HAS_CRONITER = True
except ImportError:
    HAS_CRONITER = False
    croniter = None

try:
    from asyncdb import AsyncDB
    HAS_ASYNCDB = True
except ImportError:
    HAS_ASYNCDB = False
    AsyncDB = None

if TYPE_CHECKING:
    from ..registry import AgentRegistry


logger = logging.getLogger("Parrot.AgentService")


# =============================================================================
# Enums & Config
# =============================================================================


class TaskPriority(Enum):
    """Priority levels for task execution ordering."""

    LOW = 0
    NORMAL = 1
    HIGH = 2
    CRITICAL = 3


class TaskStatus(Enum):
    """Task lifecycle states."""

    PENDING = "pending"
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    RETRYING = "retrying"


class SessionMode(Enum):
    """How the agent session is managed for a task."""

    MAIN = "main"  # Uses the agent's persistent session/context
    ISOLATED = "isolated"  # Fresh session, no conversation history


class WakeMode(Enum):
    """When to execute a heartbeat-triggered task."""

    NOW = "now"  # Execute immediately
    NEXT_HEARTBEAT = "next_beat"  # Wait for next scheduled heartbeat


@dataclass
class AgentServiceConfig:
    """Configuration for the AgentService."""

    # Service identity
    service_name: str = "parrot-agent-service"
    service_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])

    # Worker pool
    max_workers: int = 5
    queue_size: int = 100

    # Redis IPC
    redis_dsn: str = "redis://localhost:6379/0"
    task_stream: str = "parrot:agent:tasks"
    result_stream: str = "parrot:agent:results"
    notification_channel: str = "parrot:agent:notifications"

    # Persistence
    state_prefix: str = "parrot:agent:state"
    jobs_prefix: str = "parrot:agent:jobs"
    cron_prefix: str = "parrot:agent:cron"

    # Heartbeat defaults
    default_heartbeat_interval: int = 1800  # 30 minutes
    default_active_hours: tuple = (7, 23)

    # Graceful shutdown timeout
    shutdown_timeout: int = 30

    # Task retry
    max_retries: int = 3
    retry_backoff_base: float = 2.0


# =============================================================================
# Task Definition
# =============================================================================


@dataclass
class AgentTask:
    """A unit of work to be executed by an agent."""

    task_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    agent_name: str = ""
    prompt: str = ""
    priority: TaskPriority = TaskPriority.NORMAL
    status: TaskStatus = TaskStatus.PENDING
    session_mode: SessionMode = SessionMode.MAIN

    # Execution context
    user_id: Optional[str] = None
    session_id: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    # Overrides for isolated sessions
    model_override: Optional[str] = None
    max_tokens: Optional[int] = None

    # Scheduling
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    scheduled_at: Optional[datetime] = None

    # Results
    result: Optional[Any] = None
    error: Optional[str] = None
    retries: int = 0

    # Delivery: where to send results
    delivery_channel: Optional[str] = None  # "websocket", "webhook", "redis", "email"
    delivery_target: Optional[str] = None

    # Source: who originated this task
    source: str = "internal"  # "heartbeat", "cron", "api", "internal", "redis"

    def to_dict(self) -> Dict[str, Any]:
        """Serialize task to dictionary for Redis persistence."""
        return {
            "task_id": self.task_id,
            "agent_name": self.agent_name,
            "prompt": self.prompt,
            "priority": self.priority.value,
            "status": self.status.value,
            "session_mode": self.session_mode.value,
            "user_id": self.user_id,
            "session_id": self.session_id,
            "metadata": self.metadata,
            "model_override": self.model_override,
            "created_at": self.created_at.isoformat(),
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "result": str(self.result) if self.result else None,
            "error": self.error,
            "retries": self.retries,
            "source": self.source,
            "delivery_channel": self.delivery_channel,
            "delivery_target": self.delivery_target,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> AgentTask:
        """Deserialize task from dictionary."""
        return cls(
            task_id=data.get("task_id", str(uuid.uuid4())),
            agent_name=data["agent_name"],
            prompt=data["prompt"],
            priority=TaskPriority(data.get("priority", 1)),
            status=TaskStatus(data.get("status", "pending")),
            session_mode=SessionMode(data.get("session_mode", "main")),
            user_id=data.get("user_id"),
            session_id=data.get("session_id"),
            metadata=data.get("metadata", {}),
            model_override=data.get("model_override"),
            source=data.get("source", "internal"),
            delivery_channel=data.get("delivery_channel"),
            delivery_target=data.get("delivery_target"),
        )


# =============================================================================
# Priority Queue (asyncio.PriorityQueue wrapper)
# =============================================================================


class TaskQueue:
    """
    Priority-based async task queue with optional Redis persistence.

    Tasks are ordered by priority (CRITICAL > HIGH > NORMAL > LOW),
    then by creation time (FIFO within same priority).
    """

    def __init__(self, maxsize: int = 100, redis: Optional[Any] = None):
        self._queue: asyncio.PriorityQueue = asyncio.PriorityQueue(maxsize=maxsize)
        self._redis = redis
        self._pending: Dict[str, AgentTask] = {}
        self._lock = asyncio.Lock()

    async def put(self, task: AgentTask) -> None:
        """Enqueue a task with priority ordering."""
        # Lower number = higher priority in PriorityQueue
        # We invert: CRITICAL(3) -> sort_key(0), LOW(0) -> sort_key(3)
        sort_key = (3 - task.priority.value, task.created_at.timestamp())
        task.status = TaskStatus.QUEUED
        async with self._lock:
            self._pending[task.task_id] = task
        await self._queue.put((sort_key, task.task_id, task))
        if self._redis:
            await self._persist_task(task)

    async def get(self) -> AgentTask:
        """Dequeue the highest-priority task."""
        _, task_id, task = await self._queue.get()
        async with self._lock:
            self._pending.pop(task_id, None)
        return task

    def task_done(self) -> None:
        """Mark a task as done."""
        self._queue.task_done()

    @property
    def qsize(self) -> int:
        """Return current queue size."""
        return self._queue.qsize()

    @property
    def empty(self) -> bool:
        """Check if queue is empty."""
        return self._queue.empty()

    async def _persist_task(self, task: AgentTask) -> None:
        """Persist task state to Redis for crash recovery."""
        try:
            async with self._redis as conn:
                await conn.set(
                    f"parrot:queue:{task.task_id}",
                    json.dumps(task.to_dict()),
                    ex=86400,  # 24h TTL
                )
        except Exception as e:
            logger.warning(f"Failed to persist task {task.task_id}: {e}")

    async def recover_pending(self) -> int:
        """Recover pending tasks from Redis after restart."""
        if not self._redis:
            return 0
        recovered = 0
        try:
            async with self._redis as conn:
                keys = await conn.keys("parrot:queue:*")
                for key in keys:
                    data = await conn.get(key)
                    if data:
                        task = AgentTask.from_dict(json.loads(data))
                        if task.status in (TaskStatus.PENDING, TaskStatus.QUEUED):
                            await self.put(task)
                            recovered += 1
                        await conn.delete(key)
        except Exception as e:
            logger.error(f"Failed to recover tasks: {e}")
        return recovered


# =============================================================================
# Heartbeat Scheduler
# =============================================================================


@dataclass
class HeartbeatConfig:
    """Configuration for an agent's heartbeat."""

    agent_name: str
    interval_seconds: int = 1800
    active_hours: tuple = (7, 23)  # UTC hours
    enabled: bool = True
    heartbeat_prompt: Optional[str] = None
    tasks_source: Optional[str] = None  # File or DB key for pending tasks
    noop_token: str = "HEARTBEAT_OK"  # Agent responds with this if nothing to do
    wake_mode: WakeMode = WakeMode.NOW


class HeartbeatScheduler:
    """
    Manages periodic heartbeats for registered agents.

    Each agent gets its own heartbeat loop. On each beat, the agent
    receives a heartbeat prompt, reasons about pending work, and either
    returns HEARTBEAT_OK (no-op) or generates tasks to enqueue.
    """

    def __init__(self, task_queue: TaskQueue):
        self._queue = task_queue
        self._configs: Dict[str, HeartbeatConfig] = {}
        self._tasks: Dict[str, asyncio.Task] = {}
        self._running = False

    def register(self, config: HeartbeatConfig) -> None:
        """Register a heartbeat for an agent."""
        self._configs[config.agent_name] = config
        logger.info(
            f"Heartbeat registered: {config.agent_name} "
            f"every {config.interval_seconds}s"
        )
        if self._running and config.agent_name not in self._tasks:
            self._tasks[config.agent_name] = asyncio.create_task(
                self._heartbeat_loop(config)
            )

    def unregister(self, agent_name: str) -> None:
        """Stop and remove a heartbeat."""
        if agent_name in self._tasks:
            self._tasks[agent_name].cancel()
            del self._tasks[agent_name]
        self._configs.pop(agent_name, None)

    async def start(self) -> None:
        """Start all registered heartbeat loops."""
        self._running = True
        for name, config in self._configs.items():
            if config.enabled:
                self._tasks[name] = asyncio.create_task(self._heartbeat_loop(config))
        logger.info(f"HeartbeatScheduler started with {len(self._tasks)} agents")

    async def stop(self) -> None:
        """Stop all heartbeat loops."""
        self._running = False
        for task in self._tasks.values():
            task.cancel()
        await asyncio.gather(*self._tasks.values(), return_exceptions=True)
        self._tasks.clear()

    async def _heartbeat_loop(self, config: HeartbeatConfig) -> None:
        """Main heartbeat loop for a single agent."""
        agent_name = config.agent_name
        logger.info(f"Heartbeat loop started for {agent_name}")

        while self._running:
            try:
                now = datetime.now(timezone.utc)
                if not self._in_active_hours(now, config.active_hours):
                    sleep_seconds = self._seconds_until_active(now, config.active_hours)
                    logger.debug(
                        f"{agent_name}: outside active hours, sleeping {sleep_seconds}s"
                    )
                    await asyncio.sleep(min(sleep_seconds, config.interval_seconds))
                    continue

                prompt = await self._build_heartbeat_prompt(config)
                task = AgentTask(
                    agent_name=agent_name,
                    prompt=prompt,
                    priority=TaskPriority.LOW,
                    session_mode=SessionMode.MAIN,
                    source="heartbeat",
                    metadata={
                        "heartbeat": True,
                        "noop_token": config.noop_token,
                        "beat_time": now.isoformat(),
                    },
                )
                await self._queue.put(task)
                logger.debug(f"Heartbeat enqueued for {agent_name}")

                await asyncio.sleep(config.interval_seconds)

            except asyncio.CancelledError:
                logger.info(f"Heartbeat loop cancelled for {agent_name}")
                break
            except Exception as e:
                logger.error(f"Heartbeat error for {agent_name}: {e}", exc_info=True)
                await asyncio.sleep(60)

    async def _build_heartbeat_prompt(self, config: HeartbeatConfig) -> str:
        """Build the heartbeat prompt for an agent."""
        now = datetime.now(timezone.utc)

        if config.heartbeat_prompt:
            return config.heartbeat_prompt.format(
                current_time=now.isoformat(), agent_name=config.agent_name
            )

        return (
            f"[HEARTBEAT] Time: {now.isoformat()}\n"
            f"You are agent '{config.agent_name}' running autonomously.\n"
            f"Review your pending tasks and context.\n"
            f"If nothing requires action, respond with: {config.noop_token}\n"
            f"Otherwise, describe what action you are taking and execute it."
        )

    @staticmethod
    def _in_active_hours(now: datetime, active_hours: tuple) -> bool:
        """Check if current time is within active hours."""
        start, end = active_hours
        hour = now.hour
        if start <= end:
            return start <= hour < end
        # Wraps around midnight (e.g., 22 to 6)
        return hour >= start or hour < end

    @staticmethod
    def _seconds_until_active(now: datetime, active_hours: tuple) -> int:
        """Calculate seconds until active hours start."""
        start_hour = active_hours[0]
        target = now.replace(hour=start_hour, minute=0, second=0, microsecond=0)
        if target <= now:
            target += timedelta(days=1)
        return int((target - now).total_seconds())


# =============================================================================
# Cron Scheduler
# =============================================================================


@dataclass
class CronJob:
    """A scheduled cron job definition."""

    job_id: str = field(default_factory=lambda: str(uuid.uuid4())[:12])
    name: str = ""
    agent_name: str = ""
    prompt: str = ""

    # Schedule: one of these must be set
    cron_expression: Optional[str] = None  # "0 7 * * *"
    run_at: Optional[datetime] = None  # One-shot at specific time
    interval_seconds: Optional[int] = None  # Simple interval

    # Execution
    session_mode: SessionMode = SessionMode.ISOLATED
    model_override: Optional[str] = None
    priority: TaskPriority = TaskPriority.NORMAL

    # Delivery
    delivery_channel: Optional[str] = None
    delivery_target: Optional[str] = None

    # State
    enabled: bool = True
    delete_after_run: bool = False  # One-shot jobs
    last_run: Optional[datetime] = None
    next_run: Optional[datetime] = None
    run_count: int = 0
    max_runs: Optional[int] = None  # None = unlimited

    # Timezone
    timezone_str: str = "UTC"

    def compute_next_run(self) -> Optional[datetime]:
        """Compute the next run time based on schedule type."""
        now = datetime.now(timezone.utc)

        if self.cron_expression and HAS_CRONITER:
            cron = croniter(self.cron_expression, now)
            self.next_run = cron.get_next(datetime).replace(tzinfo=timezone.utc)
            return self.next_run

        if self.run_at:
            if self.run_at > now and self.run_count == 0:
                self.next_run = self.run_at
                return self.next_run
            return None

        if self.interval_seconds:
            base = self.last_run or now
            self.next_run = base + timedelta(seconds=self.interval_seconds)
            return self.next_run

        return None

    def should_run(self, now: datetime) -> bool:
        """Check if this job should run at the given time."""
        if not self.enabled:
            return False
        if self.max_runs is not None and self.run_count >= self.max_runs:
            return False
        if self.next_run is None:
            self.compute_next_run()
        return self.next_run is not None and now >= self.next_run

    def to_dict(self) -> Dict[str, Any]:
        """Serialize job to dictionary."""
        return {
            "job_id": self.job_id,
            "name": self.name,
            "agent_name": self.agent_name,
            "prompt": self.prompt,
            "cron_expression": self.cron_expression,
            "run_at": self.run_at.isoformat() if self.run_at else None,
            "interval_seconds": self.interval_seconds,
            "session_mode": self.session_mode.value,
            "model_override": self.model_override,
            "enabled": self.enabled,
            "delete_after_run": self.delete_after_run,
            "last_run": self.last_run.isoformat() if self.last_run else None,
            "next_run": self.next_run.isoformat() if self.next_run else None,
            "run_count": self.run_count,
            "max_runs": self.max_runs,
            "delivery_channel": self.delivery_channel,
            "delivery_target": self.delivery_target,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> CronJob:
        """Deserialize job from dictionary."""
        run_at = data.get("run_at")
        if run_at and isinstance(run_at, str):
            run_at = datetime.fromisoformat(run_at)

        last_run = data.get("last_run")
        if last_run and isinstance(last_run, str):
            last_run = datetime.fromisoformat(last_run)

        next_run = data.get("next_run")
        if next_run and isinstance(next_run, str):
            next_run = datetime.fromisoformat(next_run)

        return cls(
            job_id=data.get("job_id", str(uuid.uuid4())[:12]),
            name=data.get("name", ""),
            agent_name=data.get("agent_name", ""),
            prompt=data.get("prompt", ""),
            cron_expression=data.get("cron_expression"),
            run_at=run_at,
            interval_seconds=data.get("interval_seconds"),
            session_mode=SessionMode(data.get("session_mode", "isolated")),
            model_override=data.get("model_override"),
            priority=TaskPriority(data.get("priority", 1)),
            enabled=data.get("enabled", True),
            delete_after_run=data.get("delete_after_run", False),
            last_run=last_run,
            next_run=next_run,
            run_count=data.get("run_count", 0),
            max_runs=data.get("max_runs"),
            delivery_channel=data.get("delivery_channel"),
            delivery_target=data.get("delivery_target"),
        )


class CronScheduler:
    """
    Cron-based task scheduler.

    Evaluates all registered cron jobs every N seconds and enqueues
    tasks that are due for execution.
    """

    def __init__(
        self,
        task_queue: TaskQueue,
        check_interval: float = 30.0,
        redis: Optional[Any] = None,
        state_prefix: str = "parrot:agent:cron",
    ):
        self._queue = task_queue
        self._check_interval = check_interval
        self._redis = redis
        self._state_prefix = state_prefix
        self._jobs: Dict[str, CronJob] = {}
        self._task: Optional[asyncio.Task] = None
        self._running = False

    def add_job(self, job: CronJob) -> str:
        """Add a cron job. Returns job_id."""
        job.compute_next_run()
        self._jobs[job.job_id] = job
        logger.info(f"Cron job added: {job.name} ({job.job_id}) next_run={job.next_run}")
        if self._redis:
            asyncio.create_task(self._persist_job(job))
        return job.job_id

    def remove_job(self, job_id: str) -> bool:
        """Remove a cron job by ID."""
        if job_id in self._jobs:
            del self._jobs[job_id]
            if self._redis:
                asyncio.create_task(self._delete_job_state(job_id))
            return True
        return False

    def list_jobs(self) -> List[Dict[str, Any]]:
        """List all registered cron jobs."""
        return [job.to_dict() for job in self._jobs.values()]

    async def start(self) -> None:
        """Start the cron scheduler loop."""
        self._running = True
        await self._recover_jobs()
        self._task = asyncio.create_task(self._scheduler_loop())
        logger.info(f"CronScheduler started with {len(self._jobs)} jobs")

    async def stop(self) -> None:
        """Stop the cron scheduler."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        await self._persist_all()

    async def _scheduler_loop(self) -> None:
        """Main loop: check all jobs every check_interval seconds."""
        while self._running:
            try:
                now = datetime.now(timezone.utc)
                jobs_to_remove = []

                for job_id, job in self._jobs.items():
                    if job.should_run(now):
                        await self._execute_job(job)
                        job.last_run = now
                        job.run_count += 1
                        if job.delete_after_run:
                            jobs_to_remove.append(job_id)
                        else:
                            job.compute_next_run()
                            if self._redis:
                                await self._persist_job(job)

                for job_id in jobs_to_remove:
                    self.remove_job(job_id)
                    logger.info(f"One-shot cron job {job_id} removed after execution")

                await asyncio.sleep(self._check_interval)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"CronScheduler error: {e}", exc_info=True)
                await asyncio.sleep(self._check_interval)

    async def _execute_job(self, job: CronJob) -> None:
        """Create and enqueue a task from a cron job."""
        task = AgentTask(
            agent_name=job.agent_name,
            prompt=f"[cron:{job.job_id} {job.name}] {job.prompt}",
            priority=job.priority,
            session_mode=job.session_mode,
            model_override=job.model_override,
            source="cron",
            delivery_channel=job.delivery_channel,
            delivery_target=job.delivery_target,
            metadata={
                "cron_job_id": job.job_id,
                "cron_job_name": job.name,
                "run_count": job.run_count + 1,
            },
        )
        await self._queue.put(task)
        logger.info(f"Cron job enqueued: {job.name} -> task {task.task_id}")

    async def _persist_job(self, job: CronJob) -> None:
        """Persist job state to Redis."""
        try:
            async with self._redis as conn:
                await conn.set(
                    f"{self._state_prefix}:{job.job_id}", json.dumps(job.to_dict())
                )
        except Exception as e:
            logger.warning(f"Failed to persist cron job {job.job_id}: {e}")

    async def _delete_job_state(self, job_id: str) -> None:
        """Delete job state from Redis."""
        try:
            async with self._redis as conn:
                await conn.delete(f"{self._state_prefix}:{job_id}")
        except Exception as e:
            logger.warning(f"Failed to delete cron job state {job_id}: {e}")

    async def _recover_jobs(self) -> None:
        """Recover persisted cron jobs from Redis."""
        if not self._redis:
            return
        try:
            async with self._redis as conn:
                keys = await conn.keys(f"{self._state_prefix}:*")
                for key in keys:
                    data = await conn.get(key)
                    if data:
                        job = CronJob.from_dict(json.loads(data))
                        job.compute_next_run()
                        self._jobs[job.job_id] = job
            logger.info(f"Recovered {len(self._jobs)} cron jobs from Redis")
        except Exception as e:
            logger.error(f"Failed to recover cron jobs: {e}")

    async def _persist_all(self) -> None:
        """Persist all job states before shutdown."""
        if not self._redis:
            return
        for job in self._jobs.values():
            await self._persist_job(job)


# =============================================================================
# Worker Pool
# =============================================================================


class WorkerPool:
    """
    Pool of async workers that consume tasks from the queue
    and execute them against registered agents.
    """

    def __init__(
        self,
        task_queue: TaskQueue,
        agent_factory: Callable,
        num_workers: int = 5,
        max_retries: int = 3,
        retry_backoff: float = 2.0,
        result_callback: Optional[Callable] = None,
    ):
        self._queue = task_queue
        self._agent_factory = agent_factory
        self._num_workers = num_workers
        self._max_retries = max_retries
        self._retry_backoff = retry_backoff
        self._result_callback = result_callback
        self._workers: List[asyncio.Task] = []
        self._running = False
        self._active_tasks: Dict[str, AgentTask] = {}
        self._semaphore = asyncio.Semaphore(num_workers)

    async def start(self) -> None:
        """Start the worker pool."""
        self._running = True
        for i in range(self._num_workers):
            worker = asyncio.create_task(self._worker_loop(worker_id=i))
            self._workers.append(worker)
        logger.info(f"WorkerPool started with {self._num_workers} workers")

    async def stop(self) -> None:
        """Stop all workers."""
        self._running = False
        for worker in self._workers:
            worker.cancel()
        await asyncio.gather(*self._workers, return_exceptions=True)
        self._workers.clear()
        logger.info("WorkerPool stopped")

    @property
    def active_count(self) -> int:
        """Number of currently active tasks."""
        return len(self._active_tasks)

    @property
    def stats(self) -> Dict[str, Any]:
        """Worker pool statistics."""
        return {
            "workers": self._num_workers,
            "active_tasks": self.active_count,
            "queue_size": self._queue.qsize,
        }

    async def _worker_loop(self, worker_id: int) -> None:
        """Main worker loop: dequeue and execute tasks."""
        logger.debug(f"Worker-{worker_id} started")

        while self._running:
            try:
                task = await self._queue.get()

                async with self._semaphore:
                    self._active_tasks[task.task_id] = task
                    try:
                        await self._execute_task(task, worker_id)
                    finally:
                        self._active_tasks.pop(task.task_id, None)
                        self._queue.task_done()

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Worker-{worker_id} unexpected error: {e}", exc_info=True)
                await asyncio.sleep(1)

        logger.debug(f"Worker-{worker_id} stopped")

    async def _execute_task(self, task: AgentTask, worker_id: int) -> None:
        """Execute a single task with retry logic."""
        task.status = TaskStatus.RUNNING
        task.started_at = datetime.now(timezone.utc)
        logger.info(
            f"Worker-{worker_id} executing task {task.task_id} "
            f"({task.agent_name}, source={task.source})"
        )

        try:
            agent = await self._agent_factory(
                agent_name=task.agent_name,
                session_mode=task.session_mode,
                model_override=task.model_override,
                task=task,
            )

            if agent is None:
                raise RuntimeError(f"Agent '{task.agent_name}' not found")

            result = await self._run_agent(agent, task)

            # Check for heartbeat no-op
            is_heartbeat = task.metadata.get("heartbeat", False)
            noop_token = task.metadata.get("noop_token", "HEARTBEAT_OK")
            if is_heartbeat and noop_token in str(result):
                logger.debug(f"Heartbeat no-op for {task.agent_name}")
                task.status = TaskStatus.COMPLETED
                task.result = None
                task.completed_at = datetime.now(timezone.utc)
                return

            task.status = TaskStatus.COMPLETED
            task.result = result
            task.completed_at = datetime.now(timezone.utc)

            logger.info(
                f"Task {task.task_id} completed "
                f"({(task.completed_at - task.started_at).total_seconds():.2f}s)"
            )

            if task.delivery_channel:
                await self._deliver_result(task)

            if self._result_callback:
                await self._result_callback(task)

        except Exception as e:
            task.retries += 1
            if task.retries <= self._max_retries:
                backoff = self._retry_backoff**task.retries
                logger.warning(
                    f"Task {task.task_id} failed (attempt {task.retries}), "
                    f"retrying in {backoff}s: {e}"
                )
                task.status = TaskStatus.RETRYING
                await asyncio.sleep(backoff)
                await self._queue.put(task)
            else:
                task.status = TaskStatus.FAILED
                task.error = str(e)
                task.completed_at = datetime.now(timezone.utc)
                logger.error(
                    f"Task {task.task_id} failed permanently after "
                    f"{self._max_retries} retries: {e}"
                )
                if self._result_callback:
                    await self._result_callback(task)

    async def _run_agent(self, agent: Any, task: AgentTask) -> Any:
        """Run the agent with the task prompt."""
        kwargs = {}
        if task.user_id:
            kwargs["user_id"] = task.user_id
        if task.session_id:
            kwargs["session_id"] = task.session_id

        if hasattr(agent, "ask"):
            response, _ = await agent.ask(task.prompt, **kwargs)
            return response
        elif hasattr(agent, "run"):
            return await agent.run(task.prompt, **kwargs)
        else:
            raise TypeError(f"Agent {task.agent_name} has no 'ask' or 'run' method")

    async def _deliver_result(self, task: AgentTask) -> None:
        """Deliver task results to the specified channel."""
        channel = task.delivery_channel
        target = task.delivery_target

        if channel == "redis" and self._queue._redis:
            try:
                async with self._queue._redis as conn:
                    await conn.publish(
                        f"parrot:delivery:{target or 'default'}",
                        json.dumps(task.to_dict()),
                    )
            except Exception as e:
                logger.error(f"Redis delivery failed: {e}")

        elif channel == "webhook":
            logger.info(f"Webhook delivery to {target}: {task.task_id}")

        elif channel == "websocket":
            if self._queue._redis:
                try:
                    async with self._queue._redis as conn:
                        await conn.publish(
                            "parrot:ws:push",
                            json.dumps(
                                {
                                    "user_id": task.user_id,
                                    "task_id": task.task_id,
                                    "result": str(task.result),
                                    "agent_name": task.agent_name,
                                }
                            ),
                        )
                except Exception as e:
                    logger.error(f"WebSocket delivery via Redis failed: {e}")

        else:
            logger.debug(f"No delivery handler for channel '{channel}'")


# =============================================================================
# Redis IPC Listener
# =============================================================================


class RedisTaskListener:
    """
    Listens for task requests from the web server via Redis Streams.

    Protocol:
        Web Server -> XADD parrot:agent:tasks { agent_name, prompt, ... }
        AgentService <- XREAD (blocking) from parrot:agent:tasks
        AgentService -> XADD parrot:agent:results { task_id, result, ... }
    """

    def __init__(
        self,
        task_queue: TaskQueue,
        redis_dsn: str,
        task_stream: str = "parrot:agent:tasks",
        result_stream: str = "parrot:agent:results",
        consumer_group: str = "agent-service",
        consumer_name: Optional[str] = None,
    ):
        self._queue = task_queue
        self._redis_dsn = redis_dsn
        self._task_stream = task_stream
        self._result_stream = result_stream
        self._consumer_group = consumer_group
        self._consumer_name = consumer_name or f"worker-{uuid.uuid4().hex[:8]}"
        self._redis = None
        self._task: Optional[asyncio.Task] = None
        self._running = False

    async def start(self) -> None:
        """Start listening for tasks."""
        self._running = True
        if HAS_ASYNCDB:
            self._redis = AsyncDB("redis", dsn=self._redis_dsn)
        self._task = asyncio.create_task(self._listen_loop())
        logger.info(f"RedisTaskListener started on stream '{self._task_stream}'")

    async def stop(self) -> None:
        """Stop the listener."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def publish_result(self, task: AgentTask) -> None:
        """Publish task result back to Redis Stream."""
        if not self._redis:
            return
        try:
            async with self._redis as conn:
                await conn.execute(
                    "XADD",
                    self._result_stream,
                    "*",
                    "task_id",
                    task.task_id,
                    "agent_name",
                    task.agent_name,
                    "status",
                    task.status.value,
                    "result",
                    json.dumps(str(task.result) if task.result else None),
                    "error",
                    task.error or "",
                    "source",
                    task.source,
                    "user_id",
                    task.user_id or "",
                )
        except Exception as e:
            logger.error(f"Failed to publish result: {e}")

    async def _listen_loop(self) -> None:
        """Main loop: read from Redis Stream and enqueue tasks."""
        if not self._redis:
            logger.warning("Redis not available, listener disabled")
            return

        # Ensure consumer group exists
        try:
            async with self._redis as conn:
                await conn.execute(
                    "XGROUP",
                    "CREATE",
                    self._task_stream,
                    self._consumer_group,
                    "0",
                    "MKSTREAM",
                )
        except Exception:
            pass  # Group may already exist

        last_id = ">"  # Read only new messages

        while self._running:
            try:
                async with self._redis as conn:
                    messages = await conn.execute(
                        "XREADGROUP",
                        "GROUP",
                        self._consumer_group,
                        self._consumer_name,
                        "COUNT",
                        "10",
                        "BLOCK",
                        "5000",
                        "STREAMS",
                        self._task_stream,
                        last_id,
                    )

                if not messages:
                    continue

                for stream_name, entries in messages:
                    for msg_id, fields in entries:
                        try:
                            task_data = self._parse_stream_message(fields)
                            task = AgentTask.from_dict(task_data)
                            task.source = "redis"
                            await self._queue.put(task)
                            logger.info(
                                f"Received task from Redis: {task.task_id} "
                                f"({task.agent_name})"
                            )
                            async with self._redis as conn:
                                await conn.execute(
                                    "XACK",
                                    self._task_stream,
                                    self._consumer_group,
                                    msg_id,
                                )
                        except Exception as e:
                            logger.error(f"Failed to parse task from stream: {e}")

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Redis listener error: {e}")
                await asyncio.sleep(5)

    @staticmethod
    def _parse_stream_message(fields: list) -> Dict[str, Any]:
        """Parse flat Redis Stream fields into a dict."""
        data = {}
        it = iter(fields)
        for key, value in zip(it, it):
            key = key.decode() if isinstance(key, bytes) else key
            value = value.decode() if isinstance(value, bytes) else value
            try:
                data[key] = json.loads(value)
            except (json.JSONDecodeError, TypeError):
                data[key] = value
        return data


# =============================================================================
# AgentService: Main Orchestrator
# =============================================================================


class AgentService:
    """
    Standalone asyncio service for autonomous agent execution.

    This is the main entry point. It composes:
    - TaskQueue: priority-based async queue
    - HeartbeatScheduler: periodic agent wake-ups
    - CronScheduler: cron-based task scheduling
    - WorkerPool: concurrent task execution
    - RedisTaskListener: IPC with the web server
    """

    def __init__(
        self,
        config: Optional[AgentServiceConfig] = None,
        agent_registry: Optional[AgentRegistry] = None,
    ):
        self.config = config or AgentServiceConfig()
        self._registry = agent_registry
        self._redis = None

        # Components (initialized in start())
        self._queue: Optional[TaskQueue] = None
        self._heartbeat: Optional[HeartbeatScheduler] = None
        self._cron: Optional[CronScheduler] = None
        self._workers: Optional[WorkerPool] = None
        self._listener: Optional[RedisTaskListener] = None

        # Agent instances cache (for MAIN session mode)
        self._agent_cache: Dict[str, Any] = {}
        self._agent_locks: Dict[str, asyncio.Lock] = {}

        # Service state
        self._running = False
        self._shutdown_event = asyncio.Event()

    # ---- Lifecycle ----

    async def start(self) -> None:
        """Initialize all components and start the service."""
        logger.info(
            f"Starting AgentService '{self.config.service_name}' "
            f"(id={self.config.service_id})"
        )

        if HAS_ASYNCDB:
            self._redis = AsyncDB("redis", dsn=self.config.redis_dsn)

        self._queue = TaskQueue(maxsize=self.config.queue_size, redis=self._redis)

        self._heartbeat = HeartbeatScheduler(task_queue=self._queue)
        self._cron = CronScheduler(
            task_queue=self._queue,
            redis=self._redis,
            state_prefix=self.config.cron_prefix,
        )

        self._workers = WorkerPool(
            task_queue=self._queue,
            agent_factory=self._resolve_agent,
            num_workers=self.config.max_workers,
            max_retries=self.config.max_retries,
            retry_backoff=self.config.retry_backoff_base,
            result_callback=self._on_task_complete,
        )

        self._listener = RedisTaskListener(
            task_queue=self._queue,
            redis_dsn=self.config.redis_dsn,
            task_stream=self.config.task_stream,
            result_stream=self.config.result_stream,
        )

        recovered = await self._queue.recover_pending()
        if recovered:
            logger.info(f"Recovered {recovered} pending tasks from Redis")

        await self._workers.start()
        await self._heartbeat.start()
        await self._cron.start()
        await self._listener.start()

        self._running = True
        logger.info(
            f"AgentService started: "
            f"workers={self.config.max_workers}, "
            f"heartbeats={len(self._heartbeat._configs)}, "
            f"cron_jobs={len(self._cron._jobs)}"
        )

    async def stop(self) -> None:
        """Graceful shutdown of all components."""
        logger.info("Shutting down AgentService...")
        self._running = False

        await self._listener.stop()
        await self._heartbeat.stop()
        await self._cron.stop()

        try:
            await asyncio.wait_for(
                self._drain_workers(), timeout=self.config.shutdown_timeout
            )
        except asyncio.TimeoutError:
            logger.warning(
                f"Shutdown timeout ({self.config.shutdown_timeout}s), "
                f"force-stopping workers"
            )

        await self._workers.stop()

        for agent in self._agent_cache.values():
            if hasattr(agent, "close"):
                try:
                    await agent.close()
                except Exception:
                    pass
        self._agent_cache.clear()

        self._shutdown_event.set()
        logger.info("AgentService stopped")

    async def _drain_workers(self) -> None:
        """Wait until all active tasks are complete."""
        while self._workers.active_count > 0:
            await asyncio.sleep(0.5)

    async def run(self) -> None:
        """
        Main entry point: start the service and run until interrupted.

        Usage:
            service = AgentService(config=config, agent_registry=registry)
            asyncio.run(service.run())
        """
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, lambda: asyncio.create_task(self.stop()))

        await self.start()
        await self._shutdown_event.wait()

    # ---- Agent Resolution ----

    async def _resolve_agent(
        self,
        agent_name: str,
        session_mode: SessionMode = SessionMode.MAIN,
        model_override: Optional[str] = None,
        task: Optional[AgentTask] = None,
    ) -> Any:
        """
        Resolve an agent instance for task execution.

        MAIN mode: returns a cached, persistent agent instance.
        ISOLATED mode: creates a fresh agent instance per task.
        """
        if session_mode == SessionMode.ISOLATED:
            return await self._create_agent(agent_name, model_override=model_override)

        if agent_name not in self._agent_locks:
            self._agent_locks[agent_name] = asyncio.Lock()

        async with self._agent_locks[agent_name]:
            if agent_name not in self._agent_cache:
                agent = await self._create_agent(agent_name, model_override=model_override)
                if agent:
                    self._agent_cache[agent_name] = agent
            return self._agent_cache.get(agent_name)

    async def _create_agent(
        self, agent_name: str, model_override: Optional[str] = None
    ) -> Any:
        """Create and configure an agent instance."""
        if self._registry:
            agent = await self._registry.get_instance(agent_name)
            if agent and model_override:
                if hasattr(agent, "set_model"):
                    agent.set_model(model_override)
            return agent

        logger.error(f"No agent registry configured, cannot resolve '{agent_name}'")
        return None

    # ---- Result Handling ----

    async def _on_task_complete(self, task: AgentTask) -> None:
        """Called when a task completes (success or failure)."""
        if self._listener:
            await self._listener.publish_result(task)

        if task.status == TaskStatus.COMPLETED:
            logger.info(
                f"Task {task.task_id} completed: "
                f"agent={task.agent_name}, source={task.source}"
            )
        elif task.status == TaskStatus.FAILED:
            logger.error(
                f"Task {task.task_id} failed: "
                f"agent={task.agent_name}, error={task.error}"
            )

    # ---- Public API ----

    async def submit_task(self, task: AgentTask) -> str:
        """Submit a task for execution. Returns task_id."""
        await self._queue.put(task)
        return task.task_id

    async def submit(
        self,
        agent_name: str,
        prompt: str,
        *,
        priority: TaskPriority = TaskPriority.NORMAL,
        session_mode: SessionMode = SessionMode.MAIN,
        user_id: Optional[str] = None,
        delivery_channel: Optional[str] = None,
        delivery_target: Optional[str] = None,
        **metadata,
    ) -> str:
        """Convenience method to submit a task. Returns task_id."""
        task = AgentTask(
            agent_name=agent_name,
            prompt=prompt,
            priority=priority,
            session_mode=session_mode,
            user_id=user_id,
            source="api",
            delivery_channel=delivery_channel,
            delivery_target=delivery_target,
            metadata=metadata,
        )
        return await self.submit_task(task)

    def register_heartbeat(self, config: HeartbeatConfig) -> None:
        """Register an agent heartbeat."""
        self._heartbeat.register(config)

    def add_cron_job(self, job: CronJob) -> str:
        """Add a cron job. Returns job_id."""
        return self._cron.add_job(job)

    def remove_cron_job(self, job_id: str) -> bool:
        """Remove a cron job."""
        return self._cron.remove_job(job_id)

    @property
    def stats(self) -> Dict[str, Any]:
        """Get service statistics."""
        return {
            "service_name": self.config.service_name,
            "service_id": self.config.service_id,
            "running": self._running,
            "workers": self._workers.stats if self._workers else {},
            "heartbeats": len(self._heartbeat._configs) if self._heartbeat else 0,
            "cron_jobs": len(self._cron._jobs) if self._cron else 0,
            "cached_agents": len(self._agent_cache),
        }


# =============================================================================
# Client: For the web server to submit tasks to the AgentService
# =============================================================================


class AgentServiceClient:
    """
    Client for the web server to communicate with the AgentService
    via Redis Streams.

    Usage in aiohttp:
        client = AgentServiceClient(redis_dsn="redis://localhost:6379/0")

        # In a request handler:
        task_id = await client.submit_task(
            agent_name="my_agent",
            prompt="Analyze quarterly report",
            user_id=request_user_id,
            delivery_channel="websocket",
        )

        # Poll for result:
        result = await client.get_result(task_id, timeout=60)
    """

    def __init__(
        self,
        redis_dsn: str = "redis://localhost:6379/0",
        task_stream: str = "parrot:agent:tasks",
        result_stream: str = "parrot:agent:results",
    ):
        self._redis_dsn = redis_dsn
        self._task_stream = task_stream
        self._result_stream = result_stream
        self._redis = None
        if HAS_ASYNCDB:
            self._redis = AsyncDB("redis", dsn=redis_dsn)

    async def submit_task(
        self,
        agent_name: str,
        prompt: str,
        *,
        priority: int = 1,
        session_mode: str = "main",
        user_id: Optional[str] = None,
        delivery_channel: Optional[str] = None,
        delivery_target: Optional[str] = None,
        **metadata,
    ) -> str:
        """Submit a task to the AgentService via Redis Stream."""
        task_id = str(uuid.uuid4())

        fields = {
            "task_id": task_id,
            "agent_name": agent_name,
            "prompt": prompt,
            "priority": str(priority),
            "session_mode": session_mode,
            "user_id": user_id or "",
            "delivery_channel": delivery_channel or "",
            "delivery_target": delivery_target or "",
            "metadata": json.dumps(metadata),
        }

        try:
            async with self._redis as conn:
                flat_fields = []
                for k, v in fields.items():
                    flat_fields.extend([k, str(v)])
                await conn.execute("XADD", self._task_stream, "*", *flat_fields)
        except Exception as e:
            logger.error(f"Failed to submit task: {e}")
            raise

        return task_id

    async def get_result(
        self,
        task_id: str,
        timeout: float = 60.0,
        poll_interval: float = 0.5,
    ) -> Optional[Dict[str, Any]]:
        """Poll for a task result from the result stream."""
        deadline = asyncio.get_event_loop().time() + timeout

        while asyncio.get_event_loop().time() < deadline:
            try:
                async with self._redis as conn:
                    entries = await conn.execute(
                        "XREVRANGE", self._result_stream, "+", "-", "COUNT", "50"
                    )
                    if entries:
                        for msg_id, fields in entries:
                            data = {}
                            it = iter(fields)
                            for k, v in zip(it, it):
                                k = k.decode() if isinstance(k, bytes) else k
                                v = v.decode() if isinstance(v, bytes) else v
                                data[k] = v
                            if data.get("task_id") == task_id:
                                return data
            except Exception as e:
                logger.warning(f"Error polling result: {e}")

            await asyncio.sleep(poll_interval)

        return None


# =============================================================================
# Entry point for standalone execution
# =============================================================================

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Parrot Agent Service")
    parser.add_argument("--workers", type=int, default=5, help="Number of workers")
    parser.add_argument("--redis", type=str, default="redis://localhost:6379/0")
    parser.add_argument("--name", type=str, default="parrot-agent-service")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    )

    config = AgentServiceConfig(
        service_name=args.name,
        max_workers=args.workers,
        redis_dsn=args.redis,
    )

    service = AgentService(config=config)
    asyncio.run(service.run())
