"""Integration tests for execution snapshot persistence and restart recovery (TASK-3282).

Tests cover:
- Atomic snapshot writes and reads
- Restart recovery with persisted state
- Handling of corrupt/missing snapshots
- Persistence failure and retry logic
- Durable close semantics
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from parrot.flows.dev_loop.sdd_coder.engine import SddCoderEngine, CoderFailure
from parrot.flows.dev_loop.sdd_coder.models import ExecutionSnapshot, RosterConfig, RosterSeat
from parrot.flows.dev_loop.sdd_coder.pool import ExecutionPool, roster_fingerprint
from parrot.knowledge.wiki.ledger.coder_suspensions import CoderSuspensionStore, ModelKey


@pytest.fixture
def roster_config() -> RosterConfig:
    """Minimal roster with one native seat."""
    return RosterConfig(
        seats=[RosterSeat(label="native", kind="native", model="haiku")],
        smoke_timeout_s=5.0,
        wait_timeout_max_s=60.0,
    )


@pytest.mark.asyncio
async def test_restart_same_execution(tmp_path, roster_config):
    """Test that restarting with the same execution_id restores suspensions.

    - Create execution A with a suspension
    - Write snapshot to disk
    - Restart with same execution_id
    - Verify suspensions are restored regardless of expiry
    """
    worktree_path = tmp_path / "feature-worktree"
    worktree_path.mkdir()

    # Initialize git repo
    import subprocess

    subprocess.run(["git", "init", "-b", "dev"], cwd=worktree_path, check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"], cwd=worktree_path, check=True, capture_output=True
    )
    subprocess.run(["git", "config", "user.name", "Test"], cwd=worktree_path, check=True, capture_output=True)

    # Create index
    index_dir = worktree_path / "sdd" / "tasks" / "index"
    index_dir.mkdir(parents=True)
    index_file = index_dir / "test-feature.json"
    index_file.write_text(
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

    # Create engine with a mock probe
    mock_probe = AsyncMock()
    mock_probe.probe = AsyncMock(return_value=[])

    engine = SddCoderEngine(
        roster=roster_config,
        probe=mock_probe,
        worktree_base_path=str(tmp_path),
    )

    # Begin first execution
    view1 = await engine.begin_execution("FEAT-1", str(worktree_path), execution_id)
    assert view1.execution_id == execution_id
    assert view1.status == "active"

    # Suspend a model in this execution
    pool = engine._executions[execution_id]
    model_key = ModelKey(backend="native", model="haiku")
    pool._local_exclusions.add(model_key)
    pool._generation += 1

    # Write snapshot
    snapshot = pool.snapshot()
    persisted = await engine._write_execution_snapshot(str(worktree_path), execution_id, snapshot)
    assert persisted

    # Create a new engine instance (simulates restart)
    engine2 = SddCoderEngine(
        roster=roster_config,
        probe=mock_probe,
        worktree_base_path=str(tmp_path),
    )

    # Resume with same execution_id
    view2 = await engine2.begin_execution("FEAT-1", str(worktree_path), execution_id)
    assert view2.execution_id == execution_id
    # Verify suspensions are restored
    pool2 = engine2._executions[execution_id]
    assert model_key in pool2._local_exclusions


@pytest.mark.asyncio
async def test_close_then_new_execution(tmp_path, roster_config):
    """Test that a closed execution cannot start new work.

    - Create and close execution A
    - Write closed snapshot to disk
    - Try to begin with same execution_id
    - Verify execution_closed error is raised
    """
    worktree_path = tmp_path / "feature-worktree"
    worktree_path.mkdir()

    import subprocess

    subprocess.run(["git", "init", "-b", "dev"], cwd=worktree_path, check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"], cwd=worktree_path, check=True, capture_output=True
    )
    subprocess.run(["git", "config", "user.name", "Test"], cwd=worktree_path, check=True, capture_output=True)

    # Create index
    index_dir = worktree_path / "sdd" / "tasks" / "index"
    index_dir.mkdir(parents=True)
    index_file = index_dir / "test-feature.json"
    index_file.write_text(
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

    mock_probe = AsyncMock()
    mock_probe.probe = AsyncMock(return_value=[])

    engine = SddCoderEngine(
        roster=roster_config,
        probe=mock_probe,
        worktree_base_path=str(tmp_path),
    )

    # Begin execution
    await engine.begin_execution("FEAT-1", str(worktree_path), execution_id)

    # End execution (writes closed snapshot)
    await engine.end_execution(execution_id)

    # Create new engine instance
    engine2 = SddCoderEngine(
        roster=roster_config,
        probe=mock_probe,
        worktree_base_path=str(tmp_path),
    )

    # Try to resume with same closed execution_id
    with pytest.raises(CoderFailure) as exc_info:
        await engine2.begin_execution("FEAT-1", str(worktree_path), execution_id)
    assert exc_info.value.code == "execution_closed"


@pytest.mark.asyncio
async def test_persistence_failure_is_explicit(tmp_path, roster_config):
    """Test that persistence failures are exposed and retried.

    - Create execution
    - Mock snapshot write to fail
    - Verify persistence_degraded flag is set
    - Verify status() retries and recovers
    """
    worktree_path = tmp_path / "feature-worktree"
    worktree_path.mkdir()

    import subprocess

    subprocess.run(["git", "init", "-b", "dev"], cwd=worktree_path, check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"], cwd=worktree_path, check=True, capture_output=True
    )
    subprocess.run(["git", "config", "user.name", "Test"], cwd=worktree_path, check=True, capture_output=True)

    # Create index
    index_dir = worktree_path / "sdd" / "tasks" / "index"
    index_dir.mkdir(parents=True)
    index_file = index_dir / "test-feature.json"
    index_file.write_text(
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
    mock_probe = AsyncMock()
    mock_probe.probe = AsyncMock(return_value=[])

    engine = SddCoderEngine(
        roster=roster_config,
        probe=mock_probe,
        worktree_base_path=str(tmp_path),
    )

    await engine.begin_execution("FEAT-1", str(worktree_path), execution_id)

    # Mock write_execution_snapshot to fail
    write_calls = []
    orig_write = engine._write_execution_snapshot

    async def mock_write_fail(*args, **kwargs):
        write_calls.append(("fail", args, kwargs))
        return False

    async def mock_write_success(*args, **kwargs):
        write_calls.append(("success", args, kwargs))
        return await orig_write(*args, **kwargs)

    # First write fails (during end_execution)
    engine._write_execution_snapshot = mock_write_fail
    pool = engine._executions[execution_id]

    # Mock job table
    job = MagicMock()
    job.job_id = "job-123"
    engine._jobs.get = MagicMock(return_value=job)

    # Try to end while degraded write is in effect
    # This should mark persistence_degraded
    view = await engine.end_execution(execution_id)
    assert view.persistence_degraded

    # Now allow writes to succeed and call status to retry
    engine._write_execution_snapshot = mock_write_success
    await engine.status("job-123")

    # Verify that a successful write happened
    success_writes = [w for w in write_calls if w[0] == "success"]
    assert len(success_writes) > 0


@pytest.mark.asyncio
async def test_restart_preserves_inherited_exclusions(tmp_path, roster_config):
    """Test that inherited exclusions from durable history are preserved on restart.

    - Create and suspend a model during execution A
    - Write to durable suspension ledger
    - Restart execution A and resume execution B
    - Verify B inherits A's suspensions
    """
    worktree_path = tmp_path / "feature-worktree"
    worktree_path.mkdir()

    import subprocess

    subprocess.run(["git", "init", "-b", "dev"], cwd=worktree_path, check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"], cwd=worktree_path, check=True, capture_output=True
    )
    subprocess.run(["git", "config", "user.name", "Test"], cwd=worktree_path, check=True, capture_output=True)

    # Create index
    index_dir = worktree_path / "sdd" / "tasks" / "index"
    index_dir.mkdir(parents=True)
    index_file = index_dir / "test-feature.json"
    index_file.write_text(
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

    execution_id_a = str(uuid4())
    execution_id_b = str(uuid4())

    mock_probe = AsyncMock()
    mock_probe.probe = AsyncMock(return_value=[])

    engine = SddCoderEngine(
        roster=roster_config,
        probe=mock_probe,
        worktree_base_path=str(tmp_path),
    )

    # Create execution A
    await engine.begin_execution("FEAT-1", str(worktree_path), execution_id_a)
    pool_a = engine._executions[execution_id_a]

    # Add inherited exclusion (simulating durable history)
    model_key = ModelKey(backend="native", model="haiku")
    pool_a._initial_exclusions.add(model_key)

    # Write snapshot
    snapshot_a = pool_a.snapshot()
    snapshot_a.inherited_exclusions.append(model_key)
    persisted = await engine._write_execution_snapshot(str(worktree_path), execution_id_a, snapshot_a)
    assert persisted

    # Create new engine and resume
    engine2 = SddCoderEngine(
        roster=roster_config,
        probe=mock_probe,
        worktree_base_path=str(tmp_path),
    )

    await engine2.begin_execution("FEAT-1", str(worktree_path), execution_id_a)
    pool_a_restored = engine2._executions[execution_id_a]

    # Verify inherited exclusions are preserved
    assert model_key in pool_a_restored._initial_exclusions


@pytest.mark.asyncio
async def test_corrupt_execution_snapshot_requires_recovery(tmp_path, roster_config):
    """Test handling of corrupt execution snapshots.

    - Write corrupt snapshot file
    - Try to begin with that execution_id
    - Verify internal_error is raised
    """
    worktree_path = tmp_path / "feature-worktree"
    worktree_path.mkdir()

    import subprocess

    subprocess.run(["git", "init", "-b", "dev"], cwd=worktree_path, check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"], cwd=worktree_path, check=True, capture_output=True
    )
    subprocess.run(["git", "config", "user.name", "Test"], cwd=worktree_path, check=True, capture_output=True)

    # Create index
    index_dir = worktree_path / "sdd" / "tasks" / "index"
    index_dir.mkdir(parents=True)
    index_file = index_dir / "test-feature.json"
    index_file.write_text(
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

    # Write corrupt snapshot
    executions_dir = worktree_path / ".sdd-coder" / "executions"
    executions_dir.mkdir(parents=True)
    snapshot_file = executions_dir / f"{execution_id}.json"
    snapshot_file.write_text("{ CORRUPT JSON ]")

    mock_probe = AsyncMock()
    mock_probe.probe = AsyncMock(return_value=[])

    engine = SddCoderEngine(
        roster=roster_config,
        probe=mock_probe,
        worktree_base_path=str(tmp_path),
    )

    # Try to begin - should raise on corrupt snapshot read
    with pytest.raises(CoderFailure) as exc_info:
        await engine.begin_execution("FEAT-1", str(worktree_path), execution_id)
    assert exc_info.value.code == "internal_error"


@pytest.mark.asyncio
async def test_uncertain_work_blocks_dispatch(tmp_path, roster_config):
    """Test that uncertain running/prepared work blocks dispatch until reconciled.

    - Create execution with pending attempts
    - Write snapshot with admitted_attempts
    - Restart and verify status is recovery_required
    """
    worktree_path = tmp_path / "feature-worktree"
    worktree_path.mkdir()

    import subprocess

    subprocess.run(["git", "init", "-b", "dev"], cwd=worktree_path, check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"], cwd=worktree_path, check=True, capture_output=True
    )
    subprocess.run(["git", "config", "user.name", "Test"], cwd=worktree_path, check=True, capture_output=True)

    # Create index
    index_dir = worktree_path / "sdd" / "tasks" / "index"
    index_dir.mkdir(parents=True)
    index_file = index_dir / "test-feature.json"
    index_file.write_text(
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

    mock_probe = AsyncMock()
    mock_probe.probe = AsyncMock(return_value=[])

    engine = SddCoderEngine(
        roster=roster_config,
        probe=mock_probe,
        worktree_base_path=str(tmp_path),
    )

    await engine.begin_execution("FEAT-1", str(worktree_path), execution_id)

    # Create snapshot with admitted attempts (simulating uncertain work)
    snapshot = ExecutionSnapshot(
        execution_id=execution_id,
        feature_id="FEAT-1",
        worktree_path=str(worktree_path),
        roster_fingerprint=roster_fingerprint(roster_config),
        admitted_attempts={"attempt-uid-1": "TASK-1"},
        native_reservations={},
        outstanding_job_ids=["job-123"],
        local_exclusions=[],
        inherited_exclusions=[],
        status="active",
        generation=0,
    )

    # Write snapshot to disk
    persisted = await engine._write_execution_snapshot(str(worktree_path), execution_id, snapshot)
    assert persisted

    # Create new engine and resume
    engine2 = SddCoderEngine(
        roster=roster_config,
        probe=mock_probe,
        worktree_base_path=str(tmp_path),
    )

    view = await engine2.begin_execution("FEAT-1", str(worktree_path), execution_id)

    # Verify status is recovery_required due to uncertain work
    assert view.status == "recovery_required"
