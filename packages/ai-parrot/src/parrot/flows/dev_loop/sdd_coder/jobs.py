"""In-memory job registry for the sdd_coder MCP server (spec §3 M4; AC-12, AC-21)."""
from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime, timezone
from typing import Awaitable, Callable, Dict, List

from parrot.flows.dev_loop.sdd_coder.models import CoderJob, TaskResult


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class JobTable:
    """Registry of running/finished ``CoderJob`` snapshots for ONE server process."""

    def __init__(self) -> None:
        self.logger = logging.getLogger(__name__)
        self._jobs: Dict[str, CoderJob] = {}
        self._tasks: Dict[str, "asyncio.Task[List[TaskResult]]"] = {}

    def create(
        self, feature_id: str, task_ids: List[str], runner: Callable[[], Awaitable[List[TaskResult]]]
    ) -> CoderJob:
        """Register + schedule immediately (asyncio.create_task); return the initial snapshot."""
        job = CoderJob(
            job_id=f"job-{uuid.uuid4().hex[:12]}",
            feature_id=feature_id,
            chunk_task_ids=list(task_ids),
            state="running",
            started_at=_now(),
        )
        self._jobs[job.job_id] = job
        self._tasks[job.job_id] = asyncio.create_task(self._run(job.job_id, runner))
        return job.model_copy(deep=True)

    async def _run(self, job_id: str, runner: Callable[[], Awaitable[List[TaskResult]]]) -> List[TaskResult]:
        """Run `runner()`, updating the tracked snapshot with the outcome. Never raises out of this
        coroutine: an exception from `runner()` is captured into the job's `error` field so that
        `wait()`/`get()` always have a snapshot to return instead of an unhandled task exception."""
        job = self._jobs[job_id]
        tasks: List[TaskResult] = []
        try:
            tasks = await runner()
        except Exception as exc:  # noqa: BLE001 — captured into job state, never re-raised
            self.logger.exception("sdd_coder job %s failed", job_id)
            job.state = "error"
            job.error = str(exc)
        else:
            job.tasks = tasks
            job.state = "done"
        finally:
            job.ended_at = _now()
        return tasks

    def running_task_ids(self) -> set[str]:
        """Task ids owned by jobs still in state 'running' (engine uses it for task_already_running / orphan detection)."""
        return {t for j in self._jobs.values() if j.state == "running" for t in j.chunk_task_ids}

    def get(self, job_id: str) -> CoderJob:
        """Raises KeyError when unknown (toolkit maps it to job_not_found)."""
        return self._jobs[job_id].model_copy(deep=True)

    def snapshot(self, job_id: str) -> CoderJob:
        return self.get(job_id)

    async def wait(self, job_id: str, timeout_s: float) -> CoderJob:
        """Await completion up to timeout_s; ALWAYS returns a snapshot (state stays 'running' on timeout)."""
        task = self._tasks.get(job_id)
        if task is None:
            raise KeyError(job_id)
        try:
            await asyncio.wait_for(asyncio.shield(task), timeout=timeout_s)
        except asyncio.TimeoutError:
            pass
        return self.get(job_id)
