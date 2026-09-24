"""Regression scenarios for FEAT-584 M2/R3 `record_native_observation`.

Uses isolated git-sandbox fixtures and a synthetic durable telemetry root
under `tmp_path`, never live providers or a real dispatcher.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from parrot.flows.dev_loop.sdd_coder.engine import CoderFailure, SddCoderEngine
from parrot.flows.dev_loop.sdd_coder.models import RosterConfig, RosterSeat

from .test_engine_plan_merge import _write_and_commit


def _observation(attempt_uid: str, **overrides: object) -> dict[str, object]:
    """A minimally valid `coder_record_native_observation.observation` payload."""
    observed_at = datetime(2026, 9, 21, 12, 0, 0, tzinfo=timezone.utc)
    base: dict[str, object] = {
        "event_id": "evt-1",
        "task_id": "TASK-0001",
        "attempt_uid": attempt_uid,
        "agent_id": "agent-77",
        "observed_at": observed_at.isoformat(),
        "kind": "finished",
        "started_at": (observed_at - timedelta(minutes=3)).isoformat(),
        "ended_at": observed_at.isoformat(),
        "terminal": "completed",
        "evidence_ref": {
            "artifact_id": "a" * 64,
            "sha256": "a" * 64,
            "relative_path": "handback/agent-77.json",
            "size_bytes": 42,
            "media_type": "application/json",
        },
    }
    base.update(overrides)
    return base


async def test_observation_does_not_settle_attempt(tmp_path: Path, git_sandbox_feature, noop_probe) -> None:
    """Valid native completion observation leaves reservation and merge gates intact."""
    worktree, _branch, base_path, _index_path = git_sandbox_feature
    roster = RosterConfig(seats=[RosterSeat(label="h", kind="native", model="haiku")])
    engine = SddCoderEngine(
        roster=roster,
        probe=noop_probe,
        worktree_base_path=str(base_path),
        telemetry_dir=str(tmp_path / "telemetry"),
    )
    execution_id = "550e0000-0000-0000-0000-000000000071"
    await engine.begin_execution("demo", str(worktree), execution_id)
    prep = await engine.prepare_native("demo", str(worktree), "TASK-0001", execution_id)

    pool = engine._executions[execution_id]
    assert prep.attempt_uid in pool._admitted  # noqa: SLF001 -- asserting the reservation is still live

    ref = await engine.record_native_observation("demo", str(worktree), execution_id, _observation(prep.attempt_uid))
    assert ref.artifact_id == "evt-1"

    # The reservation is untouched: no release, no settlement, no merge side effect.
    assert prep.attempt_uid in pool._admitted  # noqa: SLF001
    assert pool._admitted[prep.attempt_uid][0] == "TASK-0001"  # noqa: SLF001

    # No AttemptRecord/usage row was fabricated by the observation (AC6: "no crean tokens/spans").
    assert engine._latest_attempt == {}
    telemetry_file = tmp_path / "telemetry" / "FEAT-549.jsonl"
    assert not telemetry_file.exists()


async def test_foreign_or_conflicting_identity(tmp_path: Path, git_sandbox_feature, noop_probe) -> None:
    """Foreign execution, unknown attempt and contradictory event_id fail before mutation."""
    worktree, _branch, base_path, _index_path = git_sandbox_feature
    roster = RosterConfig(seats=[RosterSeat(label="h", kind="native", model="haiku")])
    engine = SddCoderEngine(
        roster=roster,
        probe=noop_probe,
        worktree_base_path=str(base_path),
        telemetry_dir=str(tmp_path / "telemetry"),
    )
    execution_id = "550e0000-0000-0000-0000-000000000072"
    await engine.begin_execution("demo", str(worktree), execution_id)
    prep = await engine.prepare_native("demo", str(worktree), "TASK-0001", execution_id)

    events_path = tmp_path / "telemetry" / "executions" / execution_id / "events.jsonl"

    # Foreign execution: this engine has no record of it at all.
    with pytest.raises(CoderFailure) as excinfo:
        await engine.record_native_observation(
            "demo",
            str(worktree),
            "550e0000-0000-0000-0000-000000000099",
            _observation(prep.attempt_uid),
        )
    assert excinfo.value.code == "execution_not_found"

    # Unknown attempt: well-formed but never issued by this execution.
    with pytest.raises(CoderFailure) as excinfo:
        await engine.record_native_observation("demo", str(worktree), execution_id, _observation(uuid.uuid4().hex))
    assert excinfo.value.code == "attempt_not_found"

    # Neither failure wrote anything durable.
    assert not events_path.exists()

    # A genuinely valid observation settles durably.
    ref = await engine.record_native_observation("demo", str(worktree), execution_id, _observation(prep.attempt_uid))
    assert ref.artifact_id == "evt-1"

    # Contradictory event_id: same id, different agent_id -> rejected as a conflict.
    with pytest.raises(CoderFailure) as excinfo:
        await engine.record_native_observation(
            "demo", str(worktree), execution_id, _observation(prep.attempt_uid, agent_id="agent-2")
        )
    assert excinfo.value.code == "observation_conflict"

    # The conflicting retry never mutated the durably recorded event.
    lines = [line for line in events_path.read_text("utf-8").splitlines() if line.strip()]
    assert len(lines) == 1
    recorded = json.loads(lines[0])
    assert recorded["payload"]["agent_id"] == "agent-77"

    # The reservation is still untouched by any of the above.
    pool = engine._executions[execution_id]
    assert prep.attempt_uid in pool._admitted  # noqa: SLF001


async def test_telemetry_failure_is_reported(tmp_path: Path, git_sandbox_feature, noop_probe, monkeypatch) -> None:
    """Observational write failures are visible but do not invalidate a correct merge."""
    worktree, _feature_branch, base_path, _index_path = git_sandbox_feature
    roster = RosterConfig(seats=[RosterSeat(label="h", kind="native", model="haiku")])
    engine = SddCoderEngine(
        roster=roster,
        probe=noop_probe,
        worktree_base_path=str(base_path),
        telemetry_dir=str(tmp_path / "telemetry"),
    )
    execution_id = "550e0000-0000-0000-0000-000000000073"
    await engine.begin_execution("demo", str(worktree), execution_id)
    prep = await engine.prepare_native("demo", str(worktree), "TASK-0001", execution_id)

    async def _broken_append_event(event):
        raise OSError("simulated disk failure")

    monkeypatch.setattr(engine._evidence_store, "append_event", _broken_append_event)

    with pytest.raises(CoderFailure) as excinfo:
        await engine.record_native_observation("demo", str(worktree), execution_id, _observation(prep.attempt_uid))
    assert excinfo.value.code == "evidence_persistence_failed"

    # The observation write failure is visible (raised), but a genuinely correct
    # merge for the SAME task is entirely unaffected by it.
    sub_worktree = Path(prep.worktree_path)
    await _write_and_commit(sub_worktree, "pkg/t1.py", "# t1\n", "implement TASK-0001")
    result = await engine.merge("demo", str(worktree), "TASK-0001", execution_id)
    assert result.outcome == "merged"


async def test_prepare_native_on_a_busy_seat_fails_with_seat_busy(
    tmp_path: Path, git_sandbox_feature, noop_probe
) -> None:
    """A second native preparation on the same model must not wait for the first task's merge.

    Regression for the 2026-09-24 FEAT-581 run: `coder_prepare_native(TASK-3548)` held
    native/sonnet, `coder_prepare_native(TASK-3540)` parked forever in `pool.admit`, and the
    serial stdio loop then starved the `coder_merge` that would have released the seat.
    """
    worktree, _branch, base_path, _index_path = git_sandbox_feature
    roster = RosterConfig(seats=[RosterSeat(label="h", kind="native", model="haiku")])
    engine = SddCoderEngine(
        roster=roster,
        probe=noop_probe,
        worktree_base_path=str(base_path),
        telemetry_dir=str(tmp_path / "telemetry"),
    )
    execution_id = "550e0000-0000-0000-0000-000000000073"
    await engine.begin_execution("demo", str(worktree), execution_id)
    plan = await engine.plan("demo", str(worktree), execution_id=execution_id)
    native_ids = [t.task_id for c in plan.chunks for t in c.tasks if t.native]
    assert len(native_ids) >= 2, native_ids
    first, second = native_ids[0], native_ids[1]

    prep = await engine.prepare_native("demo", str(worktree), first, execution_id)

    with pytest.raises(CoderFailure) as excinfo:
        await asyncio.wait_for(engine.prepare_native("demo", str(worktree), second, execution_id), timeout=5)
    assert excinfo.value.code == "seat_busy"
    assert excinfo.value.details["held_by_task_id"] == first
    assert excinfo.value.details["model"] == "haiku"

    # No worktree or reservation was allocated for the rejected task.
    assert (execution_id, second) not in engine._native_reservations  # noqa: SLF001
    pool = engine._executions[execution_id]  # noqa: SLF001
    assert list(pool._admitted) == [prep.attempt_uid]  # noqa: SLF001

    # A duplicate call for the task that already holds the seat still reuses its reservation.
    again = await engine.prepare_native("demo", str(worktree), first, execution_id)
    assert again.attempt_uid == prep.attempt_uid


async def test_concurrent_duplicate_prepare_native_shares_one_worktree(
    tmp_path: Path, git_sandbox_feature, noop_probe
) -> None:
    """Two overlapping `prepare_native` calls for the same task resolve to one reservation and one worktree.

    The stdio server now dispatches requests concurrently, so a duplicate call can arrive
    while the first is still creating its sub-worktree (codex review, 2026-09-24).
    """
    worktree, _branch, base_path, _index_path = git_sandbox_feature
    roster = RosterConfig(seats=[RosterSeat(label="h", kind="native", model="haiku")])
    engine = SddCoderEngine(
        roster=roster,
        probe=noop_probe,
        worktree_base_path=str(base_path),
        telemetry_dir=str(tmp_path / "telemetry"),
    )
    execution_id = "550e0000-0000-0000-0000-000000000074"
    await engine.begin_execution("demo", str(worktree), execution_id)

    first, second = await asyncio.gather(
        engine.prepare_native("demo", str(worktree), "TASK-0001", execution_id),
        engine.prepare_native("demo", str(worktree), "TASK-0001", execution_id),
    )
    assert first.attempt_uid == second.attempt_uid
    assert first.worktree_path == second.worktree_path
    assert Path(first.worktree_path).is_dir()
    pool = engine._executions[execution_id]  # noqa: SLF001
    assert list(pool._admitted) == [first.attempt_uid]  # noqa: SLF001
