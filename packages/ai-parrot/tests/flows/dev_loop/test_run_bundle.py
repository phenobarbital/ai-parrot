"""Unit tests for the RunBundle model/builder/renderer (FEAT-378 TASK-1928).

Builds realistic terminal ``Snapshot``s via the real reducer chain
(``reduce``) rather than hand-crafting ``DevLoopSessionState`` directly,
so these tests double as a light integration check that
``build_run_bundle``/``render_markdown`` interpret the actual state shape
correctly.
"""

from __future__ import annotations

from typing import Any, Dict, List

from parrot.flows.dev_loop.models import (
    CriterionResult,
    DevelopmentOutput,
    QAReport,
    ResearchOutput,
    WorkerSummary,
)
from parrot.flows.dev_loop.run_bundle import (
    DevelopedWork,
    RunBundle,
    build_run_bundle,
    render_markdown,
)
from parrot.flows.dev_loop.session_state import (
    ActionEnvelope,
    ApprovalGate,
    DevLoopSessionState,
    DispatchCompleted,
    DispatchQueued,
    DispatchStarted,
    GateOpened,
    GateResolved,
    NodeCompleted,
    NodeFailed,
    NodeStarted,
    RunCancelled,
    RunClosed,
    RunCreated,
    Snapshot,
    reduce,
    session_channel,
)

RUN_ID = "run-bundle0001"


def _fresh_state() -> DevLoopSessionState:
    return DevLoopSessionState(run_id=RUN_ID, channel=session_channel(RUN_ID))


def _envelopes(n: int) -> List[ActionEnvelope]:
    channel = session_channel(RUN_ID)
    return [
        ActionEnvelope(channel=channel, server_seq=i, action=RunCreated(run_id=RUN_ID))
        for i in range(n)
    ]


def _research_output(**overrides: Any) -> ResearchOutput:
    defaults: Dict[str, Any] = dict(
        jira_issue_key="OPS-42",
        spec_path="sdd/specs/x.spec.md",
        feat_id="FEAT-999",
        branch_name="feat-999-x",
        worktree_path="/abs/.claude/worktrees/feat-999-x",
    )
    defaults.update(overrides)
    return ResearchOutput(**defaults)


def _qa_report(**overrides: Any) -> QAReport:
    defaults: Dict[str, Any] = dict(
        passed=True,
        criterion_results=[
            CriterionResult(
                name="run tests", kind="shell", exit_code=0,
                duration_seconds=1.5, passed=True,
            ),
        ],
        lint_passed=True,
    )
    defaults.update(overrides)
    return QAReport(**defaults)


# ---------------------------------------------------------------------------
# build_run_bundle
# ---------------------------------------------------------------------------


def test_build_bundle_successful_run():
    state = reduce(_fresh_state(), RunCreated(run_id=RUN_ID, work_kind="bug", summary="fix x"))
    state = reduce(state, NodeStarted(node_id="research", ts=1.0))
    state = reduce(state, NodeCompleted(node_id="research", ts=2.0))
    state = reduce(state, DispatchQueued(node_id="development"))
    state = reduce(state, DispatchStarted(node_id="development", ts=2.0))
    state = reduce(
        state,
        DispatchCompleted(
            node_id="development", ts=5.0,
            input_tokens=100, output_tokens=50, total_cost_usd=0.02, num_turns=3,
            duration_ms=3000,
        ),
    )
    state = reduce(state, NodeStarted(node_id="development", ts=2.0))
    state = reduce(state, NodeCompleted(node_id="development", ts=5.0))
    state = reduce(
        state,
        RunClosed(outcome="succeeded", jira_issue_key="OPS-42", pr_url="https://pr/1"),
    )

    research = _research_output()
    qa_report = _qa_report()
    shared: Dict[str, Any] = {
        "mode": "initial",
        "research_output": research,
        "qa_report": qa_report,
        "deployment_result": {"pr_url": "https://pr/1", "pr_number": 7},
    }

    bundle = build_run_bundle(
        Snapshot(channel=state.channel, state=state, from_seq=0),
        _envelopes(4),
        shared,
    )

    assert isinstance(bundle, RunBundle)
    assert bundle.run_id == RUN_ID
    assert bundle.mode == "initial"
    assert bundle.outcome == "succeeded"
    assert bundle.action_count == 4
    node_ids = {n.node_id for n in bundle.nodes}
    assert {"research", "development"} <= node_ids
    dev_node = next(n for n in bundle.nodes if n.node_id == "development")
    assert dev_node.status == "completed"
    assert dev_node.input_tokens == 100
    assert dev_node.output_tokens == 50
    assert dev_node.total_cost_usd == 0.02

    assert bundle.developed.jira_issue_key == "OPS-42"
    assert bundle.developed.pr_url == "https://pr/1"
    assert bundle.developed.pr_number == 7
    assert bundle.developed.feature_id == "FEAT-999"
    assert bundle.developed.qa_passed is True
    assert bundle.developed.lint_passed is True
    assert len(bundle.developed.criteria) == 1
    assert bundle.developed.criteria[0].name == "run tests"


def test_build_bundle_failed_run_minimal_shared():
    """A failed/cancelled run may only have `mode` in shared state."""
    state = reduce(_fresh_state(), RunCreated(run_id=RUN_ID, work_kind="bug", summary=""))
    state = reduce(state, NodeStarted(node_id="qa", ts=1.0))
    state = reduce(state, NodeFailed(node_id="qa", ts=2.0, error="boom"))
    state = reduce(state, RunClosed(outcome="failed"))

    bundle = build_run_bundle(
        Snapshot(channel=state.channel, state=state, from_seq=0),
        _envelopes(2),
        {"mode": "initial"},
    )

    assert bundle.outcome == "failed"
    assert bundle.developed == DevelopedWork()
    qa_node = next(n for n in bundle.nodes if n.node_id == "qa")
    assert qa_node.status == "failed"
    assert qa_node.error == "boom"


def test_build_bundle_gate_audit():
    state = reduce(_fresh_state(), RunCreated(run_id=RUN_ID))
    state = reduce(
        state,
        GateOpened(
            gate=ApprovalGate(
                gate_id="g1", kind="manual_criterion", node_id="qa", title="Manual check",
            )
        ),
    )
    state = reduce(
        state, GateResolved(gate_id="g1", resolution="approved", resolved_by="alice")
    )
    state = reduce(state, RunClosed(outcome="succeeded"))

    bundle = build_run_bundle(
        Snapshot(channel=state.channel, state=state, from_seq=0), _envelopes(3), {},
    )

    assert len(bundle.gates) == 1
    gate = bundle.gates[0]
    assert gate.kind == "manual_criterion"
    assert gate.node_id == "qa"
    assert gate.status == "approved"
    assert gate.resolved_by == "alice"


# ---------------------------------------------------------------------------
# Totals aggregation
# ---------------------------------------------------------------------------


def test_totals_aggregate_partial_telemetry():
    """Only nodes that reported telemetry contribute to the sum."""
    state = reduce(_fresh_state(), RunCreated(run_id=RUN_ID))
    state = reduce(state, DispatchQueued(node_id="research"))
    state = reduce(state, DispatchCompleted(node_id="research", input_tokens=10))
    state = reduce(state, DispatchQueued(node_id="development"))
    state = reduce(
        state, DispatchCompleted(node_id="development", input_tokens=20, output_tokens=5)
    )
    state = reduce(state, RunClosed(outcome="succeeded"))

    bundle = build_run_bundle(
        Snapshot(channel=state.channel, state=state, from_seq=0), _envelopes(1), {},
    )

    assert bundle.totals.input_tokens == 30
    assert bundle.totals.output_tokens == 5
    assert bundle.totals.dispatch_count == 2


def test_totals_none_when_no_telemetry():
    state = reduce(_fresh_state(), RunCreated(run_id=RUN_ID))
    state = reduce(state, DispatchQueued(node_id="research"))
    state = reduce(state, DispatchCompleted(node_id="research"))
    state = reduce(state, RunClosed(outcome="succeeded"))

    bundle = build_run_bundle(
        Snapshot(channel=state.channel, state=state, from_seq=0), _envelopes(1), {},
    )

    assert bundle.totals.input_tokens is None
    assert bundle.totals.output_tokens is None
    assert bundle.totals.total_cost_usd is None
    assert bundle.totals.dispatch_count == 1


def test_task_ids_from_worker_summaries():
    state = reduce(_fresh_state(), RunCreated(run_id=RUN_ID))
    state = reduce(state, RunClosed(outcome="succeeded"))

    development_output = DevelopmentOutput(
        files_changed=["a.py"], commit_shas=["abc123"], summary="done",
        worker_summaries=[
            WorkerSummary(
                worker_id="development.w1", agent="codex", model="gpt",
                tasks_completed=["TASK-1", "TASK-2"],
            ),
            WorkerSummary(
                worker_id="development.w2", agent="claude-code", model="sonnet",
                tasks_completed=["TASK-3"],
            ),
        ],
    )
    bundle = build_run_bundle(
        Snapshot(channel=state.channel, state=state, from_seq=0),
        _envelopes(1),
        {"development_output": development_output},
    )
    assert bundle.developed.task_ids == ["TASK-1", "TASK-2", "TASK-3"]


# ---------------------------------------------------------------------------
# render_markdown
# ---------------------------------------------------------------------------


def test_render_markdown_full():
    state = reduce(_fresh_state(), RunCreated(run_id=RUN_ID, work_kind="bug", summary="fix x"))
    state = reduce(state, NodeStarted(node_id="development", ts=1.0))
    state = reduce(state, DispatchQueued(node_id="development"))
    state = reduce(state, DispatchStarted(node_id="development", ts=1.0))
    state = reduce(
        state,
        DispatchCompleted(
            node_id="development", ts=4.0, input_tokens=10, output_tokens=5,
            total_cost_usd=0.01,
        ),
    )
    state = reduce(state, NodeCompleted(node_id="development", ts=4.0))
    state = reduce(
        state,
        GateOpened(gate=ApprovalGate(gate_id="g1", kind="manual_criterion", node_id="qa")),
    )
    state = reduce(
        state, GateResolved(gate_id="g1", resolution="approved", resolved_by="bob")
    )
    state = reduce(
        state, RunClosed(outcome="succeeded", jira_issue_key="OPS-1", pr_url="https://pr/9")
    )

    shared = {
        "research_output": _research_output(),
        "qa_report": _qa_report(code_review_findings=["nit: rename var"]),
        "deployment_result": {"pr_url": "https://pr/9", "pr_number": 9},
    }
    bundle = build_run_bundle(
        Snapshot(channel=state.channel, state=state, from_seq=0), _envelopes(5), shared,
    )
    report = render_markdown(bundle)

    assert f"# Dev-Loop Run Report — {RUN_ID}" in report
    assert "OPS-1" in report
    assert "https://pr/9" in report
    assert "## Agents" in report
    assert "development" in report
    assert "## Gate Audit" in report
    assert "manual_criterion" in report
    assert "## What Was Developed" in report
    assert "FEAT-999" in report
    assert "nit: rename var" in report
    assert "None" not in report


def test_render_markdown_omits_empty_sections():
    state = reduce(_fresh_state(), RunCreated(run_id=RUN_ID))
    state = reduce(state, RunCancelled(requested_by="alice"))

    bundle = build_run_bundle(
        Snapshot(channel=state.channel, state=state, from_seq=0), _envelopes(1), {},
    )
    report = render_markdown(bundle)

    assert "## Agents" not in report
    assert "## Gate Audit" not in report
    assert "## What Was Developed" not in report
    assert "None" not in report
