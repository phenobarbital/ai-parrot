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
                CodeReviewVerdict(passed=True),
                QAReport(passed=True, criterion_results=[], lint_passed=True),
            ]
        )
        node = QANode(dispatcher=dispatcher)
        await node.execute(ctx)
        # Write-enabled reviewers run FIRST (so their fixes land before the
        # deterministic pass). The deterministic sdd-qa pass is the SECOND
        # dispatch; code-review is covered in test_qa_codereview.py.
        profile: ClaudeCodeDispatchProfile = (
            dispatcher.dispatch.await_args_list[1].kwargs["profile"]
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
                CodeReviewVerdict(passed=True),
                QAReport(passed=True, criterion_results=[], lint_passed=True),
            ]
        )
        node = QANode(dispatcher=dispatcher)
        sentinel_host = object()
        ctx["session_host"] = sentinel_host

        await node.execute(ctx)

        review_kwargs = dispatcher.dispatch.await_args_list[0].kwargs
        deterministic_kwargs = dispatcher.dispatch.await_args_list[1].kwargs
        assert deterministic_kwargs["session_host"] is sentinel_host
        assert review_kwargs["session_host"] is sentinel_host

    @pytest.mark.asyncio
    async def test_session_host_none_when_absent(self, ctx):
        dispatcher = MagicMock()
        dispatcher.dispatch = AsyncMock(
            side_effect=[
                CodeReviewVerdict(passed=True),
                QAReport(passed=True, criterion_results=[], lint_passed=True),
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
            side_effect=[CodeReviewVerdict(passed=True), failing]
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
            side_effect=[CodeReviewVerdict(passed=True), passing]
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


class TestSkipQA:
    @pytest.mark.asyncio
    async def test_skip_qa_returns_synthetic_pass(self, ctx):
        dispatcher = MagicMock()
        dispatcher.dispatch = AsyncMock()
        node = QANode(dispatcher=dispatcher, skip_qa=True)
        result = await node.execute(ctx)

        assert result.passed is True
        assert result.lint_passed is True
        assert result.code_review_passed is True
        assert "skip_qa=True" in result.notes
        assert ctx["qa_report"] is result
        dispatcher.dispatch.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_skip_qa_false_runs_normally(self, ctx):
        dispatcher = MagicMock()
        dispatcher.dispatch = AsyncMock(
            side_effect=[
                CodeReviewVerdict(passed=True),
                QAReport(passed=True, criterion_results=[], lint_passed=True),
            ]
        )
        node = QANode(dispatcher=dispatcher, skip_qa=False)
        result = await node.execute(ctx)

        assert result.passed is True
        assert dispatcher.dispatch.await_count == 2


class TestCwd:
    @pytest.mark.asyncio
    async def test_cwd_uses_worktree_path(self, ctx):
        passing = QAReport(
            passed=True, criterion_results=[], lint_passed=True
        )
        dispatcher = MagicMock()
        dispatcher.dispatch = AsyncMock(
            side_effect=[CodeReviewVerdict(passed=True), passing]
        )
        node = QANode(dispatcher=dispatcher)
        await node.execute(ctx)
        # Deterministic QA is the second dispatch (after code review)
        assert (
            dispatcher.dispatch.await_args_list[1].kwargs["cwd"]
            == ctx["research_output"].worktree_path
        )
