"""QANode additive code-review gate (FEAT-250 TASK-008)."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from parrot.flows.dev_loop import (
    BugBrief,
    FlowtaskCriterion,
    QAReport,
    ResearchOutput,
)
from parrot.flows.dev_loop.nodes.qa import QANode, _CodeReviewVerdict


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
    d = MagicMock()
    if isinstance(verdict_or_exc, Exception):
        d.dispatch = AsyncMock(side_effect=[qa_report, verdict_or_exc])
    else:
        d.dispatch = AsyncMock(side_effect=[qa_report, verdict_or_exc])
    return d


@pytest.mark.asyncio
async def test_qa_codereview_gate_blocks_on_fail(ctx):
    qa = QAReport(passed=True, criterion_results=[], lint_passed=True)
    verdict = _CodeReviewVerdict(passed=False, findings=["AC not met"], summary="nope")
    node = QANode(dispatcher=_dispatcher(qa, verdict))
    report = await node.execute(ctx)
    assert report.passed is False
    assert report.code_review_passed is False
    assert report.code_review_findings == ["AC not met"]


@pytest.mark.asyncio
async def test_qa_codereview_passes_when_both_pass(ctx):
    qa = QAReport(passed=True, criterion_results=[], lint_passed=True)
    verdict = _CodeReviewVerdict(passed=True, findings=[])
    node = QANode(dispatcher=_dispatcher(qa, verdict))
    report = await node.execute(ctx)
    assert report.passed is True
    assert report.code_review_passed is True
    assert report.code_review_findings == []


@pytest.mark.asyncio
async def test_deterministic_fail_keeps_run_failed(ctx):
    qa = QAReport(passed=False, criterion_results=[], lint_passed=False)
    verdict = _CodeReviewVerdict(passed=True, findings=[])
    node = QANode(dispatcher=_dispatcher(qa, verdict))
    report = await node.execute(ctx)
    # Deterministic gate already failed → overall fail even if review passes.
    assert report.passed is False
    assert report.code_review_passed is True


@pytest.mark.asyncio
async def test_qa_codereview_dispatch_is_read_only(ctx):
    qa = QAReport(passed=True, criterion_results=[], lint_passed=True)
    verdict = _CodeReviewVerdict(passed=True, findings=[])
    node = QANode(dispatcher=_dispatcher(qa, verdict))
    await node.execute(ctx)
    # The SECOND dispatch is the code-review gate.
    cr_profile = node._dispatcher.dispatch.await_args_list[1].kwargs["profile"]
    assert cr_profile.subagent == "sdd-codereview"
    assert cr_profile.permission_mode == "plan"
    assert "Edit" not in (cr_profile.allowed_tools or [])
    assert "Write" not in (cr_profile.allowed_tools or [])
    assert set(["Read", "Bash", "Grep", "Glob"]).issubset(cr_profile.allowed_tools)


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
    verdict = _CodeReviewVerdict(passed=True, findings=[])
    node = QANode(dispatcher=_dispatcher(qa, verdict))
    await node.execute(ctx)
    cr_cwd = node._dispatcher.dispatch.await_args_list[1].kwargs["cwd"]
    assert cr_cwd == "/abs/.claude/worktrees/repos/r1/nav"
