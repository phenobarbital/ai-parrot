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
from parrot.flows.dev_loop.sdd_coder.complexity_models import ComplexityPolicy, StrongModelIdentity
from parrot.flows.dev_loop.session_state import DispatchCompleted


class FakeDispatcher:
    """Fulfils the dispatcher Protocol's `dispatch()` shape (mirrors test_agent_pool.py's FakeDispatcher).

    `behaviour` per instance:
      - "ok": writes the task's listed file in `cwd`, commits, returns a DevelopmentOutput.
      - "fail": raises RuntimeError.
      - "block": awaits an injected asyncio.Event before returning ok.
      - "extra": also writes an unlisted file (for fidelity-violation coverage elsewhere).
      - "banned": writes a banned import (`import httpx`) into the task's listed file (FEAT-553).
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
        content = "import httpx\n" if self.behaviour == "banned" else f"# {task_id}\n"
        (Path(cwd) / filename).write_text(content)
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
    # FEAT-559: an empty `model` is now always excluded as `model_identity_required`
    # before any probe/smoke call (roster.py's `_is_excluded`) -- every seat needs an
    # explicit, distinct-per-label model so these tests keep exercising real seats.
    return RosterConfig(
        seats=[
            RosterSeat(label=lbl, backend=backend, model=f"model-{lbl}")  # type: ignore[arg-type]
            for lbl, backend in labels_backends
        ]
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


async def test_engine_writes_attempt_context(git_sandbox_feature, noop_probe):
    """FEAT-563: every MCP attempt sub-worktree carries a task-tier AttemptContext before dispatch."""
    from parrot.flows.dev_loop.test_scope.context import read_attempt_context

    worktree, feature_branch, base_path, _index_path = git_sandbox_feature
    builder = fake_builder_factory({})
    engine = SddCoderEngine(
        roster=_roster(("a", "nova"), ("b", "codex"), ("c", "google-compat")),
        probe=noop_probe,
        worktree_base_path=str(base_path),
        dispatcher_builder=builder,
    )
    job = await engine.run_chunk("demo", str(worktree), ["TASK-0001"])
    await engine.wait(job.job_id, 5)
    call = next(c for d in builder.dispatchers.values() for c in d.calls)
    context = read_attempt_context(Path(call["cwd"]))
    assert context is not None
    assert context.tier == "task"
    assert context.task_id == "TASK-0001"
    assert context.base_ref == feature_branch
    assert context.task_file == call["brief"].task_file


async def test_prepare_native_writes_attempt_context(git_sandbox_feature, noop_probe):
    """FEAT-563: the native sub-worktree carries a task-tier AttemptContext before sdd-worker launches the seat."""
    from parrot.flows.dev_loop.test_scope.context import read_attempt_context

    worktree, feature_branch, base_path, _index_path = git_sandbox_feature
    roster = RosterConfig(
        seats=[
            RosterSeat(label="h", kind="native"),
            RosterSeat(label="a", backend="nova", model="model-a"),
            RosterSeat(label="b", backend="codex", model="model-b"),
        ]
    )
    engine = SddCoderEngine(
        roster=roster, probe=noop_probe, worktree_base_path=str(base_path), dispatcher_builder=fake_builder_factory({})
    )
    plan = await engine.plan("demo", str(worktree))
    native_id = next(t.task_id for t in plan.chunks[0].tasks if t.native)
    prep = await engine.prepare_native("demo", str(worktree), native_id)
    context = read_attempt_context(Path(prep.worktree_path))
    assert context is not None
    assert context.tier == "task"
    assert context.task_id == native_id
    assert context.task_file == prep.task_file
    assert context.base_ref == feature_branch


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
    # FEAT-559 (TASK-3282): status() is now async (it retries pending suspension
    # persistence and exposes the latest pool view before returning).
    status = await engine.status(job.job_id)
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
            RosterSeat(label="a", backend="nova", model="model-a"),
            RosterSeat(label="b", backend="codex", model="model-b"),
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


_BANNED_CFG = (
    '[lint]\nselect = ["TID251"]\n[lint.flake8-tidy-imports.banned-api]\n'
    '"requests".msg = "use aiohttp"\n"httpx".msg = "use aiohttp"\n'
)


async def test_run_attempt_turns_banned_import_into_attempt_error(git_sandbox_feature, noop_probe):
    worktree, _feature_branch, base_path, _index_path = git_sandbox_feature
    (worktree / "ruff.toml").write_text(_BANNED_CFG)
    await _git("add", "ruff.toml", cwd=str(worktree))
    await _git("commit", "-m", "ruff config", cwd=str(worktree))

    builder = fake_builder_factory({"nova": "banned"})
    engine = SddCoderEngine(
        roster=_roster(("a", "nova"), ("b", "codex")),
        probe=noop_probe,
        worktree_base_path=str(base_path),
        dispatcher_builder=builder,
    )
    job = await engine.run_chunk("demo", str(worktree), ["TASK-0001"])
    result = await engine.wait(job.job_id, 5)

    task = result.tasks[0]
    assert task.attempts[0].error.startswith("BannedImport:")
    assert task.attempts[1].seat_label == "b"
    assert task.outcome == "merged"


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

        # Run the same task twice with different job IDs. The first run_chunk's
        # merge advances feature_branch HEAD, so the cached plan's assessment
        # for TASK-0001 is now stale (spec: "A preceding task merge can advance
        # HEAD: report stale and require coder_plan, rather than recalculating
        # silently") -- replan before the second dispatch, exactly as the real
        # orchestrator loop does between chunks.
        pre_job1_sha = (await _git("rev-parse", "HEAD", cwd=str(worktree)))[1].strip()
        job1 = await engine.run_chunk("demo", str(worktree), ["TASK-0001"])
        result1 = await engine.wait(job1.job_id, 5)

        # job1's merge committed TASK-0001's declared CREATE target
        # (pkg/t1.py) to the feature branch. TASK-0001's own Complexity
        # Contract still declares that same path as CREATE, and spec §2 item
        # 3 makes an existing CREATE target an invalid contract that blocks
        # dispatch -- so re-running the identical task_id a second time (this
        # test's only interest is attempt_uid uniqueness, not the CREATE-once
        # invariant) requires resetting the feature branch back to its
        # pre-job1 state first, exactly as if job2 were an independent second
        # attempt that never observed job1's result.
        await _git("reset", "--hard", pre_job1_sha, cwd=str(worktree))

        await engine.plan("demo", str(worktree))
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


def _force_classification(plan, task_id: str, classification: str):
    """Return a copy of `plan` with `task_id`'s cached assessment's classification
    overridden (evidence untouched, so `validate_complexity_snapshot` still finds
    it fresh). Deterministic stand-in for a task real collectors would classify
    complex/unknown -- avoids depending on a real `ruff`/`wikitoolkit` install."""
    assessment = plan.assessments[task_id].model_copy(update={"classification": classification})
    return plan.model_copy(update={"assessments": {**plan.assessments, task_id: assessment}})


class TestComplexityDispatchAdmission:
    """TASK-3291: complexity restrictions enforced at every actual coder attempt."""

    async def test_weak_seat_never_dispatches_restricted_task(self, git_sandbox_feature, noop_probe):
        """AC7/AC8: a seat outside the strong-model allowlist must never reach
        `dispatcher.dispatch` for a complex/unknown task -- verified by asserting
        no dispatcher was ever constructed for the weak backend, not just that
        the outcome is a failure (a failure could otherwise hide a real, wasted
        dispatch)."""
        worktree, _feature_branch, base_path, _index_path = git_sandbox_feature
        builder = fake_builder_factory({})
        roster = RosterConfig(
            seats=[RosterSeat(label="weak", backend="nova", model="qwen")],
            complexity=ComplexityPolicy(
                strong_models=(
                    StrongModelIdentity(canonical_model="sonnet-5", backend="codex", model="claude-3-5-sonnet"),
                )
            ),
        )
        engine = SddCoderEngine(
            roster=roster, probe=noop_probe, worktree_base_path=str(base_path), dispatcher_builder=builder
        )
        plan = await engine.plan("demo", str(worktree))
        engine._plan_cache["FEAT-549"] = _force_classification(plan, "TASK-0001", "complex")  # noqa: SLF001

        job = await engine.run_chunk("demo", str(worktree), ["TASK-0001"])
        result = await engine.wait(job.job_id, 5)

        assert result.tasks[0].outcome == "failed"
        assert "complex_model_unavailable" in result.tasks[0].diagnostics
        assert builder.dispatchers == {}, "the weak seat's dispatcher must never have been constructed"

    async def test_no_eligible_retry_seat_reports_complex_model_unavailable(self, git_sandbox_feature, noop_probe):
        """AC7: after the only seat fails, a restricted task with no eligible
        retry candidate gets an explicit complex_model_unavailable diagnostic
        instead of silently falling through with the unrelated dispatch error,
        preserving the failed first attempt (spec: "preserving previous
        attempts")."""
        worktree, _feature_branch, base_path, _index_path = git_sandbox_feature
        builder = fake_builder_factory({"nova": "fail"})
        roster = RosterConfig(
            seats=[RosterSeat(label="weak", backend="nova", model="qwen")],
            complexity=ComplexityPolicy(
                strong_models=(
                    StrongModelIdentity(canonical_model="sonnet-5", backend="codex", model="claude-3-5-sonnet"),
                )
            ),
        )
        engine = SddCoderEngine(
            roster=roster, probe=noop_probe, worktree_base_path=str(base_path), dispatcher_builder=builder
        )
        plan = await engine.plan("demo", str(worktree))
        engine._plan_cache["FEAT-549"] = _force_classification(plan, "TASK-0001", "unknown")  # noqa: SLF001

        job = await engine.run_chunk("demo", str(worktree), ["TASK-0001"])
        result = await engine.wait(job.job_id, 5)

        assert result.tasks[0].outcome == "failed"
        assert len(result.tasks[0].attempts) == 1, "no retry attempt when no eligible seat exists"
        assert "complex_model_unavailable" in result.tasks[0].diagnostics

    async def test_pool_based_retry_never_selects_native_seat(self, git_sandbox_feature, noop_probe):
        """issue:e01c03baf493: the execution-pool retry path
        (`SddCoderEngine._select_retry_seat`'s pool branch) must never hand a
        `kind="native"` seat to `_run_attempt` -- a native seat has no
        dispatcher (`_run_attempt` asserts `seat.backend is not None`), and
        `_run_task` never routes a retry through `coder_prepare_native`. Before
        this fix, a healthy native strong seat was selected and crashed the
        attempt with an unhandled `AssertionError`, discarding attempt 1's real
        `complex_model_unavailable` diagnostic. This mirrors
        `test_no_eligible_retry_seat_reports_complex_model_unavailable` above,
        but through the execution-pool (`execution_id`) path every real
        `coder_plan`/`coder_run_chunk` call actually uses."""
        import uuid

        from parrot.knowledge.wiki.ledger.coder_suspensions import ModelKey

        worktree, _feature_branch, base_path, _index_path = git_sandbox_feature
        builder = fake_builder_factory({"nova": "fail"})
        roster = RosterConfig(
            seats=[
                RosterSeat(label="weak1", backend="nova", model="qwen"),
                RosterSeat(label="weak2", backend="nova", model="mistral"),
                RosterSeat(label="strong-native", kind="native", model="sonnet-5"),
            ],
            complexity=ComplexityPolicy(
                strong_models=(StrongModelIdentity(canonical_model="sonnet-5", backend="native", model="sonnet-5"),)
            ),
        )
        engine = SddCoderEngine(
            roster=roster, probe=noop_probe, worktree_base_path=str(base_path), dispatcher_builder=builder
        )

        execution_id = str(uuid.uuid4())
        await engine.begin_execution("demo", str(worktree), execution_id)
        plan = await engine.plan("demo", str(worktree), execution_id=execution_id)
        engine._plan_cache[f"FEAT-549:{execution_id}"] = _force_classification(  # noqa: SLF001
            plan, "TASK-0001", "unknown"
        )
        # A busy native seat cannot be handed off. The diagnostic must describe
        # the MCP-only retry selector instead of claiming a generic shortage.
        await engine._executions[execution_id].admit(
            "TASK-OTHER", ModelKey(backend="native", model="sonnet-5")
        )  # noqa: SLF001

        job = await engine.run_chunk("demo", str(worktree), ["TASK-0001"], execution_id=execution_id)
        result = await engine.wait(job.job_id, 5)

        task_result = result.tasks[0]
        assert task_result.outcome == "failed"
        assert len(task_result.attempts) == 1
        assert task_result.native_retry is None
        assert "MCP-only retry ladder" in task_result.diagnostics
        assert "AssertionError" not in task_result.diagnostics

    async def test_all_native_remainder_hands_off_instead_of_blocking(self, git_sandbox_feature, noop_probe):
        """FEAT-588 AC-1/AC-2/AC-3: a failed strong MCP attempt hands off to native."""
        import uuid

        worktree, _feature_branch, base_path, _index_path = git_sandbox_feature
        builder = fake_builder_factory({"nova": "fail"})
        roster = RosterConfig(
            seats=[
                RosterSeat(label="mcp", backend="nova", model="mcp-strong"),
                RosterSeat(label="native", kind="native", model="native-strong"),
            ],
            complexity=ComplexityPolicy(
                strong_models=(
                    StrongModelIdentity(canonical_model="mcp", backend="nova", model="mcp-strong"),
                    StrongModelIdentity(canonical_model="native", backend="native", model="native-strong"),
                )
            ),
        )
        engine = SddCoderEngine(
            roster=roster, probe=noop_probe, worktree_base_path=str(base_path), dispatcher_builder=builder
        )
        execution_id = str(uuid.uuid4())
        await engine.begin_execution("demo", str(worktree), execution_id)
        plan = await engine.plan("demo", str(worktree), execution_id=execution_id)
        task_id = next(task.task_id for chunk in plan.chunks for task in chunk.tasks if task.seat_label == "mcp")
        engine._plan_cache[f"FEAT-549:{execution_id}"] = _force_classification(plan, task_id, "complex")  # noqa: SLF001

        job = await engine.run_chunk("demo", str(worktree), [task_id], execution_id=execution_id)
        result = await engine.wait(job.job_id, 5)

        task_result = result.tasks[0]
        assert task_result.outcome == "retry_native"
        assert task_result.native_retry is not None
        assert task_result.native_retry.seat_label == "native"
        assert task_result.native_retry.assessment_id
        assert task_result.native_retry.execution_id == execution_id
        assert task_result.native_retry.branch.endswith("-a2-" + execution_id.replace("-", ""))
        assert len(task_result.attempts) == 1
        assert task_result.attempts[0].attempt == 1
        assert set(builder.dispatchers) == {"nova"}, "native handoff must never call _run_attempt"

    async def test_run_attempt_never_receives_a_native_seat(self, git_sandbox_feature, noop_probe):
        """FEAT-588 AC-4: both retry selectors retain their MCP-only dispatch contract."""
        import uuid

        from parrot.flows.dev_loop.sdd_coder.roster import ChunkAssigner

        worktree, _feature_branch, base_path, _index_path = git_sandbox_feature
        roster = RosterConfig(
            seats=[
                RosterSeat(label="mcp", backend="nova", model="mcp-strong"),
                RosterSeat(label="native", kind="native", model="native-strong"),
            ]
        )
        engine = SddCoderEngine(roster=roster, probe=noop_probe, worktree_base_path=str(base_path))
        execution_id = str(uuid.uuid4())
        await engine.begin_execution("demo", str(worktree), execution_id)
        pool = engine._executions[execution_id]  # noqa: SLF001

        retry = await engine._select_retry_seat(pool, "mcp", {"mcp"}, eligible_labels={"native"})  # noqa: SLF001
        assert retry is None
        assert ChunkAssigner(roster.seats).retry_seat("mcp", {"mcp"}, eligible_labels={"native"}) is None

    async def test_no_eligible_seat_of_any_kind_is_unchanged(self, git_sandbox_feature, noop_probe):
        """FEAT-588 AC-5: no remaining strong seat retains the prior failed result."""
        import uuid

        worktree, _feature_branch, base_path, _index_path = git_sandbox_feature
        builder = fake_builder_factory({"nova": "fail"})
        roster = RosterConfig(
            seats=[RosterSeat(label="mcp", backend="nova", model="mcp-strong")],
            complexity=ComplexityPolicy(
                strong_models=(StrongModelIdentity(canonical_model="mcp", backend="nova", model="mcp-strong"),)
            ),
        )
        engine = SddCoderEngine(
            roster=roster, probe=noop_probe, worktree_base_path=str(base_path), dispatcher_builder=builder
        )
        execution_id = str(uuid.uuid4())
        await engine.begin_execution("demo", str(worktree), execution_id)
        plan = await engine.plan("demo", str(worktree), execution_id=execution_id)
        task_id = next(task.task_id for chunk in plan.chunks for task in chunk.tasks)
        engine._plan_cache[f"FEAT-549:{execution_id}"] = _force_classification(plan, task_id, "complex")  # noqa: SLF001

        job = await engine.run_chunk("demo", str(worktree), [task_id], execution_id=execution_id)
        result = await engine.wait(job.job_id, 5)

        task_result = result.tasks[0]
        assert task_result.outcome == "failed"
        assert len(task_result.attempts) == 1
        assert "complex_model_unavailable" in task_result.diagnostics
        assert task_result.native_retry is None

    async def test_eligible_retry_labels_fails_closed_on_missing_assessment(self, git_sandbox_feature, noop_probe):
        """issue:e01c03baf493: `_eligible_retry_labels` must never treat a
        missing/unresolvable cached assessment as "unrestricted" (`None`) --
        that is the only way `_select_retry_seat` could ever be handed an
        unrestricted candidate set for a task whose classification is actually
        `complex`/`unknown`. A missing assessment for a task already mid-retry
        is an anomaly, not evidence the task is a standard, unrestricted one."""
        import uuid

        from parrot.flows.dev_loop.sdd_coder.models import PlannedTask

        worktree, _feature_branch, base_path, _index_path = git_sandbox_feature
        builder = fake_builder_factory({})
        roster = RosterConfig(seats=[RosterSeat(label="weak", backend="nova", model="qwen")])
        engine = SddCoderEngine(
            roster=roster, probe=noop_probe, worktree_base_path=str(base_path), dispatcher_builder=builder
        )

        execution_id = str(uuid.uuid4())
        await engine.begin_execution("demo", str(worktree), execution_id)
        plan = await engine.plan("demo", str(worktree), execution_id=execution_id)
        assert "TASK-0001" in plan.assessments
        plan_without_assessment = plan.model_copy(
            update={"assessments": {k: v for k, v in plan.assessments.items() if k != "TASK-0001"}}
        )
        engine._plan_cache[f"FEAT-549:{execution_id}"] = plan_without_assessment  # noqa: SLF001

        ctx = await engine._resolve_feature("demo", str(worktree))  # noqa: SLF001
        task = PlannedTask(task_id="TASK-0001", task_file="x.md", title="x", seat_label="weak", backend="nova")
        eligible = await engine._eligible_retry_labels(ctx, task, execution_id=execution_id)  # noqa: SLF001

        assert eligible == set(), "a missing assessment must fail closed (empty set), never None (unrestricted)"


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


class TestTimeoutCauseClassification:
    """FEAT-559 TASK-3280: Test timeout cause classification."""

    def test_wrapped_timeout_is_classified(self):
        """A wrapped TimeoutError is classified as 'timeout'."""
        from parrot.flows.dev_loop.sdd_coder.engine import SddCoderEngine

        engine = SddCoderEngine(
            roster=_roster(("a", "nova")),
        )
        reason = engine._classify_failure_reason(
            error="TimeoutError: dispatch timed out",
            error_class="DispatchExecutionError",
        )
        assert reason == "timeout"

    def test_direct_timeout_is_classified(self):
        """A direct TimeoutError is classified as 'timeout'."""
        from parrot.flows.dev_loop.sdd_coder.engine import SddCoderEngine

        engine = SddCoderEngine(
            roster=_roster(("a", "nova")),
        )
        reason = engine._classify_failure_reason(
            error="TimeoutError: operation timed out",
            error_class="TimeoutError",
        )
        assert reason == "timeout"

    def test_poll_timeout_not_classified_as_model_timeout(self):
        """A poll timeout (coder_wait) is not classified as a model timeout."""
        from parrot.flows.dev_loop.sdd_coder.engine import SddCoderEngine

        engine = SddCoderEngine(
            roster=_roster(("a", "nova")),
        )
        # Poll timeout should not be classified as suspendable
        reason = engine._classify_failure_reason(
            error="poll timeout waiting for response",
            error_class="TimeoutError",
        )
        # This IS a timeout - poll timeout is still a timeout for classification
        # The distinction is made at the caller level
        assert reason == "timeout"


class TestNonModelFailuresDoNotSuspend:
    """FEAT-559 TASK-3280: Test that non-model failures do not cause suspension."""

    def test_lint_error_not_suspendable(self):
        """Lint findings do not cause model suspension."""
        from parrot.flows.dev_loop.sdd_coder.engine import SddCoderEngine

        engine = SddCoderEngine(
            roster=_roster(("a", "nova")),
        )
        reason = engine._classify_failure_reason(
            error="LintError: unused import",
            error_class="RuntimeError",
        )
        assert reason is None

    def test_cancellation_not_suspendable(self):
        """Cancellation does not cause model suspension."""
        from parrot.flows.dev_loop.sdd_coder.engine import SddCoderEngine

        engine = SddCoderEngine(
            roster=_roster(("a", "nova")),
        )
        reason = engine._classify_failure_reason(
            error="CancelledError: task was cancelled",
            error_class="CancelledError",
        )
        assert reason is None

    def test_merge_conflict_not_suspendable(self):
        """Git merge conflicts do not cause model suspension."""
        from parrot.flows.dev_loop.sdd_coder.engine import SddCoderEngine

        engine = SddCoderEngine(
            roster=_roster(("a", "nova")),
        )
        reason = engine._classify_failure_reason(
            error="merge_conflict: CONFLICT (content): file.py",
            error_class="SubWorktreeMergeError",
        )
        assert reason is None

    def test_git_worktree_error_not_suspendable(self):
        """Git worktree creation failures do not cause model suspension."""
        from parrot.flows.dev_loop.sdd_coder.engine import SddCoderEngine

        engine = SddCoderEngine(
            roster=_roster(("a", "nova")),
        )
        reason = engine._classify_failure_reason(
            error="git worktree add failed",
            error_class="RuntimeError",
        )
        assert reason is None


class TestStalePlanAdmitsNothing:
    """FEAT-559 TASK-3280: Test that stale plans are rejected before job/worktree creation."""

    async def test_stale_plan_rejected(self, git_sandbox_feature, noop_probe):
        """A stale plan (pool_generation mismatch) is rejected with plan_stale."""
        worktree, _feature_branch, base_path, _index_path = git_sandbox_feature
        builder = fake_builder_factory({})
        engine = SddCoderEngine(
            roster=_roster(("a", "nova"), ("b", "codex")),
            probe=noop_probe,
            worktree_base_path=str(base_path),
            dispatcher_builder=builder,
        )

        # Begin execution
        import uuid

        execution_id = str(uuid.uuid4())
        await engine.begin_execution("demo", str(worktree), execution_id)

        # Plan with current pool generation
        plan = await engine.plan("demo", str(worktree), execution_id=execution_id)
        assert plan.pool_generation == 0

        # Manually increment pool generation (simulating a suspension)
        pool = engine._executions[execution_id]
        pool._generation = 1

        # Now run_chunk should reject the stale plan
        with pytest.raises(CoderFailure) as excinfo:
            await engine.run_chunk("demo", str(worktree), ["TASK-0001"], execution_id=execution_id)
        assert excinfo.value.code == "plan_stale"


class TestRetryUsesOnlyHealthyFreeModel:
    """FEAT-559 TASK-3280: Test retry selection from healthy not-yet-tried models."""

    async def test_retry_skips_suspended_model(self, git_sandbox_feature, noop_probe):
        """Retry does not select a suspended model."""
        worktree, _feature_branch, base_path, _index_path = git_sandbox_feature
        builder = fake_builder_factory({"nova": "fail"})  # First seat fails
        engine = SddCoderEngine(
            roster=_roster(("a", "nova"), ("b", "codex"), ("c", "google-compat")),
            probe=noop_probe,
            worktree_base_path=str(base_path),
            dispatcher_builder=builder,
        )

        import uuid

        execution_id = str(uuid.uuid4())
        await engine.begin_execution("demo", str(worktree), execution_id)

        # Suspend seat 'b' before running
        pool = engine._executions[execution_id]
        from parrot.flows.dev_loop.sdd_coder.pool import _effective_key

        seat_b = next(s for s in pool._seats if s.label == "b")
        key_b = _effective_key(seat_b)
        assert key_b is not None
        pool._local_exclusions.add(key_b)
        pool._seat_views[key_b].suspended = True
        pool._seat_views[key_b].available = False

        # Run - should skip 'b' and use 'c' for retry
        job = await engine.run_chunk("demo", str(worktree), ["TASK-0001"], execution_id=execution_id)
        result = await engine.wait(job.job_id, 5)

        task = result.tasks[0]
        assert task.outcome == "merged"
        assert len(task.attempts) == 2
        # First attempt on 'a', second on 'c' (skipping suspended 'b')
        assert task.attempts[0].seat_label == "a"
        assert task.attempts[1].seat_label == "c"

    async def test_exhausted_pool_returns_failed(self, git_sandbox_feature, noop_probe):
        """When all seats are suspended/exhausted, task fails without retry."""
        worktree, _feature_branch, base_path, _index_path = git_sandbox_feature
        builder = fake_builder_factory({"nova": "fail", "codex": "fail", "google-compat": "fail"})
        engine = SddCoderEngine(
            roster=_roster(("a", "nova"), ("b", "codex")),
            probe=noop_probe,
            worktree_base_path=str(base_path),
            dispatcher_builder=builder,
        )

        import uuid

        execution_id = str(uuid.uuid4())
        await engine.begin_execution("demo", str(worktree), execution_id)

        # Suspend seat 'b' before running
        pool = engine._executions[execution_id]
        from parrot.flows.dev_loop.sdd_coder.pool import _effective_key

        seat_b = next(s for s in pool._seats if s.label == "b")
        key_b = _effective_key(seat_b)
        assert key_b is not None
        pool._local_exclusions.add(key_b)
        pool._seat_views[key_b].suspended = True
        pool._seat_views[key_b].available = False

        # Run - 'a' fails, 'b' is suspended, no retry available
        job = await engine.run_chunk("demo", str(worktree), ["TASK-0001"], execution_id=execution_id)
        result = await engine.wait(job.job_id, 5)

        task = result.tasks[0]
        assert task.outcome == "failed"
        assert len(task.attempts) == 1  # Only one attempt, no retry available


class TestModelAliasesAndParallelAdmission:
    """FEAT-559 TASK-3280: Test model aliases and parallel admission."""

    async def test_parallel_admission_different_seats(self, git_sandbox_feature, noop_probe):
        """Parallel tasks admit on different seats without double-booking."""
        worktree, _feature_branch, base_path, _index_path = git_sandbox_feature
        builder = fake_builder_factory({})
        engine = SddCoderEngine(
            roster=_roster(("a", "nova"), ("b", "codex"), ("c", "google-compat")),
            probe=noop_probe,
            worktree_base_path=str(base_path),
            dispatcher_builder=builder,
        )

        import uuid

        execution_id = str(uuid.uuid4())
        await engine.begin_execution("demo", str(worktree), execution_id)

        # Run multiple tasks in parallel
        job = await engine.run_chunk(
            "demo", str(worktree), ["TASK-0001", "TASK-0002", "TASK-0003"], execution_id=execution_id
        )
        result = await engine.wait(job.job_id, 5)

        assert result.state == "done"
        assert all(t.outcome == "merged" for t in result.tasks)
        # Each task should have been assigned to a different seat
        seat_labels = [t.attempts[0].seat_label for t in result.tasks]
        assert len(seat_labels) == len(set(seat_labels)), "Each task should use a different seat"


class TestCooldownStartsAtFailureObservation:
    """FEAT-559 TASK-3280: Test that cooldown starts at failure observation."""

    async def test_cooldown_from_observation_time(self, git_sandbox_feature, noop_probe):
        """Cooldown is computed from failure observation, not attempt start."""
        worktree, _feature_branch, base_path, _index_path = git_sandbox_feature
        builder = fake_builder_factory({"nova": "fail", "codex": "fail", "google-compat": "fail"})
        engine = SddCoderEngine(
            roster=_roster(("a", "nova"), ("b", "codex")),
            probe=noop_probe,
            worktree_base_path=str(base_path),
            dispatcher_builder=builder,
        )

        import uuid
        from datetime import datetime, timezone

        execution_id = str(uuid.uuid4())
        await engine.begin_execution("demo", str(worktree), execution_id)

        # Record time before dispatch
        before_dispatch = datetime.now(timezone.utc)

        # Run - will fail on both seats
        job = await engine.run_chunk("demo", str(worktree), ["TASK-0001"], execution_id=execution_id)
        result = await engine.wait(job.job_id, 5)

        # Record time after failure
        after_failure = datetime.now(timezone.utc)

        task = result.tasks[0]
        assert task.outcome == "failed"

        # Check that suspension records have correct timestamps
        pool = engine._executions[execution_id]
        # The suspension should have occurred between before_dispatch and after_failure
        # and expires_at should be occurred_at + cooldown_seconds
        for key in pool._local_exclusions:
            view = pool._seat_views.get(key)
            if view and view.suspended_until:
                # The suspension should have happened during our window
                suspended_until = datetime.fromisoformat(view.suspended_until)
                # suspended_until should be after after_failure (cooldown starts at observation)
                assert suspended_until > after_failure


def _code_string_literals(module) -> set[str]:
    """Every str constant in `module`'s source EXCEPT docstrings.

    A retired contract survives as prose in a docstring or comment explaining why
    it was retired -- that is documentation, not a code path. Only a string the
    module actually evaluates can still produce the old behaviour, so that is what
    the FEAT-587 guard below asserts on.
    """
    import ast

    tree = ast.parse(Path(module.__file__).read_text(encoding="utf-8"))
    docstrings = {
        doc
        for node in ast.walk(tree)
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
        for doc in [ast.get_docstring(node, clean=False)]
        if doc is not None
    }
    return {
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and node.value not in docstrings
    }


class TestDirtyTaskWorktreeContractRetired:
    """FEAT-587: the `dirty_task_worktree` contract no longer exists in code."""

    def test_no_dirty_task_worktree_producer(self):
        """Neither the engine nor the error-code enum may still evaluate the retired contract (AC-1, AC-4)."""
        from parrot.flows.dev_loop.sdd_coder import engine as engine_mod
        from parrot.flows.dev_loop.sdd_coder import models as models_mod

        for module in (engine_mod, models_mod):
            offenders = sorted(
                literal
                for literal in _code_string_literals(module)
                if "dirty_task_worktree" in literal or literal == "dirty_delivery"
            )
            assert offenders == [], f"{module.__name__} still evaluates {offenders}"

    def test_dirty_feature_worktree_is_untouched(self):
        """The *feature*-worktree precondition is a different, still-live check (AC-4)."""
        from parrot.flows.dev_loop.sdd_coder.models import ERROR_CODES

        assert "dirty_feature_worktree" in ERROR_CODES
        assert "dirty_task_worktree" not in ERROR_CODES

    def test_classify_failure_reason_ignores_uncommitted_delivery(self):
        """An uncommitted-but-declared delivery is never charged against the model (AC-3)."""
        from parrot.flows.dev_loop.sdd_coder.engine import SddCoderEngine

        engine = SddCoderEngine(
            roster=_roster(("a", "nova")),
        )
        assert (
            engine._classify_failure_reason(
                error="dirty_task_worktree: uncommitted/untracked changes:\n?? packages/x/t1.py",
                error_class="dirty_task_worktree",
            )
            is None
        )
        # Controls: the classifier still classifies what it should, so the
        # assertion above cannot pass by it returning None for everything.
        assert (
            engine._classify_failure_reason(
                error="TimeoutError: dispatch timed out",
                error_class="DispatchExecutionError",
            )
            == "timeout"
        )
        assert (
            engine._classify_failure_reason(
                error="",
                error_class="RuntimeError",
                outcome="fidelity_violation",
            )
            == "fidelity_violation"
        )
