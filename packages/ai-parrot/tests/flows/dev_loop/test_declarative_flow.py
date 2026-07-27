"""Declarative dev-loop definition + factories + parity (FEAT-250 TASK-010)."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from parrot.bots.flows.flow.flow import NODE_REGISTRY
from parrot.bots.flows.flow.cel_evaluator import CELPredicateEvaluator
from parrot.flows.dev_loop.definition import build_dev_loop_definition
from parrot.flows.dev_loop.factories import build_dev_loop_node_factories
from parrot.flows.dev_loop.flow import build_dev_loop_flow
from parrot.flows.dev_loop.models import (
    CodexCodeDispatchProfile,
    LLMCodeDispatchProfile,
    QAReport,
    WorkBrief,
)
from parrot.flows.dev_loop.nodes.bug_intake import BugIntakeNode
from parrot.flows.dev_loop.nodes.close import DevLoopCloseNode
from parrot.flows.dev_loop.nodes.deployment_handoff import DeploymentHandoffNode
from parrot.flows.dev_loop.nodes.development import DevelopmentNode
from parrot.flows.dev_loop.nodes.failure_handler import FailureHandlerNode
from parrot.flows.dev_loop.nodes.intent_classifier import IntentClassifierNode
from parrot.flows.dev_loop.nodes.qa import QANode
from parrot.flows.dev_loop.nodes.research import ResearchNode

_DEV_LOOP_TYPES = [
    "dev_loop.intent_classifier",
    "dev_loop.bug_intake",
    "dev_loop.research",
    "dev_loop.development",
    "dev_loop.qa",
    "dev_loop.deployment_handoff",
    "dev_loop.failure_handler",
    "dev_loop.close",
    "dev_loop.revision_handoff",  # FEAT-250 TASK-012
    "dev_loop.planner",  # FEAT-378 TASK-1925
    "dev_loop.synthesis",  # FEAT-378 TASK-1925
    "dev_loop.feedback_router",  # FEAT-378 TASK-1925
    "dev_loop.feature_handoff",  # FEAT-378 TASK-1925
]

# Snapshot of the pre-FEAT-378 bug + revision definitions (git history,
# 2026-07-27) — asserted byte-identical (node ids + edge (from, to,
# condition, predicate) tuples) after this feature's changes, per
# TASK-1925's "byte-identical" acceptance criterion.
_BUG_NODE_IDS = {
    "intent_classifier", "bug_intake", "research", "development",
    "qa", "deployment_handoff", "failure_handler", "close",
}
_BUG_EDGES = {
    ("intent_classifier", "bug_intake", "on_condition", 'result.kind == "bug"'),
    ("intent_classifier", "research", "on_condition", 'result.kind != "bug"'),
    ("bug_intake", "research", "on_success", None),
    ("research", "development", "on_success", None),
    ("development", "qa", "on_success", None),
    ("qa", "deployment_handoff", "on_condition", "result.passed == true"),
    ("qa", "failure_handler", "on_condition", "result.passed == false"),
    ("deployment_handoff", "close", "on_success", None),
    ("intent_classifier", "failure_handler", "on_error", None),
    ("bug_intake", "failure_handler", "on_error", None),
    ("research", "failure_handler", "on_error", None),
    ("development", "failure_handler", "on_error", None),
    ("qa", "failure_handler", "on_error", None),
    ("deployment_handoff", "failure_handler", "on_error", None),
}
_REVISION_NODE_IDS = {"development", "qa", "revision_handoff", "failure_handler", "close"}
_REVISION_EDGES = {
    ("development", "qa", "on_success", None),
    ("qa", "revision_handoff", "on_condition", "result.passed == true"),
    ("qa", "failure_handler", "on_condition", "result.passed == false"),
    ("revision_handoff", "close", "on_success", None),
    ("development", "failure_handler", "on_error", None),
    ("qa", "failure_handler", "on_error", None),
    ("revision_handoff", "failure_handler", "on_error", None),
}


def _edge_tuples(defn) -> set:
    return {
        (e.from_, e.to, e.condition, getattr(e, "predicate", None))
        for e in defn.edges
    }


def _brief(kind: str) -> WorkBrief:
    from parrot.flows.dev_loop.models import FlowtaskCriterion

    return WorkBrief(
        kind=kind,
        summary="customer sync drops the last row sometimes",
        affected_component="etl/customers/sync.yaml",
        log_sources=[],
        acceptance_criteria=[FlowtaskCriterion(name="run", task_path="a.yaml")],
        escalation_assignee="a",
        reporter="b",
    )


# ── registration ───────────────────────────────────────────────────────


def test_register_node_dev_loop_types():
    import parrot.flows.dev_loop.factories  # noqa: F401 - triggers registration

    for t in _DEV_LOOP_TYPES:
        assert t in NODE_REGISTRY


# ── definition validity ────────────────────────────────────────────────


def test_definition_is_valid_and_complete():
    defn = build_dev_loop_definition()
    ids = {n.id for n in defn.nodes}
    assert ids == {
        "intent_classifier",
        "bug_intake",
        "research",
        "development",
        "qa",
        "deployment_handoff",
        "failure_handler",
        "close",
    }
    # every node type is a registered dev_loop.* type
    assert all(n.type.startswith("dev_loop.") for n in defn.nodes)
    # the success path terminates at close
    assert any(e.from_ == "deployment_handoff" and e.to == "close" for e in defn.edges)


def test_definition_revision_graph():
    # FEAT-250 TASK-012 authored the revision graph.
    defn = build_dev_loop_definition(revision=True)
    ids = {n.id for n in defn.nodes}
    assert ids == {"development", "qa", "revision_handoff", "failure_handler", "close"}
    assert "research" not in ids and "intent_classifier" not in ids


def test_definition_feature_graph():
    # FEAT-378 TASK-1925 authored the feature-mode graph.
    defn = build_dev_loop_definition(feature=True)
    ids = {n.id for n in defn.nodes}
    assert ids == {
        "intent_classifier", "planner", "development", "synthesis",
        "qa", "feedback_router", "feature_handoff", "failure_handler", "close",
    }
    assert "research" not in ids and "bug_intake" not in ids
    assert all(n.type.startswith("dev_loop.") for n in defn.nodes)

    edges = _edge_tuples(defn)
    assert ("intent_classifier", "planner", "on_condition", 'result.kind == "feature"') in edges
    assert ("planner", "development", "on_success", None) in edges
    assert ("development", "synthesis", "on_success", None) in edges
    assert ("synthesis", "qa", "on_success", None) in edges
    assert ("qa", "feature_handoff", "on_condition", "result.passed == true") in edges
    assert ("qa", "feedback_router", "on_condition", "result.passed == false") in edges
    assert (
        "feedback_router", "failure_handler", "on_condition", 'result.decision == "escalate"'
    ) in edges
    assert (
        "feedback_router", "feature_handoff", "on_condition",
        'result.decision == "accept_with_notes"',
    ) in edges
    assert ("feature_handoff", "close", "on_success", None) in edges
    # No retry edge — FEAT-377/A absent as of this task (spec §7).
    assert not any(
        e[0] == "feedback_router" and e[1] == "development" for e in edges
    )


def test_bug_topology_unchanged():
    """Bug + revision topologies are byte-identical to the pre-FEAT-378 snapshot."""
    bug_defn = build_dev_loop_definition()
    assert {n.id for n in bug_defn.nodes} == _BUG_NODE_IDS
    assert _edge_tuples(bug_defn) == _BUG_EDGES

    rev_defn = build_dev_loop_definition(revision=True)
    assert {n.id for n in rev_defn.nodes} == _REVISION_NODE_IDS
    assert _edge_tuples(rev_defn) == _REVISION_EDGES


# ── factories ──────────────────────────────────────────────────────────


def test_factories_cover_all_types_and_construct_nodes():
    factories = build_dev_loop_node_factories(dispatcher=MagicMock(), jira_toolkit=MagicMock(), redis_url="redis://x")
    assert set(factories) == set(_DEV_LOOP_TYPES)
    defn = build_dev_loop_definition()
    by_id = {n.id: n for n in defn.nodes}
    node = factories["dev_loop.research"](by_id["research"], {"intent_classifier"}, {"development"})
    assert node.node_id == "research"
    assert "intent_classifier" in node.dependencies
    assert "development" in node.successors


def test_development_factory_accepts_alternate_dispatcher():
    default_dispatcher = MagicMock()
    development_dispatcher = MagicMock()
    development_profile = CodexCodeDispatchProfile()
    factories = build_dev_loop_node_factories(
        dispatcher=default_dispatcher,
        development_dispatcher=development_dispatcher,
        development_profile=development_profile,
        jira_toolkit=MagicMock(),
        redis_url="redis://x",
    )
    defn = build_dev_loop_definition()
    by_id = {n.id: n for n in defn.nodes}

    node = factories["dev_loop.development"](by_id["development"], {"research"}, {"qa"})

    assert isinstance(node, DevelopmentNode)
    assert node._dispatcher is development_dispatcher
    assert node._dispatch_profile is development_profile


def test_development_factory_accepts_llm_dispatch_profile():
    default_dispatcher = MagicMock()
    development_dispatcher = MagicMock()
    development_profile = LLMCodeDispatchProfile(llm="nvidia:z-ai/glm-5.1")
    factories = build_dev_loop_node_factories(
        dispatcher=default_dispatcher,
        development_dispatcher=development_dispatcher,
        development_profile=development_profile,
        jira_toolkit=MagicMock(),
        redis_url="redis://x",
    )
    defn = build_dev_loop_definition()
    by_id = {n.id: n for n in defn.nodes}

    node = factories["dev_loop.development"](by_id["development"], {"research"}, {"qa"})

    assert isinstance(node, DevelopmentNode)
    assert node._dispatcher is development_dispatcher
    assert node._dispatch_profile is development_profile


# ── CEL parity with the legacy Python callables ────────────────────────


def test_cel_predicates_match_legacy_semantics():
    assert CELPredicateEvaluator('result.kind == "bug"')(_brief("bug")) is True
    assert CELPredicateEvaluator('result.kind == "bug"')(_brief("enhancement")) is False
    assert CELPredicateEvaluator('result.kind != "bug"')(_brief("enhancement")) is True
    passed = QAReport(passed=True, criterion_results=[], lint_passed=True)
    failed = QAReport(passed=False, criterion_results=[], lint_passed=True)
    assert CELPredicateEvaluator("result.passed == true")(passed) is True
    assert CELPredicateEvaluator("result.passed == true")(failed) is False
    assert CELPredicateEvaluator("result.passed == false")(failed) is True


# ── end-to-end routing parity (drives the real build_dev_loop_flow) ─────


def _stub_executes(monkeypatch, *, intent_kind: str, qa_passed: bool):
    """Patch each node class' execute with a lightweight typed stub."""
    from parrot.flows.dev_loop.models import (
        DevelopmentOutput,
        ResearchOutput,
    )

    brief = _brief(intent_kind)

    async def intent_exec(self, ctx, deps=None, **kw):
        return brief

    async def bug_exec(self, ctx, deps=None, **kw):
        return brief

    async def research_exec(self, ctx, deps=None, **kw):
        return ResearchOutput(
            jira_issue_key="OPS-1",
            spec_path="x",
            feat_id="FEAT-1",
            branch_name="feat-1-x",
            worktree_path="/tmp/feat-1-x",
        )

    async def dev_exec(self, ctx, deps=None, **kw):
        return DevelopmentOutput(files_changed=[], commit_shas=[], summary="ok")

    async def qa_exec(self, ctx, deps=None, **kw):
        return QAReport(passed=qa_passed, criterion_results=[], lint_passed=qa_passed)

    async def handoff_exec(self, ctx, deps=None, **kw):
        return {"status": "ready_to_deploy", "pr_url": "u", "pr_number": 1}

    async def failure_exec(self, ctx, deps=None, **kw):
        return {"status": "escalated"}

    async def close_exec(self, ctx, deps=None, **kw):
        return {"status": "closed"}

    monkeypatch.setattr(IntentClassifierNode, "execute", intent_exec)
    monkeypatch.setattr(BugIntakeNode, "execute", bug_exec)
    monkeypatch.setattr(ResearchNode, "execute", research_exec)
    monkeypatch.setattr(DevelopmentNode, "execute", dev_exec)
    monkeypatch.setattr(QANode, "execute", qa_exec)
    monkeypatch.setattr(DeploymentHandoffNode, "execute", handoff_exec)
    monkeypatch.setattr(FailureHandlerNode, "execute", failure_exec)
    monkeypatch.setattr(DevLoopCloseNode, "execute", close_exec)


def _flow():
    return build_dev_loop_flow(
        dispatcher=MagicMock(),
        jira_toolkit=MagicMock(),
        log_toolkits={},
        redis_url="redis://x",
        publish_flow_events=False,
        lifecycle_events=False,
    )


def _ran(result) -> set:
    nr = getattr(result, "node_results", None)
    if isinstance(nr, dict):
        return set(nr.keys())
    return set(getattr(result, "results", {}).keys())


@pytest.mark.asyncio
async def test_routing_non_bug_skips_bug_intake(monkeypatch):
    _stub_executes(monkeypatch, intent_kind="enhancement", qa_passed=True)
    flow = _flow()
    res = await flow.run_flow("go")
    ran = _ran(res)
    assert {"intent_classifier", "research", "development", "qa", "deployment_handoff", "close"}.issubset(ran)
    assert "bug_intake" not in ran
    assert "failure_handler" not in ran


@pytest.mark.asyncio
async def test_routing_bug_runs_bug_intake(monkeypatch):
    _stub_executes(monkeypatch, intent_kind="bug", qa_passed=True)
    flow = _flow()
    res = await flow.run_flow("go")
    ran = _ran(res)
    assert {"intent_classifier", "bug_intake", "research", "development", "qa", "deployment_handoff", "close"}.issubset(
        ran
    )
    assert "failure_handler" not in ran


@pytest.mark.asyncio
async def test_routing_qa_fail_goes_to_failure(monkeypatch):
    _stub_executes(monkeypatch, intent_kind="enhancement", qa_passed=False)
    flow = _flow()
    res = await flow.run_flow("go")
    ran = _ran(res)
    assert "failure_handler" in ran
    assert "deployment_handoff" not in ran
    assert "close" not in ran


# ── FEAT-378 feature-mode CEL parity ────────────────────────────────────


def test_cel_predicates_match_feature_mode_semantics():
    from parrot.flows.dev_loop.models import FeatureBrief, FeedbackDecision

    feature = FeedbackDecision(decision="escalate")
    accept = FeedbackDecision(decision="accept_with_notes")
    assert CELPredicateEvaluator('result.decision == "escalate"')(feature) is True
    assert CELPredicateEvaluator('result.decision == "escalate"')(accept) is False
    assert CELPredicateEvaluator('result.decision == "accept_with_notes"')(accept) is True

    def _feature_brief(tmp_path):
        doc = tmp_path / "x.proposal.md"
        doc.write_text("# p")
        return FeatureBrief(document_path=str(doc), document_kind="proposal")

    import tempfile
    from pathlib import Path

    with tempfile.TemporaryDirectory() as td:
        fb = _feature_brief(Path(td))
        assert CELPredicateEvaluator('result.kind == "feature"')(fb) is True
        assert CELPredicateEvaluator('result.kind == "bug"')(fb) is False


# FEAT-378 IntentClassifierNode routing, end-to-end feature-flow routing,
# and declarative/imperative parity for the feature topology all live in
# test_feature_flow.py (TASK-1925) — this file stays scoped to the
# declarative definition + factories + CEL-predicate suite.
