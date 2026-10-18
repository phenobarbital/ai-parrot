"""FEAT-699: bounded fallback must not import a foreign red suite baseline.

`issue:181bd0c01bb4` — a diff confined to `parrot/outputs/a2ui/linked/*` escalated
outward until the merge gate collected ~2800 tests across every distribution, and
so inherited `parrot-formdesigner`'s 40 pre-existing failures. The gate then
reported a red no task's diff caused, for every task in the feature.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from parrot.flows.dev_loop.test_scope.policy import ScopePolicy
from parrot.flows.dev_loop.test_scope.select import plan_tests


def _git(root: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=root, check=True, capture_output=True)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """git repo: dist `b` imports `pa.base` from dist `a`, each with its own tests.

    Changing `packages/a/src/pa/base.py` therefore impacts `b`'s tests while `b`
    owns none of the changed files — exactly the "foreign" shape the guard targets.
    """
    files = {
        "packages/a/src/pa/base.py": "X = 1\n",
        "packages/a/tests/test_base.py": "import pa.base\n",
        "packages/b/src/pb/use.py": "from pa.base import X\n",
        "packages/b/tests/test_use.py": "import pb.use\n",
    }
    for rel, text in files.items():
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / rel).write_text(text)
    _git(tmp_path, "init", "-q", "-b", "main")
    _git(tmp_path, "-c", "user.email=t@t", "-c", "user.name=t", "add", "-A")
    _git(tmp_path, "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "init")
    return tmp_path


def _plan(repo: Path, policy: ScopePolicy):
    """Merge-tier plan for a change confined to distribution `a`."""
    return plan_tests(
        worktree=repo,
        changed_files=["packages/a/src/pa/base.py"],
        tier="merge",
        policy=policy,
    )


def test_cap_truncates_foreign_importers_without_suite(repo: Path) -> None:
    """A cap-exceeded foreign distribution yields a note and no target."""
    plan = _plan(repo, ScopePolicy(impact_cap=0, core_fanin_threshold=999))

    assert "b" not in plan.escalated
    assert not [inv for inv in plan.invocations if inv.distribution == "b"]
    assert any("b: 1 impacted tests exceed cap 0; kept 0" in note for note in plan.notes)
    assert plan.escalated == ()
    assert any(inv.distribution == "a" for inv in plan.invocations)


def test_foreign_dist_is_absent_from_all_escalation_metadata(repo: Path) -> None:
    """Fallback caps never populate the obsolete escalation metadata."""
    plan = _plan(repo, ScopePolicy(impact_cap=0, core_fanin_threshold=999))

    assert "b" not in plan.escalated
    assert "b" not in plan.skipped_escalations
    assert "b" not in plan.cap_hits


def test_foreign_escalation_policy_is_inert(repo: Path) -> None:
    """The legacy escalation opt-in cannot restore suite targets."""
    plan = _plan(
        repo,
        ScopePolicy(impact_cap=0, core_fanin_threshold=999, escalate_foreign_dists=True),
    )

    assert "b" not in plan.escalated
    assert not [inv for inv in plan.invocations if inv.distribution == "b"]
    assert any("b: 1 impacted tests exceed cap 0; kept 0" in note for note in plan.notes)


def test_core_reached_distribution_is_nightly_only(repo: Path) -> None:
    """Core detection stays informative and does not restore a foreign suite."""
    plan = _plan(repo, ScopePolicy(impact_cap=0, core_fanin_threshold=1))

    assert "b" not in plan.escalated
    assert not [inv for inv in plan.invocations if inv.distribution == "b"]
    assert plan.core_hits
    assert any("covered by nightly" in note for note in plan.notes)


def test_guard_is_inert_when_nothing_exceeds_the_cap(repo: Path) -> None:
    """With a generous cap, the direct foreign importer remains file-level."""
    plan = _plan(repo, ScopePolicy(impact_cap=999, core_fanin_threshold=999))

    foreign_targets = [target.path for inv in plan.invocations if inv.distribution == "b" for target in inv.targets]
    assert foreign_targets == ["packages/b/tests/test_use.py"]
    assert all(path != "packages/b/tests" for path in foreign_targets)
