"""Unit tests for UsageReport (FEAT-405, TASK-2090, Module 7a).

Mirrors ``test_run_bundle.py``'s pattern: realistic terminal ``Snapshot``s
via the real reducer chain (``reduce``) rather than hand-crafted
``DevLoopSessionState`` directly.
"""

from __future__ import annotations

from typing import Any

import pytest
from parrot.flows.dev_loop.models import DevelopmentOutput, WorkerSummary
from parrot.flows.dev_loop.run_bundle import build_run_bundle, render_markdown
from parrot.flows.dev_loop.session_state import (
    DevLoopSessionState,
    DispatchCompleted,
    DispatchQueued,
    DispatchStarted,
    NodeCompleted,
    NodeStarted,
    RunClosed,
    RunCreated,
    Snapshot,
    reduce,
    session_channel,
)
from parrot.flows.dev_loop.usage_report import (
    AgentUsage,
    UsageReport,
    build_usage_report,
    render_usage_markdown,
)

RUN_ID = "run-usage0001"


def _fresh_state() -> DevLoopSessionState:
    return DevLoopSessionState(run_id=RUN_ID, channel=session_channel(RUN_ID))


@pytest.fixture
def report() -> UsageReport:
    return UsageReport(
        run_id="run-1",
        generated_at=0.0,
        agents=[
            AgentUsage(
                seat="dev-agent-1",
                node_id="development",
                backend="nova",
                model="minimax.minimax-m2.5",
                rounds=7,
                input_tokens=1000,
                output_tokens=250,
            ),
            AgentUsage(
                seat="adversarial",
                node_id="qa",
                backend="nova",
                model="us.anthropic.claude-opus-5",
                rounds=1,
            ),  # no tokens
        ],
    )


@pytest.fixture
def snapshot_with_two_agents() -> Snapshot:
    """A terminal Snapshot with two dispatching nodes: "development" (full
    telemetry) and "qa" (no telemetry reported — unset config / a backend
    that doesn't emit round events).

    Node-granular, matching what ``Snapshot.state.nodes`` can actually
    hold — ``NodeId`` is a closed ``Literal`` of the 12 fixed flow nodes,
    so a per-pool-worker id like ``"development.w1"`` cannot appear here
    (see ``build_usage_report``'s docstring for the full explanation).
    """
    state = reduce(_fresh_state(), RunCreated(run_id=RUN_ID, work_kind="bug", summary="fix x"))
    state = reduce(state, NodeStarted(node_id="development", ts=1.0))
    state = reduce(
        state, DispatchQueued(node_id="development", dispatcher="nova")
    )
    state = reduce(state, DispatchStarted(node_id="development", ts=1.0))
    state = reduce(
        state,
        DispatchCompleted(
            node_id="development", ts=5.0,
            input_tokens=1000, output_tokens=250, num_turns=7, duration_ms=4000,
        ),
    )
    state = reduce(state, NodeCompleted(node_id="development", ts=5.0))

    state = reduce(state, NodeStarted(node_id="qa", ts=1.0))
    state = reduce(
        state, DispatchQueued(node_id="qa", dispatcher="claude-code")
    )
    state = reduce(state, DispatchStarted(node_id="qa", ts=1.0))
    state = reduce(
        state,
        DispatchCompleted(node_id="qa", ts=3.0),  # no telemetry reported
    )
    state = reduce(state, NodeCompleted(node_id="qa", ts=3.0))

    state = reduce(state, RunClosed(outcome="succeeded"))
    return Snapshot(channel=state.channel, state=state, from_seq=0)


class TestRendering:
    def test_dash_for_unreported(self, report):
        md = render_usage_markdown(report)
        assert "—" in md, "unreported tokens must render as an em dash"
        assert " 0 in / 0 out" not in md, "must never fabricate zeros"

    def test_rows_carry_backend_model_rounds(self, report):
        md = render_usage_markdown(report)
        assert "minimax.minimax-m2.5" in md and "nova" in md and "7" in md

    def test_no_pricing_in_output(self, report):
        assert "$" not in render_usage_markdown(report)

    def test_seat_and_node_id_both_rendered(self, report):
        md = render_usage_markdown(report)
        assert "dev-agent-1" in md
        assert "development" in md


class TestSerialization:
    def test_json_roundtrip(self, report, tmp_path):
        p = tmp_path / "usage.json"
        p.write_text(report.model_dump_json())
        assert UsageReport.model_validate_json(p.read_text()) == report

    def test_empty_run_renders(self):
        empty = UsageReport(run_id="r", generated_at=0.0, agents=[])
        assert render_usage_markdown(empty)
        assert "No agent usage" in render_usage_markdown(empty)


class TestBuild:
    def test_one_entry_per_seat(self, snapshot_with_two_agents):
        rep = build_usage_report(snapshot_with_two_agents, run_id=RUN_ID)
        assert len({a.seat for a in rep.agents}) == 2

    def test_seat_equals_node_id(self, snapshot_with_two_agents):
        rep = build_usage_report(snapshot_with_two_agents, run_id=RUN_ID)
        seats = {a.seat for a in rep.agents}
        assert seats == {"development", "qa"}

    def test_telemetry_attributed_correctly(self, snapshot_with_two_agents):
        rep = build_usage_report(snapshot_with_two_agents, run_id=RUN_ID)
        dev = next(a for a in rep.agents if a.seat == "development")
        qa = next(a for a in rep.agents if a.seat == "qa")
        assert dev.backend == "nova"
        assert dev.rounds == 7
        assert dev.input_tokens == 1000
        assert qa.backend == "claude-code"
        assert qa.rounds is None
        assert qa.input_tokens is None

    def test_totals_sum_reported_only(self, snapshot_with_two_agents):
        rep = build_usage_report(snapshot_with_two_agents, run_id=RUN_ID)
        assert rep.total_input_tokens == 1000
        assert rep.total_rounds == 7

    def test_empty_run_still_valid(self):
        state = reduce(_fresh_state(), RunCreated(run_id=RUN_ID))
        state = reduce(state, RunClosed(outcome="succeeded"))
        snap = Snapshot(channel=state.channel, state=state, from_seq=0)
        rep = build_usage_report(snap, run_id=RUN_ID)
        assert rep.agents == []
        assert rep.total_input_tokens is None

    def test_single_worker_summary_supplies_model(self, snapshot_with_two_agents):
        """A single pool worker (WorkerSummary) unambiguously supplies its
        node's backend/model — DispatchState alone has no model field."""
        development_output = DevelopmentOutput(
            files_changed=[],
            commit_shas=[],
            summary="done",
            worker_summaries=[
                WorkerSummary(
                    worker_id="development.w1", agent="nova",
                    model="minimax.minimax-m2.5",
                ),
            ],
        )
        shared: dict[str, Any] = {"development_output": development_output}
        rep = build_usage_report(snapshot_with_two_agents, run_id=RUN_ID, shared=shared)
        dev = next(a for a in rep.agents if a.seat == "development")
        assert dev.model == "minimax.minimax-m2.5"
        assert dev.backend == "nova"

    def test_ambiguous_multi_worker_leaves_model_blank(self, snapshot_with_two_agents):
        """Two workers under the same node id cannot be disambiguated —
        the node's model must NOT guess which worker it reflects."""
        development_output = DevelopmentOutput(
            files_changed=[],
            commit_shas=[],
            summary="done",
            worker_summaries=[
                WorkerSummary(
                    worker_id="development.w1", agent="nova",
                    model="minimax.minimax-m2.5",
                ),
                WorkerSummary(
                    worker_id="development.w2", agent="claude-code",
                    model="claude-sonnet-4-6",
                ),
            ],
        )
        shared: dict[str, Any] = {"development_output": development_output}
        rep = build_usage_report(snapshot_with_two_agents, run_id=RUN_ID, shared=shared)
        dev = next(a for a in rep.agents if a.seat == "development")
        assert dev.model == ""

    def test_no_shared_leaves_model_blank(self, snapshot_with_two_agents):
        rep = build_usage_report(snapshot_with_two_agents, run_id=RUN_ID)
        assert all(a.model == "" for a in rep.agents)


class TestBundleIntegration:
    def test_usage_markdown_spliced_into_bundle(self, snapshot_with_two_agents):
        """render_markdown(bundle, usage_markdown) includes the usage section."""
        bundle = build_run_bundle(snapshot_with_two_agents, [], {})
        rep = build_usage_report(snapshot_with_two_agents, run_id=RUN_ID)
        md = render_markdown(bundle, render_usage_markdown(rep))
        assert "## Usage" in md
        assert "development" in md

    def test_no_usage_markdown_is_byte_identical_default(self, snapshot_with_two_agents):
        """[R3]-style regression guard: omitting usage_markdown changes nothing."""
        bundle = build_run_bundle(snapshot_with_two_agents, [], {})
        assert "## Usage" not in render_markdown(bundle)
