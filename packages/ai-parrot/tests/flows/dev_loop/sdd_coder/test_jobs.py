import asyncio

import pytest

from parrot.flows.dev_loop.sdd_coder.jobs import JobTable
from parrot.flows.dev_loop.sdd_coder.models import TaskResult

EXEC_A = "33333333-3333-4333-8333-333333333333"
EXEC_B = "44444444-4444-4444-8444-444444444444"


async def test_job_wait_returns_snapshot_on_timeout():
    gate = asyncio.Event()

    async def runner():
        await gate.wait()
        return [TaskResult(task_id="TASK-1", outcome="merged")]

    table = JobTable()
    job = table.create("FEAT-549", ["TASK-1"], runner, execution_id=EXEC_A)
    snap = await table.wait(job.job_id, 0.01)
    assert snap.state == "running" and table.running_task_ids(EXEC_A) == {"TASK-1"}
    gate.set()
    done = await table.wait(job.job_id, 1)
    assert done.state == "done" and done.tasks[0].outcome == "merged" and table.running_task_ids(EXEC_A) == set()


async def test_job_error_state():
    async def runner():
        raise RuntimeError("boom")

    table = JobTable()
    job = table.create("F", ["TASK-2"], runner, execution_id=EXEC_A)
    done = await table.wait(job.job_id, 1)
    assert done.state == "error" and "boom" in done.error


def test_job_unknown_id():
    with pytest.raises(KeyError):
        JobTable().get("nope")


async def test_job_running_tasks_are_execution_scoped():
    """Two jobs with the same task id in different executions never collide (FEAT-559 AC-6/AC-11)."""
    gate_a = asyncio.Event()
    gate_b = asyncio.Event()

    async def runner_a():
        await gate_a.wait()
        return [TaskResult(task_id="TASK-1", outcome="merged")]

    async def runner_b():
        await gate_b.wait()
        return [TaskResult(task_id="TASK-1", outcome="merged")]

    table = JobTable()
    job_a = table.create("F", ["TASK-1"], runner_a, execution_id=EXEC_A)
    job_b = table.create("F", ["TASK-1"], runner_b, execution_id=EXEC_B)

    assert table.running_task_ids(EXEC_A) == {"TASK-1"}
    assert table.running_task_ids(EXEC_B) == {"TASK-1"}
    # Unscoped (shutdown/orphan-detection) view sees the union across executions.
    assert table.running_task_ids() == {"TASK-1"}

    gate_a.set()
    await table.wait(job_a.job_id, 1)
    # A finishing must not affect B's identical-task-id, different-execution job.
    assert table.running_task_ids(EXEC_A) == set()
    assert table.running_task_ids(EXEC_B) == {"TASK-1"}

    gate_b.set()
    await table.wait(job_b.job_id, 1)
    assert table.running_task_ids(EXEC_B) == set()
    assert table.running_task_ids() == set()
