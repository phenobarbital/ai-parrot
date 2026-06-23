"""Repo provisioning on ResearchNode (FEAT-250 TASK-006 / FEAT-253 TASK-003).

Verifies:
- _provision_repos returns str(BASE_DIR) when no repos/no git toolkit.
- _provision_repos returns clone path when a repo is declared.
- _provision_repos falls back to BASE_DIR on clone error (FEAT-253 CRITICAL-2).
- execute runs provisioning BEFORE the sdd-research dispatch.
- With a declared repo, the dispatch receives cwd == repo_path (clone).
- With no repo, the dispatch receives cwd == conf.WORKTREE_BASE_PATH (abspath).
- ResearchOutput.repo_path is always set after execute, distinct from worktree_path.
- DevelopmentNode dispatch still uses cwd == research.worktree_path (regression).
"""
from __future__ import annotations

import os
from unittest.mock import AsyncMock, MagicMock

import pytest

from navconfig import BASE_DIR

from parrot.flows.dev_loop import BugBrief, FlowtaskCriterion, ResearchOutput
from parrot.flows.dev_loop.models import RepoSpec
from parrot.flows.dev_loop.nodes.research import ResearchNode


# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------


def _make_brief() -> BugBrief:
    return BugBrief(
        summary="customer sync drops the last row",
        affected_component="etl/customers/sync.yaml",
        log_sources=[],
        acceptance_criteria=[FlowtaskCriterion(name="run", task_path="a.yaml")],
        escalation_assignee="557058:abc",
        reporter="557058:def",
    )


@pytest.fixture
def good_brief() -> BugBrief:
    return _make_brief()


def _make_research_out(tmp_path) -> ResearchOutput:
    wt_path = str(tmp_path / "feat-x-branch")
    return ResearchOutput(
        jira_issue_key="OPS-1",
        spec_path="sdd/specs/x.spec.md",
        feat_id="FEAT-130",
        branch_name="feat-130-novel-branch",
        worktree_path=wt_path,
    )


@pytest.fixture
def research_out_fixture(tmp_path) -> ResearchOutput:
    return _make_research_out(tmp_path)


def _make_node(research_out, *, git_toolkit=None, repos=None, monkeypatch=None,
               tmp_path=None):
    if monkeypatch is not None and tmp_path is not None:
        monkeypatch.setattr(
            "parrot.flows.dev_loop.nodes.research.conf.WORKTREE_BASE_PATH",
            str(tmp_path),
        )
        monkeypatch.setattr(
            "parrot.flows.dev_loop.nodes.research.conf.DEV_LOOP_REPO_BASE_PATH",
            str(tmp_path / "repos"),
        )
    jira = MagicMock()
    jira.jira_create_issue = AsyncMock(return_value={"key": "OPS-1"})
    jira.jira_add_comment = AsyncMock(return_value={"id": "c1"})
    jira.jira_search_issues = AsyncMock(return_value={"status": "empty"})
    dispatcher = MagicMock()
    dispatcher.dispatch = AsyncMock(return_value=research_out)
    node = ResearchNode(
        dispatcher=dispatcher,
        jira_toolkit=jira,
        log_toolkits={},
        git_toolkit=git_toolkit,
        repos=repos,
    )
    # Stub the plan client so no network call is made.
    node._plan_client = MagicMock()
    node._plan_client.ask = AsyncMock(return_value=MagicMock(response="plan."))
    return node


# ---------------------------------------------------------------------------
# _provision_repos — basic behavior
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_provision_repos_local_fallback_returns_base_dir(
    tmp_path,
) -> None:
    """No repos / no git toolkit -> returns str(BASE_DIR), not ''."""
    research_out = _make_research_out(tmp_path)
    node = _make_node(research_out)  # no repos, no git_toolkit
    result = await node._provision_repos("run-001")
    assert result == str(BASE_DIR), (
        f"Expected str(BASE_DIR)={str(BASE_DIR)!r}, got {result!r}"
    )


@pytest.mark.asyncio
async def test_provision_repos_empty_no_clone(research_out_fixture) -> None:
    """FEAT-253: no repos -> local fallback returns str(BASE_DIR), no clone."""
    git = MagicMock()
    git.clone_repo = AsyncMock()
    node = _make_node(research_out_fixture, git_toolkit=git, repos=[])
    primary = await node._provision_repos("run-x")
    assert primary == str(BASE_DIR)
    git.clone_repo.assert_not_called()


@pytest.mark.asyncio
async def test_provision_repos_no_git_toolkit_returns_base_dir(
    tmp_path,
) -> None:
    """Repos declared but no git_toolkit -> local fallback (str(BASE_DIR))."""
    research_out = _make_research_out(tmp_path)
    node = _make_node(
        research_out,
        git_toolkit=None,
        repos=[RepoSpec(alias="nav", url="org/nav")],
    )
    result = await node._provision_repos("run-001")
    assert result == str(BASE_DIR)


@pytest.mark.asyncio
async def test_provision_repos_clones_each(research_out_fixture, monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(
        "parrot.flows.dev_loop.nodes.research.conf.DEV_LOOP_REPO_BASE_PATH",
        str(tmp_path / "repos"),
    )
    git = MagicMock()
    git.clone_repo = AsyncMock(side_effect=lambda url, dest, **kw: {"path": dest})
    node = _make_node(research_out_fixture, git_toolkit=git,
                      repos=[RepoSpec(alias="nav", url="org/nav", branch="dev"),
                             RepoSpec(alias="api", url="org/api")])
    primary = await node._provision_repos("run-x")
    assert git.clone_repo.await_count == 2
    # primary is the first repo's clone path, under the configured base.
    assert primary.endswith("/run-x/nav")
    assert str(tmp_path / "repos") in primary


@pytest.mark.asyncio
async def test_provision_repos_clone_path_anchored(
    tmp_path, monkeypatch
) -> None:
    """Declared repo clones into BASE_DIR/.claude/worktrees/repos/<run_id>/<alias>."""
    monkeypatch.setattr(
        "parrot.flows.dev_loop.nodes.research.conf.DEV_LOOP_REPO_BASE_PATH",
        str(tmp_path / "repos"),
    )
    git = MagicMock()
    git.clone_repo = AsyncMock(side_effect=lambda url, dest, **kw: {"path": dest})
    research_out = _make_research_out(tmp_path)
    node = _make_node(
        research_out,
        git_toolkit=git,
        repos=[RepoSpec(alias="ai-parrot", url="git@github.com:phenobarbital/ai-parrot.git")],
    )
    result = await node._provision_repos("run-123")
    assert result.endswith("/run-123/ai-parrot"), f"Got: {result!r}"
    assert str(tmp_path / "repos") in result


@pytest.mark.asyncio
async def test_provision_repos_passes_private_and_branch(
    research_out_fixture, monkeypatch, tmp_path
) -> None:
    monkeypatch.setattr(
        "parrot.flows.dev_loop.nodes.research.conf.DEV_LOOP_REPO_BASE_PATH",
        str(tmp_path / "repos"),
    )
    git = MagicMock()
    git.clone_repo = AsyncMock(side_effect=lambda url, dest, **kw: {"path": dest})
    node = _make_node(research_out_fixture, git_toolkit=git,
                      repos=[RepoSpec(alias="nav", url="org/nav", branch="dev",
                                      private=True)])
    await node._provision_repos("run-x")
    kwargs = git.clone_repo.await_args.kwargs
    assert kwargs["branch"] == "dev"
    assert kwargs["private"] is True


@pytest.mark.asyncio
async def test_provision_repos_clone_error_falls_back_to_base_dir(
    tmp_path, monkeypatch
) -> None:
    """FEAT-253 CRITICAL-2: clone failure must degrade to BASE_DIR, not raise."""
    monkeypatch.setattr(
        "parrot.flows.dev_loop.nodes.research.conf.DEV_LOOP_REPO_BASE_PATH",
        str(tmp_path / "repos"),
    )
    git = MagicMock()
    git.clone_repo = AsyncMock(side_effect=RuntimeError("network timeout"))
    research_out = _make_research_out(tmp_path)
    node = _make_node(
        research_out,
        git_toolkit=git,
        repos=[RepoSpec(alias="nav", url="org/nav")],
    )
    result = await node._provision_repos("run-err")
    # Must not raise; must fall back gracefully.
    assert result == str(BASE_DIR), (
        f"Expected BASE_DIR fallback on clone error, got {result!r}"
    )


# ---------------------------------------------------------------------------
# execute() ordering and cwd tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_execute_sets_repo_path(research_out_fixture, monkeypatch, tmp_path) -> None:
    git = MagicMock()
    git.clone_repo = AsyncMock(side_effect=lambda url, dest, **kw: {"path": dest})
    node = _make_node(research_out_fixture, git_toolkit=git,
                      repos=[RepoSpec(alias="nav", url="org/nav")],
                      monkeypatch=monkeypatch, tmp_path=tmp_path)
    result = await node.execute({"bug_brief": _make_brief(), "run_id": "run-x"})
    git.clone_repo.assert_awaited_once()
    assert result.repo_path.endswith("/run-x/nav")
    assert str(tmp_path / "repos") in result.repo_path


@pytest.mark.asyncio
async def test_execute_without_repos_sets_repo_path_to_base_dir(
    research_out_fixture, monkeypatch, tmp_path
) -> None:
    """FEAT-253: no repos -> execute sets repo_path to str(BASE_DIR)."""
    node = _make_node(research_out_fixture, git_toolkit=None, repos=[],
                      monkeypatch=monkeypatch, tmp_path=tmp_path)
    result = await node.execute({"bug_brief": _make_brief(), "run_id": "run-x"})
    assert result.repo_path == str(BASE_DIR)


@pytest.mark.asyncio
async def test_provision_runs_before_dispatch(
    tmp_path, monkeypatch
) -> None:
    """_provision_repos must be called before dispatcher.dispatch."""
    call_order: list[str] = []
    research_out = _make_research_out(tmp_path)

    monkeypatch.setattr(
        "parrot.flows.dev_loop.nodes.research.conf.WORKTREE_BASE_PATH",
        str(tmp_path),
    )
    monkeypatch.setattr(
        "parrot.flows.dev_loop.nodes.research.conf.DEV_LOOP_REPO_BASE_PATH",
        str(tmp_path / "repos"),
    )

    git = MagicMock()

    async def clone_and_record(*args, **kwargs):
        call_order.append("provision")
        return {"path": str(tmp_path / "repos" / "run-x" / "nav")}

    git.clone_repo = AsyncMock(side_effect=clone_and_record)
    jira = MagicMock()
    jira.jira_create_issue = AsyncMock(return_value={"key": "OPS-99"})
    jira.jira_add_comment = AsyncMock(return_value={"id": "c1"})
    jira.jira_search_issues = AsyncMock(return_value={"status": "empty"})
    dispatcher = MagicMock()

    async def dispatch_and_record(**kwargs):
        call_order.append("dispatch")
        return research_out

    dispatcher.dispatch = AsyncMock(side_effect=dispatch_and_record)
    node = ResearchNode(
        dispatcher=dispatcher,
        jira_toolkit=jira,
        log_toolkits={},
        git_toolkit=git,
        repos=[RepoSpec(alias="nav", url="org/nav")],
    )
    node._plan_client = MagicMock()
    node._plan_client.ask = AsyncMock(return_value=MagicMock(response="plan."))

    await node.execute({"bug_brief": _make_brief(), "run_id": "run-x"})
    assert call_order == ["provision", "dispatch"], (
        f"Expected provision before dispatch, got: {call_order}"
    )


@pytest.mark.asyncio
async def test_research_dispatch_cwd_is_clone_when_declared(
    tmp_path, monkeypatch
) -> None:
    """With a declared repo, sdd-research dispatch cwd == repo_path (clone)."""
    clone_dest = str(tmp_path / "repos" / "run-x" / "nav")
    research_out = _make_research_out(tmp_path)
    monkeypatch.setattr(
        "parrot.flows.dev_loop.nodes.research.conf.WORKTREE_BASE_PATH",
        str(tmp_path),
    )
    monkeypatch.setattr(
        "parrot.flows.dev_loop.nodes.research.conf.DEV_LOOP_REPO_BASE_PATH",
        str(tmp_path / "repos"),
    )
    git = MagicMock()
    git.clone_repo = AsyncMock(return_value={"path": clone_dest})

    jira = MagicMock()
    jira.jira_create_issue = AsyncMock(return_value={"key": "OPS-99"})
    jira.jira_add_comment = AsyncMock(return_value={"id": "c1"})
    jira.jira_search_issues = AsyncMock(return_value={"status": "empty"})
    dispatcher = MagicMock()
    dispatcher.dispatch = AsyncMock(return_value=research_out)

    node = ResearchNode(
        dispatcher=dispatcher,
        jira_toolkit=jira,
        log_toolkits={},
        git_toolkit=git,
        repos=[RepoSpec(alias="nav", url="org/nav")],
    )
    node._plan_client = MagicMock()
    node._plan_client.ask = AsyncMock(return_value=MagicMock(response="plan."))

    await node.execute({"bug_brief": _make_brief(), "run_id": "run-x"})

    dispatch_kwargs = dispatcher.dispatch.call_args.kwargs
    assert dispatch_kwargs["cwd"] == clone_dest, (
        f"Expected cwd={clone_dest!r}, got {dispatch_kwargs['cwd']!r}"
    )


@pytest.mark.asyncio
async def test_research_dispatch_cwd_is_worktree_base_when_local(
    tmp_path, monkeypatch
) -> None:
    """With no repo declared, sdd-research dispatch cwd == conf.WORKTREE_BASE_PATH."""
    monkeypatch.setattr(
        "parrot.flows.dev_loop.nodes.research.conf.WORKTREE_BASE_PATH",
        str(tmp_path),
    )
    research_out = _make_research_out(tmp_path)
    node = _make_node(
        research_out,
        git_toolkit=None,
        repos=[],
        monkeypatch=monkeypatch,
        tmp_path=tmp_path,
    )

    await node.execute({"bug_brief": _make_brief(), "run_id": "run-x"})

    dispatcher = node._dispatcher
    dispatch_kwargs = dispatcher.dispatch.call_args.kwargs
    expected_cwd = os.path.abspath(str(tmp_path))
    assert dispatch_kwargs["cwd"] == expected_cwd, (
        f"Expected cwd={expected_cwd!r}, got {dispatch_kwargs['cwd']!r}"
    )


@pytest.mark.asyncio
async def test_research_sets_repo_path_distinct_from_worktree(
    tmp_path, monkeypatch
) -> None:
    """ResearchOutput.repo_path is set and is NOT equal to worktree_path."""
    research_out = _make_research_out(tmp_path)
    node = _make_node(
        research_out,
        git_toolkit=None,
        repos=[],
        monkeypatch=monkeypatch,
        tmp_path=tmp_path,
    )
    result = await node.execute({"bug_brief": _make_brief(), "run_id": "run-x"})
    assert result.repo_path, "repo_path should not be empty"
    assert result.repo_path != result.worktree_path, (
        f"repo_path ({result.repo_path!r}) must differ from "
        f"worktree_path ({result.worktree_path!r})"
    )


@pytest.mark.asyncio
async def test_development_cwd_still_worktree_path(
    tmp_path,
) -> None:
    """Regression: DevelopmentNode must use research.worktree_path as cwd (not repo_path).

    DevelopmentNode reads cwd directly from research.worktree_path (development.py:88).
    Ensure repo_path (set by FEAT-253) does NOT leak into the Development dispatch.
    """
    from parrot.flows.dev_loop.nodes.development import DevelopmentNode  # noqa: PLC0415

    wt_path = str(tmp_path / "feat-x-branch")
    os.makedirs(wt_path, exist_ok=True)
    research_out = ResearchOutput(
        jira_issue_key="OPS-99",
        spec_path="sdd/specs/x.spec.md",
        feat_id="FEAT-X",
        branch_name="feat-x-branch",
        worktree_path=wt_path,
        repo_path=str(BASE_DIR),  # different from worktree_path (FEAT-253)
    )

    dev_dispatcher = MagicMock()
    dev_dispatcher.dispatch = AsyncMock(
        return_value=MagicMock(
            worktree_path=wt_path,
            code_diff="",
            commit_sha="abc",
        )
    )
    dev_node = DevelopmentNode(dispatcher=dev_dispatcher)
    ctx = {
        "research_output": research_out,
        "run_id": "run-x",
        "jira_issue_key": "OPS-99",
    }
    await dev_node.execute(ctx)

    dispatch_kwargs = dev_dispatcher.dispatch.call_args.kwargs
    assert dispatch_kwargs["cwd"] == wt_path, (
        f"DevelopmentNode must dispatch with cwd=worktree_path={wt_path!r}, "
        f"got {dispatch_kwargs['cwd']!r}"
    )
