"""``DevFlowModelPlan`` threading through the dev-flow build surface.

FEAT-486 TASK-2652 / spec §4 rows ``test_build_dev_flow_without_plan_unchanged``,
``test_build_dev_flow_threads_pool`` and
``test_execution_policy_fingerprint_includes_plan``.

The assertions read the *materialized* ``DevelopmentNode``'s private
wiring attributes (``_pool_config`` / ``_dispatcher_builder``, set via
``object.__setattr__`` in ``development.py:130-133``) because that node —
not the factory map — is where the plan has to land for the pool to
actually deploy.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest
from parrot.flows.dev_flow.factories import build_dev_flow_node_factories
from parrot.flows.dev_flow.flow import build_dev_flow
from parrot.flows.dev_flow.model_plan import (
    DevFlowModelPlan,
    ResearchPartnerPlan,
    ReviewPairPlan,
)
from parrot.flows.dev_flow.runner import DevFlowRunner
from parrot.flows.dev_loop.agent_builder import build_dispatcher
from parrot.flows.dev_loop.definition import DEVELOPMENT
from parrot.flows.dev_loop.models.base import DevAgentPoolConfig, DevAgentSpec

TWO_SEATS = [
    DevAgentSpec(agent="nova", model="zai.glm-5"),
    DevAgentSpec(agent="nova", model="qwen.qwen3-coder-480b-a35b-v1:0"),
]


def _flow(**kwargs: Any):
    """Build a dev-flow with event publishing off (no Redis in tests)."""
    return build_dev_flow(
        dispatcher=MagicMock(),
        redis_url="redis://x",
        publish_flow_events=False,
        lifecycle_events=False,
        **kwargs,
    )


def _development_node(flow: Any) -> Any:
    return flow._nodes[DEVELOPMENT]


class TestBackwardCompatibility:
    """An omitted plan must produce today's wiring, exactly."""

    def test_omitted_plan_leaves_pool_unwired(self):
        node = _development_node(_flow())
        assert node._pool_config is None
        assert node._dispatcher_builder is None

    def test_explicit_none_plan_leaves_pool_unwired(self):
        node = _development_node(_flow(model_plan=None))
        assert node._pool_config is None
        assert node._dispatcher_builder is None

    def test_omitted_plan_ignores_env_pool(self, monkeypatch):
        """A stray ``DEV_FLOW_DEV_POOL`` must not silently create a pool."""
        monkeypatch.setenv("DEV_FLOW_DEV_POOL", '[{"agent": "nova"}]')
        node = _development_node(_flow())
        assert node._pool_config is None

    def test_existing_dispatcher_builder_still_honoured(self):
        sentinel = MagicMock()
        node = _development_node(_flow(development_dispatcher_builder=sentinel))
        assert node._dispatcher_builder is sentinel

    def test_flow_still_builds_every_node(self):
        """Sanity: the plan kwarg does not disturb the topology."""
        without = set(_flow()._nodes)
        with_plan = set(_flow(model_plan=DevFlowModelPlan(dev_pool=TWO_SEATS))._nodes)
        assert without == with_plan


class TestPoolThreading:
    """A non-empty ``dev_pool`` must reach ``DevelopmentNode``."""

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

    def test_explicit_builder_beats_plan_derived(self):
        sentinel = MagicMock()
        node = _development_node(
            _flow(
                model_plan=DevFlowModelPlan(dev_pool=TWO_SEATS),
                development_dispatcher_builder=sentinel,
            )
        )
        assert node._dispatcher_builder is sentinel
        assert node._pool_config is not None

    def test_plan_opts_into_env_resolution(self, monkeypatch):
        """Supplying *any* plan enables ``DEV_FLOW_*`` env resolution."""
        monkeypatch.setenv(
            "DEV_FLOW_DEV_POOL", '[{"agent": "nova", "model": "zai.glm-5"}]'
        )
        node = _development_node(_flow(model_plan=DevFlowModelPlan()))
        assert node._pool_config is not None
        assert [s.model for s in node._pool_config.agents] == ["zai.glm-5"]

    def test_factory_map_accepts_the_plan_directly(self):
        factories = build_dev_flow_node_factories(
            dispatcher=MagicMock(),
            redis_url="redis://x",
            model_plan=DevFlowModelPlan(dev_pool=TWO_SEATS),
        )
        assert "dev_flow.ideation" in factories
        assert "dev_loop.development" in factories

    def test_unknown_backend_fails_before_build(self):
        with pytest.raises(ValueError, match="unknown dev agent backend"):
            _flow(
                model_plan=DevFlowModelPlan.model_validate(
                    {"dev_pool": [{"agent": "bogus"}]}
                )
            )


class TestExecutionPolicyFingerprint:
    """Routing-relevant plan fields only (FEAT-480 compatibility)."""

    @staticmethod
    def _policy(**flow_kwargs: Any) -> dict[str, Any]:
        runner = DevFlowRunner.__new__(DevFlowRunner)
        runner._dev_loop_flow_kwargs = flow_kwargs or None
        return runner._execution_policy_for_fingerprint()

    def test_no_plan_omits_the_key_entirely(self):
        """Pre-FEAT-486 fingerprints must not move."""
        policy = self._policy(skip_qa=False)
        assert "model_plan" not in policy
        assert set(policy) == {
            "skip_qa",
            "require_plan_approval",
            "development_pool_max",
            "ideation_max_rounds",
        }

    def test_fingerprint_includes_routing_fields(self):
        policy = self._policy(model_plan=DevFlowModelPlan(dev_pool=TWO_SEATS))
        assert policy["model_plan"]["dev_pool"] == [
            {"agent": "nova", "count": 1},
            {"agent": "nova", "count": 1},
        ]
        assert policy["model_plan"]["review_primary_agent"] == "claude-code"
        assert policy["model_plan"]["research_partner_enabled"] is False

    def test_pool_size_change_moves_the_fingerprint(self):
        one = self._policy(model_plan=DevFlowModelPlan(dev_pool=TWO_SEATS[:1]))
        two = self._policy(model_plan=DevFlowModelPlan(dev_pool=TWO_SEATS))
        assert one != two

    def test_worker_count_change_moves_the_fingerprint(self):
        a = self._policy(
            model_plan=DevFlowModelPlan(dev_pool=[DevAgentSpec(agent="nova", count=1)])
        )
        b = self._policy(
            model_plan=DevFlowModelPlan(dev_pool=[DevAgentSpec(agent="nova", count=2)])
        )
        assert a != b

    def test_partner_toggle_moves_the_fingerprint(self):
        off = self._policy(model_plan=DevFlowModelPlan())
        on = self._policy(
            model_plan=DevFlowModelPlan(
                research_partner=ResearchPartnerPlan(enabled=True)
            )
        )
        assert off != on

    def test_review_backend_change_moves_the_fingerprint(self):
        claude = self._policy(model_plan=DevFlowModelPlan())
        codex = self._policy(
            model_plan=DevFlowModelPlan(
                review=ReviewPairPlan(primary=DevAgentSpec(agent="codex"))
            )
        )
        assert claude != codex

    def test_fingerprint_excludes_nonrouting_model_strings(self):
        """Swapping a model must be a resume *hit*, not a fresh run."""
        base = DevFlowModelPlan(dev_pool=TWO_SEATS)
        swapped = DevFlowModelPlan(
            research_primary="claude-sonnet-4-6",
            dev_pool=[
                DevAgentSpec(agent="nova", model="something-else"),
                DevAgentSpec(agent="nova", model="another-thing"),
            ],
            review=ReviewPairPlan(counter_model="nova-2-lite"),
        )
        assert self._policy(model_plan=base) == self._policy(model_plan=swapped)

    def test_policy_is_json_serializable(self):
        """``compute_input_fingerprint`` hashes ``json.dumps`` of this."""
        import json

        json.dumps(self._policy(model_plan=DevFlowModelPlan(dev_pool=TWO_SEATS)))
