"""Unit tests for DevLoopCloseNode (FEAT-250 TASK-009)."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from parrot.flows.dev_loop.models import QAReport, ResearchOutput
from parrot.flows.dev_loop.nodes.close import DevLoopCloseNode


@pytest.fixture
def research() -> ResearchOutput:
    return ResearchOutput(
        jira_issue_key="OPS-1",
        spec_path="x",
        feat_id="FEAT-130",
        branch_name="feat-130-fix",
        worktree_path="/abs/.claude/worktrees/feat-130-fix",
    )


@pytest.fixture
def jira() -> MagicMock:
    j = MagicMock()
    j.jira_add_comment = AsyncMock(return_value={"id": "c1"})
    j.jira_transition_issue = AsyncMock(return_value={"ok": True})
    # FEAT: helper now prefers the workflow-path walker; it falls back to a
    # single direct hop internally when no path is declared.
    j.jira_transition_to = AsyncMock(return_value={"ok": True})
    return j


def test_close_node_default_id_matches_graph():
    # The graph wires this node as "close" (definition.py CLOSE); the default
    # node_id must match so a factory-less construction is still dispatchable.
    assert DevLoopCloseNode(jira_toolkit=MagicMock()).node_id == "close"


@pytest.mark.asyncio
async def test_close_node_transitions_jira_initial(research, jira):
    ctx = {
        "research_output": research,
        "qa_report": QAReport(passed=True, criterion_results=[], lint_passed=True),
        "deployment_result": {"pr_url": "https://github.com/o/r/pull/5", "pr_number": 5},
    }
    node = DevLoopCloseNode(jira_toolkit=jira)
    out = await node.execute(ctx, deps=None)
    assert out["status"] == "closed"
    assert out["mode"] == "initial"
    jira.jira_add_comment.assert_awaited_once()
    jira.jira_transition_to.assert_awaited_once_with(
        issue="OPS-1", target_status="Ready to Deploy"
    )


@pytest.mark.asyncio
async def test_close_node_revision_transition(research, jira):
    ctx = {
        "research_output": research,
        "mode": "revision",
        "revision_result": {"pr_number": 5},
    }
    node = DevLoopCloseNode(jira_toolkit=jira)
    out = await node.execute(ctx, deps=None)
    assert out["status"] == "closed"
    assert out["mode"] == "revision"
    jira.jira_transition_to.assert_awaited_once_with(
        issue="OPS-1", target_status="In Review – revised"
    )


@pytest.mark.asyncio
async def test_close_node_without_ticket(jira):
    node = DevLoopCloseNode(jira_toolkit=jira)
    out = await node.execute({}, deps=None)
    assert out["status"] == "closed_without_ticket"
    jira.jira_add_comment.assert_not_called()


@pytest.mark.asyncio
async def test_close_node_degrades_on_jira_error(research):
    jira = MagicMock()
    jira.jira_add_comment = AsyncMock(side_effect=RuntimeError("jira down"))
    jira.jira_transition_issue = AsyncMock()
    node = DevLoopCloseNode(jira_toolkit=jira)
    out = await node.execute({"research_output": research}, deps=None)
    assert out["status"] == "close_failed"
    assert out["issue_key"] == "OPS-1"
    assert "jira down" in out["error"]


@pytest.mark.asyncio
async def test_close_node_includes_codereview_findings(research, jira):
    ctx = {
        "research_output": research,
        "qa_report": QAReport(
            passed=True,
            criterion_results=[],
            lint_passed=True,
            code_review_passed=True,
            code_review_findings=["nit: rename foo"],
        ),
    }
    node = DevLoopCloseNode(jira_toolkit=jira)
    await node.execute(ctx, deps=None)
    body = jira.jira_add_comment.await_args.kwargs["body"]
    assert "nit: rename foo" in body
