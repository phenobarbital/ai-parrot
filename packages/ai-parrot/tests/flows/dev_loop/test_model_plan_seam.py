"""``DevFlowModelPlan`` threading through the ops (``dev_loop``) build
surface (FEAT-490 TASK-2690, Module 7).

Mirrors ``tests/flows/dev_flow/test_plan_threading.py``'s harness and
assertion style — the *materialized* node's private wiring attributes
(``_pool_config``/``_dispatcher_builder`` on ``DevelopmentNode``,
``_codereview_dispatcher`` on ``QANode``, both set via
``object.__setattr__``) are what prove the plan actually reached the seat,
not just the factory map.

This topology has no ``IdeationNode`` — only the development pool and the
adversarial review pair are wireable seats here; ``model_plan.
research_primary``/``research_partner`` have nothing to map onto (spec §3
Module 7 / "Does NOT Exist": no ``IdeationNode`` in the ops topology).
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest
from parrot.flows.dev_flow.model_plan import DevFlowModelPlan, ReviewPairPlan
from parrot.flows.dev_loop.agent_builder import build_dispatcher
from parrot.flows.dev_loop.definition import DEVELOPMENT, QA
from parrot.flows.dev_loop.flow import build_dev_loop_flow
from parrot.flows.dev_loop.models.base import DevAgentPoolConfig, DevAgentSpec

TWO_SEATS = [
    DevAgentSpec(agent="nova", model="zai.glm-5"),
    DevAgentSpec(agent="nova", model="qwen.qwen3-coder-480b-a35b-v1:0"),
]


def _flow(**kwargs: Any):
    """Build a dev-loop flow with event publishing off (no Redis in tests)."""
    return build_dev_loop_flow(
        dispatcher=MagicMock(),
        jira_toolkit=MagicMock(),
        log_toolkits={},
        redis_url="redis://x",
        publish_flow_events=False,
        lifecycle_events=False,
        **kwargs,
    )


def _development_node(flow: Any) -> Any:
    return flow._nodes[DEVELOPMENT]


def _qa_node(flow: Any) -> Any:
    return flow._nodes[QA]


class TestBackwardCompatibility:
    """An omitted plan must produce today's wiring, exactly — spec
    acceptance criterion: ``build_dev_loop_flow(model_plan=None)`` is
    byte-identical to every existing ops call site."""

    def test_omitted_plan_leaves_pool_unwired(self):
        node = _development_node(_flow())
        assert node._pool_config is None
        assert node._dispatcher_builder is None

    def test_explicit_none_plan_leaves_pool_unwired(self):
        node = _development_node(_flow(model_plan=None))
        assert node._pool_config is None
        assert node._dispatcher_builder is None

    def test_omitted_plan_leaves_review_dispatcher_unwired(self):
        """No explicit codereview_dispatcher, no plan -> QANode's own
        ClaudeCodeReviewDispatcher fallback (qa.py's default), not a
        plan-derived pair."""
        node = _qa_node(_flow())
        # The default fallback wraps `dispatcher`, never a
        # ParallelPerspectiveReviewDispatcher a plan would produce.
        assert type(node._codereview_dispatcher).__name__ == "ClaudeCodeReviewDispatcher"

    def test_existing_dispatcher_builder_still_honoured(self):
        sentinel = MagicMock()
        node = _development_node(_flow(development_dispatcher_builder=sentinel))
        assert node._dispatcher_builder is sentinel

    def test_existing_pool_config_still_honoured(self):
        sentinel = DevAgentPoolConfig(agents=[DevAgentSpec(agent="claude-code")])
        node = _development_node(_flow(development_pool_config=sentinel))
        assert node._pool_config is sentinel

    def test_existing_codereview_dispatcher_still_honoured(self):
        sentinel = MagicMock()
        node = _qa_node(_flow(codereview_dispatcher=sentinel))
        assert node._codereview_dispatcher is sentinel

    def test_flow_still_builds_every_node(self):
        """Sanity: the plan kwarg does not disturb the topology."""
        without = set(_flow()._nodes)
        with_plan = set(_flow(model_plan=DevFlowModelPlan(dev_pool=TWO_SEATS))._nodes)
        assert without == with_plan


class TestPlanAppliesTheOpsSeats:
    """A supplied plan selects the ops seats it maps to."""

    def test_pool_threaded_into_development_node(self):
        node = _development_node(_flow(model_plan=DevFlowModelPlan(dev_pool=TWO_SEATS)))
        assert isinstance(node._pool_config, DevAgentPoolConfig)
        assert [(s.agent, s.model) for s in node._pool_config.agents] == [
            ("nova", "zai.glm-5"),
            ("nova", "qwen.qwen3-coder-480b-a35b-v1:0"),
        ]

    def test_pool_gets_the_real_dispatcher_builder(self):
        node = _development_node(_flow(model_plan=DevFlowModelPlan(dev_pool=TWO_SEATS)))
        assert node._dispatcher_builder is build_dispatcher

    def test_empty_pool_plan_wires_nothing(self):
        """A plan is not a pool — an empty ``dev_pool`` stays single-agent."""
        node = _development_node(_flow(model_plan=DevFlowModelPlan()))
        assert node._pool_config is None
        assert node._dispatcher_builder is None

    def test_review_pair_threaded_into_qa_node(self):
        plan = DevFlowModelPlan(review=ReviewPairPlan(counter_model="nova-2-lite"))
        node = _qa_node(_flow(model_plan=plan))
        assert type(node._codereview_dispatcher).__name__ == "ParallelPerspectiveReviewDispatcher"

    def test_review_pair_defaults_to_claude_code_primary(self):
        node = _qa_node(_flow(model_plan=DevFlowModelPlan()))
        # DevFlowModelPlan()'s review.primary defaults to claude-code, so
        # the primary reuses the flow's shared dispatcher (no second one
        # constructed) — same rule dev-flow's _build_primary_reviewer uses.
        assert type(node._codereview_dispatcher).__name__ == "ParallelPerspectiveReviewDispatcher"


class TestExplicitArgumentWinsOverThePlan:
    """Spec §3 Module 7: explicit codereview_dispatcher/development_pool_config
    always wins over the plan — this is the acceptance-criterion-named case."""

    def test_explicit_dispatcher_builder_beats_plan_derived(self):
        sentinel = MagicMock()
        node = _development_node(
            _flow(
                model_plan=DevFlowModelPlan(dev_pool=TWO_SEATS),
                development_dispatcher_builder=sentinel,
            )
        )
        assert node._dispatcher_builder is sentinel
        # The plan-derived pool_config still applies — only the builder
        # was explicitly overridden.
        assert node._pool_config is not None

    def test_explicit_pool_config_beats_plan_derived(self):
        sentinel = DevAgentPoolConfig(agents=[DevAgentSpec(agent="claude-code")])
        node = _development_node(
            _flow(
                model_plan=DevFlowModelPlan(dev_pool=TWO_SEATS),
                development_pool_config=sentinel,
            )
        )
        assert node._pool_config is sentinel

    def test_explicit_codereview_dispatcher_beats_the_plan(self):
        sentinel = MagicMock()
        node = _qa_node(
            _flow(
                model_plan=DevFlowModelPlan(review=ReviewPairPlan(counter_model="nova-2-lite")),
                codereview_dispatcher=sentinel,
            )
        )
        assert node._codereview_dispatcher is sentinel


class TestNoIdeationSeatInThisTopology:
    """spec: this topology has no IdeationNode — the plan's research_primary/
    research_partner fields have nothing to map onto here."""

    def test_research_coordinator_unaffected_by_the_plan(self):
        """research_coordinator stays an explicit-only seam, untouched by
        model_plan (unlike dev-flow's IdeationNode coordinator)."""
        sentinel = MagicMock()
        flow_with = _flow(model_plan=DevFlowModelPlan(), research_coordinator=sentinel)
        node = flow_with._nodes["research"]
        assert node._coordinator is sentinel

    def test_no_ideation_node_exists(self):
        node_types = {type(n).__name__ for n in _flow(model_plan=DevFlowModelPlan())._nodes.values()}
        assert "IdeationNode" not in node_types


class TestUnknownBackendFailsBeforeBuild:
    def test_unknown_pool_backend_rejected(self):
        with pytest.raises(ValueError, match="unknown dev agent backend"):
            _flow(model_plan=DevFlowModelPlan.model_validate({"dev_pool": [{"agent": "bogus"}]}))

    def test_unknown_review_primary_rejected(self):
        # A valid DevAgentSpec.agent literal, but not in PRIMARY_REVIEW_BACKENDS.
        with pytest.raises(ValueError, match="cannot serve as the primary reviewer"):
            _flow(model_plan=DevFlowModelPlan.model_validate({"review": {"primary": {"agent": "nova"}}}))
