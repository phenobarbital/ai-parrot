"""Fake-dispatcher tests for SddCoderEngine's dispatch/retry side (TASK-3121)."""
from __future__ import annotations

import asyncio
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
    return RosterConfig(seats=[RosterSeat(label=lbl, backend=backend) for lbl, backend in labels_backends])


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
