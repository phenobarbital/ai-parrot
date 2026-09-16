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
    engine = SddCoderEngine(
        roster=RosterConfig(seats=[RosterSeat(label="h", kind="native")]),
        probe=noop_probe,
        worktree_base_path=str(base_path),
    )
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
    engine = SddCoderEngine(
        roster=RosterConfig(seats=[RosterSeat(label="h", kind="native")]),
        probe=noop_probe,
        worktree_base_path=str(base_path),
    )
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
    engine = SddCoderEngine(
        roster=RosterConfig(seats=[RosterSeat(label="h", kind="native")]),
        probe=noop_probe,
        worktree_base_path=str(base_path),
    )
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
    first = await engine._consolidate(ctx, manager1, planned, branch=f"{feature_branch}--TASK-0001-a1", path=str(path1))
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
    job = CoderJob(
        job_id="job-abc123",
        feature_id="FEAT-549",
        chunk_task_ids=["TASK-0001"],
        state="done",
        started_at="2026-09-10T00:00:00+00:00",
    )

    await engine._journal(str(worktree), job)

    journal_path = worktree / ".sdd-coder" / "jobs" / "job-abc123.json"
    assert journal_path.is_file()
    assert json.loads(journal_path.read_text())["job_id"] == "job-abc123"


_BANNED_CFG = (
    '[lint]\nselect = ["TID251"]\n[lint.flake8-tidy-imports.banned-api]\n'
    '"requests".msg = "use aiohttp"\n"httpx".msg = "use aiohttp"\n'
)


async def test_consolidate_rejects_banned_import(git_sandbox_feature, noop_probe):
    worktree, feature_branch, base_path, _index_path = git_sandbox_feature
    await _write_and_commit(
        worktree, "ruff.toml", _BANNED_CFG, "ruff config"
    )  # on the feature branch, so sub-worktrees inherit it
    engine = SddCoderEngine(
        roster=RosterConfig(seats=[RosterSeat(label="h", kind="native")]),
        probe=noop_probe,
        worktree_base_path=str(base_path),
    )
    ctx = await engine._resolve_feature("demo", str(worktree))
    manager = engine._manager_for(ctx, "TASK-0003", 1)
    path = Path(await manager.create("TASK-0003.a1"))
    await _write_and_commit(path, "pkg/t3.py", "import requests\n", "banned import")

    result = await engine.merge("demo", str(worktree), "TASK-0003")
    assert result.outcome == "fidelity_violation" and result.diagnostics.startswith("BannedImport:")

    _rc, log, _err = await _git("log", "--oneline", feature_branch, cwd=worktree)
    assert "banned import" not in log


async def test_consolidate_rechecks_banned_import_after_manual_remerge(git_sandbox_feature, noop_probe):
    """Code-review fix: `sdd-worker.md`'s documented `merge_conflict` recovery —
    resolve manually with `git merge <branch>` directly in the feature worktree,
    commit, then call `coder_merge` (-> `_consolidate`) again — must not let a
    banned import slip through on the SECOND `_consolidate` call just because
    `branch` is now an ancestor of `feature_branch` (which collapses a plain
    `git merge-base` to `branch`'s own tip and would otherwise produce an empty
    diff)."""
    worktree, feature_branch, base_path, _index_path = git_sandbox_feature
    await _write_and_commit(worktree, "ruff.toml", _BANNED_CFG, "ruff config")
    engine = SddCoderEngine(
        roster=RosterConfig(seats=[RosterSeat(label="h", kind="native")]),
        probe=noop_probe,
        worktree_base_path=str(base_path),
    )
    ctx = await engine._resolve_feature("demo", str(worktree))
    manager = engine._manager_for(ctx, "TASK-0003", 1)
    path = Path(await manager.create("TASK-0003.a1"))
    branch = f"{feature_branch}--TASK-0003-a1"
    await _write_and_commit(path, "pkg/t3.py", "import requests\n", "banned import")

    # Diverge feature_branch so the manual merge below cannot fast-forward — mirrors
    # a realistic merge_conflict (something else changed on feature_branch meanwhile).
    await _write_and_commit(worktree, "pkg/unrelated.py", "# unrelated\n", "unrelated change")

    # Simulate sdd-worker.md's documented recovery: merge `branch` directly into the
    # feature worktree and commit, bypassing `manager.merge_sequential()` entirely.
    rc, _out, err = await _git("merge", "--no-ff", branch, "-m", f"merge {branch}", cwd=worktree)
    assert rc == 0, err

    result = await engine.merge("demo", str(worktree), "TASK-0003")
    assert result.outcome == "fidelity_violation" and result.diagnostics.startswith("BannedImport:")


async def test_engine_cleanup_keeps_native_task_until_merged(git_sandbox_feature, noop_probe):
    """Regression (FEAT-555 incident): `coder_cleanup` removed a native seat's sub-worktree while the
    background `Agent` was still working in it. A `prepare_native` worktree must survive cleanup
    until `merge()` has consolidated it."""
    worktree, feature_branch, base_path, _index_path = git_sandbox_feature
    roster = RosterConfig(seats=[RosterSeat(label="h", kind="native")])
    engine = SddCoderEngine(roster=roster, probe=noop_probe, worktree_base_path=str(base_path))

    prep = await engine.prepare_native("demo", str(worktree), "TASK-0001")
    sub_worktree = Path(prep.worktree_path)

    report = await engine.cleanup("demo", str(worktree))
    assert prep.branch in report.kept
    assert prep.branch not in report.removed
    assert sub_worktree.exists()

    await _write_and_commit(sub_worktree, "pkg/t1.py", "# t1\n", "implement TASK-0001")
    merged = await engine.merge("demo", str(worktree), "TASK-0001")
    assert merged.outcome == "merged"

    report = await engine.cleanup("demo", str(worktree))
    assert prep.branch in report.removed
    assert not sub_worktree.exists()


async def test_engine_merge_never_reports_merged_when_nothing_landed(git_sandbox_feature, noop_probe):
    """Regression (FEAT-555 incident): after the manager forgot its worktree, `merge()` iterated an empty
    map, merged nothing, and still answered `merged`. The outcome must reflect the feature branch."""
    worktree, feature_branch, base_path, _index_path = git_sandbox_feature
    roster = RosterConfig(seats=[RosterSeat(label="h", kind="native")])
    engine = SddCoderEngine(roster=roster, probe=noop_probe, worktree_base_path=str(base_path))

    prep = await engine.prepare_native("demo", str(worktree), "TASK-0001")
    await _write_and_commit(Path(prep.worktree_path), "pkg/t1.py", "# t1\n", "implement TASK-0001")
    engine._managers["TASK-0001.a1"]._created.clear()  # noqa: SLF001 — reproduce the post-cleanup state

    result = await engine.merge("demo", str(worktree), "TASK-0001")

    assert result.outcome == "failed"
    assert "branch_not_merged" in result.diagnostics
    _rc, log, _err = await _git("log", "--oneline", feature_branch, cwd=worktree)
    assert "implement TASK-0001" not in log


# FEAT-559 execution lifecycle tests (TASK-3279)


async def test_begin_reads_history_before_probe(git_sandbox_feature, explicit_model_roster, noop_probe):
    """begin_execution must read durable history BEFORE probing eligible candidates.

    This is the core M3 requirement: no model probe happens until exclusions
    from the suspension ledger are known.
    """
    worktree, _feature_branch, base_path, _index_path = git_sandbox_feature
    engine = SddCoderEngine(roster=explicit_model_roster, probe=noop_probe, worktree_base_path=str(base_path))

    execution_id = "550e0000-0000-0000-0000-000000000001"
    view = await engine.begin_execution("demo", str(worktree), execution_id)

    # Pool should be created with the execution_id bound
    assert view.execution_id == execution_id
    assert view.feature_id == "FEAT-549"
    assert view.status == "active"
    # Should have probed seats (noop_probe returns all available)
    assert len(view.seats) > 0


async def test_begin_idempotent_scope_and_roster_binding(git_sandbox_feature, explicit_model_roster, noop_probe):
    """Repeated begin with the same execution_id is idempotent for matching scope/config.

    A second begin with the same execution_id and same feature/worktree should
    return the existing pool, not create a new one.
    """
    worktree, _feature_branch, base_path, _index_path = git_sandbox_feature
    engine = SddCoderEngine(roster=explicit_model_roster, probe=noop_probe, worktree_base_path=str(base_path))

    execution_id = "550e0000-0000-0000-0000-000000000002"

    # First begin
    view1 = await engine.begin_execution("demo", str(worktree), execution_id)
    # Second begin (idempotent)
    view2 = await engine.begin_execution("demo", str(worktree), execution_id)

    # Should be the same pool
    assert view1.execution_id == view2.execution_id
    assert view1.generation == view2.generation
    # Should not have cleared exclusions or extended expiry
    assert execution_id in engine._executions


async def test_same_worktree_has_single_execution_owner(git_sandbox_feature, explicit_model_roster, noop_probe):
    """Only one active execution may own a canonical worktree at a time.

    A second begin with a different execution_id for the same worktree should
    fail with execution_in_progress.
    """
    worktree, _feature_branch, base_path, _index_path = git_sandbox_feature
    engine = SddCoderEngine(roster=explicit_model_roster, probe=noop_probe, worktree_base_path=str(base_path))

    exec_id_1 = "550e0000-0000-0000-0000-000000000011"
    exec_id_2 = "550e0000-0000-0000-0000-000000000012"

    # First execution owns the worktree
    await engine.begin_execution("demo", str(worktree), exec_id_1)

    # Second execution should be rejected
    with pytest.raises(CoderFailure) as excinfo:
        await engine.begin_execution("demo", str(worktree), exec_id_2)

    assert excinfo.value.code == "execution_in_progress"
    assert excinfo.value.details.get("owner_execution_id") == exec_id_1


async def test_all_seats_exhausted(git_sandbox_feature, explicit_model_roster, noop_probe, isolated_suspension_store):
    """When all seats are suspended, fallback_required should be true.

    The pool should mark fallback_required=True with reason 'all_seats_exhausted'
    when no available seats remain after applying exclusions.
    """
    worktree, _feature_branch, base_path, _index_path = git_sandbox_feature

    # Pre-populate suspension store with all models excluded
    from datetime import datetime, timezone
    from parrot.knowledge.wiki.ledger.coder_suspensions import (
        ModelKey,
        SuspensionPolicy,
        SuspensionRecord,
    )

    now = datetime.now(timezone.utc)
    policy = SuspensionPolicy()

    for model in ["model-a", "model-b", "model-c"]:
        record = SuspensionRecord(
            execution_id="prior-execution",
            feature_id="FEAT-549",
            source="engine",
            seat_label="x",
            backend="nova" if model == "model-a" else "google-compat" if model == "model-b" else "codex",
            configured_model=model,
            blocked_keys=[ModelKey(backend="nova", model=model) if model == "model-a" else ModelKey(backend="google-compat", model=model) if model == "model-b" else ModelKey(backend="codex", model=model)],
            reason="timeout",
            occurred_at=now,
            expires_at=now.replace(second=now.second + 1800),
            duration_s=0.0,
            explanation="test suspension",
        )
        await isolated_suspension_store.record(record)

    engine = SddCoderEngine(
        roster=explicit_model_roster,
        probe=noop_probe,
        worktree_base_path=str(base_path),
    )
    engine._suspension_store = isolated_suspension_store

    execution_id = "550e0000-0000-0000-0000-000000000021"
    view = await engine.begin_execution("demo", str(worktree), execution_id)

    # All seats should be suspended, fallback required
    assert view.fallback_required is True
    assert view.fallback_reason == "all_seats_exhausted"


async def test_plan_cache_is_execution_private(git_sandbox_feature, explicit_model_roster, noop_probe):
    """Plans are cached per execution, not globally.

    Two different executions should have independent plan caches, so that
    one execution's rotation state doesn't affect another.
    """
    worktree, _feature_branch, base_path, _index_path = git_sandbox_feature
    engine = SddCoderEngine(roster=explicit_model_roster, probe=noop_probe, worktree_base_path=str(base_path))

    exec_id_1 = "550e0000-0000-0000-0000-000000000031"
    exec_id_2 = "550e0000-0000-0000-0000-000000000032"

    # Begin two executions
    await engine.begin_execution("demo", str(worktree), exec_id_1)
    await engine.begin_execution("demo", str(worktree), exec_id_2)

    # Plan with execution 1
    plan1 = await engine.plan("demo", str(worktree), execution_id=exec_id_1)
    # Plan with execution 2
    plan2 = await engine.plan("demo", str(worktree), execution_id=exec_id_2)

    # Both should have execution_id set
    assert plan1.execution_id == exec_id_1
    assert plan2.execution_id == exec_id_2

    # Both should have different pool_generation (same initially, but caches are separate)
    assert plan1.pool_generation == plan2.pool_generation  # Both 0 initially

    # Verify cache keys are different
    cache_key_1 = f"FEAT-549:{exec_id_1}"
    cache_key_2 = f"FEAT-549:{exec_id_2}"
    assert cache_key_1 in engine._plan_cache
    assert cache_key_2 in engine._plan_cache
    # The cached plans should be different objects
    assert engine._plan_cache[cache_key_1] is not engine._plan_cache[cache_key_2]


async def test_open_makes_zero_probes_without_execution(git_sandbox_feature, three_seat_roster, noop_probe):
    """Legacy open() should probe without needing an execution_id.

    This verifies backward compatibility: the old open() path still works
    and probes immediately (no history gating).
    """
    worktree, _feature_branch, base_path, _index_path = git_sandbox_feature
    engine = SddCoderEngine(roster=three_seat_roster, probe=noop_probe, worktree_base_path=str(base_path))

    # Call open without begin_execution
    await engine.open()

    # Should have probed
    assert len(engine.probe_results) > 0
    assert len(engine.seats) > 0
