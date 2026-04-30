"""Unit tests for parrot.flows.dev_loop.flow.build_dev_loop_flow (TASK-886, TASK-901).

These tests verify the *topology* of the assembled AgentsFlow rather
than running it end-to-end (the full run path is exercised by the
live integration tests in TASK-889). Topology checks: nodes registered,
branching topology (FEAT-132), linear chain wired, QA conditional
branch present (pass + fail), and the global error route from each
middle node to the failure handler.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest

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
        names = set(flow.nodes.keys())
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
        """bug path: intent_classifier → bug_intake (conditional)."""
        targets = _outgoing_targets(flow, "intent_classifier")
        assert "bug_intake" in targets

    def test_intent_classifier_routes_to_research(self, flow):
        """non-bug path: intent_classifier → research directly (conditional)."""
        targets = _outgoing_targets(flow, "intent_classifier")
        assert "research" in targets

    def test_bug_intake_routes_to_research(self, flow):
        """bug path continuation: bug_intake → research (linear)."""
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
        # Find the QA→handoff transition; activate it with passed=True.
        transitions = flow.nodes["qa"].outgoing_transitions
        targets_for_pass = set()
        passing_report = QAReport(
            passed=True, criterion_results=[], lint_passed=True
        )
        for t in transitions:
            if t.predicate is not None and t.predicate(passing_report):
                targets_for_pass.update(t.targets)
        assert "deployment_handoff" in targets_for_pass

    def test_qa_fail_routes_to_failure_handler(self, flow):
        transitions = flow.nodes["qa"].outgoing_transitions
        targets_for_fail = set()
        failing_report = QAReport(
            passed=False, criterion_results=[], lint_passed=False
        )
        for t in transitions:
            if t.predicate is not None and t.predicate(failing_report):
                targets_for_fail.update(t.targets)
        assert "failure_handler" in targets_for_fail


class TestErrorRoutes:
    @pytest.mark.parametrize(
        "source",
        ["intent_classifier", "research", "development", "qa", "deployment_handoff"],
    )
    def test_error_transition_to_failure_handler(self, flow, source):
        transitions = flow.nodes[source].outgoing_transitions
        # An ON_ERROR transition has no predicate but its `condition`
        # enum value is "on_error". We accept either signal.
        from parrot.bots.flow.fsm import TransitionCondition

        error_targets = set()
        for t in transitions:
            if t.condition == TransitionCondition.ON_ERROR:
                error_targets.update(t.targets)
        assert "failure_handler" in error_targets


class TestKindRouting:
    """FEAT-132: Verify the IntentClassifier-driven on_condition routing."""

    def _get_conditional_targets(self, flow, source_name: str, result: Any) -> set:
        """Collect targets for which predicates fire with *result*."""
        targets: set = set()
        for t in flow.nodes[source_name].outgoing_transitions:
            if t.predicate is not None and t.predicate(result):
                targets.update(t.targets)
        return targets

    def test_routes_bug_through_bug_intake(self, flow):
        """kind='bug' should route intent_classifier → bug_intake."""
        from parrot.flows.dev_loop import ShellCriterion
        brief = WorkBrief(
            kind="bug",
            summary="Customer sync drops the last row",
            affected_component="etl/customers/sync.yaml",
            acceptance_criteria=[ShellCriterion(name="lint", command="ruff check .")],
            escalation_assignee="oncall@example.com",
            reporter="reporter@example.com",
        )
        targets = self._get_conditional_targets(flow, "intent_classifier", brief)
        assert "bug_intake" in targets
        assert "research" not in targets

    @pytest.mark.parametrize("kind", ["enhancement", "new_feature"])
    def test_routes_non_bug_skips_bug_intake(self, flow, kind):
        """kind != 'bug' should route intent_classifier → research directly."""
        from parrot.flows.dev_loop import ShellCriterion
        brief = WorkBrief(
            kind=kind,
            summary="Add dark mode to the reporting dashboard",
            affected_component="frontend/reporting",
            acceptance_criteria=[ShellCriterion(name="lint", command="ruff check .")],
            escalation_assignee="oncall@example.com",
            reporter="reporter@example.com",
        )
        targets = self._get_conditional_targets(flow, "intent_classifier", brief)
        assert "research" in targets
        assert "bug_intake" not in targets


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _outgoing_targets(flow, source_name: str) -> set[str]:
    targets: set[str] = set()
    for t in flow.nodes[source_name].outgoing_transitions:
        targets.update(t.targets)
    return targets
