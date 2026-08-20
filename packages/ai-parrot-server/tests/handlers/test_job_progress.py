"""Durable progress reporting on ``JobManager``.

``_persist`` is called on status transitions only, so a handler that mutates
``job.metadata`` in place updates the in-memory object and nothing else. For
a long job whose whole reason to publish progress is that it takes minutes,
that meant a poll served by another worker — or served after the in-memory
entry was evicted — reported the job's state from whenever it last changed
status.

These tests pin the public API that fixes it, using an injected fake store
rather than a real Redis (the same approach ``test_render_jobs.py`` takes,
and for the same reason: no reachable Redis in this environment).
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

import pytest

from parrot.handlers.jobs import JobManager
from parrot.handlers.jobs.models import Job


class _FakeStore:
    """Records every save, so "was this persisted?" is directly observable."""

    def __init__(self) -> None:
        self.saved: List[Dict[str, Any]] = []
        self.jobs: Dict[str, Job] = {}

    async def save(self, job: Job) -> None:
        # Snapshot the metadata: the manager hands us the live Job object, so
        # keeping a reference would make every record look like the last one.
        self.saved.append({"job_id": job.job_id, "metadata": dict(job.metadata or {})})
        self.jobs[job.job_id] = job

    async def get(self, job_id: str) -> Optional[Job]:
        return self.jobs.get(job_id)

    async def delete(self, job_id: str) -> bool:
        return self.jobs.pop(job_id, None) is not None


@pytest.fixture
def manager() -> JobManager:
    mgr = JobManager()
    mgr._store = _FakeStore()
    return mgr


def _store(manager: JobManager) -> _FakeStore:
    return manager._store


async def test_update_metadata_persists_the_change(manager):
    job = manager.create_job(job_id="j1", obj_id="flow_authoring", query="q")
    _store(manager).saved.clear()

    await manager.update_metadata(job.job_id, stage="nodes")

    assert job.metadata["stage"] == "nodes"
    assert _store(manager).saved, "the change must reach the store"
    assert _store(manager).saved[-1]["metadata"]["stage"] == "nodes"


async def test_update_metadata_merges_rather_than_replaces(manager):
    job = manager.create_job(job_id="j1", obj_id="x", query="q")
    await manager.update_metadata(job.job_id, first=1)
    await manager.update_metadata(job.job_id, second=2)

    assert job.metadata["first"] == 1
    assert job.metadata["second"] == 2


async def test_update_metadata_on_an_unknown_job_is_not_fatal(manager):
    """A late progress callback must not take down a job that already ended."""
    assert await manager.update_metadata("nope", stage="nodes") is None


async def test_report_progress_dumps_a_pydantic_payload(manager):
    """The job layer should not need to know the progress model's shape."""
    from parrot.bots.flows.authoring import AuthoringProgress, AuthoringStage

    job = manager.create_job(job_id="j1", obj_id="flow_authoring", query="q")
    await manager.report_progress(
        job.job_id,
        AuthoringProgress(
            stage=AuthoringStage.NODES,
            nodes_total=7,
            nodes_done=4,
            message="Authoring",
        ),
    )

    stored = _store(manager).saved[-1]["metadata"]["progress"]
    # Plain JSON, not a model instance — it round-trips through the store.
    assert stored == {
        "stage": "nodes",
        "nodes_total": 7,
        "nodes_done": 4,
        "message": "Authoring",
    }


async def test_report_progress_accepts_a_plain_payload(manager):
    job = manager.create_job(job_id="j1", obj_id="x", query="q")
    await manager.report_progress(job.job_id, {"stage": "custom"})
    assert job.metadata["progress"] == {"stage": "custom"}


async def test_each_progress_tick_is_persisted_separately(manager):
    """The counter is only useful if intermediate values actually land."""
    job = manager.create_job(job_id="j1", obj_id="x", query="q")
    _store(manager).saved.clear()

    for done in range(1, 4):
        await manager.report_progress(job.job_id, {"nodes_done": done})

    persisted = [rec["metadata"]["progress"]["nodes_done"] for rec in _store(manager).saved]
    assert persisted == [1, 2, 3]


async def test_a_failing_store_does_not_break_progress_reporting(manager):
    """Progress is telemetry; losing it must not fail the job."""

    class _BrokenStore(_FakeStore):
        async def save(self, job: Job) -> None:
            raise RuntimeError("redis is down")

    job = manager.create_job(job_id="j1", obj_id="x", query="q")
    manager._store = _BrokenStore()

    updated = await manager.report_progress(job.job_id, {"nodes_done": 1})

    assert updated is not None
    assert job.metadata["progress"] == {"nodes_done": 1}


async def test_progress_survives_losing_the_in_memory_job(manager):
    """The case the fix exists for: another worker, or a restart."""
    job = manager.create_job(job_id="j1", obj_id="x", query="q")
    await manager.report_progress(job.job_id, {"nodes_done": 4, "nodes_total": 7})

    # Simulate a poll that finds nothing in memory and falls back to the store.
    del manager.jobs[job.job_id]
    recovered = await manager.get_job_async(job.job_id)

    assert recovered is not None
    assert recovered.metadata["progress"]["nodes_done"] == 4
