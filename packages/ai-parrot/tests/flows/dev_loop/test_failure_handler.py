"""Unit tests for parrot.flows.dev_loop.nodes.failure_handler (TASK-885)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from parrot.flows.dev_loop import (
    BugBrief,
    CriterionResult,
    FlowtaskCriterion,
    QAReport,
    ResearchOutput,
)
from parrot.flows.dev_loop.nodes.failure_handler import FailureHandlerNode


@pytest.fixture
def brief() -> BugBrief:
    return BugBrief(
        summary="x" * 20,
        affected_component="y",
        log_sources=[],
        acceptance_criteria=[
            FlowtaskCriterion(name="x", task_path="a.yaml")
        ],
        escalation_assignee="557058:human",
        reporter="557058:other",
    )


@pytest.fixture
def research() -> ResearchOutput:
    return ResearchOutput(
        jira_issue_key="OPS-1",
        spec_path="x",
        feat_id="FEAT-130",
        branch_name="feat-130-fix",
        worktree_path="/abs/.claude/worktrees/feat-130-fix",
        log_excerpts=[],
    )


@pytest.fixture
def jira() -> MagicMock:
    j = MagicMock()
    j.jira_add_comment = AsyncMock(return_value={"id": "c1"})
    j.jira_transition_issue = AsyncMock(return_value={"ok": True})
    # FEAT-377 TASK-1907: FailureHandlerNode now routes through
    # transition_issue_with_candidates, which prefers the workflow-path
    # walker (see deployment_handoff.py / close.py fixtures for the same
    # pattern).
    j.jira_transition_to = AsyncMock(return_value={"ok": True})
    j.jira_assign_issue = AsyncMock(return_value={"ok": True})
    return j


class TestQAFailedPath:
    @pytest.mark.asyncio
    async def test_reassigns_to_escalation(self, jira, brief, research):
        qa = QAReport(
            passed=False,
            criterion_results=[
                CriterionResult(
                    name="run",
                    kind="flowtask",
                    exit_code=1,
                    duration_seconds=1.0,
                    stdout_tail="",
                    stderr_tail="boom",
                    passed=False,
                )
            ],
            lint_passed=True,
        )
        node = FailureHandlerNode(jira_toolkit=jira)
        ctx = {
            "bug_brief": brief,
            "research_output": research,
            "failure_kind": "qa_failed",
            "failure_payload": qa,
        }
        result = await node.execute(ctx)
        assert result == {"status": "escalated", "issue_key": "OPS-1"}
        jira.jira_assign_issue.assert_awaited_with(
            issue="OPS-1", assignee="557058:human"
        )

    @pytest.mark.asyncio
    async def test_comment_includes_criterion_results(
        self, jira, brief, research
    ):
        qa = QAReport(
            passed=False,
            criterion_results=[
                CriterionResult(
                    name="customers-sync",
                    kind="flowtask",
                    exit_code=42,
                    duration_seconds=1.0,
                    stdout_tail="",
                    stderr_tail="boom",
                    passed=False,
                )
            ],
            lint_passed=True,
        )
        node = FailureHandlerNode(jira_toolkit=jira)
        ctx = {
            "bug_brief": brief,
            "research_output": research,
            "failure_kind": "qa_failed",
            "failure_payload": qa,
        }
        await node.execute(ctx)
        body = jira.jira_add_comment.await_args.kwargs["body"]
        assert "customers-sync" in body
        assert "exit=42" in body


class TestNodeErrorPath:
    @pytest.mark.asyncio
    async def test_comment_includes_node_and_exception(
        self, jira, brief, research
    ):
        node = FailureHandlerNode(jira_toolkit=jira)
        ctx = {
            "bug_brief": brief,
            "research_output": research,
            "failure_kind": "node_error",
            "failure_payload": {
                "node_id": "development",
                "exception_type": "DispatchExecutionError",
                "message": "transport lost",
            },
        }
        await node.execute(ctx)
        body = jira.jira_add_comment.await_args.kwargs["body"]
        assert "development" in body
        assert "DispatchExecutionError" in body


class TestNoTicket:
    @pytest.mark.asyncio
    async def test_returns_special_status_when_no_research(self, jira, brief):
        node = FailureHandlerNode(jira_toolkit=jira)
        ctx = {
            "bug_brief": brief,
            "failure_kind": "node_error",
            "failure_payload": {},
        }
        result = await node.execute(ctx)
        assert result == {"status": "escalated_without_ticket"}
        jira.jira_add_comment.assert_not_awaited()


class TestNeverRaises:
    @pytest.mark.asyncio
    async def test_jira_failure_returns_structured_error(
        self, jira, brief, research
    ):
        jira.jira_add_comment = AsyncMock(side_effect=RuntimeError("API down"))
        node = FailureHandlerNode(jira_toolkit=jira)
        ctx = {
            "bug_brief": brief,
            "research_output": research,
            "failure_kind": "node_error",
            "failure_payload": {"node_id": "x", "exception_type": "y"},
        }
        result = await node.execute(ctx)
        assert result["status"] == "escalation_failed"
        assert "API down" in result["error"]


class TestTransitionCandidates:
    """FEAT-377 TASK-1907: replaces the hard-coded 'Needs Human Review'
    transition with an ordered-candidates fallback, matching
    deployment_handoff.py / close.py."""

    @pytest.mark.asyncio
    async def test_uses_preferred_transition_when_available(
        self, jira, brief, research
    ):
        node = FailureHandlerNode(jira_toolkit=jira)
        ctx = {
            "bug_brief": brief,
            "research_output": research,
            "failure_kind": "node_error",
            "failure_payload": {"node_id": "x", "exception_type": "y"},
        }
        result = await node.execute(ctx)
        assert result == {"status": "escalated", "issue_key": "OPS-1"}
        jira.jira_transition_to.assert_awaited_once_with(
            issue="OPS-1", target_status="Needs Human Review"
        )

    @pytest.mark.asyncio
    async def test_falls_through_candidates_when_workflow_lacks_preferred(
        self, jira, brief, research
    ):
        """A workflow without 'Needs Human Review' or 'Blocked' still
        succeeds by falling through to 'To Do'."""

        async def _transition_to(*, issue: str, target_status: str, **_kw):
            if target_status in ("Needs Human Review", "Blocked"):
                raise ValueError(
                    f"Invalid transition {target_status!r} for {issue}."
                )
            return {"ok": True, "applied": target_status}

        jira.jira_transition_to = AsyncMock(side_effect=_transition_to)
        node = FailureHandlerNode(jira_toolkit=jira)
        ctx = {
            "bug_brief": brief,
            "research_output": research,
            "failure_kind": "node_error",
            "failure_payload": {"node_id": "x", "exception_type": "y"},
        }
        result = await node.execute(ctx)
        assert result == {"status": "escalated", "issue_key": "OPS-1"}
        assert jira.jira_transition_to.await_count == 3
        jira.jira_transition_to.assert_awaited_with(
            issue="OPS-1", target_status="To Do"
        )
