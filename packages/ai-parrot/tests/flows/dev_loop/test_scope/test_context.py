"""Attempt context + escalation ledger tests on real temp git repos/worktrees (FEAT-563 M3)."""

import subprocess
from pathlib import Path

import pytest

from parrot.flows.dev_loop.test_scope import AttemptContext, CoreHit
from parrot.flows.dev_loop.test_scope import context as ctxmod


def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init", "-q")
    _git(root, "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "--allow-empty", "-m", "init")
    (root / "core.py").write_text("x = 1\n")
    return root


@pytest.fixture
def linked(repo: Path, tmp_path: Path) -> Path:
    wt = tmp_path / "wt"
    _git(repo, "worktree", "add", "-q", str(wt))
    (wt / "core.py").write_text("x = 1\n")
    return wt


def test_context_in_per_worktree_gitdir(repo: Path, linked: Path):
    ctx = AttemptContext(tier="task", task_id="TASK-1", task_file="sdd/tasks/active/TASK-1-x.md", base_ref="feat-x")
    path = ctxmod.write_attempt_context(linked, ctx)
    assert path.parent != repo / ".git"
    assert "worktrees" in path.parts
    assert not (linked / ctxmod.CONTEXT_FILENAME).exists()
    assert ctxmod.read_attempt_context(linked) == ctx
    assert ctxmod.read_attempt_context(repo) is None


def test_malformed_context_is_inactive(linked: Path):
    git_dir = ctxmod.worktree_git_dir(linked)
    (git_dir / ctxmod.CONTEXT_FILENAME).write_text("{not json")
    assert ctxmod.read_attempt_context(linked) is None


def test_ledger_skips_green_same_content(linked: Path):
    hit = CoreHit(path="core.py", module="core", fanin=60, forced=False, distributions=("a", "b"))
    assert ctxmod.pending_escalations(linked, [hit]) == (["a", "b"], [])
    ctxmod.record_green_escalation(linked, ["a"], ["core.py"])
    assert ctxmod.pending_escalations(linked, [hit]) == (["b"], ["a"])


def test_ledger_rearms_on_content_change(linked: Path):
    hit = CoreHit(path="core.py", module="core", fanin=60, forced=True, distributions=("a",))
    ctxmod.record_green_escalation(linked, ["a"], ["core.py"])
    (linked / "core.py").write_text("x = 2\n")
    assert ctxmod.pending_escalations(linked, [hit]) == (["a"], [])


def test_ledger_rearms_on_a_red_run_even_with_unchanged_content(linked: Path):
    """FEAT-563 review (R14/AC9c): "any content change **or red run** re-arms it" — record_red_run
    is the writer for the second half; record_green_escalation alone never covers this case."""
    hit = CoreHit(path="core.py", module="core", fanin=60, forced=True, distributions=("a", "b"))
    ctxmod.record_green_escalation(linked, ["a", "b"], ["core.py"])
    assert ctxmod.pending_escalations(linked, [hit]) == ([], ["a", "b"])  # both skipped, still green
    ctxmod.record_red_run(linked, ["a"])
    # "a" re-armed by the red run; "b" is untouched and still correctly skipped.
    assert ctxmod.pending_escalations(linked, [hit]) == (["a"], ["b"])


def test_record_red_run_on_a_distribution_with_no_ledger_entry_is_a_no_op(linked: Path):
    ctxmod.record_red_run(linked, ["never-recorded"])  # must not raise or create a spurious entry
    assert ctxmod.read_ledger(linked) == {}


def test_malformed_ledger_is_empty(linked: Path):
    (ctxmod.worktree_git_dir(linked) / ctxmod.LEDGER_FILENAME).write_text('{"a": 3}')
    assert ctxmod.read_ledger(linked) == {}
