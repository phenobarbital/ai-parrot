"""Unit tests for UsageReport (FEAT-405 Module 7a, rebuilt on the FEAT-479
per-run ledger, Module 7).

Builds reports from a real :class:`RunLedgerRecorder` (the append-only sink
``build_usage_report`` now reads) rather than a session-state ``Snapshot``.
``TestBundleIntegration`` still builds a ``Snapshot`` for
``build_run_bundle`` — that half of the run bundle is untouched by this
feature.
"""

from __future__ import annotations

import pytest
from parrot.flows.dev_loop.run_bundle import build_run_bundle, render_markdown
from parrot.flows.dev_loop.session_state import (
    DevLoopSessionState,
    RunClosed,
    RunCreated,
    Snapshot,
    reduce,
    session_channel,
)
from parrot.flows.dev_loop.usage_report import (
    AgentUsage,
    CycleUsage,
    UsageReport,
    build_usage_report,
    render_usage_markdown,
)
from parrot.observability.recorders.models import UsageRecord
from parrot.observability.recorders.run_ledger import RunLedgerRecorder

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
async def ledger_with_two_agents() -> RunLedgerRecorder:
    """A ledger with two seats: "development" (full telemetry, two retry
    cycles) and "qa" (no telemetry reported — unset config / a backend
    that doesn't emit round events)."""
    ledger = RunLedgerRecorder(run_id=RUN_ID)
    await ledger.record(
        UsageRecord(
            provider="nova", client_name="nova", model="minimax.minimax-m2.5",
            seat="development", node_id="development",
            input_tokens=1000, output_tokens=250, duration_ms=4000,
        )
    )
    await ledger.record(
        UsageRecord(
            provider="claude-code", client_name="claude-code",
            seat="qa", node_id="qa",
            input_tokens=0, output_tokens=0, usage_reported=False,
        )
    )
    return ledger


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
    async def test_one_entry_per_seat(self, ledger_with_two_agents):
        rep = build_usage_report(ledger_with_two_agents, run_id=RUN_ID)
        assert len({a.seat for a in rep.agents}) == 2

    async def test_seat_equals_node_id(self, ledger_with_two_agents):
        rep = build_usage_report(ledger_with_two_agents, run_id=RUN_ID)
        seats = {a.seat for a in rep.agents}
        assert seats == {"development", "qa"}

    async def test_telemetry_attributed_correctly(self, ledger_with_two_agents):
        rep = build_usage_report(ledger_with_two_agents, run_id=RUN_ID)
        dev = next(a for a in rep.agents if a.seat == "development")
        qa = next(a for a in rep.agents if a.seat == "qa")
        assert dev.backend == "nova"
        assert dev.model == "minimax.minimax-m2.5"
        assert dev.input_tokens == 1000
        assert qa.backend == "claude-code"
        assert qa.input_tokens is None  # unreported -> None, never 0

    async def test_totals_sum_reported_only(self, ledger_with_two_agents):
        rep = build_usage_report(ledger_with_two_agents, run_id=RUN_ID)
        assert rep.total_input_tokens == 1000

    async def test_empty_run_still_valid(self):
        rep = build_usage_report(RunLedgerRecorder(run_id=RUN_ID), run_id=RUN_ID)
        assert rep.agents == []
        assert rep.total_input_tokens is None

    async def test_report_sums_cycles_per_seat(self):
        """Regression guard for FEAT-479 Finding 2 — appends accumulate,
        never overwrite."""
        ledger = RunLedgerRecorder(run_id=RUN_ID)
        await ledger.record(
            UsageRecord(
                provider="nova", client_name="nova", seat="development",
                node_id="development", input_tokens=1000, output_tokens=500,
            )
        )
        await ledger.record(
            UsageRecord(
                provider="nova", client_name="nova", seat="development",
                node_id="development", input_tokens=2000, output_tokens=700,
            )
        )
        report = build_usage_report(ledger, run_id=RUN_ID)
        (agent,) = report.agents
        assert agent.input_tokens == 3000  # not 2000 (the last cycle)
        assert [c.cycle for c in agent.cycles] == [1, 2]

    async def test_report_includes_pool_workers(self):
        """Regression guard for Finding 3 — pool-worker seats are
        first-class rows, each with its own real model."""
        ledger = RunLedgerRecorder(run_id=RUN_ID)
        await ledger.record(
            UsageRecord(
                provider="nova", client_name="nova", model="model-a",
                seat="development.w1", node_id="development",
                input_tokens=100, output_tokens=50,
            )
        )
        await ledger.record(
            UsageRecord(
                provider="anthropic", client_name="claude-code", model="model-b",
                seat="development.w2", node_id="development",
                input_tokens=200, output_tokens=60,
            )
        )
        report = build_usage_report(ledger, run_id=RUN_ID)
        seats = {a.seat for a in report.agents}
        assert {"development.w1", "development.w2"} <= seats
        assert all(
            a.model for a in report.agents if a.seat.startswith("development.")
        )
        assert all(a.node_id == "development" for a in report.agents)

    async def test_report_never_fabricates_zero(self):
        ledger = RunLedgerRecorder(run_id=RUN_ID)
        await ledger.record(
            UsageRecord(
                provider="claude-code", client_name="claude-code", seat="qa",
                node_id="qa", input_tokens=0, output_tokens=0,
                usage_reported=False,
            )
        )
        report = build_usage_report(ledger, run_id=RUN_ID)
        assert report.agents[0].input_tokens is None
        assert report.total_input_tokens is None

    def test_empty_ledger_yields_valid_report(self):
        report = build_usage_report(RunLedgerRecorder(run_id=RUN_ID), run_id=RUN_ID)
        assert report.agents == []
        assert report.total_input_tokens is None

    async def test_partial_flag_propagates(self):
        ledger = RunLedgerRecorder(run_id=RUN_ID)
        ledger.mark_partial("resumed in a new process")
        report = build_usage_report(ledger, run_id=RUN_ID)
        assert report.partial is True
        assert report.partial_reason

    def test_single_worker_summary_helper_is_gone(self):
        """The pool-size-1 guess is obsolete — the model is real data now."""
        import parrot.flows.dev_loop.usage_report as ur

        assert not hasattr(ur, "_single_worker_summary_for_node")

    async def test_failed_cycle_retained_and_counted(self):
        ledger = RunLedgerRecorder(run_id=RUN_ID)
        await ledger.record(
            UsageRecord(
                provider="nova", client_name="nova", seat="qa", node_id="qa",
                input_tokens=900, output_tokens=100, status="failed",
                error_type="TimeoutError",
            )
        )
        report = build_usage_report(ledger, run_id=RUN_ID)
        (agent,) = report.agents
        assert agent.failures == 1
        assert agent.cycles[0].status == "failed"
        assert agent.cycles[0].error_type == "TimeoutError"
        assert agent.input_tokens == 900  # tokens burned before failing


class TestBundleIntegration:
    @pytest.fixture
    def snapshot(self) -> Snapshot:
        state = reduce(
            _fresh_state(), RunCreated(run_id=RUN_ID, work_kind="bug", summary="fix x")
        )
        state = reduce(state, RunClosed(outcome="succeeded"))
        return Snapshot(channel=state.channel, state=state, from_seq=0)

    async def test_usage_markdown_spliced_into_bundle(self, snapshot, ledger_with_two_agents):
        """render_markdown(bundle, usage_markdown) includes the usage section."""
        bundle = build_run_bundle(snapshot, [], {})
        rep = build_usage_report(ledger_with_two_agents, run_id=RUN_ID)
        md = render_markdown(bundle, render_usage_markdown(rep))
        assert "## Usage" in md
        assert "development" in md

    def test_no_usage_markdown_is_byte_identical_default(self, snapshot):
        """[R3]-style regression guard: omitting usage_markdown changes nothing."""
        bundle = build_run_bundle(snapshot, [], {})
        assert "## Usage" not in render_markdown(bundle)


# ─────────────────────────────────────────────────────────────────────
# FEAT-479 Module 7b — node/cycle/worker rendering, Failures, partial marker
# ─────────────────────────────────────────────────────────────────────


@pytest.fixture
def report_with_cycles_and_workers() -> UsageReport:
    return UsageReport(
        run_id="run-1",
        generated_at=0.0,
        agents=[
            AgentUsage(
                seat="development", node_id="development", backend="anthropic",
                model="claude-opus-5", rounds=2,
                input_tokens=3000, output_tokens=1200,
                cycles=[
                    CycleUsage(cycle=1, model="claude-opus-5", input_tokens=1000, output_tokens=500),
                    CycleUsage(cycle=2, model="claude-opus-5", input_tokens=2000, output_tokens=700),
                ],
            ),
            AgentUsage(
                seat="development.w1", node_id="development", backend="anthropic",
                model="claude-sonnet-4-6", rounds=1,
                input_tokens=100, output_tokens=50,
                cycles=[CycleUsage(cycle=1, model="claude-sonnet-4-6", input_tokens=100, output_tokens=50)],
            ),
            AgentUsage(
                seat="development.w2", node_id="development", backend="anthropic",
                model="claude-sonnet-4-6", rounds=1,
                input_tokens=200, output_tokens=60,
                cycles=[CycleUsage(cycle=1, model="claude-sonnet-4-6", input_tokens=200, output_tokens=60)],
            ),
        ],
    )


@pytest.fixture
def report_single_cycle() -> UsageReport:
    return UsageReport(
        run_id="run-1",
        generated_at=0.0,
        agents=[
            AgentUsage(
                seat="qa", node_id="qa", backend="nova", model="m", rounds=1,
                input_tokens=10, output_tokens=5,
                cycles=[CycleUsage(cycle=1, model="m", input_tokens=10, output_tokens=5)],
            ),
        ],
    )


@pytest.fixture
def report_with_failure() -> UsageReport:
    return UsageReport(
        run_id="run-1",
        generated_at=0.0,
        agents=[
            AgentUsage(
                seat="qa", node_id="qa", backend="nova", model="m", rounds=2,
                input_tokens=900, output_tokens=100, failures=1,
                cycles=[
                    CycleUsage(cycle=1, model="m", status="completed"),
                    CycleUsage(
                        cycle=2, model="m", input_tokens=900, output_tokens=100,
                        status="failed", error_type="TimeoutError",
                    ),
                ],
            ),
        ],
    )


@pytest.fixture
def report_clean() -> UsageReport:
    return UsageReport(
        run_id="run-1",
        generated_at=0.0,
        agents=[
            AgentUsage(
                seat="qa", node_id="qa", backend="nova", model="m", rounds=1,
                input_tokens=10, output_tokens=5,
                cycles=[CycleUsage(cycle=1, model="m", input_tokens=10, output_tokens=5)],
            ),
        ],
    )


@pytest.fixture
def report_partial() -> UsageReport:
    return UsageReport(
        run_id="run-1",
        generated_at=0.0,
        agents=[
            AgentUsage(
                seat="development", node_id="development", backend="nova",
                model="m", rounds=1, input_tokens=100, output_tokens=50,
            ),
        ],
        partial=True, partial_reason="resumed in a new process",
    )


class TestNodeCycleWorkerRendering:
    def test_report_renders_node_cycle_worker(self, report_with_cycles_and_workers):
        md = render_usage_markdown(report_with_cycles_and_workers)
        assert "development" in md
        assert "cycle 1" in md and "cycle 2" in md
        assert "development.w1" in md and "development.w2" in md

    def test_single_cycle_seat_has_no_cycle_rows(self, report_single_cycle):
        assert "cycle 1" not in render_usage_markdown(report_single_cycle)


class TestFailuresSection:
    def test_report_failures_section(self, report_with_failure):
        md = render_usage_markdown(report_with_failure)
        assert "Failures" in md
        assert "TimeoutError" in md

    def test_no_failures_section_when_clean(self, report_clean):
        assert "Failures" not in render_usage_markdown(report_clean)

    def test_no_error_message_in_failures_section(self, report_with_failure):
        """Only error_type appears — never a message (privacy contract).

        The renderer's own footnote legitimately contains the word
        "messages" (pointing the reader at the run bundle); what must
        never appear is actual message TEXT, which ``CycleUsage`` has no
        field for at all in the first place.
        """
        md = render_usage_markdown(report_with_failure)
        assert not hasattr(CycleUsage, "error_message")
        assert "Error messages are not shown here" in md


class TestPartialMarkerMarkdown:
    def test_partial_ledger_is_labelled(self, report_partial):
        """Spec §8 Q1: a partial run must SAY so, not print a total that
        silently omits pre-park usage."""
        md = render_usage_markdown(report_partial)
        assert "artial" in md
        assert "partial" in md.lower().split("**totals")[1][:40]


class TestNoPricingWithCyclesAndFailures:
    def test_no_pricing_in_output(self, report_with_cycles_and_workers, report_with_failure):
        for rep in (report_with_cycles_and_workers, report_with_failure):
            out = render_usage_markdown(rep)
            assert "$" not in out
            assert "cost" not in out.lower()
