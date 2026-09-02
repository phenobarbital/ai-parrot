"""Plan-driven adversarial review pair assembly (FEAT-486 TASK-2655).

Spec §4 row ``test_review_pair_assembly`` plus the three-way precedence
(explicit argument > plan > ``None``) and the guarantee that the judge
panel stays out of this path entirely.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest
from parrot.flows.dev_flow.factories import build_dev_flow_node_factories
from parrot.flows.dev_flow.model_plan import DevFlowModelPlan, ReviewPairPlan
from parrot.flows.dev_loop.code_review import (
    ClaudeCodeReviewDispatcher,
    JudgePanelReviewDispatcher,
    ParallelPerspectiveReviewDispatcher,
)
from parrot.flows.dev_loop.definition import QA
from parrot.flows.dev_loop.dispatchers.mantle import (
    MantleAdversarialReviewDispatcher,
)
from parrot.flows.dev_loop.models.base import DevAgentSpec


def _qa_node(**kwargs: Any) -> Any:
    """Materialize the QA node from the factory map, like the flow does."""
    from parrot.bots.flows import AgentsFlow
    from parrot.flows.dev_flow.definition import build_dev_flow_definition
    from parrot.flows.dev_loop.flow import _NullAgentRegistry

    definition = build_dev_flow_definition()
    factories = build_dev_flow_node_factories(dispatcher=MagicMock(), redis_url="redis://x", **kwargs)
    staged = AgentsFlow.from_definition(definition, agent_registry=_NullAgentRegistry(), node_factories=factories)
    return staged._materialize_nodes()[QA]


class TestPairAssembly:
    """Spec G5 defaults: Opus 5 primary + gpt-5.6-sol counter-reviewer."""

    def test_default_plan_assembles_parallel_pair(self):
        node = _qa_node(model_plan=DevFlowModelPlan())
        pair = node._codereview_dispatcher
        assert isinstance(pair, ParallelPerspectiveReviewDispatcher)

    def test_primary_is_write_enabled_claude_opus_5(self):
        node = _qa_node(model_plan=DevFlowModelPlan())
        primary = node._codereview_dispatcher._primary
        assert isinstance(primary, ClaudeCodeReviewDispatcher)
        assert primary._model == "claude-opus-5"
        assert primary.advisory is False

    def test_primary_reuses_the_shared_dispatcher(self):
        """No second ClaudeCodeDispatcher is constructed for review."""
        shared = MagicMock()
        from parrot.bots.flows import AgentsFlow
        from parrot.flows.dev_flow.definition import build_dev_flow_definition
        from parrot.flows.dev_loop.flow import _NullAgentRegistry

        factories = build_dev_flow_node_factories(
            dispatcher=shared, redis_url="redis://x", model_plan=DevFlowModelPlan()
        )
        staged = AgentsFlow.from_definition(
            build_dev_flow_definition(),
            agent_registry=_NullAgentRegistry(),
            node_factories=factories,
        )
        primary = staged._materialize_nodes()[QA]._codereview_dispatcher._primary
        assert primary._dispatcher is shared

    def test_adversary_is_read_only_mantle_gpt_5_6_sol(self):
        node = _qa_node(model_plan=DevFlowModelPlan())
        adversary = node._codereview_dispatcher._adversary
        assert isinstance(adversary, MantleAdversarialReviewDispatcher)
        assert adversary._model == "gpt-5.6-sol"
        assert adversary.advisory is True

    def test_counter_model_is_configurable(self):
        node = _qa_node(model_plan=DevFlowModelPlan(review=ReviewPairPlan(counter_model="openai.gpt-oss-120b")))
        assert node._codereview_dispatcher._adversary._model == "openai.gpt-oss-120b"

    def test_primary_model_is_configurable(self):
        node = _qa_node(
            model_plan=DevFlowModelPlan(
                review=ReviewPairPlan(primary=DevAgentSpec(agent="claude-code", model="claude-haiku-4-5"))
            )
        )
        assert node._codereview_dispatcher._primary._model == "claude-haiku-4-5"

    def test_judge_synthesis_stays_off(self):
        """Deterministic merge is authoritative (DEV_LOOP_CODEREVIEW_JUDGE default)."""
        pair = _qa_node(model_plan=DevFlowModelPlan())._codereview_dispatcher
        assert pair._judge_enabled is False
        assert pair._judge_dispatcher is None

    def test_unsupported_primary_backend_fails_fast(self):
        with pytest.raises(ValueError, match="cannot serve as the primary reviewer"):
            build_dev_flow_node_factories(
                dispatcher=MagicMock(),
                redis_url="redis://x",
                model_plan=DevFlowModelPlan(review=ReviewPairPlan(primary=DevAgentSpec(agent="nova"))),
            )


class TestPrecedence:
    """explicit argument > plan > None."""

    def test_explicit_dispatcher_wins_over_plan(self):
        sentinel = MagicMock()
        node = _qa_node(model_plan=DevFlowModelPlan(), codereview_dispatcher=sentinel)
        assert node._codereview_dispatcher is sentinel

    def test_no_plan_keeps_qanodes_own_fallback(self):
        """No plan ⇒ ``None`` is forwarded, so QANode's own backward-compat
        wrap (``qa.py:147-148``) applies — a plain write-enabled Claude
        reviewer, NOT a parallel pair. This is the pre-FEAT-486 behaviour.
        """
        node = _qa_node()
        assert isinstance(node._codereview_dispatcher, ClaudeCodeReviewDispatcher)
        assert not isinstance(node._codereview_dispatcher, ParallelPerspectiveReviewDispatcher)

    def test_explicit_dispatcher_without_plan_unchanged(self):
        sentinel = MagicMock()
        node = _qa_node(codereview_dispatcher=sentinel)
        assert node._codereview_dispatcher is sentinel


class TestJudgePanelUntouched:
    """Spec: JudgeSpec / judge panel are explicitly NOT part of this path."""

    def test_pair_is_not_a_judge_panel(self):
        pair = _qa_node(model_plan=DevFlowModelPlan())._codereview_dispatcher
        assert not isinstance(pair, JudgePanelReviewDispatcher)

    def test_judge_spec_backends(self):
        """FEAT-486 kept "mantle" off the panel; the reviewer ban put it on.

        This assertion is deliberately inverted from its original form.
        When FEAT-486 landed, "mantle" was a review-PAIR backend only and
        ``JudgeSpec`` rejecting it proved the panel was untouched. The
        Gemini/agy reviewer ban then removed the panel's third seat, and
        "mantle" took it — so it must now validate. What still holds is
        the point the original test was making: the panel accepts exactly
        the backends with a review dispatcher, and nothing else.
        """
        from parrot.flows.dev_loop.models.base import JudgeSpec

        assert JudgeSpec(agent="mantle").agent == "mantle"
        assert JudgeSpec(agent="claude-code").agent == "claude-code"
        with pytest.raises(ValueError):
            JudgeSpec(agent="gemini")
