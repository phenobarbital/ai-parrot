"""HITL gate integration tests (FEAT-322 TASK-1853).

Covers ``ManualCriterion.blocking`` (default False, byte-identical
behavior), ``QANode``'s blocking-criteria gate path, and
``DeploymentHandoffNode``'s ``deployment_approval`` gate between PR
creation and the Jira transition — including the no-host legacy
fallback for both nodes.
"""

from __future__ import annotations

import asyncio
import logging
from unittest.mock import AsyncMock, MagicMock

import pytest

from parrot import conf
from parrot.flows.dev_loop import (
    BugBrief,
    DevelopmentOutput,
    FlowtaskCriterion,
    ManualCriterion,
    QAReport,
    ResearchOutput,
)
from parrot.flows.dev_loop.nodes.deployment_handoff import DeploymentHandoffNode
from parrot.flows.dev_loop.nodes.qa import QANode
from parrot.flows.dev_loop.session_state import SessionHost

RUN_ID = "run-gate0001"


# ---------------------------------------------------------------------------
# ManualCriterion.blocking — default + model shape
# ---------------------------------------------------------------------------


def test_manual_blocking_default_false_unchanged():
    criterion = ManualCriterion(name="ux-check", text="dashboard renders cleanly")
    assert criterion.blocking is False


def test_manual_blocking_explicit_true():
    criterion = ManualCriterion(
        name="ux-check", text="dashboard renders cleanly", blocking=True
    )
    assert criterion.blocking is True


# ---------------------------------------------------------------------------
# QANode — blocking manual criteria
# ---------------------------------------------------------------------------


@pytest.fixture
def qa_node() -> QANode:
    dispatcher = MagicMock()
    dispatcher.dispatch = AsyncMock()
    return QANode(dispatcher=dispatcher)


def _base_report() -> QAReport:
    return QAReport(passed=True, criterion_results=[], lint_passed=True)


@pytest.mark.asyncio
async def test_qa_blocking_gate_approved_folds_passed(qa_node):
    host = SessionHost(RUN_ID)
    shared = {"session_host": host, "run_id": RUN_ID}
    criterion = ManualCriterion(name="ux-check", text="looks right", blocking=True)

    async def _approve_soon():
        await asyncio.sleep(0.01)
        gate_id = next(iter(host.state.gates))
        host.resolve_gate(gate_id, "approved", resolved_by="alice", comment="lgtm")

    resolver = asyncio.ensure_future(_approve_soon())
    report, all_passed = await qa_node._resolve_blocking_manual_criteria(
        shared, [criterion], _base_report()
    )
    await resolver

    assert all_passed is True
    manual_results = [r for r in report.criterion_results if r.kind == "manual"]
    assert len(manual_results) == 1
    assert manual_results[0].passed is True
    assert manual_results[0].name == "ux-check"
    assert "alice" in report.notes
    assert "approved" in report.notes


@pytest.mark.asyncio
async def test_qa_blocking_gate_rejected_fails_report(qa_node):
    host = SessionHost(RUN_ID)
    shared = {"session_host": host, "run_id": RUN_ID}
    criterion = ManualCriterion(name="ux-check", text="looks right", blocking=True)

    async def _reject_soon():
        await asyncio.sleep(0.01)
        gate_id = next(iter(host.state.gates))
        host.resolve_gate(gate_id, "rejected", resolved_by="bob", comment="nope")

    resolver = asyncio.ensure_future(_reject_soon())
    report, all_passed = await qa_node._resolve_blocking_manual_criteria(
        shared, [criterion], _base_report()
    )
    await resolver

    assert all_passed is False
    manual_results = [r for r in report.criterion_results if r.kind == "manual"]
    assert manual_results[0].passed is False
    assert "bob" in report.notes


@pytest.mark.asyncio
async def test_qa_multiple_blocking_criteria_awaited_concurrently(qa_node):
    host = SessionHost(RUN_ID)
    shared = {"session_host": host, "run_id": RUN_ID}
    criteria = [
        ManualCriterion(name="a", text="check a", blocking=True),
        ManualCriterion(name="b", text="check b", blocking=True),
    ]

    async def _resolve_all_soon():
        await asyncio.sleep(0.01)
        # Both gates must already be open (opened before either is awaited).
        assert len(host.state.gates) == 2
        for gate_id in list(host.state.gates):
            host.resolve_gate(gate_id, "approved", resolved_by="alice")

    resolver = asyncio.ensure_future(_resolve_all_soon())
    report, all_passed = await qa_node._resolve_blocking_manual_criteria(
        shared, criteria, _base_report()
    )
    await resolver

    assert all_passed is True
    assert len([r for r in report.criterion_results if r.kind == "manual"]) == 2


@pytest.mark.asyncio
async def test_qa_no_host_falls_back_with_warning(qa_node, caplog):
    shared: dict = {"run_id": RUN_ID}  # no "session_host"
    criterion = ManualCriterion(name="ux-check", text="looks right", blocking=True)

    with caplog.at_level(logging.WARNING):
        report, all_passed = await qa_node._resolve_blocking_manual_criteria(
            shared, [criterion], _base_report()
        )

    assert all_passed is True  # legacy synthesis: never blocks
    manual_results = [r for r in report.criterion_results if r.kind == "manual"]
    assert manual_results[0].passed is True
    assert any("no session_host" in rec.message for rec in caplog.records)


# ---------------------------------------------------------------------------
# DeploymentHandoffNode — deployment_approval gate
# ---------------------------------------------------------------------------


@pytest.fixture
def handoff_ctx() -> dict:
    return {
        "run_id": RUN_ID,
        "research_output": ResearchOutput(
            jira_issue_key="OPS-1",
            spec_path="sdd/specs/x.spec.md",
            feat_id="FEAT-130",
            branch_name="feat-130-fix",
            worktree_path="/tmp/feat-130-fix",
            log_excerpts=[],
        ),
        "bug_brief": BugBrief(
            summary="customer sync drops the last row",
            affected_component="etl/customers/sync.yaml",
            log_sources=[],
            acceptance_criteria=[FlowtaskCriterion(name="run", task_path="x.yaml")],
            escalation_assignee="a",
            reporter="b",
        ),
        "development_output": DevelopmentOutput(
            files_changed=["a.py"], commit_shas=["abc"], summary="done",
        ),
        "qa_report": QAReport(passed=True, criterion_results=[], lint_passed=True),
    }


@pytest.fixture
def jira() -> MagicMock:
    j = MagicMock()
    j.jira_transition_issue = AsyncMock(return_value={"ok": True})
    j.jira_transition_to = AsyncMock(return_value={"ok": True})
    j.jira_add_comment = AsyncMock(return_value={"id": "c1"})
    return j


async def _success_push(self, branch, cwd):
    return None


@pytest.fixture(autouse=True)
def _patch_push(monkeypatch):
    monkeypatch.setattr(DeploymentHandoffNode, "_push_branch", _success_push)
    monkeypatch.setattr(
        DeploymentHandoffNode, "_create_pr",
        AsyncMock(return_value="https://github.com/x/y/pull/42"),
    )


@pytest.mark.asyncio
async def test_handoff_default_skips_gate_even_with_host_present(handoff_ctx, jira):
    """Regression guard: ``DevLoopRunner.run()`` (TASK-1851) always seeds a
    live ``SessionHost`` in shared state now — the gate MUST stay off by
    default (``require_deployment_approval=False``) or every existing/
    legacy run would block forever on an unresolved gate. This is the
    scenario that hung the full test suite during development."""
    node = DeploymentHandoffNode(jira_toolkit=jira)  # default: opt-out
    handoff_ctx["session_host"] = SessionHost(RUN_ID)

    result = await node.execute(handoff_ctx)

    assert result["status"] == "ready_to_deploy"
    jira.jira_transition_to.assert_awaited()


@pytest.mark.asyncio
async def test_handoff_jira_not_called_until_approved(handoff_ctx, jira):
    node = DeploymentHandoffNode(jira_toolkit=jira, require_deployment_approval=True)
    host = SessionHost(RUN_ID)
    handoff_ctx["session_host"] = host

    async def _approve_soon():
        await asyncio.sleep(0.01)
        assert jira.jira_transition_to.await_count == 0  # not called yet
        gate_id = next(iter(host.state.gates))
        host.resolve_gate(gate_id, "approved", resolved_by="alice")

    resolver = asyncio.ensure_future(_approve_soon())
    result = await node.execute(handoff_ctx)
    await resolver

    assert result["status"] == "ready_to_deploy"
    jira.jira_transition_to.assert_awaited()
    gate = host.state.gates[next(iter(host.state.gates))]
    assert gate.status == "approved"


@pytest.mark.asyncio
async def test_handoff_rejected_marks_blocked_no_transition(handoff_ctx, jira):
    node = DeploymentHandoffNode(jira_toolkit=jira, require_deployment_approval=True)
    host = SessionHost(RUN_ID)
    handoff_ctx["session_host"] = host

    async def _reject_soon():
        await asyncio.sleep(0.01)
        gate_id = next(iter(host.state.gates))
        host.resolve_gate(gate_id, "rejected", resolved_by="bob", comment="not ready")

    resolver = asyncio.ensure_future(_reject_soon())
    result = await node.execute(handoff_ctx)
    await resolver

    assert result["status"] == "blocked"
    assert "deployment_approval rejected by bob" in result["error"]
    # The READY-to-deploy transition must NEVER be attempted — only the
    # BLOCKED transition (via _mark_blocked) fires.
    ready_calls = [
        c for c in jira.jira_transition_to.await_args_list
        if c.kwargs.get("target_status") in conf.DEV_LOOP_JIRA_TRANSITIONS_READY
    ]
    assert ready_calls == []
    jira.jira_transition_to.assert_awaited_once()
    assert (
        jira.jira_transition_to.await_args.kwargs["target_status"]
        in conf.DEV_LOOP_JIRA_TRANSITIONS_BLOCKED
    )
    jira.jira_add_comment.assert_awaited()


@pytest.mark.asyncio
async def test_handoff_no_host_falls_back_with_warning(handoff_ctx, jira, caplog):
    # Opted in, but no "session_host" key (e.g. a node invoked outside the
    # runner) — must warn and proceed, never deadlock.
    node = DeploymentHandoffNode(jira_toolkit=jira, require_deployment_approval=True)

    with caplog.at_level(logging.WARNING):
        result = await node.execute(handoff_ctx)

    assert result["status"] == "ready_to_deploy"
    jira.jira_transition_to.assert_awaited()
    assert any("no session_host" in rec.message for rec in caplog.records)
