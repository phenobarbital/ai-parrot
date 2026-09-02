"""DevelopmentNode reconciles ``files_changed`` against git.

Coding agents under-report what they touched — they list the source
files they set out to edit and omit the test modules they wrote along
the way. QA scopes its pytest run to these paths, so an omitted test
module is a test that never runs; the handoff nodes render them into the
PR body. Git is the authority, so anything git sees and the agent did not
is appended (never substituted — the agent's own entries survive).
"""

from __future__ import annotations

import subprocess
from unittest.mock import AsyncMock, MagicMock

import pytest

from parrot.flows.dev_loop.models import DevelopmentOutput, ResearchOutput
from parrot.flows.dev_loop.nodes.development import DevelopmentNode


def _git(worktree, *args: str) -> None:
    subprocess.run(["git", *args], cwd=worktree, check=True, capture_output=True)


@pytest.fixture
def repo(tmp_path):
    """A worktree on a feature branch cut from a local ``origin/dev``."""
    origin = tmp_path / "origin"
    origin.mkdir()
    _git(origin, "init", "-q", "-b", "dev")
    _git(origin, "config", "user.email", "t@t.t")
    _git(origin, "config", "user.name", "t")
    (origin / "seed.txt").write_text("seed\n")
    _git(origin, "add", "-A")
    _git(origin, "commit", "-qm", "seed")

    work = tmp_path / "work"
    subprocess.run(
        ["git", "clone", "-q", str(origin), str(work)],
        check=True,
        capture_output=True,
    )
    _git(work, "config", "user.email", "t@t.t")
    _git(work, "config", "user.name", "t")
    _git(work, "checkout", "-q", "-b", "feat-1-x")
    return work


def _research(worktree, base_branch: str = "dev") -> ResearchOutput:
    return ResearchOutput(
        jira_issue_key="OPS-1",
        spec_path="sdd/specs/x.spec.md",
        feat_id="FEAT-1",
        branch_name="feat-1-x",
        worktree_path=str(worktree),
        log_excerpts=[],
        base_branch=base_branch,
    )


def _node(dev_out: DevelopmentOutput) -> tuple[DevelopmentNode, MagicMock]:
    dispatcher = MagicMock()
    dispatcher.dispatch = AsyncMock(return_value=dev_out)
    return DevelopmentNode(dispatcher=dispatcher), dispatcher


@pytest.mark.asyncio
async def test_committed_test_module_the_agent_omitted_is_added(repo):
    """The observed failure: source reported, its new test module not."""
    (repo / "src.py").write_text("x = 1\n")
    (repo / "test_src.py").write_text("def test_x(): pass\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "work")

    dev_out = DevelopmentOutput(files_changed=["src.py"], commit_shas=["a"], summary="s")
    node, _ = _node(dev_out)
    ctx = {"run_id": "r1", "research_output": _research(repo)}

    result = await node.execute(ctx)

    assert result.files_changed == ["src.py", "test_src.py"]
    assert ctx["development_output"] is result


@pytest.mark.asyncio
async def test_uncommitted_and_untracked_files_are_added(repo):
    """A test module written but not yet committed still counts."""
    (repo / "test_new.py").write_text("def test_y(): pass\n")

    dev_out = DevelopmentOutput(files_changed=[], commit_shas=[], summary="s")
    node, _ = _node(dev_out)

    result = await node.execute({"run_id": "r1", "research_output": _research(repo)})

    assert result.files_changed == ["test_new.py"]


@pytest.mark.asyncio
async def test_agent_entries_are_preserved_and_ordered_first(repo):
    """A path git cannot see is kept, not second-guessed away."""
    (repo / "test_src.py").write_text("def test_x(): pass\n")

    dev_out = DevelopmentOutput(
        files_changed=["reverted/elsewhere.py"],
        commit_shas=[],
        summary="s",
    )
    node, _ = _node(dev_out)

    result = await node.execute({"run_id": "r1", "research_output": _research(repo)})

    assert result.files_changed == ["reverted/elsewhere.py", "test_src.py"]


@pytest.mark.asyncio
async def test_nothing_missing_returns_the_same_object(repo):
    """No additions → no copy, so identity-sensitive callers are untouched."""
    (repo / "src.py").write_text("x = 1\n")

    dev_out = DevelopmentOutput(files_changed=["src.py"], commit_shas=[], summary="s")
    node, _ = _node(dev_out)

    result = await node.execute({"run_id": "r1", "research_output": _research(repo)})

    assert result is dev_out


@pytest.mark.asyncio
async def test_non_git_worktree_leaves_the_report_alone(tmp_path):
    dev_out = DevelopmentOutput(files_changed=["a.py"], commit_shas=[], summary="s")
    node, _ = _node(dev_out)

    result = await node.execute({"run_id": "r1", "research_output": _research(tmp_path)})

    assert result is dev_out


@pytest.mark.asyncio
async def test_deletions_are_not_reported_as_changed(repo):
    """A deleted path is nothing downstream can lint, test, or link to."""
    _git(repo, "rm", "-q", "seed.txt")

    dev_out = DevelopmentOutput(files_changed=[], commit_shas=[], summary="s")
    node, _ = _node(dev_out)

    result = await node.execute({"run_id": "r1", "research_output": _research(repo)})

    assert result is dev_out


@pytest.mark.asyncio
async def test_rename_reports_the_new_path_only(repo):
    _git(repo, "mv", "seed.txt", "renamed.txt")

    dev_out = DevelopmentOutput(files_changed=[], commit_shas=[], summary="s")
    node, _ = _node(dev_out)

    result = await node.execute({"run_id": "r1", "research_output": _research(repo)})

    assert result.files_changed == ["renamed.txt"]


@pytest.mark.asyncio
async def test_empty_diff_does_not_fall_through_to_another_base(repo):
    """A branch with nothing committed must not inherit dev's own commits."""
    _git(repo, "checkout", "-q", "-b", "main-ish", "dev")
    (repo / "on_dev_only.py").write_text("x = 1\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "dev-only")
    _git(repo, "checkout", "-q", "feat-1-x")

    dev_out = DevelopmentOutput(files_changed=[], commit_shas=[], summary="s")
    node, _ = _node(dev_out)

    result = await node.execute({"run_id": "r1", "research_output": _research(repo)})

    # origin/dev resolves and its diff is legitimately empty — the
    # ladder must stop there, not retry against another ref.
    assert result is dev_out


@pytest.mark.asyncio
async def test_reconciliation_never_fails_a_successful_dispatch(repo, monkeypatch):
    monkeypatch.setattr(
        DevelopmentNode,
        "_git_changed_files",
        AsyncMock(side_effect=OSError("git exploded")),
    )
    dev_out = DevelopmentOutput(files_changed=["src.py"], commit_shas=[], summary="s")
    node, _ = _node(dev_out)

    result = await node.execute({"run_id": "r1", "research_output": _research(repo)})

    assert result is dev_out
