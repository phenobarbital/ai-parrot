"""End-to-end QA repair-loop integration tests (FEAT-377 TASK-1911).

Drives the REAL ``DevLoopRunner.run()`` / ``build_dev_loop_flow()`` engine
(mocked dispatcher/Jira, no network, no real CLIs) to prove the whole
Module 3 stack works together: TASK-1910's topology + engine cyclic
re-entry, and this task's node behavior (attempt stamping,
``QaAttemptRecorded`` emission, development's feedback redispatch, the
failure_handler's attempt trail).

Mirrors the harness style of ``tests/flows/dev_loop/test_runner.py`` and
``integration/test_pool_e2e.py`` (deterministic in-process stubs, no
``@pytest.mark.live``).
"""

from __future__ import annotations

from typing import Dict, List
from unittest.mock import AsyncMock, MagicMock

import pytest

from parrot.bots.flows.core.types import FlowStatus
from parrot.flows.dev_loop import (
    BugBrief,
    DevLoopRunner,
    QAReport,
    ResearchOutput,
    ShellCriterion,
    build_dev_loop_flow,
)
from parrot.flows.dev_loop.models import CriterionResult, DevelopmentOutput
from parrot.flows.dev_loop.nodes.deployment_handoff import DeploymentHandoffNode


@pytest.fixture
def brief() -> BugBrief:
    return BugBrief(
        summary="Customer sync drops the last row",
        affected_component="etl/customers/sync.yaml",
        log_sources=[],
        acceptance_criteria=[ShellCriterion(name="lint", command="ruff check .")],
        escalation_assignee="557058:abc",
        reporter="557058:def",
    )


def _research_output(tmp_path) -> ResearchOutput:
    return ResearchOutput(
        jira_issue_key="OPS-1",
        spec_path="sdd/specs/x.spec.md",
        feat_id="FEAT-130",
        branch_name="feat-130-fix",
        worktree_path=str(tmp_path / "feat-130-fix"),
        log_excerpts=[],
    )


@pytest.fixture
def mock_jira():
    j = MagicMock()
    j.jira_create_issue = AsyncMock(return_value={"key": "OPS-1"})
    j.jira_get_issue = AsyncMock(return_value={"status": "error"})
    j.jira_search_issues = AsyncMock(return_value={"status": "empty"})
    j.jira_transition_issue = AsyncMock(return_value={"ok": True})
    j.jira_transition_to = AsyncMock(return_value={"ok": True})
    j.jira_add_comment = AsyncMock(return_value={"id": "c1"})
    j.jira_assign_issue = AsyncMock(return_value={"ok": True})
    return j


@pytest.fixture
def patch_handoff(monkeypatch):
    """Neutralize git push / PR creation at class level (frozen models)."""
    monkeypatch.setattr(
        DeploymentHandoffNode, "_push_branch", AsyncMock(return_value=None)
    )
    monkeypatch.setattr(
        DeploymentHandoffNode,
        "_create_pr",
        AsyncMock(return_value="https://github.com/x/y/pull/1"),
    )


@pytest.fixture
def patch_worktree_base(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "parrot.flows.dev_loop.nodes.research.conf.WORKTREE_BASE_PATH",
        str(tmp_path),
    )
    return tmp_path


def _failing_report() -> QAReport:
    """A failing QAReport with enough detail for condense_qa_failure() to
    render a non-trivial feedback line (verified in the redispatch brief)."""
    return QAReport(
        passed=False,
        criterion_results=[
            CriterionResult(
                name="customers-sync", kind="flowtask", exit_code=1,
                duration_seconds=1.0, stdout_tail="", stderr_tail="boom: null row",
                passed=False,
            )
        ],
        lint_passed=True,
    )


def _repair_loop_dispatcher(research_out: ResearchOutput, qa_outcomes: List[bool]):
    """Dispatcher stub whose QA verdict follows ``qa_outcomes`` in order.

    Returns ``(dispatcher, calls, dev_briefs)``: ``calls`` counts
    dispatches per output_model name; ``dev_briefs`` captures every
    ``brief`` (a :class:`ResearchOutput`) handed to a DevelopmentOutput
    dispatch, in order, so the redispatch feedback can be asserted on.
    """
    calls: Dict[str, int] = {"qa": 0, "development": 0}
    dev_briefs: List[ResearchOutput] = []

    async def dispatch(*, brief, profile, output_model, run_id, node_id, cwd, session_host=None):
        if output_model is ResearchOutput:
            return research_out
        if output_model is DevelopmentOutput:
            dev_briefs.append(brief)
            calls["development"] += 1
            return DevelopmentOutput(
                files_changed=["x.py"], commit_shas=[f"sha{calls['development']}"],
                summary="implemented the fix",
            )
        if output_model is QAReport:
            passed = qa_outcomes[calls["qa"]]
            calls["qa"] += 1
            if passed:
                return QAReport(passed=True, criterion_results=[], lint_passed=True)
            return _failing_report()
        raise AssertionError(f"unexpected output_model {output_model}")

    d = MagicMock()
    d.dispatch = AsyncMock(side_effect=dispatch)
    return d, calls, dev_briefs


def _build_flow(dispatcher, jira):
    return build_dev_loop_flow(
        dispatcher=dispatcher,
        jira_toolkit=jira,
        log_toolkits={},
        redis_url="redis://localhost:6399/9",  # never connected in tests
        publish_flow_events=False,
    )


@pytest.mark.asyncio
async def test_repair_loop_e2e(brief, mock_jira, patch_handoff, patch_worktree_base):
    """QA fails once (feedback redispatch) → passes on attempt 2 → close."""
    research = _research_output(patch_worktree_base)
    dispatcher, calls, dev_briefs = _repair_loop_dispatcher(
        research, qa_outcomes=[False, True]
    )
    flow = _build_flow(dispatcher, mock_jira)
    runner = DevLoopRunner(flow, max_concurrent_runs=2)

    result = await runner.run(brief, run_id="run-repair")

    executed = set(result.responses)
    assert "close" in executed
    assert "failure_handler" not in executed
    assert result.status == FlowStatus.COMPLETED

    final_report: QAReport = result.responses["qa"]
    assert final_report.passed is True
    assert final_report.attempt == 2

    # Development dispatched twice: the initial pass, then the retry.
    assert calls["development"] == 2
    assert calls["qa"] == 2
    # The retry's brief carries the prior failure's feedback.
    retry_brief = dev_briefs[1]
    assert any(
        "customers-sync" in excerpt and "boom: null row" in excerpt
        for excerpt in retry_brief.log_excerpts
    )
    # Attempt 1's brief carries no feedback (nothing to redispatch from yet).
    assert dev_briefs[0].log_excerpts == []

    # No Jira escalation ("QA failed" / attempt-trail comment) on the
    # eventual success path — only the close node's own completion
    # comment, unrelated to this task's escalation path.
    bodies = [c.kwargs["body"] for c in mock_jira.jira_add_comment.call_args_list]
    assert not any("QA failed" in b or "Repair-loop attempt trail" in b for b in bodies)


@pytest.mark.asyncio
async def test_repair_loop_exhaustion_e2e(brief, mock_jira, patch_handoff, patch_worktree_base):
    """QA fails every attempt up to the cap → failure_handler; the Jira
    escalation comment includes the attempt trail."""
    from parrot import conf

    n = int(conf.DEV_LOOP_QA_MAX_RETRIES)
    research = _research_output(patch_worktree_base)
    dispatcher, calls, dev_briefs = _repair_loop_dispatcher(
        research, qa_outcomes=[False] * n
    )
    flow = _build_flow(dispatcher, mock_jira)
    runner = DevLoopRunner(flow, max_concurrent_runs=2)

    result = await runner.run(brief, run_id="run-exhaust")

    executed = set(result.responses)
    assert "failure_handler" in executed
    assert "close" not in executed
    assert "deployment_handoff" not in executed

    final_report: QAReport = result.responses["qa"]
    assert final_report.passed is False
    assert final_report.attempt == n

    # Development dispatched once per attempt (no dispatch beyond the cap).
    assert calls["development"] == n
    assert calls["qa"] == n

    bodies = [c.kwargs["body"] for c in mock_jira.jira_add_comment.call_args_list]
    assert any("QA failed" in b for b in bodies)
    # Exactly n-1 retries were recorded (the n-th failure exhausts — no
    # further retry is dispatched for it, so no trail entry either).
    trail_bodies = [b for b in bodies if "Repair-loop attempt trail" in b]
    assert len(trail_bodies) == 1
    trail = trail_bodies[0]
    for attempt in range(1, n):
        assert f"attempt {attempt}:" in trail
    assert f"attempt {n}:" not in trail
