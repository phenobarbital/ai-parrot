"""Local-first, bounded execution of platform-neutral queued commands."""

import asyncio
import logging
import shlex
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, List, Literal, Optional

from parrot.jobs import JobManager, JobStatus, RedisJobStore

from parrot.integrations.parser import parse_response
from parrot.integrations.utils import parse_kwargs

from .context import CommandJobContext, current_command_job
from .models import (
    CommandUsageError,
    Deliver,
    JobNotice,
    JobView,
    PreparedCommand,
    QueuedCommand,
    Requester,
    SubmitOutcome,
)

_SHUTDOWN_REASON = "interrupted — the bot is shutting down; run the command again"
_REQUESTER_CANCEL_REASON = "cancelled by the requester"
_TERMINAL_STATUSES = {JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED}


class QueuedCommandService:
    """Own one wrapper's jobs, concurrency groups and delivery callbacks."""

    def __init__(
        self,
        *,
        owner: str,
        job_manager: Optional[JobManager] = None,
        use_redis: bool = True,
        key_prefix: str = "parrot:chat_jobs",
        job_ttl: int = 86400,
        expiry_grace: float = 300.0,
        prepare_timeout: float = 10.0,
        admission_timeout: float = 10.0,
        notify_timeout: float = 30.0,
    ) -> None:
        """Configure local admission and finite prepare, execution and delivery budgets."""

        self.logger = logging.getLogger(__name__)
        self.owner = owner
        self.manager = job_manager
        self._use_redis = use_redis
        self._key_prefix = key_prefix
        self._job_ttl = job_ttl
        self._expiry_grace = expiry_grace
        self._prepare_timeout = prepare_timeout
        self._admission_timeout = admission_timeout
        self._notify_timeout = notify_timeout
        self._started = False
        self._stopping = False
        self._lifecycle_lock = asyncio.Lock()
        self._admission_lock = asyncio.Lock()
        self._reservations: dict[str, str] = {}
        self._groups: dict[str, asyncio.Semaphore] = {}
        self._schedule_tasks: set[asyncio.Task[Any]] = set()
        self._schedule_by_job: dict[str, asyncio.Task[Any]] = {}
        self._live_job_ids: set[str] = set()

    async def start(self) -> None:
        """Start idempotently without waiting for Redis connectivity."""

        async with self._lifecycle_lock:
            if self._started:
                return
            if self.manager is None:
                store = RedisJobStore(key_prefix=self._key_prefix, job_ttl=self._job_ttl) if self._use_redis else None
                self.manager = JobManager(id=f"chat:{self.owner}", job_ttl=self._job_ttl, store=store)
            await self.manager.start()
            self._started = True
            self._stopping = False

    async def stop(self) -> None:
        """Cancel live jobs with interruption reasons and drain bounded delivery."""

        async with self._lifecycle_lock:
            if not self._started or self._stopping:
                return
            self._stopping = True

        async with self._admission_lock:
            pass

        schedule_tasks = list(self._schedule_tasks)
        if schedule_tasks:
            await asyncio.gather(*schedule_tasks, return_exceptions=True)

        if self.manager is not None:
            for job_id, task in list(self.manager.tasks.items()):
                if not task.done():
                    job = self.manager.jobs.get(job_id)
                    if job is not None:
                        job.error = _SHUTDOWN_REASON
            await self.manager.stop()

        async with self._lifecycle_lock:
            self._started = False
            self._stopping = False

    async def submit(
        self,
        command: QueuedCommand,
        raw_args: str,
        requester: Requester,
        deliver: Deliver,
    ) -> SubmitOutcome:
        """Prepare, reserve and schedule locally under one admission deadline."""

        async with self._admission_lock:
            if self._stopping:
                return SubmitOutcome(status="rejected", message="The command service is shutting down.")
            try:
                return await asyncio.wait_for(
                    self._submit(command, raw_args, requester, deliver),
                    timeout=self._admission_timeout,
                )
            except asyncio.TimeoutError:
                return SubmitOutcome(status="rejected", message="Command admission timed out; please try again.")

    async def get(self, job_id: str, requester: Requester) -> Optional[JobView]:
        """Read a fresh requester-scoped view with conservative foreign expiry."""

        if self.manager is None:
            return None
        job = await self.manager.get_job_async(job_id)
        if job is None or job.user_id != requester.actor:
            return None
        return self._to_view(job)

    async def list_for(self, requester: Requester, limit: int = 10) -> List[JobView]:
        """Read the requester's newest jobs using the user index."""

        if self.manager is None:
            return []
        jobs = await self.manager.list_jobs_async(user_id=requester.actor, limit=limit)
        return [self._to_view(job) for job in jobs if job.user_id == requester.actor]

    async def cancel(
        self,
        job_id: str,
        requester: Requester,
    ) -> Literal["cancelling", "not_found", "finished", "not_on_this_worker"]:
        """Cancel only a live owned task belonging to the requester."""

        if self.manager is None:
            return "not_found"
        job = await self.manager.get_job_async(job_id)
        if job is None or job.user_id != requester.actor:
            return "not_found"
        if job.status in _TERMINAL_STATUSES:
            return "finished"
        if job_id not in self.manager.jobs or job_id not in self._live_job_ids:
            return "not_on_this_worker"

        schedule_task = self._schedule_by_job.get(job_id)
        if schedule_task is not None:
            await asyncio.gather(schedule_task, return_exceptions=True)
        if await self.manager.cancel_job(job_id, _REQUESTER_CANCEL_REASON):
            return "cancelling"
        if job.status in _TERMINAL_STATUSES:
            return "finished"
        return "not_on_this_worker"

    async def _submit(
        self,
        command: QueuedCommand,
        raw_args: str,
        requester: Requester,
        deliver: Deliver,
    ) -> SubmitOutcome:
        """Run preparation, then perform the no-await admission section."""

        await self.start()
        if self._stopping:
            return SubmitOutcome(status="rejected", message="The command service is shutting down.")

        parsed_args = self._parse_arguments(command, raw_args)
        try:
            prepared = await self._prepare(command, parsed_args)
        except CommandUsageError as exc:
            return SubmitOutcome(status="rejected", message=str(exc))
        except asyncio.TimeoutError:
            return SubmitOutcome(status="rejected", message="Command preparation timed out; please try again.")

        label = prepared.label or command.spec.description or command.spec.command
        dedup_key = prepared.dedup_key
        if dedup_key is not None:
            duplicate_id = self._reservations.get(dedup_key)
            if duplicate_id is not None:
                return SubmitOutcome(status="duplicate", job_id=duplicate_id, label=label, message="")

        manager = self.manager
        if manager is None:
            return SubmitOutcome(status="rejected", message="The command service is unavailable.")

        job_id = self._new_job_id(manager)
        admission_time = datetime.now(timezone.utc)
        admission_monotonic = asyncio.get_running_loop().time()
        expires_at = admission_time + timedelta(
            seconds=command.spec.max_queue_wait
            + command.spec.max_runtime
            + self._notify_timeout
            + self._expiry_grace
        )
        metadata = {
            "command": command.spec.command,
            "label": label,
            "dedup_key": dedup_key,
            "max_runtime": command.spec.max_runtime,
            "max_queue_wait": command.spec.max_queue_wait,
            "expires_at": expires_at.isoformat(),
            "execution_started_at": None,
            "platform": requester.platform,
            "chat_id": requester.chat_id,
            "thread_id": requester.thread_id,
            "phase": "queued",
            "progress": None,
        }

        if dedup_key is not None:
            self._reservations[dedup_key] = job_id
        try:
            manager.create_job(
                job_id=job_id,
                obj_id=f"{self.owner}:{command.spec.command}",
                query={"command": command.spec.command, "args": raw_args[:500]},
                user_id=requester.actor,
                session_id=requester.chat_id,
                execution_mode="queued_command",
                metadata=metadata,
            )
            self._live_job_ids.add(job_id)
            schedule_task = asyncio.create_task(
                manager.execute_job(
                    job_id,
                    lambda: self._run_command(
                        job_id=job_id,
                        command=command,
                        prepared=prepared,
                        requester=requester,
                        deliver=deliver,
                        admission_monotonic=admission_monotonic,
                    ),
                )
            )
            self._track_schedule(job_id, schedule_task)
        except BaseException:
            self._live_job_ids.discard(job_id)
            if dedup_key is not None and self._reservations.get(dedup_key) == job_id:
                self._reservations.pop(dedup_key, None)
            manager.delete_job(job_id)
            raise

        return SubmitOutcome(status="accepted", job_id=job_id, label=label, message="")

    async def _prepare(self, command: QueuedCommand, parsed_args: Any) -> PreparedCommand:
        """Run an optional preparation hook within its independent budget."""

        if command.prepare is None:
            if command.spec.parse_mode == "keyword":
                return PreparedCommand(kwargs=parsed_args)
            if command.spec.parse_mode == "positional":
                return PreparedCommand(args=tuple(parsed_args))
            return PreparedCommand(args=(parsed_args,)) if parsed_args else PreparedCommand()

        result = command.prepare(parsed_args)
        if asyncio.iscoroutine(result):
            result = await asyncio.wait_for(result, timeout=self._prepare_timeout)
        if not isinstance(result, PreparedCommand):
            result = PreparedCommand.model_validate(result)
        return result

    @staticmethod
    def _parse_arguments(command: QueuedCommand, raw_args: str) -> Any:
        """Parse raw input according to the command's declared mode."""

        if command.spec.parse_mode == "keyword":
            return parse_kwargs(raw_args)
        if command.spec.parse_mode == "positional":
            return shlex.split(raw_args)
        return raw_args

    async def _run_command(
        self,
        *,
        job_id: str,
        command: QueuedCommand,
        prepared: PreparedCommand,
        requester: Requester,
        deliver: Deliver,
        admission_monotonic: float,
    ) -> dict[str, str]:
        """Enforce queue/runtime budgets and return the JSON-safe stored result."""

        semaphore = self._semaphore_for(command)
        acquired = False
        execution_started = admission_monotonic
        queue_deadline = admission_monotonic + command.spec.max_queue_wait
        dedup_key = prepared.dedup_key
        try:
            queue_remaining = queue_deadline - asyncio.get_running_loop().time()
            if queue_remaining <= 0:
                raise _QueueDeadlineExceeded
            try:
                await asyncio.wait_for(semaphore.acquire(), timeout=queue_remaining)
            except asyncio.TimeoutError as exc:
                raise _QueueDeadlineExceeded from exc
            acquired = True

            execution_started = asyncio.get_running_loop().time()
            execution_deadline = execution_started + command.spec.max_runtime
            try:
                await self._within_execution_budget(
                    execution_deadline,
                    self.manager.update_metadata(
                        job_id,
                        phase="running",
                        execution_started_at=datetime.now(timezone.utc).isoformat(),
                    ),
                )
                context = CommandJobContext(
                    job_id=job_id,
                    command=command.spec.command,
                    requester=requester,
                    service=self,
                )
                token = current_command_job.set(context)
                try:
                    result = await self._within_execution_budget(
                        execution_deadline,
                        command.method(*prepared.args, **prepared.kwargs),
                    )
                finally:
                    current_command_job.reset(token)
            except asyncio.TimeoutError as exc:
                error = f"timed out after {self._seconds_label(command.spec.max_runtime)}"
                await self._deliver(
                    deliver,
                    JobNotice(
                        job_id=job_id,
                        command=command.spec.command,
                        label=prepared.label or command.spec.description or command.spec.command,
                        status="timed_out",
                        error=error,
                        elapsed_s=asyncio.get_running_loop().time() - execution_started,
                    ),
                )
                raise _ExecutionDeadlineExceeded(error) from exc

            text = parse_response(result).text[:4000]
            await self._deliver(
                deliver,
                JobNotice(
                    job_id=job_id,
                    command=command.spec.command,
                    label=prepared.label or command.spec.description or command.spec.command,
                    status="completed",
                    result=result,
                    elapsed_s=asyncio.get_running_loop().time() - execution_started,
                ),
            )
            return {"text": text}
        except _QueueDeadlineExceeded as exc:
            error = f"timed out waiting for a slot after {self._seconds_label(command.spec.max_queue_wait)}"
            await self._deliver(
                deliver,
                JobNotice(
                    job_id=job_id,
                    command=command.spec.command,
                    label=prepared.label or command.spec.description or command.spec.command,
                    status="timed_out",
                    error=error,
                    elapsed_s=asyncio.get_running_loop().time() - admission_monotonic,
                ),
            )
            raise TimeoutError(error) from exc
        except _ExecutionDeadlineExceeded as exc:
            raise TimeoutError(str(exc)) from exc
        except asyncio.CancelledError:
            job = self.manager.jobs.get(job_id) if self.manager is not None else None
            error = job.error if job is not None and job.error else "Job was cancelled"
            await self._deliver(
                deliver,
                JobNotice(
                    job_id=job_id,
                    command=command.spec.command,
                    label=prepared.label or command.spec.description or command.spec.command,
                    status="cancelled",
                    error=error,
                    elapsed_s=asyncio.get_running_loop().time() - execution_started,
                ),
            )
            raise
        except Exception as exc:
            await self._deliver(
                deliver,
                JobNotice(
                    job_id=job_id,
                    command=command.spec.command,
                    label=prepared.label or command.spec.description or command.spec.command,
                    status="failed",
                    error=str(exc)[:300],
                    elapsed_s=asyncio.get_running_loop().time() - execution_started,
                ),
            )
            raise
        finally:
            if acquired:
                semaphore.release()
            self._live_job_ids.discard(job_id)
            if dedup_key is not None and self._reservations.get(dedup_key) == job_id:
                self._reservations.pop(dedup_key, None)

    async def _within_execution_budget(self, deadline: float, awaitable: Any) -> Any:
        """Await one execution step without extending the monotonic deadline."""

        remaining = deadline - asyncio.get_running_loop().time()
        if remaining <= 0:
            if asyncio.iscoroutine(awaitable):
                awaitable.close()
            raise asyncio.TimeoutError
        return await asyncio.wait_for(awaitable, timeout=remaining)

    async def _deliver(self, deliver: Deliver, notice: JobNotice) -> None:
        """Bound and isolate a platform delivery callback."""

        try:
            await asyncio.wait_for(deliver(notice), timeout=self._notify_timeout)
        except asyncio.CancelledError:
            task = asyncio.current_task()
            if task is not None and task.cancelling():
                raise
            self.logger.warning("Delivery was cancelled for queued job %s", notice.job_id)
        except Exception:  # pylint: disable=broad-except
            self.logger.warning("Delivery failed for queued job %s", notice.job_id, exc_info=True)

    def _semaphore_for(self, command: QueuedCommand) -> asyncio.Semaphore:
        """Return the command/group semaphore, preserving the first cap."""

        key = command.spec.concurrency_group or command.spec.command
        semaphore = self._groups.get(key)
        if semaphore is None:
            semaphore = asyncio.Semaphore(command.spec.max_concurrent)
            self._groups[key] = semaphore
        return semaphore

    def _to_view(self, job: Any) -> JobView:
        """Map a job record to its bounded requester-facing representation."""

        metadata = job.metadata or {}
        if job.status == JobStatus.COMPLETED:
            status = "completed"
        elif job.status == JobStatus.FAILED:
            status = "failed"
        elif job.status == JobStatus.CANCELLED:
            status = "cancelled"
        else:
            status = "queued" if metadata.get("phase") == "queued" or job.status == JobStatus.PENDING else "running"
            if job.job_id not in self._live_job_ids and self._is_expired(metadata.get("expires_at")):
                status = "expired"

        summary: Optional[str] = None
        if isinstance(job.result, dict) and job.result.get("text") is not None:
            summary = str(job.result["text"])[:500]
        elif job.result is not None:
            summary = str(job.result)[:500]

        return JobView(
            job_id=job.job_id,
            command=str(metadata.get("command", "")),
            label=str(metadata.get("label", "")),
            status=status,
            progress=str(metadata["progress"]) if metadata.get("progress") is not None else None,
            created_at=job.created_at,
            started_at=self._execution_started_at(metadata),
            completed_at=job.completed_at,
            error=job.error,
            summary=summary,
        )

    @staticmethod
    def _execution_started_at(metadata: dict[str, Any]) -> Optional[datetime]:
        """Parse the post-semaphore execution timestamp."""

        value = metadata.get("execution_started_at")
        if isinstance(value, datetime):
            return value
        if isinstance(value, str) and value:
            try:
                return datetime.fromisoformat(value)
            except ValueError:
                return None
        return None

    @staticmethod
    def _is_expired(value: Any) -> bool:
        """Return whether a persisted immutable UTC deadline has elapsed."""

        if isinstance(value, datetime):
            expires_at = value
        elif isinstance(value, str) and value:
            try:
                expires_at = datetime.fromisoformat(value)
            except ValueError:
                return False
        else:
            return False
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        return datetime.now(timezone.utc) >= expires_at

    def _track_schedule(self, job_id: str, task: asyncio.Task[Any]) -> None:
        """Track the async JobManager scheduling call and log failures."""

        self._schedule_tasks.add(task)
        self._schedule_by_job[job_id] = task

        def _done(completed: asyncio.Task[Any]) -> None:
            self._schedule_tasks.discard(completed)
            self._schedule_by_job.pop(job_id, None)
            if completed.cancelled():
                self.logger.warning("Scheduling was cancelled for queued job %s", job_id)
                self._release_failed_schedule(job_id)
                return
            error = completed.exception()
            if error is not None:
                self.logger.error("Scheduling failed for queued job %s: %s", job_id, error, exc_info=error)
                self._release_failed_schedule(job_id)

        task.add_done_callback(_done)

    def _release_failed_schedule(self, job_id: str) -> None:
        """Release local admission state when JobManager scheduling fails."""

        self._live_job_ids.discard(job_id)
        if self.manager is None:
            return
        job = self.manager.jobs.get(job_id)
        dedup_key = job.metadata.get("dedup_key") if job is not None and job.metadata else None
        if dedup_key is not None and self._reservations.get(dedup_key) == job_id:
            self._reservations.pop(dedup_key, None)
        self.manager.delete_job(job_id)

    @staticmethod
    def _new_job_id(manager: JobManager) -> str:
        """Generate a locally collision-checked 12-hex identifier."""

        while True:
            job_id = uuid.uuid4().hex[:12]
            if job_id not in manager.jobs:
                return job_id

    @staticmethod
    def _seconds_label(value: float) -> str:
        """Render a stable seconds value for timeout errors."""

        return f"{value:g}s"


class _QueueDeadlineExceeded(Exception):
    """Signal that a command exhausted its pre-execution queue budget."""


class _ExecutionDeadlineExceeded(Exception):
    """Signal that a command exhausted its execution budget after notification."""
