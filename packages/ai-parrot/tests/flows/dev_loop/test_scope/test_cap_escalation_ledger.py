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
    """Select one changed module with a cap that truncates direct importers."""
    return plan_tests(
        worktree=worktree,
        changed_files=["packages/a/src/pa/leaf.py"],
        tier="merge",
        policy=ScopePolicy(impact_cap=0, core_fanin_threshold=999),
    )


def test_plan_reports_cap_as_note_only(plan_worktree: Path) -> None:
    """The selector no longer populates escalation-ledger metadata for caps."""
    plan = _cap_plan(plan_worktree)
    assert plan.cap_hits == {}
    assert plan.cap_impacted == {}
    assert plan.escalated == ()
    assert "a: 1 impacted tests exceed cap 0; kept 0, rest covered by nightly" in plan.notes


def test_selection_is_independent_of_existing_ledger(plan_worktree: Path) -> None:
    """An existing ledger record cannot suppress the bounded mirror target."""
    record_green_escalation(plan_worktree, ["a"], [], ["packages/a/src/pa/leaf.py"], {"a": "old-hash"})

    plan = _cap_plan(plan_worktree)

    assert plan.skipped_escalations == ()
    assert [target.path for invocation in plan.invocations for target in invocation.targets] == [
        "packages/a/tests/test_leaf.py"
    ]


def test_cap_note_updates_when_impacted_set_changes(plan_worktree: Path) -> None:
    """A new importing test updates the bounded-fallback note, never ledger metadata."""
    new_test = plan_worktree / "packages/a/tests/test_second_leaf.py"
    new_test.write_text("import pa.leaf\n")
    _git(plan_worktree, "add", "-A")
    _git(plan_worktree, "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "-m", "add test")

    plan = _cap_plan(plan_worktree)

    assert plan.skipped_escalations == ()
    assert plan.cap_impacted == {}
    assert "a: 2 impacted tests exceed cap 0; kept 0, rest covered by nightly" in plan.notes
