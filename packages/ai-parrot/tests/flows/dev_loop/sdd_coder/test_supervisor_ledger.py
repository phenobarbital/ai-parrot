"""FEAT-604 M1 — the supervisor becomes a ledger writer (+ selection log header)."""

from __future__ import annotations

import asyncio
import json
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
from parrot.flows.dev_loop.test_scope import green_cache
from parrot.flows.dev_loop.test_scope.baseline import BaselineVerdict
from parrot.flows.dev_loop.test_scope.context import read_ledger, record_green_escalation, worktree_git_dir
from parrot.flows.dev_loop.test_scope.datatypes import CoreHit, Invocation, ScopePlan, TestTarget
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
    invocation = Invocation(
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
    assert empty_log.startswith("# selection tier=merge\n")
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
    assert skipped_log.startswith("# selection tier=merge\n")
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
    header_idx = nonempty_log.index("# selection tier=merge\n# note: heads up\n")
    cmd_idx = nonempty_log.index("# $ ")
    assert header_idx < cmd_idx, "the selection header must precede the first invocation's command line"


# -- Spec §4 integration rows: real selector + real green cache, only the child is synthetic -----

_JUNIT_TARGET = "packages/a/tests/test_leaf.py"
_JUNIT_TESTCASE = (
    "<testcase file='packages/a/tests/test_leaf.py' classname='packages.a.tests.test_leaf' name='test_leaf'>"
)


def _junit_child(*, failed: bool) -> tuple[str, ...]:
    """A child honouring ``--junitxml=<path>`` that writes an xunit1 report for the leaf test."""
    failure = "<failure/>" if failed else ""
    return (
        sys.executable,
        "-c",
        "import sys;"
        "p=[x for x in sys.argv if x.startswith('--junitxml=')][0].split('=',1)[1];"
        "open(p,'w').write(\"<testsuites><testsuite tests='1' failures='"
        + ("1" if failed else "0")
        + "'>"
        + _JUNIT_TESTCASE
        + failure
        + '</testcase></testsuite></testsuites>");'
        "sys.exit(" + ("1" if failed else "0") + ")",
    )


_JUNIT_GREEN_CHILD = _junit_child(failed=False)
_JUNIT_RED_CHILD = _junit_child(failed=True)


def _real_plan_with_argv(argv: tuple[str, ...]):
    """Wrap the REAL selector; only each invocation's argv becomes a controlled child."""

    def _plan(*, worktree: Path, changed_files, tier: str, **_extra) -> ScopePlan:
        plan = real_plan_tests(worktree=worktree, changed_files=changed_files, tier=tier, policy=ScopePolicy())
        invocations = tuple(
            Invocation(distribution=inv.distribution, argv=argv, targets=inv.targets) for inv in plan.invocations
        )
        return replace(plan, invocations=invocations)

    return _plan


@pytest.fixture
def cache_worktree(tmp_path: Path) -> Path:
    """A real git repo: one source module, its test, a task file and a per-spec index (fallback mode)."""
    root = tmp_path / "cache-repo"
    files = {
        "pyproject.toml": "[project]\nname = 'root'\n",
        "packages/a/pyproject.toml": "[project]\nname = 'a'\n",
        "packages/a/src/pa/__init__.py": "",
        "packages/a/src/pa/leaf.py": "VALUE = 1\n",
        "packages/a/tests/test_leaf.py": "import pa.leaf\n",
        "task.md": "# TASK-0001\n\n## Validation Commands\n\n- `pytest packages/a/tests/test_leaf.py -q`\n",
        "sdd/tasks/index/demo.json": json.dumps(
            {
                "feature": "demo",
                "feature_id": "FEAT-604",
                "base_branch": "main",
                "tasks": [{"id": "TASK-0001", "file": "task.md"}],
            }
        ),
    }
    for rel, text in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
    _git(root, "init", "-q", "-b", "main")
    _git(root, "add", "-A")
    _git(root, "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "-m", "init")
    return root


def _patch_supervisor(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, child: tuple[str, ...]) -> None:
    monkeypatch.setenv("SDD_TEST_REPORT_DIR", str(tmp_path / "reports"))
    monkeypatch.setattr(background_module, "changed_files", lambda wt, base_ref: ["packages/a/src/pa/leaf.py"])
    monkeypatch.setattr(background_module, "plan_tests", _real_plan_with_argv(child))
    monkeypatch.setattr(background_module, "protected_argv", lambda cwd, argv: list(argv))


async def _merge_plan(supervisor: ValidationSupervisor, worktree: Path) -> ScopePlan:
    return await supervisor._plan_selection(
        worktree=worktree,
        tier="merge",
        index_path=worktree / "sdd/tasks/index/demo.json",
        task_ids=["TASK-0001"],
        feature_id="FEAT-604",
    )


async def test_second_merge_validation_skips_cached_targets(
    tmp_path: Path, cache_worktree: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Integration: after a green merge validation the next merge plan drops the cached file
    (spec §4 integration row 1, re-targeted at the green cache)."""
    worktree = cache_worktree
    supervisor, registry = _make_supervisor(tmp_path)
    _patch_supervisor(monkeypatch, tmp_path, _JUNIT_GREEN_CHILD)

    first = await _merge_plan(supervisor, worktree)
    assert first.cached == ()
    assert len(first.invocations) == 1

    execution_id = str(uuid.uuid4())
    await supervisor.start(
        feature="FEAT-604",
        worktree=worktree,
        execution_id=execution_id,
        task_ids=["TASK-0001"],
        tier="merge",
        timeout_seconds=10,
        request_id="req-1",
        index_path=worktree / "sdd/tasks/index/demo.json",
    )
    await _settle(supervisor, execution_id, "req-1")
    status = await registry.status(execution_id, "req-1")
    assert status.outcome == "completed"

    second = await _merge_plan(supervisor, worktree)
    assert second.cached == (_JUNIT_TARGET,)
    assert second.invocations == ()
    assert len(second.invocations) < len(first.invocations)


async def test_red_run_leaves_no_green_cache_entry(
    tmp_path: Path, cache_worktree: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Integration: a red validation drops a previously cached green entry; the next plan is
    uncached and unchanged (spec §4 integration row 2, re-targeted at the green cache)."""
    worktree = cache_worktree
    supervisor, registry = _make_supervisor(tmp_path)
    _patch_supervisor(monkeypatch, tmp_path, _JUNIT_RED_CHILD)
    # There is no `origin/main` in the temp repo to classify against.
    monkeypatch.setattr(
        background_module.baseline,
        "classify_failures",
        lambda **kwargs: tuple(BaselineVerdict(n, "new_red") for n in kwargs["failed_nodeids"]),
    )

    first = await _merge_plan(supervisor, worktree)
    assert first.cached == ()
    assert len(first.invocations) == 1

    namespace = green_cache.cache_namespace(feature_id="FEAT-604", base_ref="origin/main", contract_digest="")
    green_cache.record_green(
        worktree, namespace=namespace, plan=first, nodes=[(f"{_JUNIT_TARGET}::test_leaf", "passed")]
    )
    seeded = await _merge_plan(supervisor, worktree)
    assert seeded.cached == (_JUNIT_TARGET,), "sanity: the seeded entry is visible"

    # The source then changes: the seeded entry is stale (its key no longer matches), so the next
    # merge validation must run the target again -- and this time it goes red.
    (worktree / "packages/a/src/pa/leaf.py").write_text("VALUE = 2\n")
    stale = await _merge_plan(supervisor, worktree)
    assert stale.cached == ()
    store_path = worktree_git_dir(worktree) / green_cache.CACHE_FILENAME
    assert _JUNIT_TARGET in green_cache._read_store(store_path, namespace), "sanity: the stale entry is still stored"

    execution_id = str(uuid.uuid4())
    await supervisor.start(
        feature="FEAT-604",
        worktree=worktree,
        execution_id=execution_id,
        task_ids=["TASK-0001"],
        tier="merge",
        timeout_seconds=10,
        request_id="req-1",
        index_path=worktree / "sdd/tasks/index/demo.json",
    )
    await _settle(supervisor, execution_id, "req-1")
    status = await registry.status(execution_id, "req-1")
    assert status.outcome == "failed"

    store = green_cache._read_store(store_path, namespace)
    assert store == {}, "a red run must never leave a green cache entry"

    after = await _merge_plan(supervisor, worktree)
    assert after.cached == ()
    assert len(after.invocations) == len(first.invocations)
