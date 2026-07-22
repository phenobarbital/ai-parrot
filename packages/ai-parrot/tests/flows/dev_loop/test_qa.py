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
from parrot.flows.dev_loop.models import CodeReviewVerdict
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
            side_effect=[
                QAReport(passed=True, criterion_results=[], lint_passed=True),
                CodeReviewVerdict(passed=True),
            ]
        )
        node = QANode(dispatcher=dispatcher)
        await node.execute(ctx)
        # The FIRST dispatch is the deterministic sdd-qa pass — the SECOND
        # (code-review, FEAT-270) is intentionally write-enabled and is
        # covered separately in test_qa_codereview.py.
        profile: ClaudeCodeDispatchProfile = (
            dispatcher.dispatch.await_args_list[0].kwargs["profile"]
        )
        assert profile.permission_mode == "plan"
        assert "Edit" not in (profile.allowed_tools or [])
        assert "Write" not in (profile.allowed_tools or [])
        assert "Read" in profile.allowed_tools
        assert "Bash" in profile.allowed_tools


class TestSessionHostForwarding:
    """FEAT-322: shared["session_host"] must reach BOTH dispatch() calls —
    the deterministic sdd-qa pass AND the code-review pass (the latter via
    ClaudeCodeReviewDispatcher.review(), which wraps the SAME dispatcher by
    default)."""

    @pytest.mark.asyncio
    async def test_session_host_forwarded_to_both_dispatch_calls(self, ctx):
        dispatcher = MagicMock()
        dispatcher.dispatch = AsyncMock(
            side_effect=[
                QAReport(passed=True, criterion_results=[], lint_passed=True),
                CodeReviewVerdict(passed=True),
            ]
        )
        node = QANode(dispatcher=dispatcher)
        sentinel_host = object()
        ctx["session_host"] = sentinel_host

        await node.execute(ctx)

        deterministic_kwargs = dispatcher.dispatch.await_args_list[0].kwargs
        review_kwargs = dispatcher.dispatch.await_args_list[1].kwargs
        assert deterministic_kwargs["session_host"] is sentinel_host
        assert review_kwargs["session_host"] is sentinel_host

    @pytest.mark.asyncio
    async def test_session_host_none_when_absent(self, ctx):
        dispatcher = MagicMock()
        dispatcher.dispatch = AsyncMock(
            side_effect=[
                QAReport(passed=True, criterion_results=[], lint_passed=True),
                CodeReviewVerdict(passed=True),
            ]
        )
        node = QANode(dispatcher=dispatcher)

        await node.execute(ctx)

        for call in dispatcher.dispatch.await_args_list:
            assert call.kwargs["session_host"] is None


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
        dispatcher.dispatch = AsyncMock(
            side_effect=[failing, CodeReviewVerdict(passed=True)]
        )
        node = QANode(dispatcher=dispatcher)
        result = await node.execute(ctx)
        assert result.passed is False
        assert ctx["qa_report"] is result


class TestSuccessReturnsReport:
    @pytest.mark.asyncio
    async def test_returns_report_on_success(self, ctx):
        passing = QAReport(
            passed=True, criterion_results=[], lint_passed=True
        )
        dispatcher = MagicMock()
        dispatcher.dispatch = AsyncMock(
            side_effect=[passing, CodeReviewVerdict(passed=True)]
        )
        node = QANode(dispatcher=dispatcher)
        result = await node.execute(ctx)
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
            await node.execute(ctx)


class TestCwd:
    @pytest.mark.asyncio
    async def test_cwd_uses_worktree_path(self, ctx):
        passing = QAReport(
            passed=True, criterion_results=[], lint_passed=True
        )
        dispatcher = MagicMock()
        dispatcher.dispatch = AsyncMock(
            side_effect=[passing, CodeReviewVerdict(passed=True)]
        )
        node = QANode(dispatcher=dispatcher)
        await node.execute(ctx)
        assert (
            dispatcher.dispatch.await_args_list[0].kwargs["cwd"]
            == ctx["research_output"].worktree_path
        )
