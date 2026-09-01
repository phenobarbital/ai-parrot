"""Research-partner passthrough — FEAT-486 TASK-2657.

Spec §3 Module 5 (partner half, goal G6): the plan's ``research_partner``
group must reach FEAT-482's ``ComplementaryResearchCoordinator``.

Also guards the trap this task exists to avoid: because the coordinator
resolves ``DEV_FLOW_RESEARCH_PARTNER`` (default ``""`` = disabled) at
``research()`` time, merely *constructing* one for a plan-enabled partner
would yield a toggle that can never enable the seat. The injection points
added to FEAT-482's two modules are what make the toggle real, so several
tests below assert the *effective* behaviour, not just the wiring.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest
from parrot import conf
from parrot.flows.dev_flow import complementary_research
from parrot.flows.dev_flow.complementary_research import (
    _EXPLICIT_BACKEND_CHOICES,
    ComplementaryResearchCoordinator,
)
from parrot.flows.dev_flow.factories import (
    _resolve_research_coordinator,
    build_dev_flow_node_factories,
)
from parrot.flows.dev_flow.model_plan import DevFlowModelPlan, ResearchPartnerPlan
from parrot.flows.dev_flow.research_partner import BedrockResearchPartner
from parrot.flows.dev_loop.catalog import _RESEARCH_PARTNER_CHOICES


def _ideation_node(**kwargs: Any) -> Any:
    """Materialize the ideation node exactly as build_dev_flow does."""
    from parrot.bots.flows import AgentsFlow
    from parrot.flows.dev_flow.definition import IDEATION, build_dev_flow_definition
    from parrot.flows.dev_loop.flow import _NullAgentRegistry

    factories = build_dev_flow_node_factories(
        dispatcher=MagicMock(), redis_url="redis://x", **kwargs
    )
    staged = AgentsFlow.from_definition(
        build_dev_flow_definition(),
        agent_registry=_NullAgentRegistry(),
        node_factories=factories,
    )
    return staged._materialize_nodes()[IDEATION]


class TestDisabledByDefault:
    """Spec G6: the partner stays off unless asked for."""

    def test_disabled_default_no_coordinator(self):
        node = _ideation_node(model_plan=DevFlowModelPlan())
        assert node._coordinator is None

    def test_no_plan_keeps_feat482_behaviour(self):
        """Without a plan, FEAT-482's always-construct path is unchanged."""
        node = _ideation_node()
        assert isinstance(node._coordinator, ComplementaryResearchCoordinator)
        assert node._coordinator._backend is None
        assert node._coordinator._model is None

    def test_plan_can_veto_a_configured_deployment(self, monkeypatch):
        """An explicitly-disabled plan overrides DEV_FLOW_RESEARCH_PARTNER."""
        monkeypatch.setattr(conf, "DEV_FLOW_RESEARCH_PARTNER", "gpt", raising=False)
        node = _ideation_node(
            model_plan=DevFlowModelPlan(
                research_partner=ResearchPartnerPlan(enabled=False)
            )
        )
        assert node._coordinator is None


class TestEnabledPassthrough:
    def test_enabled_builds_coordinator_with_plan_selection(self):
        node = _ideation_node(
            model_plan=DevFlowModelPlan(
                research_partner=ResearchPartnerPlan(enabled=True)
            )
        )
        coordinator = node._coordinator
        assert isinstance(coordinator, ComplementaryResearchCoordinator)
        assert coordinator._backend == "gpt"
        assert coordinator._model == "gpt-5.6-sol"

    def test_plan_backend_and_model_are_carried(self):
        node = _ideation_node(
            model_plan=DevFlowModelPlan(
                research_partner=ResearchPartnerPlan(
                    enabled=True, backend="nova", model="us.amazon.nova-2-lite-v1:0"
                )
            )
        )
        assert node._coordinator._backend == "nova"
        assert node._coordinator._model == "us.amazon.nova-2-lite-v1:0"

    def test_enabled_toggle_does_not_depend_on_env(self, monkeypatch):
        """THE regression this task exists for.

        With DEV_FLOW_RESEARCH_PARTNER unset, a coordinator built from a
        plan-enabled partner must still resolve an enabled backend — i.e.
        the console toggle actually enables the seat. Before the FEAT-482
        injection points existed, this resolved "" and the seat silently
        never ran.
        """
        monkeypatch.setattr(conf, "DEV_FLOW_RESEARCH_PARTNER", "", raising=False)
        node = _ideation_node(
            model_plan=DevFlowModelPlan(
                research_partner=ResearchPartnerPlan(enabled=True)
            )
        )
        assert node._coordinator._resolve_backend() == "gpt"

    def test_explicit_coordinator_still_wins(self):
        sentinel = ComplementaryResearchCoordinator(backend="nova")
        node = _ideation_node(
            research_coordinator=sentinel,
            model_plan=DevFlowModelPlan(
                research_partner=ResearchPartnerPlan(enabled=True, backend="gpt")
            ),
        )
        assert node._coordinator is sentinel


class TestCoordinatorInjection:
    """The FEAT-482-side seam added by this task (Option B)."""

    # `resolve_research_partner_backend()` reads `conf.config.get(...)`
    # (navconfig), NOT the `conf.DEV_FLOW_RESEARCH_PARTNER` module
    # attribute — so patching that attribute proves nothing. The
    # coordinator calls the resolver with no `config_getter`, so what
    # these tests must pin is DELEGATION to it.
    def test_no_override_delegates_to_the_config_resolver(self, monkeypatch):
        monkeypatch.setattr(
            complementary_research, "resolve_research_partner_backend", lambda: "nova"
        )
        assert ComplementaryResearchCoordinator()._resolve_backend() == "nova"

    def test_unset_config_still_means_disabled(self, monkeypatch):
        """The pure-addition guarantee must survive this change."""
        monkeypatch.setattr(
            complementary_research, "resolve_research_partner_backend", lambda: ""
        )
        assert ComplementaryResearchCoordinator()._resolve_backend() == ""

    def test_explicit_backend_bypasses_the_config_resolver(self, monkeypatch):
        """An override must not even consult the env path."""
        called = []

        def _boom():
            called.append(1)
            return "nova"

        monkeypatch.setattr(
            complementary_research, "resolve_research_partner_backend", _boom
        )
        assert ComplementaryResearchCoordinator(backend="gpt")._resolve_backend() == "gpt"
        assert called == []

    def test_invalid_explicit_backend_rejected(self):
        with pytest.raises(ValueError, match="gpt, nova"):
            ComplementaryResearchCoordinator(backend="bogus")._resolve_backend()

    def test_anthropic_model_still_rejected_via_injection(self):
        """The family guard must not be bypassable by injecting a model."""
        with pytest.raises(ValueError, match="research-partner seat"):
            ComplementaryResearchCoordinator(
                backend="nova", model="us.anthropic.claude-opus-5"
            )._resolve_backend()

    @pytest.mark.parametrize("model", ["claude-opus-5", "global.anthropic.claude-fable-5"])
    def test_every_anthropic_prefix_rejected(self, model: str):
        with pytest.raises(ValueError):
            ComplementaryResearchCoordinator(
                backend="gpt", model=model
            )._resolve_backend()

    def test_choice_tuple_pinned_to_catalog(self):
        """The local tuple must not drift from catalog's private one."""
        assert _EXPLICIT_BACKEND_CHOICES == _RESEARCH_PARTNER_CHOICES


class TestPartnerModelInjection:
    """``BedrockResearchPartner(model=...)`` — the second Option B seam."""

    def test_model_defaults_to_conf(self):
        partner = BedrockResearchPartner(backend="gpt")
        assert partner.model == ""

    def test_explicit_model_recorded(self):
        partner = BedrockResearchPartner(backend="gpt", model="openai.gpt-oss-120b")
        assert partner.model == "openai.gpt-oss-120b"

    def test_build_client_uses_the_override(self):
        partner = BedrockResearchPartner(backend="gpt", model="openai.gpt-oss-120b")
        client = partner._build_client()
        assert client.model == "openai.gpt-oss-120b"

    def test_build_client_falls_back_to_conf(self):
        partner = BedrockResearchPartner(backend="gpt")
        client = partner._build_client()
        assert client.model == conf.DEV_FLOW_RESEARCH_PARTNER_GPT_MODEL

    def test_build_client_rejects_injected_anthropic_model(self):
        partner = BedrockResearchPartner(backend="nova", model="claude-opus-5")
        with pytest.raises(ValueError, match="research-partner seat"):
            partner._build_client()

    def test_disabled_backend_still_rejected(self):
        with pytest.raises(ValueError, match="disabled or misconfigured"):
            BedrockResearchPartner(backend="", model="gpt-5.6-sol")


class TestResolverUnit:
    """``_resolve_research_coordinator`` precedence, directly."""

    def test_explicit_wins(self):
        sentinel = MagicMock()
        assert _resolve_research_coordinator(sentinel, DevFlowModelPlan()) is sentinel

    def test_no_plan_builds_one(self):
        assert isinstance(
            _resolve_research_coordinator(None, None), ComplementaryResearchCoordinator
        )

    def test_disabled_plan_returns_none(self):
        assert _resolve_research_coordinator(None, DevFlowModelPlan()) is None

    def test_blank_plan_fields_fall_back_to_config(self):
        """A plan that enables but names nothing defers to FEAT-482's env."""
        plan = DevFlowModelPlan(
            research_partner=ResearchPartnerPlan(enabled=True, backend="", model="")
        )
        coordinator = _resolve_research_coordinator(None, plan)
        assert coordinator._backend is None
        assert coordinator._model is None
