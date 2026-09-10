"""Git-sandbox integration tests for SddCoderEngine's read/consolidation side (TASK-3120)."""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from parrot.flows.dev_loop.sdd_coder.engine import CoderFailure, SddCoderEngine
from parrot.flows.dev_loop.sdd_coder.models import PlannedTask, RosterConfig, RosterSeat
from parrot.flows.dev_loop.task_scheduler import TaskScheduler


async def _git(*args: str, cwd: Path) -> tuple[int, str, str]:
    proc = await asyncio.create_subprocess_exec(
        "git", *args, cwd=str(cwd), stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    out, err = await proc.communicate()
    return proc.returncode or 0, out.decode(), err.decode()


async def _write_and_commit(worktree: Path, filename: str, content: str, message: str) -> None:
    path = worktree / filename
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    rc, _out, err = await _git("add", filename, cwd=worktree)
    assert rc == 0, err
    rc, _out, err = await _git("commit", "-m", message, cwd=worktree)
    assert rc == 0, err


async def test_engine_plan_from_real_index(git_sandbox_feature, three_seat_roster, noop_probe):
    worktree, feature_branch, base_path, _index_path = git_sandbox_feature
    engine = SddCoderEngine(roster=three_seat_roster, probe=noop_probe, worktree_base_path=str(base_path))

    plan = await engine.plan("demo", str(worktree))

    assert plan.feature_id == "FEAT-549"
    assert plan.feature == "demo"
    assert plan.feature_branch == feature_branch
    assert plan.pending == ["TASK-0001", "TASK-0002", "TASK-0003", "TASK-0004", "TASK-0005"]
    assert plan.blocked == ["TASK-0004", "TASK-0005"]
    assert len(plan.chunks) == 1
    wave1_ids = sorted(t.task_id for t in plan.chunks[0].tasks)
    assert wave1_ids == ["TASK-0001", "TASK-0002", "TASK-0003"]
    seat_labels = [t.seat_label for t in plan.chunks[0].tasks]
    assert len(seat_labels) == len(set(seat_labels)) == 3


async def test_engine_plan_is_deterministic(git_sandbox_feature, three_seat_roster, noop_probe, monkeypatch):
    """Shuffled `TaskScheduler.next_wave()` order yields identical chunks (S3):
    two INDEPENDENT engines (fresh ChunkAssigner each, `_start=0`) must agree,
    since the assigner's rotating start is per-engine state, not part of the
    determinism guarantee under test here."""
    worktree, _feature_branch, base_path, _index_path = git_sandbox_feature

    engine1 = SddCoderEngine(roster=three_seat_roster, probe=noop_probe, worktree_base_path=str(base_path))
    plan1 = await engine1.plan("demo", str(worktree))

    original_next_wave = TaskScheduler.next_wave

    def _reversed_next_wave(self):
        return list(reversed(original_next_wave(self)))

    monkeypatch.setattr(TaskScheduler, "next_wave", _reversed_next_wave)

    engine2 = SddCoderEngine(roster=three_seat_roster, probe=noop_probe, worktree_base_path=str(base_path))
    plan2 = await engine2.plan("demo", str(worktree))

    assert plan1.chunks == plan2.chunks


async def test_engine_plan_dependency_cycle(git_sandbox_feature, three_seat_roster, noop_probe):
    worktree, _feature_branch, base_path, index_path = git_sandbox_feature
    data = json.loads(index_path.read_text())
    data["tasks"][0]["depends_on"] = ["TASK-0002"]
    data["tasks"][1]["depends_on"] = ["TASK-0001"]
    index_path.write_text(json.dumps(data, indent=2))

    engine = SddCoderEngine(roster=three_seat_roster, probe=noop_probe, worktree_base_path=str(base_path))
    with pytest.raises(CoderFailure) as excinfo:
        await engine.plan("demo", str(worktree))
    assert excinfo.value.code == "dependency_cycle"


async def test_engine_rejects_worktree_outside_base(git_sandbox_feature, three_seat_roster, noop_probe, tmp_path):
    worktree, _feature_branch, _base_path, _index_path = git_sandbox_feature
    other_base = tmp_path / "unrelated"
    other_base.mkdir()
    engine = SddCoderEngine(roster=three_seat_roster, probe=noop_probe, worktree_base_path=str(other_base))
    with pytest.raises(CoderFailure) as excinfo:
        await engine.plan("demo", str(worktree))
    assert excinfo.value.code == "worktree_outside_base"


async def test_engine_feature_not_found(git_sandbox_feature, three_seat_roster, noop_probe):
    worktree, _feature_branch, base_path, _index_path = git_sandbox_feature
    engine = SddCoderEngine(roster=three_seat_roster, probe=noop_probe, worktree_base_path=str(base_path))
    with pytest.raises(CoderFailure) as excinfo:
        await engine.plan("no-such-feature", str(worktree))
    assert excinfo.value.code == "feature_not_found"


async def test_engine_native_prepare_then_merge(git_sandbox_feature, noop_probe):
    worktree, feature_branch, base_path, _index_path = git_sandbox_feature
    roster = RosterConfig(seats=[RosterSeat(label="h", kind="native")])
    engine = SddCoderEngine(roster=roster, probe=noop_probe, worktree_base_path=str(base_path))

    prep = await engine.prepare_native("demo", str(worktree), "TASK-0001")
    assert prep.branch == f"{feature_branch}--TASK-0001-a1"
    assert prep.task_file == "sdd/tasks/active/TASK-0001-demo.md"

    sub_worktree = Path(prep.worktree_path)
    await _write_and_commit(sub_worktree, "pkg/t1.py", "# t1\n", "implement TASK-0001")

    result = await engine.merge("demo", str(worktree), "TASK-0001")
    assert result.outcome == "merged"

    _rc, log, _err = await _git("log", "--oneline", feature_branch, cwd=worktree)
    assert "implement TASK-0001" in log
    _rc, status, _err = await _git("status", "--porcelain", cwd=worktree)
    assert status.strip() == ""


async def test_engine_rejects_dirty_task_worktree(git_sandbox_feature, noop_probe):
    worktree, feature_branch, base_path, _index_path = git_sandbox_feature
    engine = SddCoderEngine(roster=RosterConfig(seats=[RosterSeat(label="h", kind="native")]), probe=noop_probe,
                            worktree_base_path=str(base_path))
    ctx = await engine._resolve_feature("demo", str(worktree))
    manager = engine._manager_for(ctx, "TASK-0002", 1)
    path = Path(await manager.create("TASK-0002.a1"))
    await _write_and_commit(path, "pkg/t2.py", "# t2\n", "implement TASK-0002")
    (path / "stray.txt").write_text("untracked\n")

    result = await engine.merge("demo", str(worktree), "TASK-0002")
    assert result.outcome == "failed"
    assert "dirty_task_worktree" in result.diagnostics


async def test_engine_fidelity_violation_keeps_branch(git_sandbox_feature, noop_probe):
    worktree, feature_branch, base_path, _index_path = git_sandbox_feature
    engine = SddCoderEngine(roster=RosterConfig(seats=[RosterSeat(label="h", kind="native")]), probe=noop_probe,
                            worktree_base_path=str(base_path))
    ctx = await engine._resolve_feature("demo", str(worktree))
    manager = engine._manager_for(ctx, "TASK-0003", 1)
    path = Path(await manager.create("TASK-0003.a1"))
    await _write_and_commit(path, "pkg/unexpected.py", "# oops\n", "unlisted file")

    result = await engine.merge("demo", str(worktree), "TASK-0003")
    assert result.outcome == "fidelity_violation"
    assert "pkg/unexpected.py" in result.unexpected_files

    _rc, log, _err = await _git("log", "--oneline", feature_branch, cwd=worktree)
    assert "unlisted file" not in log


async def test_engine_merge_conflict_reported_and_aborted(git_sandbox_feature, noop_probe):
    worktree, feature_branch, base_path, _index_path = git_sandbox_feature
    engine = SddCoderEngine(roster=RosterConfig(seats=[RosterSeat(label="h", kind="native")]), probe=noop_probe,
                            worktree_base_path=str(base_path))
    ctx = await engine._resolve_feature("demo", str(worktree))

    manager1 = engine._manager_for(ctx, "TASK-0001", 1)
    path1 = Path(await manager1.create("TASK-0001.a1"))
    manager2 = engine._manager_for(ctx, "TASK-0001", 2)
    path2 = Path(await manager2.create("TASK-0001.a2"))

    await _write_and_commit(path1, "pkg/t1.py", "print('A')\n", "attempt 1")
    await _write_and_commit(path2, "pkg/t1.py", "print('B')\n", "attempt 2")

    planned = PlannedTask(
        task_id="TASK-0001", task_file="sdd/tasks/active/TASK-0001-demo.md", seat_label="h", native=True
    )
    first = await engine._consolidate(
        ctx, manager1, planned, branch=f"{feature_branch}--TASK-0001-a1", path=str(path1)
    )
    assert first.outcome == "merged"

    second = await engine.merge("demo", str(worktree), "TASK-0001")
    assert second.outcome == "merge_conflict"
    assert second.branch == f"{feature_branch}--TASK-0001-a2"

    _rc, status, _err = await _git("status", "--porcelain", cwd=worktree)
    assert status.strip() == ""
    _rc, branches, _err = await _git("branch", "--list", f"{feature_branch}--TASK-0001-a2", cwd=worktree)
    assert f"{feature_branch}--TASK-0001-a2" in branches


async def test_engine_orphans_listed_not_merged(git_sandbox_feature, three_seat_roster, noop_probe):
    worktree, feature_branch, base_path, _index_path = git_sandbox_feature
    orphan_branch = f"{feature_branch}--TASK-0009-a1"
    await _git("checkout", "-b", orphan_branch, cwd=worktree)
    await _write_and_commit(worktree, "pkg/orphan.py", "# orphan\n", "orphan commit")
    await _git("checkout", feature_branch, cwd=worktree)

    engine = SddCoderEngine(roster=three_seat_roster, probe=noop_probe, worktree_base_path=str(base_path))
    plan = await engine.plan("demo", str(worktree))

    orphan_ids = {o.task_id: o for o in plan.orphan_branches}
    assert "TASK-0009" in orphan_ids
    assert orphan_ids["TASK-0009"].branch == orphan_branch
    assert orphan_ids["TASK-0009"].commits == 1
    assert "pkg/orphan.py" in orphan_ids["TASK-0009"].files

    _rc, log, _err = await _git("log", "--oneline", feature_branch, cwd=worktree)
    assert "orphan commit" not in log


async def test_engine_journals_job_snapshot(git_sandbox_feature, three_seat_roster, noop_probe):
    from parrot.flows.dev_loop.sdd_coder.models import CoderJob

    worktree, _feature_branch, base_path, _index_path = git_sandbox_feature
    engine = SddCoderEngine(roster=three_seat_roster, probe=noop_probe, worktree_base_path=str(base_path))
    job = CoderJob(job_id="job-abc123", feature_id="FEAT-549", chunk_task_ids=["TASK-0001"], state="done",
                  started_at="2026-09-10T00:00:00+00:00")

    engine._journal(str(worktree), job)

    journal_path = worktree / ".sdd-coder" / "jobs" / "job-abc123.json"
    assert journal_path.is_file()
    assert json.loads(journal_path.read_text())["job_id"] == "job-abc123"
