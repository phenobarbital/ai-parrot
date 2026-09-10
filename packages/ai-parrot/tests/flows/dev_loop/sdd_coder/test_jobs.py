import asyncio

import pytest

from parrot.flows.dev_loop.sdd_coder.jobs import JobTable
from parrot.flows.dev_loop.sdd_coder.models import TaskResult


async def test_job_wait_returns_snapshot_on_timeout():
    gate = asyncio.Event()

    async def runner():
        await gate.wait()
        return [TaskResult(task_id="TASK-1", outcome="merged")]

    table = JobTable()
    job = table.create("FEAT-549", ["TASK-1"], runner)
    snap = await table.wait(job.job_id, 0.01)
    assert snap.state == "running" and table.running_task_ids() == {"TASK-1"}
    gate.set()
    done = await table.wait(job.job_id, 1)
    assert done.state == "done" and done.tasks[0].outcome == "merged" and table.running_task_ids() == set()


async def test_job_error_state():
    async def runner():
        raise RuntimeError("boom")

    table = JobTable()
    job = table.create("F", ["TASK-2"], runner)
    done = await table.wait(job.job_id, 1)
    assert done.state == "error" and "boom" in done.error


def test_job_unknown_id():
    with pytest.raises(KeyError):
        JobTable().get("nope")
