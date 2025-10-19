"""
Job Manager for Asynchronous Crew Execution.

Manages async execution of AgentCrew operations with job tracking,
status monitoring, and result retrieval.
"""
from typing import Dict, Optional, Callable, Awaitable, Any
import asyncio
import uuid
import contextlib
from datetime import datetime, timedelta, timezone
from navconfig.logging import logging
from .models import JobStatus, Job


class JobManager:
    """
    Manages asynchronous job execution for crew operations.

    Provides:
    - Job creation and tracking
    - Async execution with asyncio.create_task
    - Status monitoring
    - Result retrieval
    - Automatic cleanup of old jobs
    """

    def __init__(
        self,
        id: str = "default",
        cleanup_interval: int = 3600,  # 1 hour
        job_ttl: int = 86400  # 24 hours
    ):
        """
        Initialize JobManager.

        Args:
            cleanup_interval: Interval in seconds between cleanup runs
            job_ttl: Time-to-live for completed jobs in seconds
        """
        self.id = id
        self.jobs: Dict[str, Job] = {}
        self.tasks: Dict[str, asyncio.Task] = {}
        self.logger = logging.getLogger('Parrot.JobManager')
        self.cleanup_interval = cleanup_interval
        self.job_ttl = job_ttl
        self._cleanup_task: Optional[asyncio.Task] = None
        self._running = False
        self._loop = asyncio.get_event_loop()

    async def start(self):
        """Start the job manager and cleanup task."""
        if not self._running:
            self._running = True
            self._cleanup_task = asyncio.create_task(self._cleanup_loop())
            self.logger.info("JobManager started")

    async def stop(self):
        """Stop the job manager and cleanup task."""
        self._running = False
        if self._cleanup_task:
            self._cleanup_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._cleanup_task
        # Cancel all running tasks
        for task in self.tasks.values():
            task.cancel()
        self.logger.info("JobManager stopped")

    def create_job(
        self,
        job_id: str,
        obj_id: str,
        query: Any,
        user_id: Optional[str] = None,
        session_id: Optional[str] = None,
        execution_mode: Optional[str] = None
    ) -> Job:
        """
        Create a new job for crew execution.

        Args:
            obj_id: ID of the object to execute
            query: Query or task for the object
            user_id: Optional user identifier
            session_id: Optional session identifier
            execution_mode: Execution mode (sequential, parallel, flow)

        Returns:
            CrewJob: The created job
        """
        job_id = job_id or str(uuid.uuid4())
        job = Job(
            job_id=job_id,
            obj_id=obj_id,
            query=query,
            status=JobStatus.PENDING,
            user_id=user_id,
            session_id=session_id,
            execution_mode=execution_mode
        )
        self.jobs[job_id] = job
        self.logger.info(f"Created job {job_id} for object {obj_id}")
        return job

    async def execute_job(
        self,
        job_id: str,
        execution_func: Callable[[], Awaitable[Any]]
    ) -> None:
        """
        Execute a job asynchronously.

        Args:
            job_id: ID of the job to execute
            execution_func: Async function that executes the crew
        """
        job = self.jobs.get(job_id)
        if not job:
            self.logger.error(f"Job {job_id} not found")
            return

        # Create async task
        task = asyncio.create_task(self._run_job(job_id, execution_func))
        self.tasks[job_id] = task
        self.logger.info(f"Started execution of job {job_id}")

    async def _run_job(
        self,
        job_id: str,
        execution_func: Callable[[], Awaitable[Any]]
    ) -> None:
        """
        Internal method to run a job.

        Args:
            job_id: ID of the job
            execution_func: Async function to execute
        """
        job = self.jobs.get(job_id)
        if not job:
            return

        try:
            # Update status to running
            job.status = JobStatus.RUNNING
            job.started_at = datetime.now(timezone.utc)
            self.logger.info(f"Job {job_id} started execution")

            # Execute the function
            result = await execution_func()

            # Update job with result
            job.status = JobStatus.COMPLETED
            job.result = result
            job.completed_at = datetime.now(timezone.utc)
            self.logger.info(
                f"Job {job_id} completed successfully in "
                f"{job.elapsed_time:.2f}s"
            )

        except asyncio.CancelledError:
            job.status = JobStatus.CANCELLED
            job.completed_at = datetime.now(timezone.utc)
            job.error = "Job was cancelled"
            self.logger.warning(f"Job {job_id} was cancelled")
            raise

        except Exception as e:
            job.status = JobStatus.FAILED
            job.completed_at = datetime.now(timezone.utc)
            job.error = str(e)
            self.logger.error(f"Job {job_id} failed: {e}", exc_info=True)

        finally:
            # Remove from active tasks
            if job_id in self.tasks:
                del self.tasks[job_id]

    def get_job(self, job_id: str) -> Optional[Job]:
        """
        Get a job by ID.

        Args:
            job_id: Job identifier

        Returns:
            Job if found, None otherwise
        """
        print('JOBS > ', self.jobs)
        return self.jobs.get(job_id)

    def list_jobs(
        self,
        obj_id: Optional[str] = None,
        status: Optional[JobStatus] = None,
        limit: int = 100
    ) -> list[Job]:
        """
        List jobs with optional filtering.

        Args:
            obj_id: Filter by object ID
            status: Filter by status
            limit: Maximum number of jobs to return

        Returns:
            List of jobs matching criteria
        """
        jobs = list(self.jobs.values())

        # Apply filters
        if obj_id:
            jobs = [j for j in jobs if j.obj_id == obj_id]
        if status:
            jobs = [j for j in jobs if j.status == status]

        # Sort by creation time (newest first)
        jobs.sort(key=lambda j: j.created_at, reverse=True)

        return jobs[:limit]

    def delete_job(self, job_id: str) -> bool:
        """
        Delete a job.

        Args:
            job_id: Job identifier

        Returns:
            True if deleted, False if not found
        """
        if job_id in self.jobs:
            # Cancel task if running
            if job_id in self.tasks:
                self.tasks[job_id].cancel()
                del self.tasks[job_id]

            del self.jobs[job_id]
            self.logger.info(f"Deleted job {job_id}")
            return True
        return False

    async def _cleanup_loop(self):
        """Background task to clean up old jobs."""
        while self._running:
            try:
                await asyncio.sleep(self.cleanup_interval)
                await self._cleanup_old_jobs()
            except asyncio.CancelledError:
                break
            except Exception as e:
                self.logger.error(f"Error in cleanup loop: {e}", exc_info=True)

    async def _cleanup_old_jobs(self):
        """Remove jobs older than TTL."""
        now = datetime.now(timezone.utc)
        ttl_delta = timedelta(seconds=self.job_ttl)

        jobs_to_delete = []
        jobs_to_delete.extend(
            job_id
            for job_id, job in self.jobs.items()
            if job.completed_at
            and (now - job.completed_at) > ttl_delta
            and job.status
            in [JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED]
        )

        for job_id in jobs_to_delete:
            self.delete_job(job_id)

        if jobs_to_delete:
            self.logger.info(f"Cleaned up {len(jobs_to_delete)} old jobs")

    def get_stats(self) -> Dict[str, Any]:
        """
        Get statistics about job manager.

        Returns:
            Dictionary with job statistics
        """
        total_jobs = len(self.jobs)
        running_jobs = sum(j.status == JobStatus.RUNNING for j in self.jobs.values())
        pending_jobs = sum(j.status == JobStatus.PENDING for j in self.jobs.values())
        completed_jobs = sum(j.status == JobStatus.COMPLETED for j in self.jobs.values())
        failed_jobs = sum(j.status == JobStatus.FAILED for j in self.jobs.values())

        return {
            'total_jobs': total_jobs,
            'running_jobs': running_jobs,
            'pending_jobs': pending_jobs,
            'completed_jobs': completed_jobs,
            'failed_jobs': failed_jobs,
            'active_tasks': len(self.tasks)
        }

    def enqueue(
        self,
        func: Callable,
        args: tuple = None,
        kwargs: dict = None,
        queue: str = "default",
        timeout: Optional[int] = None,
        result_ttl: Optional[int] = None,
        job_id: Optional[str] = None,
        **extra_kwargs
    ) -> Job:
        """
        Enqueue a function for async execution.

        This method:
        1. Creates a job in your JobManager
        2. Wraps the function in an async wrapper
        3. Schedules it for execution with asyncio.create_task
        4. Returns an adapted job that looks like an RQ job

        Args:
            func: Function to execute
            args: Positional arguments for the function
            kwargs: Keyword arguments for the function
            queue: Queue name (stored in metadata)
            timeout: Execution timeout in seconds
            result_ttl: How long to keep results (not used in asyncio version)
            job_id: Optional job ID (generated if not provided)
            **extra_kwargs: Additional parameters

        Returns:
            AdaptedJob: Wrapper around your Job that looks like an RQ job
        """
        args = args or ()
        kwargs = kwargs or {}
        job_id = job_id or str(uuid.uuid4())

        # Create async wrapper for the function
        async def async_execution_wrapper():
            """Wrapper to execute the function and handle sync/async."""
            if asyncio.iscoroutinefunction(func):
                return await func(*args, **kwargs)
            else:
                # Run sync function in executor to avoid blocking
                return await self._loop.run_in_executor(
                    None,
                    lambda: func(*args, **kwargs)
                )

        # Create job in your JobManager
        job = self.create_job(
            job_id=job_id,
            obj_id=func.__name__,
            query={
                'function': func.__name__,
                'args': str(args),
                'kwargs': str(kwargs)
            },
            execution_mode=queue  # Store queue as execution_mode
        )

        # Add timeout and TTL to metadata
        if job.metadata is None:
            job.metadata = {}
        job.metadata['timeout'] = timeout
        job.metadata['result_ttl'] = result_ttl
        job.metadata['queue'] = queue

        # Schedule async execution
        # Note: We're not awaiting, just scheduling
        asyncio.create_task(
            self.execute_job(job_id, async_execution_wrapper)
        )

        return job

    def fetch_job(self, job_id: str) -> Optional[Job]:
        """
        Fetch a job by ID.

        Args:
            job_id: The job identifier

        Returns:
            AdaptedJob if found, None otherwise
        """
        return self.get_job(job_id)
