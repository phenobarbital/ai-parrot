"""Unit tests for the self-contained HTML usage report (FEAT-405, TASK-2091,
Module 7b).
"""

from __future__ import annotations

import pytest
from parrot.flows.dev_loop.usage_report import (
    AgentUsage,
    CycleUsage,
    UsageReport,
    render_usage_html,
    render_usage_markdown,
)


@pytest.fixture
def report() -> UsageReport:
    return UsageReport(
        run_id="run-1",
        generated_at=0.0,
        agents=[
            AgentUsage(
                seat="dev-agent-1", node_id="development", backend="nova",
                model="minimax.minimax-m2.5", rounds=7,
                input_tokens=1000, output_tokens=250,
            ),
            AgentUsage(
                seat="adversarial", node_id="qa", backend="nova",
                model="us.anthropic.claude-opus-5", rounds=1,
            ),
        ],
    )


class TestSelfContained:
    def test_no_external_references(self, report):
        html = render_usage_html(report)
        assert "http://" not in html and "https://" not in html
        assert "@import" not in html and "//cdn" not in html
        assert "<link" not in html.lower()
        assert "<script" not in html.lower()

    def test_is_complete_document(self, report):
        html = render_usage_html(report)
        assert html.lstrip().lower().startswith("<!doctype html>")
        assert html.rstrip().endswith("</html>")

    def test_empty_report_is_still_self_contained(self):
        empty = UsageReport(run_id="r", generated_at=0.0, agents=[])
        html = render_usage_html(empty)
        assert html.lstrip().lower().startswith("<!doctype html>")
        assert "http://" not in html and "https://" not in html


class TestContent:
    def test_row_per_agent(self, report):
        html = render_usage_html(report)
        assert "dev-agent-1" in html and "adversarial" in html

    def test_dash_for_unreported(self, report):
        html = render_usage_html(report)
        assert "—" in html
        assert ">0<" not in html, "must never fabricate zeros"

    def test_escapes_hostile_values(self):
        rep = UsageReport(
            run_id="r", generated_at=0.0,
            agents=[
                AgentUsage(
                    seat="<script>alert(1)</script>", node_id="n",
                    backend="nova", model="m",
                ),
            ],
        )
        html = render_usage_html(rep)
        assert "<script>alert(1)</script>" not in html
        assert "&lt;script&gt;" in html

    def test_no_pricing(self, report):
        assert "$" not in render_usage_html(report)

    def test_rows_carry_backend_model_rounds(self, report):
        html = render_usage_html(report)
        assert "minimax.minimax-m2.5" in html and "nova" in html and "7" in html

    def test_totals_present(self, report):
        html = render_usage_html(report)
        assert "Totals" in html

    def test_run_id_escaped_in_title(self):
        rep = UsageReport(run_id="<b>run</b>", generated_at=0.0, agents=[])
        html = render_usage_html(rep)
        assert "<b>run</b>" not in html
        assert "&lt;b&gt;run&lt;/b&gt;" in html


class TestColumnParity:
    def test_html_and_markdown_agree_on_column_labels(self, report):
        """[column set matches render_usage_markdown]"""
        md = render_usage_markdown(report)
        html = render_usage_html(report)
        for label in ("Seat", "Node", "Backend", "Model", "Rounds", "Tokens", "Duration"):
            assert label in md
            assert label in html


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


@pytest.fixture
def report_with_hostile_names() -> UsageReport:
    return UsageReport(
        run_id="run-1",
        generated_at=0.0,
        agents=[
            AgentUsage(
                seat="<script>alert(1)</script>", node_id="n",
                backend="nova", model="<img src=x>",
            ),
        ],
    )


class TestNodeCycleWorkerRenderingHtml:
    def test_report_renders_node_cycle_worker(self, report_with_cycles_and_workers):
        html = render_usage_html(report_with_cycles_and_workers)
        assert "development" in html
        assert "cycle 1" in html and "cycle 2" in html
        assert "development.w1" in html and "development.w2" in html

    def test_single_cycle_seat_has_no_cycle_rows(self, report):
        # `report` has no .cycles populated (defaults to []) — no cycle
        # sub-rows for any agent regardless of `rounds`.
        html = render_usage_html(report)
        assert "cycle 1" not in html


class TestFailuresSectionHtml:
    def test_report_failures_section(self, report_with_failure):
        html = render_usage_html(report_with_failure)
        assert "Failures" in html
        assert "TimeoutError" in html

    def test_no_failures_section_when_clean(self, report):
        assert "Failures" not in render_usage_html(report)


class TestPartialMarkerBoth:
    def test_partial_ledger_is_labelled(self, report_partial):
        """Spec §8 Q1: a partial run must SAY so, not print a total that
        silently omits pre-park usage."""
        md = render_usage_markdown(report_partial)
        html = render_usage_html(report_partial)
        assert "artial" in md and "artial" in html
        assert "partial" in md.lower().split("**totals")[1][:40]


class TestHtmlSelfContainedWithCycles:
    def test_html_is_self_contained(self, report_with_cycles_and_workers):
        html = render_usage_html(report_with_cycles_and_workers)
        for forbidden in ("<link", "<script src", "@import", "cdn."):
            assert forbidden not in html.lower()

    def test_html_escapes_seat_and_model(self, report_with_hostile_names):
        """Model ids and seat names are data, not markup."""
        html = render_usage_html(report_with_hostile_names)
        assert "<script>" not in html
        assert "&lt;script&gt;" in html


class TestNoPricingWithCyclesAndFailures:
    def test_no_pricing_in_output(self, report_with_cycles_and_workers):
        for out in (
            render_usage_markdown(report_with_cycles_and_workers),
            render_usage_html(report_with_cycles_and_workers),
        ):
            assert "$" not in out
            assert "cost" not in out.lower()
