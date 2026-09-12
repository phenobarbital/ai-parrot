"""Fake-dispatcher tests for SddCoderEngine's dispatch/retry side (TASK-3121)."""

from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path

import pytest

from parrot.flows.dev_loop.models import DevelopmentOutput
from parrot.flows.dev_loop.sdd_coder.engine import CoderFailure, SddCoderEngine
from parrot.flows.dev_loop.sdd_coder.models import RosterConfig, RosterSeat
from parrot.flows.dev_loop.session_state import DispatchCompleted


class FakeDispatcher:
    """Fulfils the dispatcher Protocol's `dispatch()` shape (mirrors test_agent_pool.py's FakeDispatcher).

    `behaviour` per instance:
      - "ok": writes the task's listed file in `cwd`, commits, returns a DevelopmentOutput.
      - "fail": raises RuntimeError.
      - "block": awaits an injected asyncio.Event before returning ok.
      - "extra": also writes an unlisted file (for fidelity-violation coverage elsewhere).
    """

    def __init__(self, behaviour: str = "ok", *, gate: asyncio.Event | None = None) -> None:
        self.behaviour = behaviour
        self.gate = gate
        self.calls: list[dict] = []

    async def dispatch(self, *, brief, profile, output_model, run_id, node_id, cwd, session_host=None, labels=None):
        self.calls.append({"brief": brief, "profile": profile, "node_id": node_id, "cwd": cwd, "labels": labels})
        if session_host is not None:
            # Mirrors dispatchers/_shared.py's `_apply_to_session_host`: the real pipeline rolls
            # `node_id` up to its owning (dot-free) segment before building the action, since
            # `DevLoopAction.node_id` is a closed `NodeId` Literal that "development.sdd-coder-x"
            # itself is not a member of.
            owning_node_id = node_id.split(".", 1)[0]
            action = DispatchCompleted(node_id=owning_node_id, ts=time.time(), input_tokens=10, output_tokens=20)
            session_host.apply(action)
        if self.behaviour == "block":
            assert self.gate is not None
            await self.gate.wait()
        if self.behaviour == "fail":
            raise RuntimeError("boom")

        task_id = brief.task_id
        n = task_id.rsplit("-", 1)[-1].lstrip("0") or "0"
        filename = f"pkg/t{int(n)}.py"
        (Path(cwd) / "pkg").mkdir(parents=True, exist_ok=True)
        (Path(cwd) / filename).write_text(f"# {task_id}\n")
        await _git("add", filename, cwd=cwd)
        await _git("commit", "-m", f"impl {task_id}", cwd=cwd)
        return DevelopmentOutput(files_changed=[filename], commit_shas=["deadbeef"], summary=task_id)


async def _git(*args: str, cwd: str) -> tuple[int, str, str]:
    proc = await asyncio.create_subprocess_exec(
        "git", *args, cwd=cwd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    out, err = await proc.communicate()
    return proc.returncode or 0, out.decode(), err.decode()


def fake_builder_factory(behaviour_by_backend: dict, *, gate: asyncio.Event | None = None):
    """(DevAgentSpec, **kwargs) -> (FakeDispatcher, profile) — keyword-compatible with build_dispatcher."""
    from parrot.flows.dev_loop.models import LLMCodeDispatchProfile

    dispatchers: dict[str, FakeDispatcher] = {}

    def _builder(spec, *, redis_url, max_concurrent, stream_ttl_seconds):
        behaviour = behaviour_by_backend.get(spec.agent, "ok")
        dispatcher = FakeDispatcher(behaviour, gate=gate)
        dispatchers[spec.agent] = dispatcher
        profile = LLMCodeDispatchProfile()
        return dispatcher, profile

    _builder.dispatchers = dispatchers  # type: ignore[attr-defined]
    return _builder


def _roster(*labels_backends: tuple[str, str]) -> RosterConfig:
    return RosterConfig(
        seats=[RosterSeat(label=lbl, backend=backend) for lbl, backend in labels_backends]  # type: ignore[arg-type]
    )


@pytest.fixture
def noop_probe():
    from parrot.flows.dev_loop.sdd_coder.roster import RosterProbe

    return RosterProbe(config_getter=lambda k, fallback=None: "x", which=lambda b: "/usr/bin/" + b, smoke=None)


async def test_engine_attempt_cwd_is_task_branch(git_sandbox_feature, noop_probe):
    worktree, feature_branch, base_path, _index_path = git_sandbox_feature
    builder = fake_builder_factory({})
    engine = SddCoderEngine(
        roster=_roster(("a", "nova"), ("b", "codex"), ("c", "google-compat")),
        probe=noop_probe,
        worktree_base_path=str(base_path),
        dispatcher_builder=builder,
    )
    job = await engine.run_chunk("demo", str(worktree), ["TASK-0001", "TASK-0002", "TASK-0003"])
    result = await engine.wait(job.job_id, 5)

    assert result.state == "done"
    for task in result.tasks:
        assert task.outcome == "merged"
        assert task.attempts[0].seat_label in {"a", "b", "c"}
        expected_path = str(Path(base_path) / f"{feature_branch}--pool" / f"{task.task_id}-a1")
        assert task.worktree_path == expected_path


async def test_engine_retry_on_other_seat_then_failed(git_sandbox_feature, noop_probe):
    worktree, _feature_branch, base_path, _index_path = git_sandbox_feature
    builder = fake_builder_factory({"nova": "fail"})
    engine = SddCoderEngine(
        roster=_roster(("a", "nova"), ("b", "codex"), ("c", "google-compat")),
        probe=noop_probe,
        worktree_base_path=str(base_path),
        dispatcher_builder=builder,
    )
    job = await engine.run_chunk("demo", str(worktree), ["TASK-0001"])
    result = await engine.wait(job.job_id, 5)

    task = result.tasks[0]
    assert task.outcome == "merged"
    assert len(task.attempts) == 2
    assert task.attempts[0].seat_label != task.attempts[1].seat_label
    assert task.attempts[0].error and not task.attempts[1].error


async def test_engine_both_attempts_fail_yields_failed(git_sandbox_feature, noop_probe):
    worktree, _feature_branch, base_path, _index_path = git_sandbox_feature
    builder = fake_builder_factory({"nova": "fail", "codex": "fail", "google-compat": "fail"})
    engine = SddCoderEngine(
        roster=_roster(("a", "nova"), ("b", "codex"), ("c", "google-compat")),
        probe=noop_probe,
        worktree_base_path=str(base_path),
        dispatcher_builder=builder,
    )
    job = await engine.run_chunk("demo", str(worktree), ["TASK-0001"])
    result = await engine.wait(job.job_id, 5)

    task = result.tasks[0]
    assert task.outcome == "failed"
    assert len(task.attempts) == 2
    assert "boom" in task.diagnostics


async def test_engine_forces_sdd_coder_subagent(git_sandbox_feature, noop_probe):
    worktree, _feature_branch, base_path, _index_path = git_sandbox_feature
    builder = fake_builder_factory({})
    engine = SddCoderEngine(
        roster=_roster(("a", "nova"), ("b", "codex"), ("c", "google-compat")),
        probe=noop_probe,
        worktree_base_path=str(base_path),
        dispatcher_builder=builder,
    )
    job = await engine.run_chunk("demo", str(worktree), ["TASK-0001", "TASK-0002", "TASK-0003"])
    await engine.wait(job.job_id, 5)

    for dispatcher in builder.dispatchers.values():
        for call in dispatcher.calls:
            assert call["profile"].subagent == "sdd-coder"


async def test_engine_run_chunk_returns_before_dispatch(git_sandbox_feature, noop_probe):
    worktree, _feature_branch, base_path, _index_path = git_sandbox_feature
    gate = asyncio.Event()
    builder = fake_builder_factory({"nova": "block"}, gate=gate)
    engine = SddCoderEngine(
        roster=_roster(("a", "nova"), ("b", "codex"), ("c", "google-compat")),
        probe=noop_probe,
        worktree_base_path=str(base_path),
        dispatcher_builder=builder,
    )
    job = await engine.run_chunk("demo", str(worktree), ["TASK-0001"])
    status = engine.status(job.job_id)
    assert status.state == "running"

    gate.set()
    result = await engine.wait(job.job_id, 5)
    assert result.state == "done"


async def test_engine_run_chunk_rejects_running_task(git_sandbox_feature, noop_probe):
    worktree, _feature_branch, base_path, _index_path = git_sandbox_feature
    gate = asyncio.Event()
    builder = fake_builder_factory({"nova": "block"}, gate=gate)
    engine = SddCoderEngine(
        roster=_roster(("a", "nova"), ("b", "codex"), ("c", "google-compat")),
        probe=noop_probe,
        worktree_base_path=str(base_path),
        dispatcher_builder=builder,
    )
    await engine.run_chunk("demo", str(worktree), ["TASK-0001"])
    with pytest.raises(CoderFailure) as excinfo:
        await engine.run_chunk("demo", str(worktree), ["TASK-0001"])
    assert excinfo.value.code == "task_already_running"
    gate.set()


async def test_engine_run_chunk_rejects_native_task(git_sandbox_feature, noop_probe):
    """A roster with a native seat alongside an mcp seat assigns some tasks
    `native=True`; `run_chunk` must reject dispatching those (they are
    `sdd-worker`'s to run via `coder_prepare_native`, not the engine's)."""
    worktree, _feature_branch, base_path, _index_path = git_sandbox_feature
    builder = fake_builder_factory({})
    mixed = RosterConfig(seats=[RosterSeat(label="a", backend="nova"), RosterSeat(label="h", kind="native")])
    engine = SddCoderEngine(
        roster=mixed, probe=noop_probe, worktree_base_path=str(base_path), dispatcher_builder=builder
    )
    plan = await engine.plan("demo", str(worktree))
    native_ids = [t.task_id for c in plan.chunks for t in c.tasks if t.native]
    assert native_ids
    with pytest.raises(CoderFailure) as excinfo:
        await engine.run_chunk("demo", str(worktree), [native_ids[0]])
    assert excinfo.value.code == "task_not_in_plan"


async def test_plan_then_dispatch_uses_consistent_seat_assignment(git_sandbox_feature, noop_probe):
    """Code-review regression (FEAT-549, CRITICAL): a task's mcp/native classification must be
    IDENTICAL between the `coder_plan()` call the orchestrator loop shows the operator and the
    following `coder_run_chunk`/`coder_prepare_native` call that actually dispatches it.

    `ChunkAssigner.assign()` mutates rotation state (`self._start`) on every call. With a roster
    that mixes one native seat among mcp seats — like the shipped `examples/sdd-coder-mcp.yaml`
    reference roster — and a wave that fills exactly one chunk (net rotation != 0 mod
    len(seats), unlike the 2-seat/3-task shape `test_engine_run_chunk_rejects_native_task` uses,
    where 2 chunks per call cancel out mod 2 and the bug stays invisible), recomputing the plan
    a second time inside `run_chunk`/`prepare_native` used to reclassify a task from native to
    mcp (or vice versa), and `run_chunk`/`prepare_native` would then reject a task the display
    plan had just shown as valid for that call, with `task_not_in_plan`.
    """
    worktree, _feature_branch, base_path, _index_path = git_sandbox_feature
    builder = fake_builder_factory({})
    roster = RosterConfig(
        seats=[
            RosterSeat(label="h", kind="native"),
            RosterSeat(label="a", backend="nova"),
            RosterSeat(label="b", backend="codex"),
        ]
    )
    engine = SddCoderEngine(
        roster=roster, probe=noop_probe, worktree_base_path=str(base_path), dispatcher_builder=builder
    )

    plan = await engine.plan("demo", str(worktree))
    assert len(plan.chunks) == 1
    displayed = {t.task_id: t.native for t in plan.chunks[0].tasks}
    mcp_ids = [tid for tid, native in displayed.items() if not native]
    native_ids = [tid for tid, native in displayed.items() if native]
    assert mcp_ids and native_ids, "the 3-seat mixed roster must classify at least one of each kind"

    # Must NOT raise task_not_in_plan — the fix (SddCoderEngine._cached_plan) guarantees
    # run_chunk/prepare_native reuse the plan just shown, instead of recomputing (and
    # re-rotating) a second time.
    job = await engine.run_chunk("demo", str(worktree), mcp_ids)
    for native_id in native_ids:
        prep = await engine.prepare_native("demo", str(worktree), native_id)
        assert prep.task_id == native_id

    done = await engine.wait(job.job_id, 5)
    assert done.state == "done"
    assert {t.outcome for t in done.tasks} == {"merged"}


async def test_engine_run_chunk_merges_clean_branches(git_sandbox_feature, noop_probe):
    worktree, feature_branch, base_path, _index_path = git_sandbox_feature
    builder = fake_builder_factory({})
    engine = SddCoderEngine(
        roster=_roster(("a", "nova"), ("b", "codex"), ("c", "google-compat")),
        probe=noop_probe,
        worktree_base_path=str(base_path),
        dispatcher_builder=builder,
    )
    job = await engine.run_chunk("demo", str(worktree), ["TASK-0001", "TASK-0002", "TASK-0003"])
    result = await engine.wait(job.job_id, 5)

    assert result.state == "done"
    assert all(t.outcome == "merged" for t in result.tasks)
    _rc, log, _err = await _git("log", "--oneline", feature_branch, cwd=worktree)
    for task_id in ("TASK-0001", "TASK-0002", "TASK-0003"):
        assert f"impl {task_id}" in log

    await engine.cleanup("demo", str(worktree))


async def test_engine_merges_serialised_across_jobs(git_sandbox_feature, noop_probe):
    """Two jobs consolidating concurrently share ONE `asyncio.Lock` around the base
    worktree's `git merge`; both must land cleanly with no corruption."""
    worktree, feature_branch, base_path, _index_path = git_sandbox_feature
    builder = fake_builder_factory({})
    engine = SddCoderEngine(
        roster=_roster(("a", "nova"), ("b", "codex"), ("c", "google-compat")),
        probe=noop_probe,
        worktree_base_path=str(base_path),
        dispatcher_builder=builder,
    )

    job1 = await engine.run_chunk("demo", str(worktree), ["TASK-0001"])
    job2 = await engine.run_chunk("demo", str(worktree), ["TASK-0002"])
    result1, result2 = await asyncio.gather(engine.wait(job1.job_id, 5), engine.wait(job2.job_id, 5))

    assert result1.state == "done" and result2.state == "done"
    assert result1.tasks[0].outcome == "merged"
    assert result2.tasks[0].outcome == "merged"

    _rc, log, _err = await _git("log", "--oneline", feature_branch, cwd=worktree)
    assert "impl TASK-0001" in log and "impl TASK-0002" in log


async def test_telemetry_collector_captures_usage():
    from parrot.flows.dev_loop.sdd_coder.engine import AttemptTelemetryCollector

    collector = AttemptTelemetryCollector(attempt=1, seat=RosterSeat(label="a", backend="nova"))
    action = DispatchCompleted(node_id="development", ts=time.time(), input_tokens=5, output_tokens=7, num_turns=2)
    collector.apply(action)
    record = collector.record()
    assert record.usage["input_tokens"] == 5
    assert record.usage["output_tokens"] == 7
    assert record.usage["num_turns"] == 2
    assert record.duration_s >= 0.0


class TestAttemptIdentity:
    async def test_uid_unique_across_jobs(self, git_sandbox_feature, noop_probe):
        """Test that two _run_task invocations for the same task in different jobs
        both produce attempt=1 and DIFFERENT attempt_uids."""
        worktree, _feature_branch, base_path, _index_path = git_sandbox_feature
        builder = fake_builder_factory({})
        engine = SddCoderEngine(
            roster=_roster(("a", "nova"), ("b", "codex"), ("c", "google-compat")),
            probe=noop_probe,
            worktree_base_path=str(base_path),
            dispatcher_builder=builder,
        )

        # Run the same task twice with different job IDs
        job1 = await engine.run_chunk("demo", str(worktree), ["TASK-0001"])
        result1 = await engine.wait(job1.job_id, 5)

        job2 = await engine.run_chunk("demo", str(worktree), ["TASK-0001"])
        result2 = await engine.wait(job2.job_id, 5)

        # Both should have attempt=1
        assert result1.tasks[0].attempts[0].attempt == 1
        assert result2.tasks[0].attempts[0].attempt == 1

        # But different attempt_uids
        assert result1.tasks[0].attempts[0].attempt_uid != result2.tasks[0].attempts[0].attempt_uid


def _read_jsonl_rows(telemetry_dir: Path, feature_id: str) -> list[dict]:
    """Read every JSONL row the sink wrote for `feature_id`, in file order."""
    path = telemetry_dir / f"{feature_id}.jsonl"
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text("utf-8").splitlines() if line.strip()]


class TestOutcomeEvents:
    async def test_both_attempts_failed(self, git_sandbox_feature, noop_probe, tmp_path):
        """A task failing on both seats writes two attempt rows and two failed outcome rows (AC-19)."""
        worktree, _feature_branch, base_path, _index_path = git_sandbox_feature
        telemetry_dir = tmp_path / "telemetry"
        builder = fake_builder_factory({"nova": "fail", "codex": "fail", "google-compat": "fail"})
        engine = SddCoderEngine(
            roster=_roster(("a", "nova"), ("b", "codex"), ("c", "google-compat")),
            probe=noop_probe,
            worktree_base_path=str(base_path),
            dispatcher_builder=builder,
            telemetry_dir=str(telemetry_dir),
        )
        job = await engine.run_chunk("demo", str(worktree), ["TASK-0001"])
        result = await engine.wait(job.job_id, 5)

        task = result.tasks[0]
        assert task.outcome == "failed"
        assert len(task.attempts) == 2
        assert task.attempts[0].attempt_uid != task.attempts[1].attempt_uid
        # Both attempts should have attempt=1 and attempt=2 respectively
        assert task.attempts[0].attempt == 1
        assert task.attempts[1].attempt == 2

        rows = _read_jsonl_rows(telemetry_dir, "FEAT-549")
        attempt_rows = [r for r in rows if r["kind"] == "attempt"]
        outcome_rows = [r for r in rows if r["kind"] == "outcome"]
        assert len(attempt_rows) == 2
        assert len(outcome_rows) == 2
        assert {r["attempt_uid"] for r in outcome_rows} == {a.attempt_uid for a in task.attempts}
        assert all(r["outcome"] == "failed" for r in outcome_rows)
        assert all(r["task_id"] == "TASK-0001" for r in attempt_rows + outcome_rows)

    async def test_failed_then_merged_per_attempt(self, git_sandbox_feature, noop_probe, tmp_path):
        """attempt 1 failed + attempt 2 merged: EACH attempt gets its own outcome row (AC-19).

        Regression coverage for the bug where `_run_task` only emitted an
        outcome for `attempts[-1]` — attempt 1's failure never got a row at
        all when a retry later succeeded.
        """
        worktree, _feature_branch, base_path, _index_path = git_sandbox_feature
        telemetry_dir = tmp_path / "telemetry"
        builder = fake_builder_factory({"nova": "fail"})  # First seat fails, others succeed
        engine = SddCoderEngine(
            roster=_roster(("a", "nova"), ("b", "codex"), ("c", "google-compat")),
            probe=noop_probe,
            worktree_base_path=str(base_path),
            dispatcher_builder=builder,
            telemetry_dir=str(telemetry_dir),
        )
        job = await engine.run_chunk("demo", str(worktree), ["TASK-0001"])
        result = await engine.wait(job.job_id, 5)

        task = result.tasks[0]
        assert task.outcome == "merged"
        assert len(task.attempts) == 2
        # Each outcome should attach to its own attempt_uid
        assert task.attempts[0].attempt_uid != task.attempts[1].attempt_uid
        assert task.attempts[0].attempt == 1
        assert task.attempts[1].attempt == 2

        rows = _read_jsonl_rows(telemetry_dir, "FEAT-549")
        outcome_rows = [r for r in rows if r["kind"] == "outcome"]
        assert len(outcome_rows) == 2, "attempt 1's failure must get its own outcome row too"
        by_uid = {r["attempt_uid"]: r for r in outcome_rows}
        assert by_uid[task.attempts[0].attempt_uid]["outcome"] == "failed"
        assert by_uid[task.attempts[1].attempt_uid]["outcome"] == "merged"
        # Never attributed to both attempts (never averaged/collapsed)
        assert by_uid[task.attempts[0].attempt_uid]["attempt"] == 1
        assert by_uid[task.attempts[1].attempt_uid]["attempt"] == 2

    async def test_conflict_then_remerge_increments_seq(self, git_sandbox_feature, noop_probe, tmp_path):
        """A merge_conflict followed by a repaired merge() yields two outcome rows
        for ONE attempt_uid with increasing event_seq (AC-19).

        Regression coverage for the bug where `merge()`'s re-emit condition
        (`result.attempts`) was always false — `_consolidate` never sets
        `attempts=` on any `TaskResult` it returns — so the whole re-emit
        path was dead code.
        """
        from parrot.flows.dev_loop.worktree_manager import SubWorktreeMergeError

        worktree, _feature_branch, base_path, _index_path = git_sandbox_feature
        telemetry_dir = tmp_path / "telemetry"
        builder = fake_builder_factory({})  # All succeed
        engine = SddCoderEngine(
            roster=_roster(("a", "nova"), ("b", "codex"), ("c", "google-compat")),
            probe=noop_probe,
            worktree_base_path=str(base_path),
            dispatcher_builder=builder,
            telemetry_dir=str(telemetry_dir),
        )

        # Force the FIRST consolidation (inside run_chunk) to hit the
        # merge_conflict branch, exactly like a real content conflict would,
        # without needing to engineer one at the git level.
        manager = engine._manager_for(await engine._resolve_feature("demo", str(worktree)), "TASK-0001", 1)
        original_merge_sequential = manager.merge_sequential
        calls = {"n": 0}

        async def _flaky_merge_sequential(*args, **kwargs):
            calls["n"] += 1
            if calls["n"] == 1:
                raise SubWorktreeMergeError(
                    "conflict", branch="feat--TASK-0001-a1", worktree_path="x", stderr="CONFLICT (content): x"
                )
            return await original_merge_sequential(*args, **kwargs)

        manager.merge_sequential = _flaky_merge_sequential

        job = await engine.run_chunk("demo", str(worktree), ["TASK-0001"])
        result = await engine.wait(job.job_id, 5)
        task = result.tasks[0]
        assert task.outcome == "merge_conflict"
        attempt_uid = task.attempts[0].attempt_uid

        # A human resolves the conflict; the coder re-runs merge() (the
        # SECOND merge_sequential call succeeds via the real implementation).
        merge_result = await engine.merge("demo", str(worktree), "TASK-0001")
        assert merge_result.task_id == "TASK-0001"
        assert merge_result.outcome == "merged"

        rows = _read_jsonl_rows(telemetry_dir, "FEAT-549")
        outcome_rows = [r for r in rows if r["kind"] == "outcome" and r["attempt_uid"] == attempt_uid]
        assert len(outcome_rows) == 2, "one attempt_uid must get TWO outcome rows across conflict + re-merge"
        outcome_rows.sort(key=lambda r: r["event_seq"])
        assert [r["event_seq"] for r in outcome_rows] == [1, 2]
        assert outcome_rows[0]["outcome"] == "merge_conflict"
        assert outcome_rows[1]["outcome"] == "merged"


class TestDurableRootGuard:
    def test_root_under_worktree_base_raises(self, tmp_path):
        """Test that a telemetry_dir under worktree_base_path raises at engine construction."""
        from parrot.flows.dev_loop.sdd_coder.engine import SddCoderEngine
        from parrot.flows.dev_loop.sdd_coder.models import RosterConfig, RosterSeat

        worktree_base = tmp_path / "worktrees"
        worktree_base.mkdir()
        telemetry_dir = worktree_base / "telemetry"
        telemetry_dir.mkdir()

        roster = RosterConfig(seats=[RosterSeat(label="a", backend="nova")])

        # This should raise a ValueError
        with pytest.raises(ValueError, match="cannot be inside or equal to worktree base path"):
            SddCoderEngine(
                roster=roster,
                worktree_base_path=str(worktree_base),
                telemetry_dir=str(telemetry_dir),
            )
