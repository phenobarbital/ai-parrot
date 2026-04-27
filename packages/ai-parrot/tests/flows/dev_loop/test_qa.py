"""Unit tests for parrot.flows.dev_loop.nodes.qa (TASK-883)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from parrot.flows.dev_loop import (
    BugBrief,
    ClaudeCodeDispatchProfile,
    DispatchOutputValidationError,
    FlowtaskCriterion,
    QAReport,
    ResearchOutput,
)
from parrot.flows.dev_loop.nodes.qa import QANode


@pytest.fixture
def ctx() -> dict:
    return {
        "run_id": "r1",
        "research_output": ResearchOutput(
            jira_issue_key="OPS-1",
            spec_path="x",
            feat_id="FEAT-130",
            branch_name="feat-130-fix",
            worktree_path="/abs/.claude/worktrees/feat-130-fix",
            log_excerpts=[],
        ),
        "bug_brief": BugBrief(
            summary="x" * 20,
            affected_component="y",
            log_sources=[],
            acceptance_criteria=[
                FlowtaskCriterion(name="run", task_path="a.yaml"),
            ],
            escalation_assignee="a",
            reporter="b",
        ),
    }


class TestPermissionMode:
    @pytest.mark.asyncio
    async def test_uses_plan_permission_no_edit_write(self, ctx):
        dispatcher = MagicMock()
        dispatcher.dispatch = AsyncMock(
            return_value=QAReport(
                passed=True, criterion_results=[], lint_passed=True
            )
        )
        node = QANode(dispatcher=dispatcher)
        await node.execute(prompt="", ctx=ctx)
        profile: ClaudeCodeDispatchProfile = (
            dispatcher.dispatch.await_args.kwargs["profile"]
        )
        assert profile.permission_mode == "plan"
        assert "Edit" not in (profile.allowed_tools or [])
        assert "Write" not in (profile.allowed_tools or [])
        assert "Read" in profile.allowed_tools
        assert "Bash" in profile.allowed_tools


class TestFailureDoesNotRaise:
    @pytest.mark.asyncio
    async def test_returns_failure_without_raising(self, ctx):
        failing = QAReport(
            passed=False,
            criterion_results=[],
            lint_passed=False,
            notes="boom",
        )
        dispatcher = MagicMock()
        dispatcher.dispatch = AsyncMock(return_value=failing)
        node = QANode(dispatcher=dispatcher)
        result = await node.execute(prompt="", ctx=ctx)
        assert result.passed is False
        assert ctx["qa_report"] is result


class TestSuccessReturnsReport:
    @pytest.mark.asyncio
    async def test_returns_report_on_success(self, ctx):
        passing = QAReport(
            passed=True, criterion_results=[], lint_passed=True
        )
        dispatcher = MagicMock()
        dispatcher.dispatch = AsyncMock(return_value=passing)
        node = QANode(dispatcher=dispatcher)
        result = await node.execute(prompt="", ctx=ctx)
        assert result.passed is True


class TestDispatchValidationErrorPropagates:
    @pytest.mark.asyncio
    async def test_dispatcher_validation_error_bubbles_up(self, ctx):
        dispatcher = MagicMock()
        dispatcher.dispatch = AsyncMock(
            side_effect=DispatchOutputValidationError(
                "no JSON", raw_payload=""
            )
        )
        node = QANode(dispatcher=dispatcher)
        with pytest.raises(DispatchOutputValidationError):
            await node.execute(prompt="", ctx=ctx)


class TestCwd:
    @pytest.mark.asyncio
    async def test_cwd_uses_worktree_path(self, ctx):
        passing = QAReport(
            passed=True, criterion_results=[], lint_passed=True
        )
        dispatcher = MagicMock()
        dispatcher.dispatch = AsyncMock(return_value=passing)
        node = QANode(dispatcher=dispatcher)
        await node.execute(prompt="", ctx=ctx)
        assert (
            dispatcher.dispatch.await_args.kwargs["cwd"]
            == ctx["research_output"].worktree_path
        )
