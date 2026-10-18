"""FEAT-699 contract and bounded-fallback selector modes."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from parrot.flows.dev_loop.test_scope.datatypes import ScopePlan, TestContract, TestTarget
from parrot.flows.dev_loop.test_scope.policy import ScopePolicy
from parrot.flows.dev_loop.test_scope.select import plan_tests


def _git(root: Path, *args: str) -> None:
    """Run git in ``root``."""
    subprocess.run(["git", *args], cwd=root, check=True, capture_output=True)


@pytest.fixture
def fixture_repo(tmp_path: Path) -> Path:
    """Create a git repository with one source module and three direct importing tests."""
    files = {
        "packages/a/src/pkg/x/foo.py": "VALUE = 1\n",
        "packages/a/tests/x/test_foo.py": "import pkg.x.foo\n",
        "packages/a/tests/x/test_foo_one.py": "import pkg.x.foo\n",
        "packages/a/tests/x/test_foo_two.py": "import pkg.x.foo\n",
    }
    for relative_path, content in files.items():
        path = tmp_path / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
    _git(tmp_path, "init", "-q", "-b", "main")
    _git(tmp_path, "-c", "user.email=t@t", "-c", "user.name=t", "add", "-A")
    _git(tmp_path, "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "init")
    return tmp_path


def _contract(*tests: str) -> TestContract:
    """Build a minimal normalized-contract-shaped value for selector tests."""
    return TestContract(schema=1, tests=tests, markers=(), digest="sha256:test")


def _targets(plan: ScopePlan) -> list[TestTarget]:
    """Flatten all plan targets."""
    return [target for invocation in plan.invocations for target in invocation.targets]


def test_plan_contract_mode_no_escalation(fixture_repo: Path) -> None:
    """Contract mode selects contract/mirror files and reports core as nightly-only."""
    plan = plan_tests(
        worktree=fixture_repo,
        changed_files=["packages/a/src/pkg/x/foo.py"],
        tier="merge",
        contract=_contract("packages/a/tests/x/test_foo_one.py"),
        policy=ScopePolicy(core_paths=("packages/a/src/pkg/x/foo.py",)),
    )

    targets = _targets(plan)
    assert plan.mode == "contract"
    assert plan.escalated == ()
    assert plan.skipped_escalations == ()
    assert plan.core_hits
    assert not [target for target in targets if target.reason == "import"]
    assert any(target.reason == "contract" for target in targets)
    assert any("covered by nightly" in note for note in plan.notes)
    assert all(target.path not in {"packages/a/tests", "tests"} for target in targets)


def test_plan_fallback_bounded(fixture_repo: Path) -> None:
    """Fallback keeps the sorted cap prefix and never substitutes a suite."""
    plan = plan_tests(
        worktree=fixture_repo,
        changed_files=["packages/a/src/pkg/x/foo.py"],
        tier="merge",
        policy=ScopePolicy(impact_cap=2, core_fanin_threshold=999),
    )

    targets = _targets(plan)
    imported = [target.path for target in targets if target.reason == "import"]
    assert plan.mode == "fallback"
    assert imported == ["packages/a/tests/x/test_foo.py", "packages/a/tests/x/test_foo_one.py"]
    assert "a: 3 impacted tests exceed cap 2; kept 2, rest covered by nightly" in plan.notes
    assert "no test contract declared — bounded fallback (own tests + direct importers)" in plan.notes
    assert all(target.path not in {"packages/a/tests", "tests"} for target in targets)


def test_task_tier_ignores_contract(fixture_repo: Path) -> None:
    """Task tier does not add contract operands or build import impact."""
    plan = plan_tests(
        worktree=fixture_repo,
        changed_files=["packages/a/src/pkg/x/foo.py"],
        tier="task",
        contract=_contract("packages/a/tests/x/test_foo_one.py"),
    )

    targets = _targets(plan)
    assert plan.mode == "contract"
    assert [target.path for target in targets] == ["packages/a/tests/x/test_foo.py"]
    assert all(target.reason == "mirror" for target in targets)


def test_missing_contract_operand_is_noted_not_broadened(fixture_repo: Path) -> None:
    """A missing contract file is skipped without replacing it with a directory."""
    missing = "packages/a/tests/x/test_missing.py"
    plan = plan_tests(
        worktree=fixture_repo,
        changed_files=[],
        tier="feature",
        contract=_contract(missing),
    )

    assert _targets(plan) == []
    assert f"contract operand missing on disk, skipped: {missing}" in plan.notes
