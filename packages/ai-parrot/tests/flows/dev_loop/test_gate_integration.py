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
from parrot.flows.dev_loop.nodes.development import DevelopmentNode
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
            # FEAT-466 TASK-2505: DeploymentHandoffNode now blocks on "".
            base_branch="dev",
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
    # FEAT-466 TASK-2505: these are gate-mechanism tests, not base-branch
    # guard tests (that logic has its own dedicated coverage in
    # test_base_branch_guard.py) — no real git plumbing here, same
    # rationale as patching _push_branch/_create_pr above. Also sidesteps a
    # real environment hazard: assert_base_is_clean's real
    # asyncio.create_subprocess_exec calls, combined with this file's
    # manually-scheduled concurrent tasks (asyncio.ensure_future) and
    # uvloop, were observed to hang the event loop across test boundaries.
    monkeypatch.setattr(
        "parrot.flows.dev_loop.nodes.deployment_handoff.assert_base_is_clean",
        AsyncMock(return_value=None),
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


# ---------------------------------------------------------------------------
# DevelopmentNode — plan_approval gate (FEAT-377 TASK-1916)
# ---------------------------------------------------------------------------


@pytest.fixture
def dev_ctx() -> dict:
    return {
        "run_id": RUN_ID,
        "research_output": ResearchOutput(
            jira_issue_key="OPS-1",
            spec_path="sdd/specs/x.spec.md",
            feat_id="FEAT-130",
            branch_name="feat-130-fix",
            worktree_path="/tmp/feat-130-fix-plan-gate",
            log_excerpts=[],
        ),
    }


@pytest.fixture
def dev_dispatcher() -> MagicMock:
    d = MagicMock()
    d.dispatch = AsyncMock(
        return_value=DevelopmentOutput(files_changed=["a.py"], commit_shas=["s1"], summary="ok")
    )
    return d


@pytest.mark.asyncio
async def test_development_default_skips_plan_gate_even_with_host_present(
    dev_ctx, dev_dispatcher
):
    """Regression guard (mirrors the deployment_approval one above):
    DevLoopRunner.run() always seeds a live SessionHost — the gate MUST
    stay off by default or every existing/legacy run would block forever."""
    node = DevelopmentNode(dispatcher=dev_dispatcher)  # default: opt-out
    dev_ctx["session_host"] = SessionHost(RUN_ID)

    result = await node.execute(dev_ctx)

    assert isinstance(result, DevelopmentOutput)
    dev_dispatcher.dispatch.assert_awaited()


@pytest.mark.asyncio
async def test_development_plan_gate_approved_proceeds(dev_ctx, dev_dispatcher):
    node = DevelopmentNode(dispatcher=dev_dispatcher, require_plan_approval=True)
    host = SessionHost(RUN_ID)
    dev_ctx["session_host"] = host

    async def _approve_soon():
        await asyncio.sleep(0.01)
        assert dev_dispatcher.dispatch.await_count == 0  # not dispatched yet
        gate_id = next(iter(host.state.gates))
        host.resolve_gate(gate_id, "approved", resolved_by="alice")

    resolver = asyncio.ensure_future(_approve_soon())
    result = await node.execute(dev_ctx)
    await resolver

    assert isinstance(result, DevelopmentOutput)
    dev_dispatcher.dispatch.assert_awaited()
    gate = host.state.gates[next(iter(host.state.gates))]
    assert gate.status == "approved"
    assert gate.on_expiry == "approve"


@pytest.mark.asyncio
async def test_development_plan_gate_rejected_raises(dev_ctx, dev_dispatcher):
    """A rejected plan_approval gate terminates the run — DevelopmentNode
    raises (routing to failure_handler via the on_error edge), the same
    "stop the run" effect a rejected deployment_approval gate has."""
    node = DevelopmentNode(dispatcher=dev_dispatcher, require_plan_approval=True)
    host = SessionHost(RUN_ID)
    dev_ctx["session_host"] = host

    async def _reject_soon():
        await asyncio.sleep(0.01)
        gate_id = next(iter(host.state.gates))
        host.resolve_gate(gate_id, "rejected", resolved_by="bob", comment="not ready")

    resolver = asyncio.ensure_future(_reject_soon())
    with pytest.raises(RuntimeError, match="plan_approval rejected by bob"):
        await node.execute(dev_ctx)
    await resolver

    dev_dispatcher.dispatch.assert_not_awaited()


@pytest.mark.asyncio
async def test_development_plan_gate_expiry_approves(dev_ctx, dev_dispatcher):
    """on_expiry="approve" (fail-open) — a TTL sweep resolves the gate to
    'approved' by the system, and the node proceeds to dispatch."""
    node = DevelopmentNode(dispatcher=dev_dispatcher, require_plan_approval=True)
    host = SessionHost(RUN_ID)
    dev_ctx["session_host"] = host

    async def _expire_soon():
        await asyncio.sleep(0.01)
        # Drive the fail-open expiry path directly via the host's sweep,
        # exactly as the runner's periodic sweep would.
        gate_id = next(iter(host.state.gates))
        gate = host.state.gates[gate_id]
        host.expire_due_gates(now=(gate.expires_at or 0) + 1)

    resolver = asyncio.ensure_future(_expire_soon())
    result = await node.execute(dev_ctx)
    await resolver

    assert isinstance(result, DevelopmentOutput)
    gate = host.state.gates[next(iter(host.state.gates))]
    assert gate.status == "approved"
    assert gate.resolved_by == "system:ttl-auto-approve"


@pytest.mark.asyncio
async def test_development_plan_gate_no_host_falls_back_with_warning(
    dev_ctx, dev_dispatcher, caplog
):
    node = DevelopmentNode(dispatcher=dev_dispatcher, require_plan_approval=True)

    with caplog.at_level(logging.WARNING):
        result = await node.execute(dev_ctx)

    assert isinstance(result, DevelopmentOutput)
    dev_dispatcher.dispatch.assert_awaited()
    assert any("no session_host" in rec.message for rec in caplog.records)


@pytest.mark.asyncio
async def test_development_plan_gate_checked_only_once_across_retries(
    dev_ctx, dev_dispatcher
):
    """A QA-repair-loop re-entry (attempt >= 2) must NOT re-open the gate
    — the plan was already approved on the first entry."""
    node = DevelopmentNode(dispatcher=dev_dispatcher, require_plan_approval=True)
    host = SessionHost(RUN_ID)
    dev_ctx["session_host"] = host

    async def _approve_soon():
        await asyncio.sleep(0.01)
        gate_id = next(iter(host.state.gates))
        host.resolve_gate(gate_id, "approved", resolved_by="alice")

    resolver = asyncio.ensure_future(_approve_soon())
    await node.execute(dev_ctx)
    await resolver
    assert len(host.state.gates) == 1

    # Simulate a QA-repair-loop retry: a failing report already in shared
    # state, same run's shared dict (dev_ctx is reused, mirroring how
    # ctx.shared_data persists across a real run's retry edge).
    dev_ctx["qa_report"] = QAReport(passed=False, criterion_results=[], lint_passed=False)
    await node.execute(dev_ctx)

    # No second gate was opened.
    assert len(host.state.gates) == 1
