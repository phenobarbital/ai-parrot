"""Feature-mode integration tests (FEAT-378 TASK-1925).

Covers: declarative/imperative parity for the feature topology,
``IntentClassifierNode`` routing of a ``FeatureBrief``, and end-to-end
routing through the real ``build_dev_loop_feature_flow`` with stubbed
node ``execute()`` methods (no live dispatch/Jira/GitHub).
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from parrot.bots.flows.core.context import FlowContext
from parrot.flows.dev_loop.definition import build_dev_loop_definition
from parrot.flows.dev_loop.models import QAReport
from parrot.flows.dev_loop.nodes.close import DevLoopCloseNode
from parrot.flows.dev_loop.nodes.development import DevelopmentNode
from parrot.flows.dev_loop.nodes.failure_handler import FailureHandlerNode
from parrot.flows.dev_loop.nodes.qa import QANode
from parrot.flows.dev_loop.runner import build_dev_loop_feature_flow

# FEAT-377/A (the repair-loop attempt counter) had not merged to `dev` as
# of this task (2026-07-27) — `FeedbackRouterNode._retry_allowed()`
# unconditionally returns False and no retry edge is wired (spec §7
# documented degradation). Flip to False once FEAT-377/A lands and the
# retry edge is wired in definition.py/runner.py.
FEAT_377A_ABSENT = True


def _ran(result) -> set:
    nr = getattr(result, "node_results", None)
    if isinstance(nr, dict):
        return set(nr.keys())
    return set(getattr(result, "results", {}).keys())


def _FeatureCtx(feature_brief):
    """Build a real ``FlowContext`` seeded with a ``FeatureBrief``."""
    return FlowContext(
        initial_task="feature run",
        shared_data={"feature_brief": feature_brief, "run_id": "r1"},
    )


# ── declarative/imperative parity ───────────────────────────────────────


def test_definition_parity_feature_mode():
    """The imperative feature flow re-declares every declarative edge."""
    definition = build_dev_loop_definition(feature=True)
    flow = build_dev_loop_feature_flow(
        dispatcher=MagicMock(), redis_url="redis://x", publish_flow_events=False,
    )

    decl_node_ids = {n.id for n in definition.nodes}
    imp_node_ids = set(flow._nodes)
    assert decl_node_ids == imp_node_ids

    # Normalize the declarative "on_success" -> imperative "always" naming
    # difference (pre-existing, established by the bug/revision topologies
    # too: definition.py's on_success edges become bare ``flow.add_edge()``
    # calls with the engine's default ``condition="always"`` — same
    # semantic edge, different vocabulary per layer).
    def _normalize(condition: str) -> str:
        return "always" if condition == "on_success" else condition

    decl_edges = {(e.from_, e.to, _normalize(e.condition)) for e in definition.edges}
    imp_edges = {(e.from_, e.to, e.condition) for e in flow._edges}
    assert decl_edges == imp_edges

    # Every on_condition edge on both sides actually carries a predicate.
    decl_predicated = {
        (e.from_, e.to) for e in definition.edges if e.condition == "on_condition"
    }
    imp_predicated = {
        (e.from_, e.to) for e in flow._edges
        if e.condition == "on_condition" and e.predicate is not None
    }
    assert decl_predicated == imp_predicated


# ── IntentClassifierNode routing (unit-level, no full flow) ─────────────


@pytest.mark.asyncio
async def test_classifier_routes_feature(tmp_path):
    from parrot.bots.flows.flow.cel_evaluator import CELPredicateEvaluator
    from parrot.flows.dev_loop.models import FeatureBrief
    from parrot.flows.dev_loop.nodes.intent_classifier import IntentClassifierNode

    doc = tmp_path / "x.proposal.md"
    doc.write_text("# proposal")
    fb = FeatureBrief(document_path=str(doc), document_kind="proposal")
    node = IntentClassifierNode(redis_url="redis://x")
    shared = {"feature_brief": fb, "run_id": ""}

    result = await node.execute(shared)

    assert isinstance(result, FeatureBrief)
    assert result.kind == "feature"
    assert shared["feature_brief"] is result
    assert CELPredicateEvaluator('result.kind == "feature"')(result) is True


@pytest.mark.asyncio
async def test_classifier_invalid_document_fails_early(tmp_path):
    from pydantic import ValidationError

    from parrot.flows.dev_loop.nodes.intent_classifier import IntentClassifierNode

    node = IntentClassifierNode(redis_url="redis://x")
    shared = {
        "feature_brief": {
            "kind": "feature",
            "document_path": str(tmp_path / "does-not-exist.md"),
            "document_kind": "proposal",
        },
        "run_id": "",
    }

    with pytest.raises(ValidationError):
        await node.execute(shared)

    # No dispatch-relevant state was published — validation failed first,
    # before any node dispatch call.
    assert shared["feature_brief"] == {
        "kind": "feature",
        "document_path": str(tmp_path / "does-not-exist.md"),
        "document_kind": "proposal",
    }


# ── end-to-end feature-flow routing (drives the real feature flow) ─────


def _stub_feature_executes(
    monkeypatch, *, qa_passed: bool, feedback_decision: str = "escalate"
):
    from parrot.flows.dev_loop.models import (
        DevelopmentOutput,
        FeedbackDecision,
        PlannerOutput,
        SynthesisReport,
    )
    from parrot.flows.dev_loop.nodes.feature_handoff import FeatureHandoffNode
    from parrot.flows.dev_loop.nodes.feedback_router import FeedbackRouterNode
    from parrot.flows.dev_loop.nodes.intent_classifier import IntentClassifierNode
    from parrot.flows.dev_loop.nodes.planner import PlannerNode
    from parrot.flows.dev_loop.nodes.synthesis import SynthesisNode

    async def intent_exec(self, ctx, deps=None, **kw):
        shared = self.shared_state(ctx)
        return shared["feature_brief"]

    async def planner_exec(self, ctx, deps=None, **kw):
        shared = self.shared_state(ctx)
        out = PlannerOutput(
            spec_path="sdd/specs/x.spec.md",
            task_index_path="/tmp/sdd/tasks/index/x.json",
            feat_id="FEAT-999",
            branch_name="feat-999-x",
            worktree_path="/tmp/feat-999-x",
        )
        shared["planner_output"] = out
        return out

    async def dev_exec(self, ctx, deps=None, **kw):
        out = DevelopmentOutput(files_changed=["a.py"], commit_shas=["abc"], summary="ok")
        self.shared_state(ctx)["development_output"] = out
        return out

    async def synthesis_exec(self, ctx, deps=None, **kw):
        out = SynthesisReport(consistent=True, adjustments=[], summary="clean")
        self.shared_state(ctx)["synthesis_report"] = out
        return out

    async def qa_exec(self, ctx, deps=None, **kw):
        return QAReport(passed=qa_passed, criterion_results=[], lint_passed=qa_passed)

    async def feedback_exec(self, ctx, deps=None, **kw):
        out = FeedbackDecision(
            decision=feedback_decision,
            notes="minor notes" if feedback_decision == "accept_with_notes" else "",
        )
        self.shared_state(ctx)["feedback_decision"] = out
        return out

    async def handoff_exec(self, ctx, deps=None, **kw):
        return {
            "status": "ready_to_deploy", "pr_url": "u", "pr_number": 1,
            "docs_path": "docs/features/feat-999-x.md", "wiki_page_id": None,
        }

    async def failure_exec(self, ctx, deps=None, **kw):
        return {"status": "escalated"}

    async def close_exec(self, ctx, deps=None, **kw):
        return {"status": "closed"}

    monkeypatch.setattr(IntentClassifierNode, "execute", intent_exec)
    monkeypatch.setattr(PlannerNode, "execute", planner_exec)
    monkeypatch.setattr(DevelopmentNode, "execute", dev_exec)
    monkeypatch.setattr(SynthesisNode, "execute", synthesis_exec)
    monkeypatch.setattr(QANode, "execute", qa_exec)
    monkeypatch.setattr(FeedbackRouterNode, "execute", feedback_exec)
    monkeypatch.setattr(FeatureHandoffNode, "execute", handoff_exec)
    monkeypatch.setattr(FailureHandlerNode, "execute", failure_exec)
    monkeypatch.setattr(DevLoopCloseNode, "execute", close_exec)


def _feature_flow():
    return build_dev_loop_feature_flow(
        dispatcher=MagicMock(),
        redis_url="redis://x",
        publish_flow_events=False,
    )


def _feature_brief(tmp_path):
    from parrot.flows.dev_loop.models import FeatureBrief

    doc = tmp_path / "x.proposal.md"
    doc.write_text("# p")
    return FeatureBrief(document_path=str(doc), document_kind="proposal")


@pytest.mark.asyncio
async def test_feature_flow_happy_path(monkeypatch, tmp_path):
    _stub_feature_executes(monkeypatch, qa_passed=True)
    flow = _feature_flow()
    res = await flow.run_flow(_FeatureCtx(_feature_brief(tmp_path)))
    ran = _ran(res)

    assert {
        "intent_classifier", "planner", "development", "synthesis",
        "qa", "feature_handoff", "close",
    }.issubset(ran)
    assert "feedback_router" not in ran
    assert "failure_handler" not in ran


@pytest.mark.asyncio
async def test_feature_flow_escalation(monkeypatch, tmp_path):
    _stub_feature_executes(monkeypatch, qa_passed=False, feedback_decision="escalate")
    flow = _feature_flow()
    res = await flow.run_flow(_FeatureCtx(_feature_brief(tmp_path)))
    ran = _ran(res)

    assert {
        "intent_classifier", "planner", "development", "synthesis",
        "qa", "feedback_router", "failure_handler",
    }.issubset(ran)
    assert "feature_handoff" not in ran
    assert "close" not in ran


@pytest.mark.asyncio
async def test_feature_flow_accept_with_notes(monkeypatch, tmp_path):
    _stub_feature_executes(monkeypatch, qa_passed=False, feedback_decision="accept_with_notes")
    flow = _feature_flow()
    res = await flow.run_flow(_FeatureCtx(_feature_brief(tmp_path)))
    ran = _ran(res)

    assert {
        "intent_classifier", "planner", "development", "synthesis",
        "qa", "feedback_router", "feature_handoff", "close",
    }.issubset(ran)
    assert "failure_handler" not in ran


def test_feature_flow_forwards_graph_memory_and_plan_approval():
    """FEAT-377 TASK-1914/1915/1916: build_dev_loop_feature_flow() must
    thread graph_memory/require_plan_approval into
    build_dev_loop_node_factories() — before this fix, feature-mode
    always got graph_memory=None and require_plan_approval=False no
    matter what the caller passed."""
    from unittest.mock import patch

    import parrot.flows.dev_loop.runner as runner_mod

    sentinel_memory = object()

    with patch.object(
        runner_mod,
        "build_dev_loop_node_factories",
        wraps=runner_mod.build_dev_loop_node_factories,
    ) as mock_factories:
        build_dev_loop_feature_flow(
            dispatcher=MagicMock(),
            redis_url="redis://x",
            publish_flow_events=False,
            graph_memory=sentinel_memory,
            require_plan_approval=True,
        )

    mock_factories.assert_called_once()
    _, kwargs = mock_factories.call_args
    assert kwargs["graph_memory"] is sentinel_memory
    assert kwargs["require_plan_approval"] is True


@pytest.mark.skipif(FEAT_377A_ABSENT, reason="retry edge requires FEAT-377/A")
@pytest.mark.asyncio
async def test_feature_flow_feedback_retry(monkeypatch, tmp_path):  # pragma: no cover
    """Once FEAT-377/A lands and the retry edge is wired, a "retry"
    FeedbackDecision should route feedback_router -> development again."""
    _stub_feature_executes(monkeypatch, qa_passed=False, feedback_decision="retry")
    flow = _feature_flow()
    res = await flow.run_flow(_FeatureCtx(_feature_brief(tmp_path)))
    ran = _ran(res)

    assert "feedback_router" in ran
    # A second development pass would be observable once the retry edge
    # and re-entrant wave tracking exist — left for the FEAT-377/A follow-up.
