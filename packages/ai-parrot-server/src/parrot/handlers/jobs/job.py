"""
Job Manager for Asynchronous Crew Execution.

Manages async execution of AgentCrew operations with job tracking,
status monitoring, and result retrieval.

When a ``RedisJobStore`` is provided at construction time the manager mirrors
every job mutation to Redis, making jobs durable across server restarts.
"""
from typing import Dict, Optional, Callable, Awaitable, Any, TYPE_CHECKING
import asyncio
import uuid
import contextlib
from datetime import datetime, timedelta, timezone
from navconfig.logging import logging
from .models import JobStatus, Job

if TYPE_CHECKING:
    from .redis_store import RedisJobStore


class JobManager:
    """Manages asynchronous job execution for crew operations.

    Provides:
    - Job creation and tracking
    - Async execution with asyncio.create_task
    - Status monitoring
    - Result retrieval
    - Automatic cleanup of old jobs
    - Optional Redis-backed persistence via RedisJobStore

    Args:
        id: Logical identifier for this manager instance.
        cleanup_interval: Seconds between automatic cleanup sweeps.
        job_ttl: Seconds to keep completed/failed jobs in memory (and Redis).
        store: Optional ``RedisJobStore`` instance.  When supplied every
            job create/update/delete is also mirrored to Redis so that
            job state survives server restarts.
    """

    def __init__(
        self,
        id: str = "default",
        cleanup_interval: int = 3600,
        job_ttl: int = 86400,
        store: Optional["RedisJobStore"] = None,
    ):
        self.id = id
        self.jobs: Dict[str, Job] = {}
        self.tasks: Dict[str, asyncio.Task] = {}
        self.logger = logging.getLogger("Parrot.JobManager")
        self.cleanup_interval = cleanup_interval
        self.job_ttl = job_ttl
        self._cleanup_task: Optional[asyncio.Task] = None
        self._running = False
        self._store: Optional["RedisJobStore"] = store

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Start the job manager and periodic cleanup task."""
        if not self._running:
            self._running = True
            self._cleanup_task = asyncio.create_task(self._cleanup_loop())
            self.logger.info("JobManager started (store=%s)", type(self._store).__name__)
            # Connect to Redis store if provided
            if self._store is not None:
                try:
                    await self._store.connect()
                    self.logger.info("RedisJobStore connected")
                except Exception as exc:  # pylint: disable=broad-except
                    self.logger.warning(
                        "RedisJobStore connection failed — jobs will be in-memory only: %s", exc
                    )
                    self._store = None

    async def stop(self) -> None:
        """Stop the job manager and cancel all running tasks."""
        self._running = False
        if self._cleanup_task:
            self._cleanup_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._cleanup_task
        running_tasks = list(self.tasks.values())
        for task in running_tasks:
            task.cancel()
        if running_tasks:
            await asyncio.gather(*running_tasks, return_exceptions=True)
        if self._store is not None:
            await self._store.close()
        self.logger.info("JobManager stopped")

    # ------------------------------------------------------------------
    # Persistence helpers
    # ------------------------------------------------------------------

    async def _persist(self, job: Job) -> None:
        """Save a job to the Redis store (silent on failure)."""
        if self._store is None:
            return
        try:
            await self._store.save(job)
        except Exception as exc:  # pylint: disable=broad-except
            self.logger.warning("RedisJobStore.save failed for job %s: %s", job.job_id, exc)

    async def _remove_from_store(self, job_id: str) -> None:
        """Remove a job from the Redis store (silent on failure)."""
        if self._store is None:
            return
        try:
            await self._store.delete(job_id)
        except Exception as exc:  # pylint: disable=broad-except
            self.logger.warning("RedisJobStore.delete failed for job %s: %s", job_id, exc)

    # ------------------------------------------------------------------
    # Job CRUD
    # ------------------------------------------------------------------

    def create_job(
        self,
        job_id: str,
        obj_id: str,
        query: Any,
        user_id: Optional[str] = None,
        session_id: Optional[str] = None,
        execution_mode: Optional[str] = None,
    ) -> Job:
        """Create a new job and register it in memory (and Redis if configured).

        Args:
            job_id: Unique identifier for the job.
            obj_id: ID of the object/handler that owns this job.
            query: The work payload (prompt, task description, etc.).
            user_id: Optional user identifier for tracking.
            session_id: Optional session identifier for tracking.
            execution_mode: Execution mode label (e.g. 'video_reel').

        Returns:
            The newly created Job.
        """
        job_id = job_id or str(uuid.uuid4())
        job = Job(
            job_id=job_id,
            obj_id=obj_id,
            query=query,
            status=JobStatus.PENDING,
            user_id=user_id,
            session_id=session_id,
            execution_mode=execution_mode,
        )
        self.jobs[job_id] = job
        self.logger.info("Created job %s for object %s", job_id, obj_id)
        # Persist asynchronously without blocking the caller
        asyncio.get_running_loop().create_task(self._persist(job))
        return job

    async def execute_job(
        self,
        job_id: str,
        execution_func: Callable[[], Awaitable[Any]],
    ) -> None:
        """Schedule a job for async execution.

        Args:
            job_id: ID of the job to execute.
            execution_func: Async callable that performs the actual work.
        """
        job = self.jobs.get(job_id)
        if not job:
            self.logger.error("Job %s not found", job_id)
            return
        task = asyncio.create_task(self._run_job(job_id, execution_func))
        self.tasks[job_id] = task
        self.logger.info("Started execution of job %s", job_id)

    async def _run_job(
        self,
        job_id: str,
        execution_func: Callable[[], Awaitable[Any]],
    ) -> None:
        """Internal coroutine that runs a job and updates its state."""
        job = self.jobs.get(job_id)
        if not job:
            return

        try:
            job.status = JobStatus.RUNNING
            job.started_at = datetime.now(timezone.utc)
            await self._persist(job)
            self.logger.info("Job %s started execution", job_id)

            result = await execution_func()

            job.status = JobStatus.COMPLETED
            job.result = result
            job.completed_at = datetime.now(timezone.utc)
            await self._persist(job)
            self.logger.info(
                "Job %s completed successfully in %.2fs",
                job_id,
                job.elapsed_time or 0,
            )

        except asyncio.CancelledError:
            job.status = JobStatus.CANCELLED
            job.completed_at = datetime.now(timezone.utc)
            job.error = "Job was cancelled"
            await self._persist(job)
            self.logger.warning("Job %s was cancelled", job_id)
            raise

        except Exception as exc:  # pylint: disable=broad-except
            job.status = JobStatus.FAILED
            job.completed_at = datetime.now(timezone.utc)
            job.error = str(exc)
            await self._persist(job)
            self.logger.error("Job %s failed: %s", job_id, exc, exc_info=True)

        finally:
            self.tasks.pop(job_id, None)

    def get_job(self, job_id: str) -> Optional[Job]:
        """Return a job from the in-memory store.

        If the job is not found in memory and a Redis store is configured,
        use ``get_job_async()`` instead for a full Redis lookup.

        Args:
            job_id: Job identifier.

        Returns:
            Job if found in memory, None otherwise.
        """
        return self.jobs.get(job_id)

    async def get_job_async(self, job_id: str) -> Optional[Job]:
        """Return a job from memory or Redis.

        Checks the in-memory dict first (fast path).  If not found and a
        Redis store is configured, queries Redis and — on a hit — re-hydrates
        the in-memory dict so subsequent calls are fast.

        Args:
            job_id: Job identifier.

        Returns:
            Job if found, None otherwise.
        """
        # Fast path: in memory
        job = self.jobs.get(job_id)
        if job is not None:
            return job

        # Slow path: Redis
        if self._store is not None:
            try:
                job = await self._store.get(job_id)
                if job is not None:
                    # Re-hydrate memory cache
                    self.jobs[job_id] = job
                    return job
            except Exception as exc:  # pylint: disable=broad-except
                self.logger.warning(
                    "RedisJobStore.get failed for job %s: %s", job_id, exc
                )

        return None

    def list_jobs(
        self,
        obj_id: Optional[str] = None,
        status: Optional[JobStatus] = None,
        limit: int = 100,
    ) -> list:
        """List in-memory jobs with optional filtering (newest first).

        For a full Redis-backed listing use ``list_jobs_async()``.

        Args:
            obj_id: Filter by object ID.
            status: Filter by status.
            limit: Maximum number of jobs to return.

        Returns:
            List of Job objects.
        """
        jobs = list(self.jobs.values())
        if obj_id:
            jobs = [j for j in jobs if j.obj_id == obj_id]
        if status:
            jobs = [j for j in jobs if j.status == status]
        jobs.sort(key=lambda j: j.created_at, reverse=True)
        return jobs[:limit]

    async def list_jobs_async(
        self,
        obj_id: Optional[str] = None,
        status: Optional[JobStatus] = None,
        limit: int = 100,
    ) -> list:
        """List jobs from Redis (if store configured) or memory.

        Args:
            obj_id: Filter by object ID.
            status: Filter by status.
            limit: Maximum number of jobs to return.

        Returns:
            List of Job objects sorted newest-first.
        """
        if self._store is not None:
            try:
                return await self._store.list_jobs(
                    obj_id=obj_id, status=status, limit=limit
                )
            except Exception as exc:  # pylint: disable=broad-except
                self.logger.warning(
                    "RedisJobStore.list_jobs failed, falling back to memory: %s", exc
                )
        return self.list_jobs(obj_id=obj_id, status=status, limit=limit)

    def delete_job(self, job_id: str) -> bool:
        """Delete a job from memory (and Redis if configured).

        Args:
            job_id: Job identifier.

        Returns:
            True if the job existed and was deleted.
        """
        if job_id in self.jobs:
            if job_id in self.tasks:
                self.tasks[job_id].cancel()
                del self.tasks[job_id]
            del self.jobs[job_id]
            asyncio.get_running_loop().create_task(self._remove_from_store(job_id))
            self.logger.info("Deleted job %s", job_id)
            return True
        return False

    # ------------------------------------------------------------------
    # Cleanup
    # ------------------------------------------------------------------

    async def _cleanup_loop(self) -> None:
        """Background task: periodically remove expired jobs."""
        while self._running:
            try:
                await asyncio.sleep(self.cleanup_interval)
                await self._cleanup_old_jobs()
            except asyncio.CancelledError:
                break
            except Exception as exc:  # pylint: disable=broad-except
                self.logger.error("Error in cleanup loop: %s", exc, exc_info=True)

    async def _cleanup_old_jobs(self) -> None:
        """Remove in-memory jobs older than ``job_ttl``."""
        now = datetime.now(timezone.utc)
        ttl_delta = timedelta(seconds=self.job_ttl)
        terminal_statuses = {JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED}

        jobs_to_delete = [
            job_id
            for job_id, job in self.jobs.items()
            if job.completed_at
            and (now - job.completed_at) > ttl_delta
            and job.status in terminal_statuses
        ]

        for job_id in jobs_to_delete:
            del self.jobs[job_id]
            if job_id in self.tasks:
                del self.tasks[job_id]

        if jobs_to_delete:
            self.logger.info("Cleaned up %d old jobs from memory", len(jobs_to_delete))

    # ------------------------------------------------------------------
    # Statistics
    # ------------------------------------------------------------------

    def get_stats(self) -> Dict[str, Any]:
        """Return statistics about the in-memory job queue.

        Returns:
            Dictionary with job counts by status and active task count.
        """
        total = len(self.jobs)
        return {
            "total_jobs": total,
            "running_jobs": sum(j.status == JobStatus.RUNNING for j in self.jobs.values()),
            "pending_jobs": sum(j.status == JobStatus.PENDING for j in self.jobs.values()),
            "completed_jobs": sum(j.status == JobStatus.COMPLETED for j in self.jobs.values()),
            "failed_jobs": sum(j.status == JobStatus.FAILED for j in self.jobs.values()),
            "active_tasks": len(self.tasks),
            "has_redis_store": self._store is not None,
        }

    # ------------------------------------------------------------------
    # RQ-compatible enqueue() helper
    # ------------------------------------------------------------------

    def enqueue(
        self,
        func: Callable,
        args: tuple = None,
        kwargs: dict = None,
        queue: str = "default",
        timeout: Optional[int] = None,
        result_ttl: Optional[int] = None,
        job_id: Optional[str] = None,
        **extra_kwargs,
    ) -> Job:
        """Enqueue a function for async execution (RQ-compatible API).

        Args:
            func: Function to execute (sync or async).
            args: Positional arguments for the function.
            kwargs: Keyword arguments for the function.
            queue: Queue name label (stored in metadata).
            timeout: Execution timeout in seconds (not enforced).
            result_ttl: How long to keep results (informational).
            job_id: Optional job ID; generated if not provided.
            **extra_kwargs: Ignored additional kwargs.

        Returns:
            The created Job.
        """
        args = args or ()
        kwargs = kwargs or {}
        job_id = job_id or str(uuid.uuid4())

        async def async_execution_wrapper() -> Any:
            if asyncio.iscoroutinefunction(func):
                return await func(*args, **kwargs)
            return await asyncio.get_running_loop().run_in_executor(
                None, lambda: func(*args, **kwargs)
            )

        job = self.create_job(
            job_id=job_id,
            obj_id=func.__name__,
            query={
                "function": func.__name__,
                "args": str(args),
                "kwargs": str(kwargs),
            },
            execution_mode=queue,
        )
        if job.metadata is None:
            job.metadata = {}
        job.metadata["timeout"] = timeout
        job.metadata["result_ttl"] = result_ttl
        job.metadata["queue"] = queue

        asyncio.create_task(self.execute_job(job_id, async_execution_wrapper))
        return job

    def fetch_job(self, job_id: str) -> Optional[Job]:
        """Fetch a job by ID (RQ-compatible API).

        Args:
            job_id: The job identifier.

        Returns:
            Job if found in memory, None otherwise.
        """
        return self.get_job(job_id)
