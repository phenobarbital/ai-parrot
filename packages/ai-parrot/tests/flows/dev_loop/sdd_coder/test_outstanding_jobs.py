"""FEAT-594: outstanding MCP jobs are the still-running ones (issue:93abecaf1152, issue:00e1ae81e08d).

`SddCoderEngine._job_worktrees` is never pruned (``wait()`` re-journals from
it), so `end_execution`/`status()` must derive "outstanding" from each job's
live `JobTable` state rather than from the map's membership.
"""

from __future__ import annotations

import asyncio
import json
import subprocess
from pathlib import Path
from typing import List
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from parrot.flows.dev_loop.sdd_coder.engine import CoderFailure, SddCoderEngine
from parrot.flows.dev_loop.sdd_coder.models import RosterConfig, RosterSeat, TaskResult


def _init_git_worktree(worktree_path: Path) -> None:
    """Git init + one empty commit so `begin_execution` can resolve the branch."""
    for args in (
        ["git", "init", "-b", "dev"],
        ["git", "config", "user.email", "test@example.com"],
        ["git", "config", "user.name", "Test"],
        ["git", "commit", "--allow-empty", "-m", "initial commit"],
    ):
        subprocess.run(args, cwd=worktree_path, check=True, capture_output=True)


def _engine(tmp_path: Path) -> SddCoderEngine:
    """An engine with a single native seat and a no-op probe (never dispatches)."""
    roster = RosterConfig(
        seats=[RosterSeat(label="native", kind="native", model="haiku")],
        smoke_timeout_s=5.0,
        wait_timeout_max_s=60.0,
    )
    probe = AsyncMock()
    probe.probe = AsyncMock(return_value=[])
    return SddCoderEngine(roster=roster, probe=probe, worktree_base_path=str(tmp_path))


def _register_job(engine: SddCoderEngine, worktree: str, execution_id: str, gate: asyncio.Event) -> str:
    """Register a JobTable job blocked on *gate*, bookkept exactly like `run_chunk` does."""

    async def runner() -> List[TaskResult]:
        await gate.wait()
        return []

    job = engine._jobs.create("FEAT-1", ["TASK-1"], runner, execution_id=execution_id)  # noqa: SLF001
    engine._job_worktrees[job.job_id] = worktree  # noqa: SLF001
    return job.job_id


async def _begin(engine: SddCoderEngine, tmp_path: Path) -> tuple[str, str]:
    worktree = tmp_path / "wt"
    worktree.mkdir()
    await asyncio.to_thread(_init_git_worktree, worktree)
    index_dir = worktree / "sdd" / "tasks" / "index"
    index_dir.mkdir(parents=True)
    (index_dir / "test-feature.json").write_text(
        json.dumps(
            {
                "feature": "test-feature",
                "feature_id": "FEAT-1",
                "spec": "sdd/specs/test.spec.md",
                "base_branch": "dev",
                "tasks": [],
            }
        )
    )
    execution_id = str(uuid4())
    await engine.begin_execution("FEAT-1", str(worktree), execution_id)
    return execution_id, engine._executions[execution_id].worktree_path  # noqa: SLF001


@pytest.mark.asyncio
async def test_finished_jobs_are_not_outstanding(tmp_path: Path) -> None:
    """A running job is outstanding; once it reaches `done` it no longer is."""
    engine = _engine(tmp_path)
    execution_id, worktree = await _begin(engine, tmp_path)
    gate = asyncio.Event()
    job_id = _register_job(engine, worktree, execution_id, gate)

    assert engine._outstanding_job_ids(execution_id, worktree) == [job_id]  # noqa: SLF001

    gate.set()
    done = await engine._jobs.wait(job_id, 5)  # noqa: SLF001
    assert done.state == "done"
    assert engine._outstanding_job_ids(execution_id, worktree) == []  # noqa: SLF001
    # The bookkeeping entry survives (wait() still re-journals from it).
    assert job_id in engine._job_worktrees  # noqa: SLF001


@pytest.mark.asyncio
async def test_outstanding_scoped_to_execution(tmp_path: Path) -> None:
    """Running jobs of another execution, or legacy jobs of another worktree, are not counted."""
    engine = _engine(tmp_path)
    execution_id, worktree = await _begin(engine, tmp_path)
    gate = asyncio.Event()
    other_exec_job = _register_job(engine, worktree, str(uuid4()), gate)
    legacy_same_wt = _register_job(engine, worktree, "", gate)
    legacy_other_wt = _register_job(engine, str(tmp_path / "elsewhere"), "", gate)
    try:
        outstanding = engine._outstanding_job_ids(execution_id, worktree)  # noqa: SLF001
        assert outstanding == [legacy_same_wt]
        assert other_exec_job not in outstanding
        assert legacy_other_wt not in outstanding
    finally:
        gate.set()
        for job_id in (other_exec_job, legacy_same_wt, legacy_other_wt):
            await engine._jobs.wait(job_id, 5)  # noqa: SLF001


@pytest.mark.asyncio
async def test_end_execution_busy_while_job_running(tmp_path: Path) -> None:
    """`end_execution` refuses with execution_busy while a job runs, then closes cleanly (AC1, AC2)."""
    engine = _engine(tmp_path)
    execution_id, worktree = await _begin(engine, tmp_path)
    gate = asyncio.Event()
    job_id = _register_job(engine, worktree, execution_id, gate)

    with pytest.raises(CoderFailure) as excinfo:
        await engine.end_execution(execution_id)
    assert excinfo.value.code == "execution_busy"

    gate.set()
    await engine._jobs.wait(job_id, 5)  # noqa: SLF001
    view = await engine.end_execution(execution_id)
    assert view.status == "closed"
    snapshot = await engine._read_execution_snapshot(worktree, execution_id)  # noqa: SLF001
    assert snapshot is not None
    assert snapshot.outstanding_job_ids == []


# --- FEAT-599 (issue:c1e28856ab0c, issue:5944887877e1, issue:971e11917b19) -----------------


def _reserve_native(engine: SddCoderEngine, execution_id: str, task_id: str) -> None:
    """Bookkeep a native reservation exactly like `prepare_native` does, for a task with no recorded attempt."""
    engine._native_reservations[(execution_id, task_id)] = "uid-" + task_id  # noqa: SLF001
    engine._manager_execution[f"{task_id}.a1"] = execution_id  # noqa: SLF001


@pytest.mark.asyncio
async def test_end_execution_reclose_with_native_reservation_does_not_raise(tmp_path: Path) -> None:
    """Idempotent re-close reaches the enrichment loop; a native task without an attempt maps to `.a1` (AC1).

    issue:c1e28856ab0c: the loop used to evaluate ``AttemptRecord(attempt=1)`` eagerly as a
    ``dict.get`` default and raise ``ValidationError`` for every native task.
    """
    engine = _engine(tmp_path)
    execution_id, worktree = await _begin(engine, tmp_path)
    pool = engine._executions[execution_id]  # noqa: SLF001
    await pool.close()  # skip the busy gate: the pool is already closed, the loop still runs
    _reserve_native(engine, execution_id, "TASK-1")
    assert "TASK-1" not in engine._latest_attempt  # noqa: SLF001

    view = await engine.end_execution(execution_id)

    assert view.status == "closed"
    snapshot = await engine._read_execution_snapshot(worktree, execution_id)  # noqa: SLF001
    assert snapshot is not None
    assert snapshot.native_reservations == {"TASK-1": "TASK-1.a1"}


@pytest.mark.asyncio
async def test_status_persistence_retry_with_native_reservation(tmp_path: Path) -> None:
    """The degraded-persistence retry in `status()` never constructs an AttemptRecord (AC1)."""
    engine = _engine(tmp_path)
    execution_id, worktree = await _begin(engine, tmp_path)
    pool = engine._executions[execution_id]  # noqa: SLF001
    pool._persistence_degraded = True  # noqa: SLF001 -- force the retry path
    _reserve_native(engine, execution_id, "TASK-1")
    gate = asyncio.Event()
    job_id = _register_job(engine, worktree, execution_id, gate)
    try:
        job = await engine.status(job_id)
    finally:
        gate.set()
        await engine._jobs.wait(job_id, 5)  # noqa: SLF001

    assert job.state == "running"
    assert pool.view().persistence_degraded is False
    snapshot = await engine._read_execution_snapshot(worktree, execution_id)  # noqa: SLF001
    assert snapshot is not None
    assert snapshot.native_reservations == {"TASK-1": "TASK-1.a1"}
    assert snapshot.outstanding_job_ids == [job_id]


@pytest.mark.asyncio
async def test_settlement_artifact_after_done_job_has_no_outstanding_ids(tmp_path: Path) -> None:
    """The published settlement of an execution whose `run_chunk` job reached `done` lists no outstanding jobs (AC5).

    issue:5944887877e1 / issue:971e11917b19 reported `prepare_review_checkpoint` refusing every
    execution that ever dispatched a job because the settlement artifact still carried the job id.
    FEAT-594 fixed the producer; this pins the artifact contract the checkpoint reads.
    """
    from parrot.flows.dev_loop.sdd_coder.checkpoint import _find_settlement_snapshot

    engine = _engine(tmp_path)
    assert engine._evidence_store is not None  # noqa: SLF001 -- bound by the hermetic conftest root
    execution_id, worktree = await _begin(engine, tmp_path)
    gate = asyncio.Event()
    job_id = _register_job(engine, worktree, execution_id, gate)
    gate.set()
    assert (await engine._jobs.wait(job_id, 5)).state == "done"  # noqa: SLF001

    await engine.end_execution(execution_id)

    settlement = await _find_settlement_snapshot(engine._evidence_store, execution_id)  # noqa: SLF001
    assert settlement is not None
    assert settlement.status == "closed"
    assert settlement.outstanding_job_ids == []
    assert job_id in engine._job_worktrees  # noqa: SLF001 -- bookkeeping kept for wait()
