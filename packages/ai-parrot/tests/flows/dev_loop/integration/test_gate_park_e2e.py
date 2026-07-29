"""End-to-end gate-park integration test (FEAT-377 TASK-1917).

Drives the REAL ``DevLoopRunner.run()`` / ``build_dev_loop_flow()`` engine
(mocked dispatcher/Jira, no network, no real CLIs) through a REAL
``plan_approval`` gate opened by ``DevelopmentNode`` (TASK-1916,
``require_plan_approval=True``) — proving TASK-1917's park/resume
mechanism against a real node graph, not just the stub flows in
``tests/flows/dev_loop/test_runner_park.py``.

Mirrors the harness style of ``integration/test_repair_loop.py``
(deterministic in-process stubs, no ``@pytest.mark.live``).
"""

from __future__ import annotations

import asyncio
from typing import Dict
from unittest.mock import AsyncMock, MagicMock

import pytest

from parrot.bots.flows.core.result import FlowResult
from parrot.bots.flows.core.types import FlowStatus
from parrot.flows.dev_loop import (
    BugBrief,
    DevLoopRunner,
    QAReport,
    ResearchOutput,
    ShellCriterion,
    build_dev_loop_flow,
)
from parrot.flows.dev_loop.models import DevelopmentOutput
from parrot.flows.dev_loop.nodes.deployment_handoff import DeploymentHandoffNode


class _InstantFlow:
    """Trivial ``run_flow`` stub used ONLY to prove a parked run's slot is
    genuinely free — swapped into ``runner.flow`` for a second run while
    run 1 is parked on its real ``plan_approval`` gate. Matches
    ``tests/flows/dev_loop/test_runner_park.py``'s harness; a second REAL
    dev-loop flow would itself need require_plan_approval to be
    satisfied, which is orthogonal to what this assertion is checking."""

    async def run_flow(self, ctx, **kwargs) -> FlowResult:
        return FlowResult(
            output=ctx.shared_data["run_id"], status=FlowStatus.COMPLETED,
        )


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


def _plan_gate_dispatcher(research_out: ResearchOutput):
    """Dispatcher stub: Research/Development/QA all succeed on first try.

    Returns ``(dispatcher, calls)`` — ``calls`` counts dispatches per
    output_model name, used to assert Development is dispatched only
    AFTER the plan_approval gate resolves.
    """
    calls: Dict[str, int] = {"research": 0, "development": 0, "qa": 0}

    async def dispatch(*, brief, profile, output_model, run_id, node_id, cwd, session_host=None):
        if output_model is ResearchOutput:
            calls["research"] += 1
            return research_out
        if output_model is DevelopmentOutput:
            calls["development"] += 1
            return DevelopmentOutput(
                files_changed=["x.py"], commit_shas=["sha1"],
                summary="implemented the fix",
            )
        if output_model is QAReport:
            calls["qa"] += 1
            return QAReport(passed=True, criterion_results=[], lint_passed=True)
        raise AssertionError(f"unexpected output_model {output_model}")

    d = MagicMock()
    d.dispatch = AsyncMock(side_effect=dispatch)
    return d, calls


def _build_flow(dispatcher, jira):
    return build_dev_loop_flow(
        dispatcher=dispatcher,
        jira_toolkit=jira,
        log_toolkits={},
        redis_url="redis://localhost:6399/9",  # never connected in tests
        publish_flow_events=False,
        require_plan_approval=True,
    )


@pytest.mark.asyncio
async def test_parked_plan_gate_e2e(brief, mock_jira, patch_handoff, patch_worktree_base):
    """A real ``plan_approval`` gate parks the run (slot freed, a queued
    second run proceeds immediately) and resolving it resumes the SAME
    run through Development/QA/Close to completion."""
    research = _research_output(patch_worktree_base)
    dispatcher, calls = _plan_gate_dispatcher(research)
    flow = _build_flow(dispatcher, mock_jira)
    runner = DevLoopRunner(flow, max_concurrent_runs=1)

    task = asyncio.ensure_future(runner.run(brief, run_id="run-plan-gate"))

    # Development opens the plan_approval gate on its first entry, before
    # ever dispatching — wait for the run to park. Research's summary/plan
    # LLM helpers attempt (and gracefully fall back from) a real
    # Anthropic client call first, so this can take a few seconds.
    for _ in range(3000):
        if runner.is_parked("run-plan-gate"):
            break
        await asyncio.sleep(0.01)
    assert runner.is_parked("run-plan-gate")
    assert not runner.is_active("run-plan-gate")
    assert calls["development"] == 0  # gate opened BEFORE dispatch

    # The slot is genuinely free: a second run can start (and finish)
    # immediately while run 1 is still parked awaiting approval — proving
    # the real plan_approval gate released the slot, not just that a
    # stub-flow test does (test_runner_park.py covers that in isolation).
    runner.flow = _InstantFlow()
    result2 = await asyncio.wait_for(
        runner.run(brief, run_id="run-plan-gate-2"), timeout=5.0
    )
    assert result2.status == FlowStatus.COMPLETED

    # Resolve run 1's plan_approval gate — it resumes and completes.
    host = runner.get_host("run-plan-gate")
    gate_id = next(iter(host.state.gates))
    gate = host.state.gates[gate_id]
    assert gate.kind == "plan_approval"
    host.resolve_gate(gate_id, "approved", resolved_by="alice")

    result = await asyncio.wait_for(task, timeout=10.0)
    assert result.status == FlowStatus.COMPLETED
    assert not runner.is_parked("run-plan-gate")
    assert not runner.is_active("run-plan-gate")

    executed = set(result.responses)
    assert "close" in executed
    assert "failure_handler" not in executed
    assert calls["development"] == 1
    assert calls["qa"] == 1


@pytest.mark.asyncio
async def test_rejected_plan_gate_e2e(brief, mock_jira, patch_handoff, patch_worktree_base):
    """Rejecting the plan_approval gate resumes the run straight into
    failure_handler (Development never dispatches) — parking must not
    change the gate's existing approve/reject semantics (TASK-1916)."""
    research = _research_output(patch_worktree_base)
    dispatcher, calls = _plan_gate_dispatcher(research)
    flow = _build_flow(dispatcher, mock_jira)
    runner = DevLoopRunner(flow, max_concurrent_runs=1)

    task = asyncio.ensure_future(runner.run(brief, run_id="run-plan-gate-reject"))
    for _ in range(3000):
        if runner.is_parked("run-plan-gate-reject"):
            break
        await asyncio.sleep(0.01)
    assert runner.is_parked("run-plan-gate-reject")

    host = runner.get_host("run-plan-gate-reject")
    gate_id = next(iter(host.state.gates))
    host.resolve_gate(gate_id, "rejected", resolved_by="bob", comment="not ready")

    result = await asyncio.wait_for(task, timeout=10.0)
    assert not runner.is_parked("run-plan-gate-reject")

    executed = set(result.responses)
    assert "failure_handler" in executed
    assert "close" not in executed
    assert calls["development"] == 0
