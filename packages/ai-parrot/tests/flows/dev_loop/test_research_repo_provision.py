"""Repo provisioning on ResearchNode (FEAT-250 TASK-006)."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from parrot.flows.dev_loop import BugBrief, FlowtaskCriterion, ResearchOutput
from parrot.flows.dev_loop.models import RepoSpec
from parrot.flows.dev_loop.nodes.research import ResearchNode


@pytest.fixture
def good_brief() -> BugBrief:
    return BugBrief(
        summary="customer sync drops the last row",
        affected_component="etl/customers/sync.yaml",
        log_sources=[],
        acceptance_criteria=[FlowtaskCriterion(name="run", task_path="a.yaml")],
        escalation_assignee="557058:abc",
        reporter="557058:def",
    )


@pytest.fixture
def research_out_fixture(tmp_path) -> ResearchOutput:
    return ResearchOutput(
        jira_issue_key="OPS-1",
        spec_path="sdd/specs/x.spec.md",
        feat_id="FEAT-130",
        branch_name="feat-130-novel-branch",
        worktree_path=str(tmp_path / "feat-130-novel-branch"),
    )


def _make_node(research_out, *, git_toolkit=None, repos=None, monkeypatch=None,
               tmp_path=None):
    if monkeypatch is not None:
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


# ── direct provisioning helper ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_provision_repos_clones_each(research_out_fixture, monkeypatch, tmp_path):
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
async def test_provision_repos_empty_no_clone(research_out_fixture):
    git = MagicMock()
    git.clone_repo = AsyncMock()
    node = _make_node(research_out_fixture, git_toolkit=git, repos=[])
    primary = await node._provision_repos("run-x")
    assert primary == ""
    git.clone_repo.assert_not_called()


@pytest.mark.asyncio
async def test_provision_repos_passes_private_and_branch(research_out_fixture, monkeypatch, tmp_path):
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


# ── execute-level wiring ───────────────────────────────────────────────


@pytest.mark.asyncio
async def test_execute_sets_repo_path(research_out_fixture, monkeypatch, tmp_path):
    git = MagicMock()
    git.clone_repo = AsyncMock(side_effect=lambda url, dest, **kw: {"path": dest})
    node = _make_node(research_out_fixture, git_toolkit=git,
                      repos=[RepoSpec(alias="nav", url="org/nav")],
                      monkeypatch=monkeypatch, tmp_path=tmp_path)
    brief = BugBrief(
        summary="customer sync drops the last row",
        affected_component="etl/customers/sync.yaml",
        log_sources=[],
        acceptance_criteria=[FlowtaskCriterion(name="run", task_path="a.yaml")],
        escalation_assignee="557058:abc",
        reporter="557058:def",
    )
    result = await node.execute({"bug_brief": brief, "run_id": "run-x"})
    git.clone_repo.assert_awaited_once()
    assert result.repo_path.endswith("/run-x/nav")
    assert str(tmp_path / "repos") in result.repo_path


@pytest.mark.asyncio
async def test_execute_without_repos_leaves_repo_path_empty(
    research_out_fixture, monkeypatch, tmp_path
):
    node = _make_node(research_out_fixture, git_toolkit=None, repos=[],
                      monkeypatch=monkeypatch, tmp_path=tmp_path)
    brief = BugBrief(
        summary="customer sync drops the last row",
        affected_component="etl/customers/sync.yaml",
        log_sources=[],
        acceptance_criteria=[FlowtaskCriterion(name="run", task_path="a.yaml")],
        escalation_assignee="557058:abc",
        reporter="557058:def",
    )
    result = await node.execute({"bug_brief": brief, "run_id": "run-x"})
    assert result.repo_path == ""
