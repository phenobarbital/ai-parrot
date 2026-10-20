"""Engine-owned task-tier validation gate and same-seat repair (FEAT-709, TASK-4532)."""

from __future__ import annotations

import contextlib
import logging
from pathlib import Path
from types import SimpleNamespace

import pytest

from parrot.flows.dev_loop.sdd_coder import engine as engine_mod
from parrot.flows.dev_loop.sdd_coder.engine import SddCoderEngine
from parrot.flows.dev_loop.sdd_coder.models import RosterConfig, RosterSeat, RunnerConfig
from parrot.flows.dev_loop.test_scope.datatypes import Failure, ValidationVerdict

from .test_engine_dispatch import _git, _roster, fake_builder_factory

EXECUTION_ID = "12345678-1234-4234-8234-123456789abc"


class FakeSupervisor:
    """Stands in for `ValidationSupervisor`: one scripted verdict status per gate run."""

    def __init__(self, statuses: list[str], order: list[str] | None = None) -> None:
        self.statuses = list(statuses)
        self.order = order
        self.starts: list[dict] = []

    async def start(self, **kwargs):
        self.starts.append(kwargs)
        if self.order is not None:
            self.order.append("gate")
        return SimpleNamespace(handle=f"h{len(self.starts)}")

    async def wait_verdict(self, execution_id, handle, timeout_s):
        status = self.statuses.pop(0) if self.statuses else "passed"
        failures = () if status == "passed" else (Failure("pytest", "tests/test_x.py::test_y", "new_red", "boom"),)
        return ValidationVerdict(schema=1, status=status, tier="task", runners=(), failures=failures)


def _engine(base_path: Path, builder, supervisor, *, repair: bool = True, roster: RosterConfig | None = None):
    roster = roster or _roster(("a", "nova"), ("b", "codex"), ("c", "google-compat"))
    roster = roster.model_copy(update={"runners": RunnerConfig(same_seat_repair=repair)})
    engine = SddCoderEngine(
        roster=roster, probe=_noop_probe(), worktree_base_path=str(base_path), dispatcher_builder=builder
    )
    engine._validation_supervisor = supervisor
    # Legacy run_chunk attempts carry no execution; give every branch one so the gate runs.
    engine._execution_for = lambda branch: EXECUTION_ID  # type: ignore[method-assign]
    return engine


def _noop_probe():
    from parrot.flows.dev_loop.sdd_coder.roster import RosterProbe

    return RosterProbe(config_getter=lambda k, fallback=None: "x", which=lambda b: "/usr/bin/" + b, smoke=None)


def _recording_builder():
    """`fake_builder_factory` keeps only the last dispatcher per backend; keep every one."""
    inner = fake_builder_factory({})
    built: list = []

    def _builder(spec, **kwargs):
        dispatcher, profile = inner(spec, **kwargs)
        built.append(dispatcher)
        return dispatcher, profile

    _builder.built = built  # type: ignore[attr-defined]
    return _builder


def _calls(builder) -> list[dict]:
    return [c for d in builder.built for c in d.calls]


async def _run_one(engine, worktree: Path):
    job = await engine.run_chunk("demo", str(worktree), ["TASK-0001"])
    result = await engine.wait(job.job_id, 10)
    return result.tasks[0]


async def test_gate_runs_after_lint_and_banned_imports_before_merge_lock(git_sandbox_feature, monkeypatch):
    worktree, _fb, base_path, _ix = git_sandbox_feature
    order: list[str] = []
    real_lint, real_banned = engine_mod.run_lint_pass, engine_mod.check_banned_imports

    async def _lint(*a, **kw):
        order.append("lint")
        return await real_lint(*a, **kw)

    async def _banned(*a, **kw):
        order.append("banned")
        return await real_banned(*a, **kw)

    monkeypatch.setattr(engine_mod, "run_lint_pass", _lint)
    monkeypatch.setattr(engine_mod, "check_banned_imports", _banned)
    supervisor = FakeSupervisor(["passed"], order)
    engine = _engine(base_path, fake_builder_factory({}), supervisor)
    real_lock = engine._acquire_merge_lock

    @contextlib.asynccontextmanager
    async def _lock(timeout_s=None):
        order.append("lock")
        async with real_lock(timeout_s):
            yield

    engine._acquire_merge_lock = _lock  # type: ignore[method-assign]
    task = await _run_one(engine, worktree)

    assert task.outcome == "merged", task.diagnostics
    consolidate_order = [o for o in order if o in ("lint", "gate", "lock")]
    assert consolidate_order == ["lint", "gate", "lock"]
    assert order.index("banned", order.index("lint")) < order.index("gate")
    start = supervisor.starts[0]
    assert start["tier"] == "task" and start["task_ids"] == ["TASK-0001"]
    assert start["attempt_uid"] == task.attempts[0].attempt_uid
    assert start["base_ref"] and start["worktree"] == Path(task.worktree_path)


async def test_red_gate_without_repair_is_validation_failed_and_nothing_merges(git_sandbox_feature):
    worktree, feature_branch, base_path, _ix = git_sandbox_feature
    engine = _engine(base_path, fake_builder_factory({}), FakeSupervisor(["failed"]), repair=False)
    _rc, before, _ = await _git("rev-parse", feature_branch, cwd=str(worktree))
    task = await _run_one(engine, worktree)
    _rc, after, _ = await _git("rev-parse", feature_branch, cwd=str(worktree))

    assert task.outcome == "validation_failed", task.diagnostics
    assert task.validation is not None and task.validation.status == "failed"
    assert before == after
    assert len(task.attempts) == 1


async def test_red_gate_repairs_on_same_seat_from_failed_branch(git_sandbox_feature):
    worktree, feature_branch, base_path, _ix = git_sandbox_feature
    builder = _recording_builder()
    engine = _engine(base_path, builder, FakeSupervisor(["failed", "passed"]))
    task = await _run_one(engine, worktree)

    assert task.outcome == "merged", task.diagnostics
    assert [a.attempt for a in task.attempts] == [1, 2]
    assert task.attempts[0].seat_label == task.attempts[1].seat_label
    assert task.attempts[0].validation_status == "failed"
    calls = _calls(builder)
    assert len(calls) == 2
    assert calls[0]["brief"].validation_verdict == ""
    assert "test_y" in calls[1]["brief"].validation_verdict
    # Seeded from the red branch: the attempt-1 commit is in the repair branch's history.
    rc, _out, _ = await _git(
        "merge-base", "--is-ancestor", f"{feature_branch}--TASK-0001-a1", "HEAD", cwd=calls[1]["cwd"]
    )
    assert rc == 0


async def test_second_red_joins_retry_ladder_without_suspension(git_sandbox_feature, monkeypatch):
    worktree, _fb, base_path, _ix = git_sandbox_feature
    builder = fake_builder_factory({})
    engine = _engine(base_path, builder, FakeSupervisor(["failed", "failed", "passed"]))
    retry_calls: list[tuple] = []
    suspend_calls: list[dict] = []
    real_select = engine._select_retry_seat

    async def _select(*a, **kw):
        retry_calls.append(a)
        return await real_select(*a, **kw)

    async def _suspend(**kw):
        suspend_calls.append(kw)

    engine._select_retry_seat = _select  # type: ignore[method-assign]
    engine._classify_and_suspend = _suspend  # type: ignore[method-assign]
    task = await _run_one(engine, worktree)

    assert retry_calls, "a second red must consult _select_retry_seat"
    assert not suspend_calls
    assert task.outcome == "merged", task.diagnostics
    assert [a.attempt for a in task.attempts] == [1, 2, 3]
    assert task.attempts[0].seat_label == task.attempts[1].seat_label != task.attempts[2].seat_label
    assert "validation_failed" in task.attempts[1].error


async def test_no_supervisor_merges_with_warning(git_sandbox_feature, caplog):
    worktree, _fb, base_path, _ix = git_sandbox_feature
    engine = _engine(base_path, fake_builder_factory({}), None)
    with caplog.at_level(logging.WARNING):
        task = await _run_one(engine, worktree)
    assert task.outcome == "merged", task.diagnostics
    assert task.validation is None
    assert any("no validation supervisor" in r.getMessage() for r in caplog.records)


async def test_prepare_native_carries_previous_red_verdict(git_sandbox_feature):
    worktree, _fb, base_path, _ix = git_sandbox_feature
    roster = RosterConfig(
        seats=[
            RosterSeat(label="h", kind="native"),
            RosterSeat(label="a", backend="nova", model="model-a"),
            RosterSeat(label="b", backend="codex", model="model-b"),
        ]
    )
    engine = _engine(base_path, fake_builder_factory({}), FakeSupervisor(["failed"]), roster=roster)
    plan = await engine.plan("demo", str(worktree))
    native_id = next(t.task_id for t in plan.chunks[0].tasks if t.native)
    prep = await engine.prepare_native("demo", str(worktree), native_id)
    assert prep.validation_verdict == ""

    n = int(native_id.rsplit("-", 1)[-1])
    (Path(prep.worktree_path) / "pkg" / f"t{n}.py").write_text(f"# {native_id}\n")
    await _git("add", "-A", cwd=prep.worktree_path)
    await _git("commit", "-m", f"impl {native_id}", cwd=prep.worktree_path)
    result = await engine.merge("demo", str(worktree), native_id)
    assert result.outcome == "validation_failed"

    repair = await engine.prepare_native("demo", str(worktree), native_id)
    assert "test_y" in repair.validation_verdict
    assert repair.branch.endswith("-a2")
    assert (Path(repair.worktree_path) / "pkg" / f"t{n}.py").exists()


@pytest.mark.parametrize("tier", ["task"])
async def test_run_validation_task_tier_requires_issued_attempt(git_sandbox_feature, tier):
    from parrot.flows.dev_loop.sdd_coder.engine import CoderFailure

    worktree, _fb, base_path, _ix = git_sandbox_feature
    engine = _engine(base_path, fake_builder_factory({}), FakeSupervisor([]))
    ctx = await engine._resolve_feature("demo", str(worktree))
    with pytest.raises(CoderFailure) as exc:
        await engine._task_tier_scope(ctx, ["TASK-0001"], EXECUTION_ID, "unknown-uid", None)
    assert exc.value.code == "validation_scope_invalid"
    engine._branch_attempts["some-branch"] = ("uid-1", EXECUTION_ID, "/abs/path", 1)
    path, base_ref = await engine._task_tier_scope(ctx, ["TASK-0001"], EXECUTION_ID, "uid-1", "abc123")
    assert (path, base_ref) == ("/abs/path", "abc123")
