"""Configurable ideation (research-primary) model — FEAT-486 TASK-2656.

Spec §4 row ``test_ideation_model_from_plan``: the dispatch profile must
use ``research_primary`` (default ``claude-opus-5``), and the
``claude-sonnet-4-6`` literal that used to sit at ``ideation.py:338`` must
be gone.
"""

from __future__ import annotations

import inspect
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest
from parrot import conf
from parrot.flows.dev_flow.factories import build_dev_flow_node_factories
from parrot.flows.dev_flow.model_plan import DevFlowModelPlan
from parrot.flows.dev_flow.nodes.ideation import IdeationNode

IDEATION_SOURCE = Path(inspect.getfile(IdeationNode))


def _ideation_node(**kwargs: Any) -> IdeationNode:
    """Materialize the ideation node exactly as the flow builder does."""
    from parrot.bots.flows import AgentsFlow
    from parrot.flows.dev_flow.definition import IDEATION, build_dev_flow_definition
    from parrot.flows.dev_loop.flow import _NullAgentRegistry

    factories = build_dev_flow_node_factories(dispatcher=MagicMock(), redis_url="redis://x", **kwargs)
    staged = AgentsFlow.from_definition(
        build_dev_flow_definition(),
        agent_registry=_NullAgentRegistry(),
        node_factories=factories,
    )
    return staged._materialize_nodes()[IDEATION]


class TestLiteralRemoved:
    """AC: the hardcoded literal is gone from the source."""

    def test_sonnet_literal_absent(self):
        """No hardcoded model value survives (the docstring may name it)."""
        source = IDEATION_SOURCE.read_text()
        assert 'model="claude-sonnet-4-6"' not in source
        assert "model=self._resolve_model()" in source

    def test_node_accepts_a_model_kwarg(self):
        params = inspect.signature(IdeationNode.__init__).parameters
        assert "model" in params
        assert params["model"].default is None
        assert params["model"].kind is inspect.Parameter.KEYWORD_ONLY


class TestModelResolution:
    """explicit constructor arg > DEV_FLOW_IDEATION_MODEL > built-in."""

    def test_default_is_opus_5(self):
        assert IdeationNode(dispatcher=MagicMock())._resolve_model() == "claude-opus-5"

    def test_conf_key_default_is_opus_5(self):
        assert conf.DEV_FLOW_IDEATION_MODEL == "claude-opus-5"

    def test_explicit_model_wins(self):
        node = IdeationNode(dispatcher=MagicMock(), model="claude-haiku-4-5")
        assert node._resolve_model() == "claude-haiku-4-5"

    def test_conf_override_applies(self, monkeypatch):
        monkeypatch.setattr(conf, "DEV_FLOW_IDEATION_MODEL", "claude-sonnet-4-6")
        assert IdeationNode(dispatcher=MagicMock())._resolve_model() == "claude-sonnet-4-6"

    def test_explicit_beats_conf(self, monkeypatch):
        monkeypatch.setattr(conf, "DEV_FLOW_IDEATION_MODEL", "claude-sonnet-4-6")
        node = IdeationNode(dispatcher=MagicMock(), model="claude-opus-5")
        assert node._resolve_model() == "claude-opus-5"

    def test_blank_override_falls_through(self):
        """An empty string must not dispatch with an empty model id."""
        assert IdeationNode(dispatcher=MagicMock(), model="")._resolve_model() == ("claude-opus-5")

    def test_conf_is_read_late_not_at_construction(self, monkeypatch):
        node = IdeationNode(dispatcher=MagicMock())
        monkeypatch.setattr(conf, "DEV_FLOW_IDEATION_MODEL", "changed-after-build")
        assert node._resolve_model() == "changed-after-build"


class TestFactoryThreading:
    """``model_plan.research_primary`` must reach the node."""

    def test_no_plan_leaves_node_resolving_conf(self):
        assert _ideation_node()._model is None

    def test_plan_default_threads_opus_5(self):
        node = _ideation_node(model_plan=DevFlowModelPlan())
        assert node._model == "claude-opus-5"
        assert node._resolve_model() == "claude-opus-5"

    def test_plan_override_threads_through(self):
        node = _ideation_node(model_plan=DevFlowModelPlan(research_primary="claude-haiku-4-5"))
        assert node._resolve_model() == "claude-haiku-4-5"

    def test_plan_beats_conf(self, monkeypatch):
        monkeypatch.setattr(conf, "DEV_FLOW_IDEATION_MODEL", "from-conf")
        node = _ideation_node(model_plan=DevFlowModelPlan(research_primary="from-plan"))
        assert node._resolve_model() == "from-plan"

    def test_no_plan_honours_conf(self, monkeypatch):
        monkeypatch.setattr(conf, "DEV_FLOW_IDEATION_MODEL", "from-conf")
        assert _ideation_node()._resolve_model() == "from-conf"


class TestDispatchProfile:
    """The resolved model must actually reach the dispatch profile."""

    @pytest.mark.asyncio
    async def test_profile_carries_the_resolved_model(self):
        from parrot.flows.dev_flow.models import DevRequestBrief

        captured: dict[str, Any] = {}

        class CapturingDispatcher:
            async def dispatch(self, *, brief, profile, **kwargs):
                captured["model"] = profile.model
                raise RuntimeError("stop after profile capture")

        node = IdeationNode(dispatcher=CapturingDispatcher(), model="claude-opus-5")
        brief = DevRequestBrief(
            kind="new_feature",
            title="a title",
            description="a description long enough to validate",
        )
        with pytest.raises(RuntimeError, match="stop after profile capture"):
            await node._dispatch(
                shared={},
                brief=brief,
                mode="brainstorm",
                graph_context="",
                answers={},
                document_path="",
                round_=1,
            )
        assert captured["model"] == "claude-opus-5"

    @pytest.mark.asyncio
    async def test_profile_defaults_to_opus_5(self):
        from parrot.flows.dev_flow.models import DevRequestBrief

        captured: dict[str, Any] = {}

        class CapturingDispatcher:
            async def dispatch(self, *, brief, profile, **kwargs):
                captured["model"] = profile.model
                raise RuntimeError("stop after profile capture")

        node = IdeationNode(dispatcher=CapturingDispatcher())
        brief = DevRequestBrief(
            kind="new_feature",
            title="a title",
            description="a description long enough to validate",
        )
        with pytest.raises(RuntimeError, match="stop after profile capture"):
            await node._dispatch(
                shared={},
                brief=brief,
                mode="brainstorm",
                graph_context="",
                answers={},
                document_path="",
                round_=1,
            )
        assert captured["model"] == "claude-opus-5"
