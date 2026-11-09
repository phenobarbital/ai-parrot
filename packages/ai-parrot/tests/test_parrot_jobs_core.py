"""Regression coverage for core job primitives and server compatibility paths."""

import asyncio

import pytest

from parrot.jobs import Job, JobManager, JobStatus, RedisJobStore


@pytest.mark.asyncio
async def test_core_and_server_paths_are_the_same_objects() -> None:
    """Verify core imports and legacy server imports resolve to the same classes."""
    from parrot.handlers.jobs import JobManager as ServerJobManager
    from parrot.handlers.jobs.job import JobManager as ServerJobModuleManager
    from parrot.handlers.jobs.models import Job as ServerJob
    from parrot.handlers.jobs.redis_store import RedisJobStore as ServerRedisJobStore

    assert JobManager is ServerJobManager
    assert JobManager is ServerJobModuleManager
    assert Job is ServerJob
    assert RedisJobStore is ServerRedisJobStore


@pytest.mark.asyncio
async def test_core_job_behavior_serialization_enqueue_fetch_and_progress() -> None:
    """Verify relocation preserves job serialization and manager compatibility APIs."""
    manager = JobManager()
    job = manager.create_job("job-1", "agent-1", {"prompt": "hello"}, user_id="user-1")

    assert job.id == "job-1"
    assert job.get_status() == JobStatus.PENDING.value
    assert job.is_queued
    assert job.to_dict()["query"] == {"prompt": "hello"}

    updated = await manager.report_progress(job.job_id, {"completed": 1, "total": 2})
    assert updated is job
    assert job.meta == {"progress": {"completed": 1, "total": 2}}

    async def work() -> str:
        return "done"

    enqueued = manager.enqueue(work, job_id="job-2", queue="core")
    for _ in range(10):
        if enqueued.is_finished:
            break
        await asyncio.sleep(0)

    fetched = manager.fetch_job("job-2")
    assert fetched is enqueued
    assert fetched is not None
    assert fetched.status is JobStatus.COMPLETED
    assert fetched.result == "done"
    assert fetched.meta["queue"] == "core"
