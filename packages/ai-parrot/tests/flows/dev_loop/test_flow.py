"""Unit tests for parrot.flows.dev_loop.flow.build_dev_loop_flow.

These tests verify the *topology* of the assembled AgentsFlow rather
than running it end-to-end (the full run path is exercised by the
live integration tests). Topology checks: nodes registered, branching
topology (FEAT-132), linear chain wired, QA conditional branch present
(pass + fail), and the global error route from each middle node to the
failure handler.

The factory builds on the FEAT-163 ``AgentsFlow`` executor using
explicit conditional edges (``add_edge`` / ``FlowEdge``); assertions
therefore inspect ``flow._nodes`` and ``flow._edges``.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest

from parrot.bots.flows.flow import FlowEdge
from parrot.flows.dev_loop import (
    QAReport,
    WorkBrief,
    build_dev_loop_flow,
)


@pytest.fixture
def flow():
    dispatcher = MagicMock()
    jira = MagicMock()
    return build_dev_loop_flow(
        dispatcher=dispatcher,
        jira_toolkit=jira,
        log_toolkits={},
        redis_url="redis://localhost:6379/0",
    )


class TestNodeRegistration:
    def test_seven_nodes_registered(self, flow):
        names = set(flow._nodes.keys())
        assert names == {
            "intent_classifier",
            "bug_intake",
            "research",
            "development",
            "qa",
            "deployment_handoff",
            "failure_handler",
        }


class TestLinearChainTransitions:
    def test_intent_classifier_routes_to_bug_intake(self, flow):
        """bug path: intent_classifier -> bug_intake (conditional)."""
        targets = _outgoing_targets(flow, "intent_classifier")
        assert "bug_intake" in targets

    def test_intent_classifier_routes_to_research(self, flow):
        """non-bug path: intent_classifier -> research directly (conditional)."""
        targets = _outgoing_targets(flow, "intent_classifier")
        assert "research" in targets

    def test_bug_intake_routes_to_research(self, flow):
        """bug path continuation: bug_intake -> research (linear)."""
        targets = _outgoing_targets(flow, "bug_intake")
        assert "research" in targets

    def test_research_routes_to_development(self, flow):
        targets = _outgoing_targets(flow, "research")
        assert "development" in targets

    def test_development_routes_to_qa(self, flow):
        targets = _outgoing_targets(flow, "development")
        assert "qa" in targets


class TestQABranching:
    def test_qa_pass_routes_to_handoff(self, flow):
        passing_report = QAReport(
            passed=True, criterion_results=[], lint_passed=True
        )
        targets = _conditional_targets(flow, "qa", passing_report)
        assert "deployment_handoff" in targets
        assert "failure_handler" not in targets

    def test_qa_fail_routes_to_failure_handler(self, flow):
        failing_report = QAReport(
            passed=False, criterion_results=[], lint_passed=False
        )
        targets = _conditional_targets(flow, "qa", failing_report)
        assert "failure_handler" in targets
        assert "deployment_handoff" not in targets


class TestErrorRoutes:
    @pytest.mark.parametrize(
        "source",
        ["intent_classifier", "research", "development", "qa", "deployment_handoff"],
    )
    def test_error_transition_to_failure_handler(self, flow, source):
        error_targets = {
            e.to
            for e in _edges_from(flow, source)
            if e.condition == "on_error"
        }
        assert "failure_handler" in error_targets


class TestKindRouting:
    """FEAT-132: Verify the IntentClassifier-driven conditional routing."""

    def test_routes_bug_through_bug_intake(self, flow):
        """kind='bug' should route intent_classifier -> bug_intake."""
        from parrot.flows.dev_loop import ShellCriterion
        brief = WorkBrief(
            kind="bug",
            summary="Customer sync drops the last row",
            affected_component="etl/customers/sync.yaml",
            acceptance_criteria=[ShellCriterion(name="lint", command="ruff check .")],
            escalation_assignee="oncall@example.com",
            reporter="reporter@example.com",
        )
        targets = _conditional_targets(flow, "intent_classifier", brief)
        assert "bug_intake" in targets
        assert "research" not in targets

    @pytest.mark.parametrize("kind", ["enhancement", "new_feature"])
    def test_routes_non_bug_skips_bug_intake(self, flow, kind):
        """kind != 'bug' should route intent_classifier -> research directly."""
        from parrot.flows.dev_loop import ShellCriterion
        brief = WorkBrief(
            kind=kind,
            summary="Add dark mode to the reporting dashboard",
            affected_component="frontend/reporting",
            acceptance_criteria=[ShellCriterion(name="lint", command="ruff check .")],
            escalation_assignee="oncall@example.com",
            reporter="reporter@example.com",
        )
        targets = _conditional_targets(flow, "intent_classifier", brief)
        assert "research" in targets
        assert "bug_intake" not in targets


class TestEventPublisherWiring:
    def test_publisher_attached_by_default(self, flow):
        assert flow._on_node_event is not None
        assert flow._event_publisher is flow._on_node_event

    def test_publisher_can_be_disabled(self):
        f = build_dev_loop_flow(
            dispatcher=MagicMock(),
            jira_toolkit=MagicMock(),
            log_toolkits={},
            redis_url="redis://localhost:6379/0",
            publish_flow_events=False,
        )
        assert f._on_node_event is None
        assert f._event_publisher is None


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _edges_from(flow, source_name: str) -> list[FlowEdge]:
    return [e for e in flow._edges if e.from_ == source_name]


def _outgoing_targets(flow, source_name: str) -> set[str]:
    return {e.to for e in _edges_from(flow, source_name)}


def _conditional_targets(flow, source_name: str, result: Any) -> set[str]:
    """Collect targets whose on_condition predicates fire for *result*."""
    targets: set[str] = set()
    for e in _edges_from(flow, source_name):
        if e.condition == "on_condition" and callable(e.predicate):
            if e.predicate(result):
                targets.add(e.to)
    return targets
