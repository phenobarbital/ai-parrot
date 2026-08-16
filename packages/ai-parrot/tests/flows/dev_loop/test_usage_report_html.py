"""Unit tests for the self-contained HTML usage report (FEAT-405, TASK-2091,
Module 7b).
"""

from __future__ import annotations

import pytest
from parrot.flows.dev_loop.usage_report import (
    AgentUsage,
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
