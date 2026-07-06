"""QANode additive code-review gate (FEAT-250 TASK-008, extended FEAT-270)."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from parrot.flows.dev_loop import (
    BugBrief,
    FlowtaskCriterion,
    QAReport,
    ResearchOutput,
)
from parrot.flows.dev_loop.models import CodeReviewFinding, CodeReviewVerdict
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
        ),
        "bug_brief": BugBrief(
            summary="x" * 20,
            affected_component="y",
            log_sources=[],
            acceptance_criteria=[FlowtaskCriterion(name="run", task_path="a.yaml")],
            escalation_assignee="a",
            reporter="b",
        ),
    }


def _dispatcher(qa_report, verdict_or_exc):
    """Backward-compat dispatcher double.

    QANode's default (no ``codereview_dispatcher`` supplied) wraps this same
    dispatcher in a ``ClaudeCodeReviewDispatcher``, so ``dispatch()`` is
    called twice: once for the deterministic ``sdd-qa`` pass, once for the
    code-review pass (``output_model=CodeReviewVerdict``).
    """
    d = MagicMock()
    d.dispatch = AsyncMock(side_effect=[qa_report, verdict_or_exc])
    return d


@pytest.mark.asyncio
async def test_qa_codereview_gate_blocks_on_fail(ctx):
    qa = QAReport(passed=True, criterion_results=[], lint_passed=True)
    verdict = CodeReviewVerdict(
        passed=False,
        findings=[CodeReviewFinding(message="AC not met", severity="major")],
        summary="nope",
    )
    node = QANode(dispatcher=_dispatcher(qa, verdict))
    report = await node.execute(ctx)
    assert report.passed is False
    assert report.code_review_passed is False
    assert report.code_review_findings == ["AC not met"]


@pytest.mark.asyncio
async def test_qa_codereview_passes_when_both_pass(ctx):
    qa = QAReport(passed=True, criterion_results=[], lint_passed=True)
    verdict = CodeReviewVerdict(passed=True, findings=[])
    node = QANode(dispatcher=_dispatcher(qa, verdict))
    report = await node.execute(ctx)
    assert report.passed is True
    assert report.code_review_passed is True
    assert report.code_review_findings == []


@pytest.mark.asyncio
async def test_deterministic_fail_keeps_run_failed(ctx):
    qa = QAReport(passed=False, criterion_results=[], lint_passed=False)
    verdict = CodeReviewVerdict(passed=True, findings=[])
    node = QANode(dispatcher=_dispatcher(qa, verdict))
    report = await node.execute(ctx)
    # Deterministic gate already failed → overall fail even if review passes.
    assert report.passed is False
    assert report.code_review_passed is True


@pytest.mark.asyncio
async def test_qa_codereview_dispatch_is_write_enabled(ctx):
    """FEAT-270: the default reviewer profile is write-enabled (not read-only)."""
    qa = QAReport(passed=True, criterion_results=[], lint_passed=True)
    verdict = CodeReviewVerdict(passed=True, findings=[])
    node = QANode(dispatcher=_dispatcher(qa, verdict))
    await node.execute(ctx)
    # The SECOND dispatch is the code-review gate.
    cr_profile = node._dispatcher.dispatch.await_args_list[1].kwargs["profile"]
    assert cr_profile.subagent == "sdd-codereview"
    assert cr_profile.permission_mode == "default"
    assert "Edit" in cr_profile.allowed_tools
    assert "Write" in cr_profile.allowed_tools


@pytest.mark.asyncio
async def test_codereview_dispatch_error_does_not_block(ctx):
    qa = QAReport(passed=True, criterion_results=[], lint_passed=True)
    node = QANode(dispatcher=_dispatcher(qa, RuntimeError("infra down")))
    report = await node.execute(ctx)  # must not raise
    assert report.passed is True
    assert report.code_review_passed is True
    assert any("could not run" in f for f in report.code_review_findings)


@pytest.mark.asyncio
async def test_codereview_cwd_prefers_repo_path(ctx):
    ctx["research_output"] = ctx["research_output"].model_copy(
        update={"repo_path": "/abs/.claude/worktrees/repos/r1/nav"}
    )
    qa = QAReport(passed=True, criterion_results=[], lint_passed=True)
    verdict = CodeReviewVerdict(passed=True, findings=[])
    node = QANode(dispatcher=_dispatcher(qa, verdict))
    await node.execute(ctx)
    cr_cwd = node._dispatcher.dispatch.await_args_list[1].kwargs["cwd"]
    assert cr_cwd == "/abs/.claude/worktrees/repos/r1/nav"


@pytest.mark.asyncio
async def test_rerun_after_fix(ctx):
    """When reviewer fixes files, deterministic QA re-runs (FEAT-270)."""
    qa = QAReport(passed=True, criterion_results=[], lint_passed=True)
    verdict = CodeReviewVerdict(
        passed=True, findings=[], files_modified=["sync.py"]
    )
    rerun_qa = QAReport(passed=True, criterion_results=[], lint_passed=True)
    dispatcher = MagicMock()
    dispatcher.dispatch = AsyncMock(side_effect=[qa, verdict, rerun_qa])
    node = QANode(dispatcher=dispatcher)
    report = await node.execute(ctx)
    assert report.passed is True
    assert dispatcher.dispatch.await_count == 3


@pytest.mark.asyncio
async def test_skip_rerun_no_fixes(ctx):
    """When reviewer passes with no fixes, skip re-run (FEAT-270)."""
    qa = QAReport(passed=True, criterion_results=[], lint_passed=True)
    verdict = CodeReviewVerdict(passed=True, findings=[], files_modified=[])
    dispatcher = MagicMock()
    dispatcher.dispatch = AsyncMock(side_effect=[qa, verdict])
    node = QANode(dispatcher=dispatcher)
    report = await node.execute(ctx)
    assert report.passed is True
    assert dispatcher.dispatch.await_count == 2


@pytest.mark.asyncio
async def test_rerun_fails_after_fix(ctx):
    """When re-run fails after reviewer fix, QA fails (FEAT-270)."""
    qa = QAReport(passed=True, criterion_results=[], lint_passed=True)
    verdict = CodeReviewVerdict(
        passed=True, findings=[], files_modified=["sync.py"]
    )
    rerun_qa = QAReport(passed=False, criterion_results=[], lint_passed=False)
    dispatcher = MagicMock()
    dispatcher.dispatch = AsyncMock(side_effect=[qa, verdict, rerun_qa])
    node = QANode(dispatcher=dispatcher)
    report = await node.execute(ctx)
    assert report.passed is False


@pytest.mark.asyncio
async def test_backward_compat_no_reviewer(ctx):
    """QANode without codereview_dispatcher auto-creates Claude reviewer."""
    node = QANode(dispatcher=MagicMock())
    assert hasattr(node, "_codereview_dispatcher")


@pytest.mark.asyncio
async def test_custom_codereview_dispatcher_used(ctx):
    """An explicit codereview_dispatcher is used instead of the default."""
    qa = QAReport(passed=True, criterion_results=[], lint_passed=True)
    dispatcher = MagicMock()
    dispatcher.dispatch = AsyncMock(return_value=qa)
    mock_reviewer = MagicMock()
    mock_reviewer.review = AsyncMock(
        return_value=CodeReviewVerdict(passed=True, findings=[])
    )
    node = QANode(dispatcher=dispatcher, codereview_dispatcher=mock_reviewer)
    report = await node.execute(ctx)
    assert report.passed is True
    mock_reviewer.review.assert_awaited_once()
    # Only the deterministic pass goes through the plain dispatcher.
    dispatcher.dispatch.assert_awaited_once()
