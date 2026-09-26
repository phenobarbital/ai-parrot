"""Cap-escalation ledger records (FEAT-604 M2) — context-level tests."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from parrot.flows.dev_loop.test_scope.context import (
    LEDGER_FILENAME,
    pending_escalations,
    read_ledger,
    record_green_escalation,
    record_red_run,
    worktree_git_dir,
)
from parrot.flows.dev_loop.test_scope.datatypes import ScopePlan
from parrot.flows.dev_loop.test_scope.policy import ScopePolicy
from parrot.flows.dev_loop.test_scope.select import plan_tests


def _git(cwd: Path, *args: str) -> str:
    """Run git in the temporary repository and return stdout."""
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


@pytest.fixture
def worktree(tmp_path: Path) -> Path:
    """Create a real temporary git repository with a tracked driving file."""
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init", "-q")
    _git(root, "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "--allow-empty", "-m", "init")
    (root / "changed.py").write_text("value = 1\n")
    return root


def test_cap_escalation_skipped_when_blobs_and_hash_match(worktree: Path) -> None:
    """Green cap record + identical content + identical impacted hash ⇒ skipped."""
    record_green_escalation(worktree, ["dist"], [], ["changed.py"], {"dist": "set-hash"})
    assert pending_escalations(worktree, [], {"dist": ["changed.py"]}, {"dist": "set-hash"}) == ([], ["dist"])


def test_cap_escalation_rearmed_by_any_content_change(worktree: Path) -> None:
    """Touching one driving file ⇒ distribution returns to to_run."""
    record_green_escalation(worktree, ["dist"], [], ["changed.py"], {"dist": "set-hash"})
    (worktree / "changed.py").write_text("value = 2\n")
    assert pending_escalations(worktree, [], {"dist": ["changed.py"]}, {"dist": "set-hash"}) == (["dist"], [])


def test_cap_escalation_rearmed_by_impacted_hash_change(worktree: Path) -> None:
    """Same blobs, different cap_impacted hash ⇒ distribution runs."""
    record_green_escalation(worktree, ["dist"], [], ["changed.py"], {"dist": "set-hash"})
    assert pending_escalations(worktree, [], {"dist": ["changed.py"]}, {"dist": "other-hash"}) == (["dist"], [])


def test_legacy_ledger_record_never_skips_cap(worktree: Path) -> None:
    """A core_blobs-only record reads empty cap fields and therefore re-runs the cap."""
    git_dir = worktree_git_dir(worktree)
    assert git_dir is not None
    (git_dir / LEDGER_FILENAME).write_text(json.dumps({"dist": {"core_blobs": {}}}))
    entry = read_ledger(worktree)["dist"]
    assert entry.impact_blobs == {}
    assert entry.impacted_hash == ""
    assert pending_escalations(worktree, [], {"dist": ["changed.py"]}, {"dist": "set-hash"}) == (["dist"], [])


def test_read_ledger_drops_unknown_keys(worktree: Path) -> None:
    """An entry with an unexpected key is dropped entirely (fail-open to running)."""
    git_dir = worktree_git_dir(worktree)
    assert git_dir is not None
    (git_dir / LEDGER_FILENAME).write_text(json.dumps({"dist": {"core_blobs": {}, "unexpected": True}}))
    assert read_ledger(worktree) == {}


def test_red_run_preserves_other_entries_new_fields(worktree: Path) -> None:
    """record_red_run on dist A must not strip dist B's cap-record fields."""
    record_green_escalation(worktree, ["a"], [], ["changed.py"], {"a": "a-hash"})
    record_green_escalation(worktree, ["b"], [], ["changed.py"], {"b": "b-hash"})
    record_red_run(worktree, ["a"])
    entries = read_ledger(worktree)
    assert set(entries) == {"b"}
    assert entries["b"].impact_blobs == {"changed.py": _git(worktree, "hash-object", "--", "changed.py")}
    assert entries["b"].impacted_hash == "b-hash"


@pytest.fixture
def plan_worktree(tmp_path: Path) -> Path:
    """Create a git worktree with one source module and its importing test."""
    root = tmp_path / "plan-repo"
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


def _cap_plan(worktree: Path) -> ScopePlan:
    """Select one changed module with a cap that escalates its distribution."""
    return plan_tests(
        worktree=worktree,
        changed_files=["packages/a/src/pa/leaf.py"],
        tier="merge",
        policy=ScopePolicy(impact_cap=0, core_fanin_threshold=999),
    )


def test_plan_reports_cap_driving_files(plan_worktree: Path) -> None:
    """ScopePlan.cap_hits names the changed files per cap-escalated distribution (spec §4)."""
    plan = _cap_plan(plan_worktree)
    assert plan.cap_hits == {"a": ("packages/a/src/pa/leaf.py",)}
    assert len(plan.cap_impacted["a"]) == 64
    assert int(plan.cap_impacted["a"], 16) >= 0


def test_second_selection_skips_unchanged_cap_suite(plan_worktree: Path) -> None:
    """Green record + identical content omits its cap suite and reports the skipped distribution."""
    first = _cap_plan(plan_worktree)
    record_green_escalation(
        plan_worktree,
        ["a"],
        [],
        first.cap_hits["a"],
        first.cap_impacted,
    )

    second = _cap_plan(plan_worktree)

    assert second.skipped_escalations == ("a",)
    assert all(invocation.distribution != "a" for invocation in second.invocations)
    assert "a: cap escalation skipped — ledger blobs and impacted hash match" in second.notes


def test_cap_skip_rearmed_by_impacted_set_change(plan_worktree: Path) -> None:
    """A new importing test changes the impacted hash and re-arms the cap suite."""
    first = _cap_plan(plan_worktree)
    record_green_escalation(
        plan_worktree,
        ["a"],
        [],
        first.cap_hits["a"],
        first.cap_impacted,
    )
    new_test = plan_worktree / "packages/a/tests/test_second_leaf.py"
    new_test.write_text("import pa.leaf\n")
    _git(plan_worktree, "add", "-A")
    _git(plan_worktree, "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "-m", "add test")

    rearmed = _cap_plan(plan_worktree)

    assert rearmed.skipped_escalations == ()
    assert rearmed.cap_impacted["a"] != first.cap_impacted["a"]
    assert any(invocation.distribution == "a" for invocation in rearmed.invocations)
