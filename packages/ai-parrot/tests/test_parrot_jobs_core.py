"""Regression coverage for core job primitives and server compatibility paths."""

import asyncio
from copy import deepcopy
from datetime import datetime, timezone
import uuid

import pytest

from parrot.jobs import Job, JobManager, JobStatus, RedisJobStore


class _MemoryStore:
    """Deterministic async store used to exercise manager ownership semantics."""

    def __init__(self) -> None:
        self.jobs: dict[str, Job] = {}
        self.saved: list[Job] = []

    async def connect(self) -> None:
        """Satisfy the store lifecycle contract."""

    async def close(self) -> None:
        """Satisfy the store lifecycle contract."""

    async def save(self, job: Job) -> None:
        """Store an immutable copy of a snapshot."""
        snapshot = deepcopy(job)
        self.saved.append(snapshot)
        self.jobs[job.job_id] = snapshot

    async def get(self, job_id: str) -> Job | None:
        """Return a detached stored job."""
        job = self.jobs.get(job_id)
        return deepcopy(job) if job else None

    async def delete(self, job_id: str) -> bool:
        """Delete one stored job."""
        return self.jobs.pop(job_id, None) is not None

    async def list_jobs(
        self,
        obj_id: str | None = None,
        status: JobStatus | None = None,
        limit: int = 100,
        user_id: str | None = None,
    ) -> list[Job]:
        """List detached stored jobs after all requested filters."""
        jobs = list(self.jobs.values())
        if obj_id:
            jobs = [job for job in jobs if job.obj_id == obj_id]
        if status:
            jobs = [job for job in jobs if job.status is status]
        if user_id:
            jobs = [job for job in jobs if job.user_id == user_id]
        return sorted((deepcopy(job) for job in jobs), key=lambda job: job.created_at, reverse=True)[:limit]


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


@pytest.mark.asyncio
async def test_cancel_job_keeps_record_with_reason() -> None:
    """Cancelling an owned running task keeps its record and supplied reason."""
    manager = JobManager()
    started = asyncio.Event()
    release = asyncio.Event()

    async def work() -> None:
        started.set()
        await release.wait()

    job = manager.create_job("cancelled", "agent", "query")
    await manager.execute_job(job.job_id, work)
    await started.wait()

    assert await manager.cancel_job(job.job_id, "requested")
    await asyncio.gather(manager.tasks.get(job.job_id), return_exceptions=True)
    assert manager.get_job(job.job_id) is job
    assert job.status is JobStatus.CANCELLED
    assert job.error == "requested"
    assert not await manager.cancel_job(job.job_id)
    assert not await manager.cancel_job("unknown")


@pytest.mark.asyncio
async def test_cancel_job_before_runner_and_finished_job_returns_false() -> None:
    """Cancellation only applies to owned live tasks, including pre-run tasks."""
    manager = JobManager()
    entered = asyncio.Event()

    async def work() -> None:
        entered.set()

    job = manager.create_job("pending", "agent", "query")
    await manager.execute_job(job.job_id, work)
    assert await manager.cancel_job(job.job_id)
    await asyncio.gather(manager.tasks.get(job.job_id), return_exceptions=True)
    assert not entered.is_set()
    assert job.status is JobStatus.CANCELLED

    finished = manager.create_job("finished", "agent", "query")
    finished.status = JobStatus.COMPLETED
    assert not await manager.cancel_job(finished.job_id)


@pytest.mark.asyncio
async def test_list_jobs_filters_by_user_id() -> None:
    """Memory listings apply the user filter before the requested limit."""
    manager = JobManager()
    first = manager.create_job("one", "agent", "query", user_id="alice")
    second = manager.create_job("two", "agent", "query", user_id="bob")
    first.created_at = datetime(2024, 1, 1, tzinfo=timezone.utc)
    second.created_at = datetime(2024, 1, 2, tzinfo=timezone.utc)

    assert [job.job_id for job in manager.list_jobs(user_id="alice", limit=1)] == ["one"]
    assert [job.job_id for job in manager.list_jobs(user_id="bob")] == ["two"]


@pytest.mark.asyncio
async def test_foreign_job_reads_refresh_without_ownership() -> None:
    """Foreign store reads are refreshed but never become locally cancellable."""
    store = _MemoryStore()
    owner = JobManager(store=store)
    reader = JobManager(store=store)
    job = owner.create_job("foreign", "agent", "query", metadata={"phase": "queued"})
    await owner._drain_persistence_tasks()
    assert store.saved[0].metadata == {"phase": "queued"}

    queued = await reader.get_job_async(job.job_id)
    assert queued is not None
    assert queued.metadata["phase"] == "queued"
    assert job.job_id not in reader.jobs

    await owner.update_metadata(job.job_id, phase="running")
    running = await reader.get_job_async(job.job_id)
    assert running is not None
    assert running.metadata["phase"] == "running"
    assert job.job_id not in reader.jobs
    assert not await reader.cancel_job(job.job_id)

    job.status = JobStatus.COMPLETED
    job.completed_at = datetime.now(timezone.utc)
    await owner._persist(deepcopy(job))
    completed = await reader.get_job_async(job.job_id)
    assert completed is not None
    assert completed.status is JobStatus.COMPLETED
    assert job.job_id not in reader.jobs


@pytest.mark.asyncio
async def test_persistence_is_bounded_ordered_and_drained() -> None:
    """Admission is non-blocking and the newest queued snapshot wins."""
    store = _MemoryStore()
    manager = JobManager(store=store, persistence_timeout=0.05)
    job = manager.create_job("ordered", "agent", "query", metadata={"phase": "queued"})
    job.status = JobStatus.COMPLETED
    job.completed_at = datetime.now(timezone.utc)
    manager._queue_persist(job)
    await asyncio.sleep(0)
    await manager._drain_persistence_tasks()
    assert store.jobs[job.job_id].status is JobStatus.COMPLETED

    class _StalledStore(_MemoryStore):
        async def save(self, job: Job) -> None:
            await asyncio.Event().wait()

    stalled = JobManager(store=_StalledStore(), persistence_timeout=0.01)
    stalled.create_job("stalled", "agent", "query")
    await asyncio.sleep(0.02)
    await stalled.stop()
    assert not stalled._persistence_tasks


@pytest.mark.asyncio
async def test_redis_user_index_lists_and_prunes() -> None:
    """A real Redis user index filters, orders and removes stale members."""
    pytest.importorskip("redis")
    prefix = f"parrot:test-jobs:{uuid.uuid4().hex}"
    store = RedisJobStore(redis_url="redis://localhost:6379/15", key_prefix=prefix)
    try:
        await store.connect()
        if not await store.ping():
            pytest.skip("localhost Redis is unavailable")
    except Exception:
        pytest.skip("localhost Redis is unavailable")

    try:
        older = Job("older", "agent", "query", user_id="alice")
        newer = Job("newer", "agent", "query", user_id="alice")
        newer.created_at = datetime(2025, 1, 1, tzinfo=timezone.utc)
        await store.save(older)
        await store.save(newer)
        await store._redis.zadd(store._user_index_key("alice"), {"stale": newer.created_at.timestamp() + 1})
        listed = await store.list_jobs(user_id="alice")
        assert [job.job_id for job in listed] == ["newer", "older"]
        assert not await store._redis.zscore(store._user_index_key("alice"), "stale")
    finally:
        if store._redis is not None:
            await store._redis.delete(store._index_key, store._user_index_key("alice"))
            await store._redis.delete(store._job_key("older"), store._job_key("newer"))
        await store.close()
