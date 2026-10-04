"""FEAT-604 M1 — the supervisor becomes a ledger writer (+ selection log header)."""

from __future__ import annotations

import asyncio
import logging
import subprocess
import sys
import uuid
from dataclasses import replace
from pathlib import Path
from typing import Tuple

import pytest

from parrot.flows.dev_loop.sdd_coder import background as background_module
from parrot.flows.dev_loop.sdd_coder.background import BackgroundRegistry, ValidationSupervisor
from parrot.flows.dev_loop.sdd_coder.evidence import ExecutionEvidenceStore
from parrot.flows.dev_loop.test_scope.context import read_ledger, record_green_escalation
from parrot.flows.dev_loop.test_scope.datatypes import CoreHit, PytestInvocation, ScopePlan, TestTarget
from parrot.flows.dev_loop.test_scope.policy import ScopePolicy
from parrot.flows.dev_loop.test_scope.select import plan_tests as real_plan_tests

_EXIT0 = (sys.executable, "-c", "import sys; sys.exit(0)")
_EXIT1 = (sys.executable, "-c", "import sys; sys.exit(1)")


def _make_supervisor(
    tmp_path: Path, *, owner_instance_id: str = "owner-A"
) -> Tuple[ValidationSupervisor, BackgroundRegistry]:
    """Build one supervisor over its own isolated evidence root (mirrors `test_background_validation.py`)."""
    store = ExecutionEvidenceStore(root=tmp_path / "evidence")
    registry = BackgroundRegistry(store=store, owner_instance_id=owner_instance_id)
    supervisor = ValidationSupervisor(registry=registry, store=store)
    return supervisor, registry


async def _settle(supervisor: ValidationSupervisor, execution_id: str, handle: str) -> None:
    """Await the background settlement task this supervisor keeps for *handle* (test-only seam)."""
    task = supervisor._background_tasks[(execution_id, handle)]
    await asyncio.wait_for(task, timeout=15)


def _canned_plan(argv: tuple[str, ...], *, reason: str, core_files: tuple[str, ...] = ()) -> ScopePlan:
    """A `ScopePlan` carrying exactly one controlled invocation attributed to distribution `root`."""
    invocation = PytestInvocation(
        distribution="root", argv=argv, targets=(TestTarget(path="tests", distribution="root", reason=reason),)
    )
    core_hits = tuple(
        CoreHit(path=path, module=path, fanin=1, forced=False, distributions=("root",)) for path in core_files
    )
    return ScopePlan(
        tier="merge",
        invocations=(invocation,),
        escalated=("root",) if reason in ("core", "escalated") else (),
        core_hits=core_hits,
        skipped_escalations=(),
        notes=(),
    )


def _install_canned(monkeypatch: pytest.MonkeyPatch, plan: ScopePlan) -> None:
    monkeypatch.setattr(background_module, "plan_tests", lambda **_: plan)
    monkeypatch.setattr(background_module, "protected_argv", lambda cwd, argv: list(argv))


def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


def _blob(worktree: Path, path: str) -> str:
    return _git(worktree, "hash-object", "--", path)


# -- M1 unit tests: `_record_invocation_outcome` through the real supervisor path ----------


async def test_supervisor_records_green_escalation(
    tmp_path: Path, git_sandbox_feature, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A green escalated invocation writes the distribution's blobs (core and/or cap)."""
    worktree, _branch, _base_path, _index = git_sandbox_feature
    supervisor, registry = _make_supervisor(tmp_path)
    execution_id = str(uuid.uuid4())
    _install_canned(monkeypatch, _canned_plan(_EXIT0, reason="core", core_files=("pkg/__init__.py",)))

    await supervisor.start(
        feature="demo",
        worktree=worktree,
        execution_id=execution_id,
        task_ids=["TASK-0001"],
        tier="merge",
        timeout_seconds=10,
        request_id="req-green",
    )
    await _settle(supervisor, execution_id, "req-green")
    status = await registry.status(execution_id, "req-green")
    assert status.outcome == "completed"
    assert status.exit_code == 0

    ledger = read_ledger(worktree)
    assert "root" in ledger
    assert ledger["root"].core_blobs == {"pkg/__init__.py": _blob(worktree, "pkg/__init__.py")}


async def test_supervisor_rearms_on_red_escalation(
    tmp_path: Path, git_sandbox_feature, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A red escalated invocation drops the record (`record_red_run`)."""
    worktree, _branch, _base_path, _index = git_sandbox_feature
    record_green_escalation(worktree, ["root"], ["pkg/__init__.py"])
    assert "root" in read_ledger(worktree)

    supervisor, registry = _make_supervisor(tmp_path)
    execution_id = str(uuid.uuid4())
    _install_canned(monkeypatch, _canned_plan(_EXIT1, reason="core", core_files=("pkg/__init__.py",)))

    await supervisor.start(
        feature="demo",
        worktree=worktree,
        execution_id=execution_id,
        task_ids=["TASK-0001"],
        tier="merge",
        timeout_seconds=10,
        request_id="req-red",
    )
    await _settle(supervisor, execution_id, "req-red")
    status = await registry.status(execution_id, "req-red")
    assert status.outcome == "failed"

    assert "root" not in read_ledger(worktree)


async def test_supervisor_rearms_on_timeout(
    tmp_path: Path, git_sandbox_feature, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A timed-out escalated invocation re-arms (proved nothing => fail-open)."""
    worktree, _branch, _base_path, _index = git_sandbox_feature
    record_green_escalation(worktree, ["root"], ["pkg/__init__.py"])
    assert "root" in read_ledger(worktree)

    supervisor, registry = _make_supervisor(tmp_path)
    execution_id = str(uuid.uuid4())
    sleep_argv = (sys.executable, "-c", "import time; time.sleep(30)")
    _install_canned(monkeypatch, _canned_plan(sleep_argv, reason="core", core_files=("pkg/__init__.py",)))

    await supervisor.start(
        feature="demo",
        worktree=worktree,
        execution_id=execution_id,
        task_ids=["TASK-0001"],
        tier="merge",
        timeout_seconds=1,
        request_id="req-timeout",
    )
    await _settle(supervisor, execution_id, "req-timeout")
    status = await registry.status(execution_id, "req-timeout")
    assert status.outcome == "timed_out"

    assert "root" not in read_ledger(worktree)


async def test_supervisor_records_nothing_without_escalation(
    tmp_path: Path, git_sandbox_feature, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A mirror/import-only invocation writes no ledger entry."""
    worktree, _branch, _base_path, _index = git_sandbox_feature
    supervisor, registry = _make_supervisor(tmp_path)
    execution_id = str(uuid.uuid4())
    _install_canned(monkeypatch, _canned_plan(_EXIT0, reason="mirror"))

    await supervisor.start(
        feature="demo",
        worktree=worktree,
        execution_id=execution_id,
        task_ids=["TASK-0001"],
        tier="merge",
        timeout_seconds=10,
        request_id="req-mirror",
    )
    await _settle(supervisor, execution_id, "req-mirror")
    status = await registry.status(execution_id, "req-mirror")
    assert status.outcome == "completed"

    assert read_ledger(worktree) == {}


async def test_supervisor_ledger_failure_never_fails_validation(
    tmp_path: Path, git_sandbox_feature, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """Unwritable ledger (e.g. read-only git dir) -> logged and swallowed; receipt stays green."""
    worktree, _branch, _base_path, _index = git_sandbox_feature
    supervisor, registry = _make_supervisor(tmp_path)
    execution_id = str(uuid.uuid4())
    _install_canned(monkeypatch, _canned_plan(_EXIT0, reason="core", core_files=("pkg/__init__.py",)))

    def _raise(*_args, **_kwargs):
        raise RuntimeError("simulated unwritable ledger (read-only git dir)")

    monkeypatch.setattr(background_module, "record_green_escalation", _raise)

    with caplog.at_level(logging.WARNING, logger="parrot.flows.dev_loop.sdd_coder.background"):
        await supervisor.start(
            feature="demo",
            worktree=worktree,
            execution_id=execution_id,
            task_ids=["TASK-0001"],
            tier="merge",
            timeout_seconds=10,
            request_id="req-unwritable",
        )
        await _settle(supervisor, execution_id, "req-unwritable")

    status = await registry.status(execution_id, "req-unwritable")
    assert status.outcome == "completed"
    assert status.exit_code == 0
    assert any("could not record escalation outcome" in record.message for record in caplog.records)


# -- OQ3: selection-summary header -----------------------------------------------------------


async def test_start_logs_selection_summary(
    tmp_path: Path, git_sandbox_feature, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`start()` writes '# selection tier=...' + '# note: ...' lines; the all-skipped empty plan
    is distinguishable from an empty diff (AC: selection-summary header)."""
    worktree, _branch, _base_path, _index = git_sandbox_feature
    supervisor, _registry = _make_supervisor(tmp_path)
    execution_id = str(uuid.uuid4())

    empty_diff_plan = ScopePlan(
        tier="merge", invocations=(), escalated=(), core_hits=(), skipped_escalations=(), notes=()
    )
    monkeypatch.setattr(background_module, "plan_tests", lambda **_: empty_diff_plan)
    monkeypatch.setattr(background_module, "protected_argv", lambda cwd, argv: list(argv))
    reg_empty = await supervisor.start(
        feature="demo",
        worktree=worktree,
        execution_id=execution_id,
        task_ids=["TASK-0001"],
        tier="merge",
        timeout_seconds=10,
        request_id="req-empty-diff",
    )
    empty_log = supervisor._log_path(execution_id, reg_empty.handle).read_text()
    assert empty_log.startswith("# selection tier=merge escalated=[] skipped_escalations=[]\n")
    assert "# note:" not in empty_log
    assert empty_log.endswith("# no applicable pytest invocations for this selection\n")

    all_skipped_plan = ScopePlan(
        tier="merge",
        invocations=(),
        escalated=(),
        core_hits=(),
        skipped_escalations=("root",),
        notes=("root: cap escalation skipped — ledger blobs and impacted hash match",),
    )
    monkeypatch.setattr(background_module, "plan_tests", lambda **_: all_skipped_plan)
    reg_skipped = await supervisor.start(
        feature="demo",
        worktree=worktree,
        execution_id=execution_id,
        task_ids=["TASK-0001"],
        tier="merge",
        timeout_seconds=10,
        request_id="req-all-skipped",
    )
    skipped_log = supervisor._log_path(execution_id, reg_skipped.handle).read_text()
    assert skipped_log.startswith("# selection tier=merge escalated=[] skipped_escalations=[root]\n")
    assert "# note: root: cap escalation skipped — ledger blobs and impacted hash match\n" in skipped_log
    assert skipped_log.endswith("# no applicable pytest invocations for this selection\n")
    # The all-skipped empty plan is distinguishable from the plain empty-diff plan.
    assert skipped_log != empty_log

    nonempty_plan = _canned_plan(_EXIT0, reason="escalated")
    nonempty_plan = replace(nonempty_plan, notes=("heads up",))
    monkeypatch.setattr(background_module, "plan_tests", lambda **_: nonempty_plan)
    reg_nonempty = await supervisor.start(
        feature="demo",
        worktree=worktree,
        execution_id=execution_id,
        task_ids=["TASK-0001"],
        tier="merge",
        timeout_seconds=10,
        request_id="req-nonempty",
    )
    await _settle(supervisor, execution_id, "req-nonempty")
    nonempty_log = supervisor._log_path(execution_id, reg_nonempty.handle).read_text()
    header_idx = nonempty_log.index(
        "# selection tier=merge escalated=[root] skipped_escalations=[]\n# note: heads up\n"
    )
    cmd_idx = nonempty_log.index("# $ ")
    assert header_idx < cmd_idx, "the selection header must precede the first invocation's command line"


# -- Spec §4 integration rows: real selector + real ledger, only the child is synthetic -----


def _cap_forcing_plan(argv: tuple[str, ...]):
    """Wrap the REAL selector (forced cap policy); only each invocation's argv becomes a controlled child."""

    def _plan(*, worktree: Path, changed_files, tier: str) -> ScopePlan:
        plan = real_plan_tests(
            worktree=worktree,
            changed_files=changed_files,
            tier=tier,
            policy=ScopePolicy(impact_cap=0, core_fanin_threshold=999),
        )
        invocations = tuple(
            PytestInvocation(distribution=inv.distribution, argv=argv, targets=inv.targets) for inv in plan.invocations
        )
        return replace(plan, invocations=invocations)

    return _plan


@pytest.fixture
def cap_worktree(tmp_path: Path) -> Path:
    """One source module + its importing test, tracked in a real git repo (mirrors
    `test_cap_escalation_ledger.py::plan_worktree`)."""
    root = tmp_path / "cap-repo"
    source = root / "packages/a/src/pa/leaf.py"
    test = root / "packages/a/tests/test_leaf.py"
    source.parent.mkdir(parents=True)
    test.parent.mkdir(parents=True)
    source.write_text("VALUE = 1\n")
    test.write_text("import pa.leaf\n")
    _git(root, "init", "-q", "-b", "main")
    _git(root, "add", "-A")
    _git(root, "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "-m", "init")
    return root


async def test_second_merge_validation_skips_unchanged_suites(
    tmp_path: Path, cap_worktree: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Integration: two consecutive merge-tier validations on a temp repo -- the second
    plans strictly fewer invocations (spec §4 integration row 1)."""
    worktree = cap_worktree
    supervisor, registry = _make_supervisor(tmp_path)
    changed = ["packages/a/src/pa/leaf.py"]
    monkeypatch.setattr(background_module, "changed_files", lambda wt, base_ref: changed)
    monkeypatch.setattr(background_module, "plan_tests", _cap_forcing_plan(_EXIT0))
    monkeypatch.setattr(background_module, "protected_argv", lambda cwd, argv: list(argv))

    first_real_plan = real_plan_tests(
        worktree=worktree,
        changed_files=changed,
        tier="merge",
        policy=ScopePolicy(impact_cap=0, core_fanin_threshold=999),
    )
    assert first_real_plan.invocations, "sanity: the cap escalation must produce an invocation before any ledger record"

    execution_id = str(uuid.uuid4())
    await supervisor.start(
        feature="demo",
        worktree=worktree,
        execution_id=execution_id,
        task_ids=["TASK-0001"],
        tier="merge",
        timeout_seconds=10,
        request_id="req-1",
    )
    await _settle(supervisor, execution_id, "req-1")
    status = await registry.status(execution_id, "req-1")
    assert status.outcome == "completed"

    second_real_plan = real_plan_tests(
        worktree=worktree,
        changed_files=changed,
        tier="merge",
        policy=ScopePolicy(impact_cap=0, core_fanin_threshold=999),
    )
    assert len(second_real_plan.invocations) < len(first_real_plan.invocations)
    assert second_real_plan.skipped_escalations == ("a",)


async def test_red_first_run_forces_full_second_run(
    tmp_path: Path, cap_worktree: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Integration: a red first validation re-arms everything; the second plans the same
    scope (spec §4 integration row 2)."""
    worktree = cap_worktree
    supervisor, registry = _make_supervisor(tmp_path)
    changed = ["packages/a/src/pa/leaf.py"]
    # A stale green record left by an earlier (now-irrelevant) run -- the red
    # run below must drop it, never leave it in place for the next selection.
    record_green_escalation(worktree, ["a"], [], ["packages/a/src/pa/leaf.py"], {"a": "stale-hash"})
    assert "a" in read_ledger(worktree)
    monkeypatch.setattr(background_module, "changed_files", lambda wt, base_ref: changed)
    monkeypatch.setattr(background_module, "plan_tests", _cap_forcing_plan(_EXIT1))
    monkeypatch.setattr(background_module, "protected_argv", lambda cwd, argv: list(argv))

    first_real_plan = real_plan_tests(
        worktree=worktree,
        changed_files=changed,
        tier="merge",
        policy=ScopePolicy(impact_cap=0, core_fanin_threshold=999),
    )

    execution_id = str(uuid.uuid4())
    await supervisor.start(
        feature="demo",
        worktree=worktree,
        execution_id=execution_id,
        task_ids=["TASK-0001"],
        tier="merge",
        timeout_seconds=10,
        request_id="req-1",
    )
    await _settle(supervisor, execution_id, "req-1")
    status = await registry.status(execution_id, "req-1")
    assert status.outcome == "failed"

    assert read_ledger(worktree) == {}, "a red escalated run must never leave a green ledger record"

    second_real_plan = real_plan_tests(
        worktree=worktree,
        changed_files=changed,
        tier="merge",
        policy=ScopePolicy(impact_cap=0, core_fanin_threshold=999),
    )
    assert len(second_real_plan.invocations) == len(first_real_plan.invocations)
    assert second_real_plan.skipped_escalations == ()
