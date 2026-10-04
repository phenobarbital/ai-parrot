"""Merge-tier validation scope and the blocking background wait; isolated fixtures, never live providers.

Two regressions are covered here.

1. A merge-tier validation used to plan its selection from `origin/dev...HEAD`
   -- the feature branch's WHOLE cumulative diff -- so every merge re-validated
   every task merged before it. Past a few dozen changed files the impact cap
   and the core-path list escalate whole package suites, and the "changed
   scope" check degenerates into a serial monorepo-wide sweep.
   `SddCoderEngine._merge_scope_base` now resolves the fork point of the merged
   tasks' own attempt branches instead, falling back to the cumulative base
   (slower, never less covered) when it cannot.

2. A `coder_run_validation` handle raises no host task notification, and
   `bg_status` is non-blocking by contract, so a caller had no sanctioned way
   to wait for one. `SddCoderEngine.bg_wait` is that missing primitive.

`ValidationSupervisor.start()` is spec-mandatory in its use of
`worktree_environment.protected_argv` (bwrap sandboxing). This module's dev/CI
shell already runs nested inside its own Bubblewrap sandbox, where a SECOND,
nested `bwrap` cannot create the namespaces it needs, independent of anything
under test here (the same constraint `test_background_validation.py` and
`test_background_mcp.py` document). Every scenario that admits a validation
therefore monkeypatches `background_module.protected_argv` to an identity
pass-through so the *synthetic* child process -- a real `python -c ...`
subprocess with precisely controlled timing -- runs directly.
"""

from __future__ import annotations

import asyncio
import sys
import time
import uuid
from pathlib import Path
from typing import Optional

import pytest

from parrot.flows.dev_loop.sdd_coder import background as background_module
from parrot.flows.dev_loop.sdd_coder.engine import CoderFailure, SddCoderEngine
from parrot.flows.dev_loop.sdd_coder.toolkit import SddCoderToolkit
from parrot.flows.dev_loop.test_scope.datatypes import PytestInvocation, ScopePlan
from parrot.flows.dev_loop.test_scope.select import changed_files

FEATURE = "demo"


async def _git(*args: str, cwd: Path) -> str:
    proc = await asyncio.create_subprocess_exec(
        "git", *args, cwd=str(cwd), stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    out, err = await proc.communicate()
    assert proc.returncode == 0, f"git {' '.join(args)} failed in {cwd}: {err.decode()}\n{out.decode()}"
    return out.decode()


async def _commit(repo: Path, filename: str, content: str, message: str) -> None:
    path = repo / filename
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    await _git("add", filename, cwd=repo)
    await _git("commit", "-m", message, cwd=repo)


async def _merged_attempt(repo: Path, feature_branch: str, task_id: str, execution_id: str, filename: str) -> str:
    """Create `<feature_branch>--<task_id>-a1-<exec hex>`, commit *filename* on it, merge it back --no-ff."""
    branch = f"{feature_branch}--{task_id}-a1-{execution_id.replace('-', '')}"
    await _git("checkout", "-b", branch, cwd=repo)
    await _commit(repo, filename, f"# {task_id}\n", f"impl {task_id}")
    await _git("checkout", feature_branch, cwd=repo)
    await _git("merge", "--no-ff", "-m", f"merge {task_id}", branch, cwd=repo)
    return branch


def _fast_plan(argv: tuple[str, ...]):
    def _plan(*, worktree, changed_files, tier, declared=(), policy=None) -> ScopePlan:
        invocation = PytestInvocation(distribution="root", argv=argv, targets=())
        return ScopePlan(
            tier=tier, invocations=(invocation,), escalated=(), core_hits=(), skipped_escalations=(), notes=()
        )

    return _plan


def _identity_protected_argv(cwd: Path, argv: list[str]) -> list[str]:
    return list(argv)


def _engine(three_seat_roster, noop_probe, base_path: Path, tmp_path: Path) -> SddCoderEngine:
    return SddCoderEngine(
        roster=three_seat_roster,
        probe=noop_probe,
        worktree_base_path=str(base_path),
        telemetry_dir=str(tmp_path / "telemetry"),
    )


# -- 1. merge-tier scope --------------------------------------------------------


async def test_merge_scope_base_covers_only_this_chunk(
    tmp_path: Path, git_sandbox_feature, three_seat_roster, noop_probe
) -> None:
    """The resolved base sees the merged task's own files, never an earlier task's."""
    worktree, feature_branch, base_path, _index = git_sandbox_feature
    execution_id = str(uuid.uuid4())
    engine = _engine(three_seat_roster, noop_probe, base_path, tmp_path)
    await engine.begin_execution(FEATURE, str(worktree), execution_id)

    # An earlier task already merged into the feature branch...
    await _merged_attempt(worktree, feature_branch, "TASK-0001", execution_id, "pkg/earlier.py")
    # ...then the chunk we are about to validate.
    await _merged_attempt(worktree, feature_branch, "TASK-0002", execution_id, "pkg/current.py")

    base = await engine._merge_scope_base(
        await engine._resolve_feature(FEATURE, str(worktree)), ["TASK-0002"], execution_id
    )

    assert base is not None
    scoped = changed_files(worktree, base)
    assert "pkg/current.py" in scoped
    assert "pkg/earlier.py" not in scoped, "the merge-tier scope must not re-validate a previously merged task"


async def test_merge_scope_base_spans_every_task_of_the_chunk(
    tmp_path: Path, git_sandbox_feature, three_seat_roster, noop_probe
) -> None:
    """Two tasks merged in one chunk resolve to a base covering both, and the worker's own follow-up commit."""
    worktree, feature_branch, base_path, _index = git_sandbox_feature
    execution_id = str(uuid.uuid4())
    engine = _engine(three_seat_roster, noop_probe, base_path, tmp_path)
    await engine.begin_execution(FEATURE, str(worktree), execution_id)

    await _merged_attempt(worktree, feature_branch, "TASK-0001", execution_id, "pkg/earlier.py")
    await _merged_attempt(worktree, feature_branch, "TASK-0002", execution_id, "pkg/first.py")
    await _merged_attempt(worktree, feature_branch, "TASK-0003", execution_id, "pkg/second.py")
    # A review fix the orchestrator committed itself on the feature branch.
    await _commit(worktree, "pkg/review_fix.py", "# fix\n", "fix(TASK-0003) review fixes")

    base = await engine._merge_scope_base(
        await engine._resolve_feature(FEATURE, str(worktree)), ["TASK-0002", "TASK-0003"], execution_id
    )

    assert base is not None
    scoped = changed_files(worktree, base)
    assert {"pkg/first.py", "pkg/second.py", "pkg/review_fix.py"} <= set(scoped)
    assert "pkg/earlier.py" not in scoped


async def test_merge_scope_base_is_none_without_a_merged_branch(
    tmp_path: Path, git_sandbox_feature, three_seat_roster, noop_probe
) -> None:
    """An unresolvable task keeps the caller on the cumulative base -- never a narrower guess."""
    worktree, feature_branch, base_path, _index = git_sandbox_feature
    execution_id = str(uuid.uuid4())
    engine = _engine(three_seat_roster, noop_probe, base_path, tmp_path)
    await engine.begin_execution(FEATURE, str(worktree), execution_id)
    ctx = await engine._resolve_feature(FEATURE, str(worktree))

    # No attempt branch at all.
    assert await engine._merge_scope_base(ctx, ["TASK-0004"], execution_id) is None

    # An attempt branch that exists but was never merged is not a merge scope either.
    branch = f"{feature_branch}--TASK-0004-a1-{execution_id.replace('-', '')}"
    await _git("checkout", "-b", branch, cwd=worktree)
    await _commit(worktree, "pkg/unmerged.py", "# nope\n", "impl TASK-0004")
    await _git("checkout", feature_branch, cwd=worktree)
    assert await engine._merge_scope_base(ctx, ["TASK-0004"], execution_id) is None


async def test_merge_scope_base_ignores_another_executions_branch(
    tmp_path: Path, git_sandbox_feature, three_seat_roster, noop_probe
) -> None:
    """A leftover branch from a previous execution never becomes this execution's scope."""
    worktree, feature_branch, base_path, _index = git_sandbox_feature
    foreign_execution = str(uuid.uuid4())
    execution_id = str(uuid.uuid4())
    engine = _engine(three_seat_roster, noop_probe, base_path, tmp_path)
    await engine.begin_execution(FEATURE, str(worktree), execution_id)

    await _merged_attempt(worktree, feature_branch, "TASK-0002", foreign_execution, "pkg/foreign.py")

    base = await engine._merge_scope_base(
        await engine._resolve_feature(FEATURE, str(worktree)), ["TASK-0002"], execution_id
    )
    assert base is None


async def test_run_validation_narrows_merge_tier_only(
    tmp_path: Path, git_sandbox_feature, three_seat_roster, noop_probe, monkeypatch: pytest.MonkeyPatch
) -> None:
    """tier='merge' plans from the resolved chunk base; tier='feature' keeps the cumulative one."""
    worktree, feature_branch, base_path, _index = git_sandbox_feature
    execution_id = str(uuid.uuid4())
    engine = _engine(three_seat_roster, noop_probe, base_path, tmp_path)
    await engine.begin_execution(FEATURE, str(worktree), execution_id)
    await _merged_attempt(worktree, feature_branch, "TASK-0001", execution_id, "pkg/earlier.py")
    await _merged_attempt(worktree, feature_branch, "TASK-0002", execution_id, "pkg/current.py")

    seen_bases: list[str] = []

    def _recording_changed_files(wt: Path, base_ref: str) -> list[str]:
        seen_bases.append(base_ref)
        return []

    monkeypatch.setattr(background_module, "changed_files", _recording_changed_files)
    monkeypatch.setattr(background_module, "plan_tests", _fast_plan((sys.executable, "-c", "import sys; sys.exit(0)")))
    monkeypatch.setattr(background_module, "protected_argv", _identity_protected_argv)

    await engine.run_validation(
        FEATURE, str(worktree), execution_id, ["TASK-0002"], "merge", 30, f"{execution_id}:TASK-0002:merge"
    )
    assert seen_bases, "the selection was never planned"
    merge_base = seen_bases[-1]
    assert merge_base != "origin/dev"
    # It is exactly the base the scope helper resolves for this chunk.
    expected = await engine._merge_scope_base(
        await engine._resolve_feature(FEATURE, str(worktree)), ["TASK-0002"], execution_id
    )
    assert merge_base == expected

    await engine.run_validation(
        FEATURE,
        str(worktree),
        execution_id,
        ["TASK-0001", "TASK-0002", "TASK-0003", "TASK-0004", "TASK-0005"],
        "feature",
        30,
        f"{execution_id}:feature",
    )
    assert seen_bases[-1] == "origin/dev", "the whole-feature gate must keep its cumulative base"


async def test_supervisor_start_defaults_to_the_cumulative_base(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Without a resolved base the supervisor plans exactly as before this fix."""
    from parrot.flows.dev_loop.sdd_coder.background import BackgroundRegistry, ValidationSupervisor
    from parrot.flows.dev_loop.sdd_coder.evidence import ExecutionEvidenceStore

    store = ExecutionEvidenceStore(root=tmp_path / "evidence")
    worktree = tmp_path / "worktree"
    worktree.mkdir()
    supervisor = ValidationSupervisor(
        registry=BackgroundRegistry(store=store, owner_instance_id="owner-A"), store=store
    )

    seen_bases: list[str] = []
    monkeypatch.setattr(background_module, "changed_files", lambda wt, base_ref: (seen_bases.append(base_ref), [])[1])
    monkeypatch.setattr(background_module, "plan_tests", _fast_plan((sys.executable, "-c", "import sys; sys.exit(0)")))
    monkeypatch.setattr(background_module, "protected_argv", _identity_protected_argv)

    execution_id = str(uuid.uuid4())
    kwargs = dict(
        feature=FEATURE,
        worktree=worktree,
        execution_id=execution_id,
        task_ids=["TASK-0001"],
        tier="merge",
        timeout_seconds=10,
    )
    await supervisor.start(request_id="req-default", **kwargs)
    await supervisor.start(request_id="req-explicit", base_ref="abc1234", **kwargs)

    assert seen_bases == ["origin/dev", "abc1234"]

    with pytest.raises(ValueError):
        await supervisor.start(request_id="req-blank", base_ref="   ", **kwargs)


# -- 2. blocking background wait -------------------------------------------------


def test_bg_wait_is_a_discoverable_tool(tmp_path: Path, three_seat_roster) -> None:
    """The blocking wait ships as its own MCP tool next to the non-blocking read."""
    toolkit = SddCoderToolkit(roster=three_seat_roster, telemetry_dir=str(tmp_path / "telemetry"))
    assert {"coder_bg_status", "coder_bg_wait"} <= {t.name for t in toolkit.get_tools()}


async def _admit(engine: SddCoderEngine, worktree: Path, execution_id: str, *, sleep_s: float, request_id: str) -> str:
    registration = await engine.run_validation(
        FEATURE, str(worktree), execution_id, ["TASK-0001"], "merge", 120, request_id
    )
    return registration.handle


@pytest.fixture
def _synthetic_validation(monkeypatch: pytest.MonkeyPatch):
    """Plan one synthetic child whose duration the test controls."""

    def _install(sleep_s: float) -> None:
        monkeypatch.setattr(background_module, "changed_files", lambda wt, base_ref: [])
        monkeypatch.setattr(
            background_module,
            "plan_tests",
            _fast_plan((sys.executable, "-c", f"import time; time.sleep({sleep_s})")),
        )
        monkeypatch.setattr(background_module, "protected_argv", _identity_protected_argv)

    return _install


async def test_bg_wait_blocks_until_the_handle_settles(
    tmp_path: Path, git_sandbox_feature, three_seat_roster, noop_probe, _synthetic_validation
) -> None:
    """The wait returns a settled receipt instead of a `running` snapshot the caller must poll."""
    worktree, _branch, base_path, _index = git_sandbox_feature
    _synthetic_validation(1.0)
    execution_id = str(uuid.uuid4())
    engine = _engine(three_seat_roster, noop_probe, base_path, tmp_path)
    await engine.begin_execution(FEATURE, str(worktree), execution_id)

    handle = await _admit(engine, worktree, execution_id, sleep_s=1.0, request_id="req-settle")
    started = time.monotonic()
    status = await engine.bg_wait(execution_id, handle, timeout_seconds=60)
    elapsed = time.monotonic() - started

    assert status.state == "finished"
    assert status.outcome == "completed"
    assert status.exit_code == 0
    assert elapsed >= 0.5, "bg_wait returned without actually waiting for the child"


async def test_bg_wait_expiry_never_cancels_the_run(
    tmp_path: Path, git_sandbox_feature, three_seat_roster, noop_probe, _synthetic_validation
) -> None:
    """An expired budget returns the last known state; the supervised run keeps going and still settles."""
    worktree, _branch, base_path, _index = git_sandbox_feature
    _synthetic_validation(2.0)
    execution_id = str(uuid.uuid4())
    engine = _engine(three_seat_roster, noop_probe, base_path, tmp_path)
    await engine.begin_execution(FEATURE, str(worktree), execution_id)

    handle = await _admit(engine, worktree, execution_id, sleep_s=2.0, request_id="req-expire")
    status = await engine.bg_wait(execution_id, handle, timeout_seconds=1)
    assert status.state in ("pending", "running")
    assert status.outcome is None

    # The run was shielded from the caller's budget: a second wait settles it.
    settled = await engine.bg_wait(execution_id, handle, timeout_seconds=60)
    assert settled.state == "finished"
    assert settled.outcome == "completed"


async def test_bg_wait_rejects_a_foreign_or_unknown_handle_without_blocking(
    tmp_path: Path, git_sandbox_feature, three_seat_roster, noop_probe
) -> None:
    """Ownership is checked before any waiting -- an invented handle fails fast, it never blocks."""
    worktree, _branch, base_path, _index = git_sandbox_feature
    execution_id = str(uuid.uuid4())
    engine = _engine(three_seat_roster, noop_probe, base_path, tmp_path)
    await engine.begin_execution(FEATURE, str(worktree), execution_id)

    started = time.monotonic()
    with pytest.raises(CoderFailure) as excinfo:
        await engine.bg_wait(execution_id, "not-a-registered-handle", timeout_seconds=300)
    assert time.monotonic() - started < 5, "an unknown handle must not consume the blocking budget"
    assert excinfo.value.code == "background_not_found"

    with pytest.raises(CoderFailure) as excinfo:
        await engine.bg_wait(str(uuid.uuid4()), "whatever", timeout_seconds=30)
    assert excinfo.value.code == "execution_not_found"


@pytest.mark.parametrize("timeout_seconds", [0, -1, 301, 7200])
async def test_bg_wait_bounds_its_budget(
    tmp_path: Path, git_sandbox_feature, three_seat_roster, noop_probe, timeout_seconds: int
) -> None:
    """The blocking budget mirrors `wait()`'s own 1..300s bounds."""
    worktree, _branch, base_path, _index = git_sandbox_feature
    execution_id = str(uuid.uuid4())
    engine = _engine(three_seat_roster, noop_probe, base_path, tmp_path)
    await engine.begin_execution(FEATURE, str(worktree), execution_id)

    with pytest.raises(CoderFailure) as excinfo:
        await engine.bg_wait(execution_id, "any-handle", timeout_seconds=timeout_seconds)
    assert excinfo.value.code == "invalid_arguments"


async def test_supervisor_wait_reports_whether_it_waited(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """`wait()` answers False for a handle it does not supervise, so the caller polls instead of assuming."""
    from parrot.flows.dev_loop.sdd_coder.background import BackgroundRegistry, ValidationSupervisor
    from parrot.flows.dev_loop.sdd_coder.evidence import ExecutionEvidenceStore

    store = ExecutionEvidenceStore(root=tmp_path / "evidence")
    worktree = tmp_path / "worktree"
    worktree.mkdir()
    registry = BackgroundRegistry(store=store, owner_instance_id="owner-A")
    supervisor = ValidationSupervisor(registry=registry, store=store)
    execution_id = str(uuid.uuid4())

    assert await supervisor.wait(execution_id, "never-registered", 1) is False

    monkeypatch.setattr(background_module, "changed_files", lambda wt, base_ref: [])
    monkeypatch.setattr(background_module, "plan_tests", _fast_plan((sys.executable, "-c", "import sys; sys.exit(0)")))
    monkeypatch.setattr(background_module, "protected_argv", _identity_protected_argv)
    await supervisor.start(
        feature=FEATURE,
        worktree=worktree,
        execution_id=execution_id,
        task_ids=["TASK-0001"],
        tier="merge",
        timeout_seconds=10,
        request_id="req-wait",
    )
    assert await supervisor.wait(execution_id, "req-wait", 30) is True
    status = await registry.status(execution_id, "req-wait")
    assert status.state == "finished"
