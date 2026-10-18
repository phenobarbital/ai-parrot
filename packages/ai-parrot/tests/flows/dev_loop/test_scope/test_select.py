"""Tier tests for test_scope.plan_tests (FEAT-563 TASK-3308)."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from parrot.flows.dev_loop.test_scope import changed_files, plan_tests
from parrot.flows.dev_loop.test_scope.policy import ScopePolicy


def _git(root: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=root, check=True, capture_output=True)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """git repo: dist a (pa/base.py imported by dist b), tests per dist, root tests."""
    files = {
        "packages/a/src/pa/base.py": "X = 1\n",
        "packages/a/src/pa/leaf.py": "Y = 2\n",
        "packages/a/tests/test_leaf.py": "import pa.leaf\n",
        "packages/b/src/pb/use.py": "from pa.base import X\n",
        "packages/b/tests/test_use.py": "import pb.use\n",
        "tests/test_root.py": "\n",
    }
    for rel, text in files.items():
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / rel).write_text(text)
    _git(tmp_path, "init", "-q", "-b", "main")
    _git(tmp_path, "-c", "user.email=t@t", "-c", "user.name=t", "add", "-A")
    _git(tmp_path, "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "init")
    return tmp_path


def test_task_tier_never_escalates(repo):
    plan = plan_tests(
        worktree=repo,
        changed_files=["packages/a/src/pa/base.py"],
        tier="task",
        policy=ScopePolicy(core_fanin_threshold=1),
    )
    assert plan.escalated == () and plan.core_hits == ()


def test_core_is_informational_and_fallback_stays_file_bounded(repo):
    plan = plan_tests(
        worktree=repo,
        changed_files=["packages/a/src/pa/base.py"],
        tier="merge",
        policy=ScopePolicy(core_fanin_threshold=1),
    )
    paths = {t.path for inv in plan.invocations for t in inv.targets}
    assert paths == {"packages/b/tests/test_use.py"}
    assert plan.escalated == ()
    assert plan.core_hits
    assert any("covered by nightly" in note for note in plan.notes)


def test_core_never_populates_escalation_fields(repo):
    """Core classification remains informative without scheduling suite targets."""
    for tier in ("merge", "feature"):
        plan = plan_tests(
            worktree=repo,
            changed_files=["packages/a/src/pa/base.py"],
            tier=tier,
            policy=ScopePolicy(core_fanin_threshold=1),
        )
        assert plan.escalated == (), (tier, plan.escalated)
        assert plan.skipped_escalations == ()
        assert plan.core_hits


def test_feature_tier_uses_direct_importers_without_core(repo):
    plan = plan_tests(
        worktree=repo,
        changed_files=["packages/a/src/pa/leaf.py"],
        tier="feature",
        policy=ScopePolicy(core_fanin_threshold=999),
    )
    targets = [t for inv in plan.invocations for t in inv.targets]
    assert [target.path for target in targets] == ["packages/a/tests/test_leaf.py"]
    assert targets[0].reason == "import"


def test_plan_does_not_consult_escalation_ledger(repo):
    plan = plan_tests(
        worktree=repo,
        changed_files=["packages/a/src/pa/base.py"],
        tier="merge",
        policy=ScopePolicy(core_fanin_threshold=1),
    )
    assert plan.skipped_escalations == ()
    assert plan.escalated == ()


def test_cap_adds_note_without_package_suite(repo):
    plan = plan_tests(
        worktree=repo,
        changed_files=["packages/a/src/pa/leaf.py"],
        tier="merge",
        policy=ScopePolicy(impact_cap=0, core_fanin_threshold=999),
    )
    assert plan.escalated == ()
    assert plan.cap_hits == {}
    assert any("exceed cap 0; kept 0, rest covered by nightly" in note for note in plan.notes)
    assert all(t.path != "packages/a/tests" for inv in plan.invocations for t in inv.targets)


def test_non_git_worktree_degrades_with_note(tmp_path):
    plan = plan_tests(worktree=tmp_path, changed_files=[], tier="merge", policy=ScopePolicy())
    assert any("index" in note for note in plan.notes)


def test_changed_files_includes_untracked(repo):
    (repo / "packages/a/src/pa/new.py").write_text("")
    assert "packages/a/src/pa/new.py" in changed_files(repo, "HEAD")


def test_merge_tier_tolerates_non_package_changed_files(repo):
    """sdd/ state files in the diff own no distribution and must not raise."""
    plan = plan_tests(
        worktree=repo,
        changed_files=["packages/a/src/pa/leaf.py", "sdd/tasks/index/x.json"],
        tier="merge",
    )
    assert any(t.path.startswith("packages/a/tests") for inv in plan.invocations for t in inv.targets)
