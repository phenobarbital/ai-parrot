"""Unit tests for `parrot.flows.thales.nodes` (FEAT-425 TASK-2229).

All LLM calls are mocked — no network, no real LLM.

**Correction (TASK-2231):** this module originally asserted NO "thales"-
prefixed key ever appears in the global ``NODE_REGISTRY`` (spec §7's
original wiring plan). Verified during TASK-2231: ``AgentsFlow``'s
``checkpoint=True`` (FEAT-399) unconditionally requires every node type to
round-trip through ``NODE_REGISTRY`` via ``to_definition()``'s fail-fast
export check — regardless of assembly mode (declarative or programmatic).
Per user decision ("Option C"), every Thales node type IS now registered,
idempotently, mirroring ``parrot.flows.dev_loop``'s own
``register_dev_loop_node`` pattern (which registers its nodes for the
exact same reason). See ``parrot/flows/thales/nodes/registry.py`` and
``sdd/specs/agentcrew-tales-research.spec.md`` §7 (revised).
"""

import json
from unittest.mock import AsyncMock

import pytest
from parrot.bots.flows.flow.flow import NODE_REGISTRY
from parrot.flows.thales.models import (
    Finding,
    ResearchAngle,
    ResearchDeck,
    SlideSpec,
    ThalesConfig,
)
from parrot.flows.thales.nodes import DeckBuilderNode, PlannerNode, SlideSpecNode
from parrot.flows.thales.nodes.deck_builder import DROPPED_DECK_SENTINEL
from parrot.flows.thales.nodes.planner import _AnglesEnvelope
from parrot.flows.thales.nodes.registry import register_thales_node


def test_thales_nodes_are_registered_for_checkpointing():
    """Every Thales node type IS in NODE_REGISTRY (see module docstring)."""
    thales_types = {k for k in NODE_REGISTRY if k.startswith("thales.")}
    assert "thales.planner" in thales_types
    assert "thales.deck_builder" in thales_types
    assert "thales.slide_spec" in thales_types


def test_registration_is_idempotent():
    """Re-registering the same name is a no-op, never raises."""

    class _Dummy(PlannerNode):
        pass

    # First call registers "thales._idempotency_probe"; second is a no-op.
    register_thales_node("thales._idempotency_probe")(_Dummy)
    register_thales_node("thales._idempotency_probe")(_Dummy)
    assert NODE_REGISTRY["thales._idempotency_probe"] is _Dummy


def _angle(angle_id: str = "a1") -> ResearchAngle:
    return ResearchAngle(angle_id=angle_id, title="t", question="q", rationale="r")


def _mock_message(**fields):
    message = AsyncMock()
    for key, value in fields.items():
        setattr(message, key, value)
    return message


class TestPlannerNode:
    @pytest.mark.asyncio
    async def test_planner_min_angles(self):
        """First LLM response returns 4 angles -> one re-prompt -> 10 angles."""
        short_angles = [
            ResearchAngle(angle_id=f"a{i}", title=f"t{i}", question=f"q{i}", rationale="r")
            for i in range(4)
        ]
        full_angles = [
            ResearchAngle(angle_id=f"a{i}", title=f"t{i}", question=f"q{i}", rationale="r")
            for i in range(10)
        ]
        client = AsyncMock()
        client.ask.side_effect = [
            _mock_message(structured_output=_AnglesEnvelope(angles=short_angles)),
            _mock_message(structured_output=_AnglesEnvelope(angles=full_angles)),
        ]
        node = PlannerNode(node_id="planner", config=ThalesConfig(thesis="t"), client=client)
        result = await node.execute(ctx=None, deps={})
        angles = json.loads(result)
        assert len(angles) >= 10
        assert client.ask.await_count == 2  # exactly one re-prompt

    @pytest.mark.asyncio
    async def test_planner_pads_when_still_short_after_retry(self):
        short_angles = [_angle("a1")]
        client = AsyncMock()
        client.ask.side_effect = [
            _mock_message(structured_output=_AnglesEnvelope(angles=short_angles)),
            _mock_message(structured_output=_AnglesEnvelope(angles=short_angles)),
        ]
        node = PlannerNode(node_id="planner", config=ThalesConfig(thesis="t", num_decks=10), client=client)
        result = await node.execute(ctx=None, deps={})
        angles = json.loads(result)
        assert len(angles) >= 10
        assert client.ask.await_count == 2  # never more than one re-prompt

    @pytest.mark.asyncio
    async def test_planner_no_retry_when_first_response_sufficient(self):
        full_angles = [
            ResearchAngle(angle_id=f"a{i}", title=f"t{i}", question=f"q{i}", rationale="r")
            for i in range(10)
        ]
        client = AsyncMock()
        client.ask.return_value = _mock_message(structured_output=_AnglesEnvelope(angles=full_angles))
        node = PlannerNode(node_id="planner", config=ThalesConfig(thesis="t"), client=client)
        result = await node.execute(ctx=None, deps={})
        angles = json.loads(result)
        assert len(angles) == 10
        assert client.ask.await_count == 1


class TestDeckBuilderNode:
    @pytest.mark.asyncio
    async def test_deck_builder_or_join_degrade(self):
        """deps = {web: findings, deep: EXCEPTION, arxiv: findings} ->
        deck.failed_sources == ['deep'], findings from web+arxiv."""
        finding = Finding(text="finding text", claims=[])
        findings_json = json.dumps([finding.model_dump(mode="json")])
        deps = {"web": findings_json, "deep": "EXCEPTION", "arxiv": findings_json}

        node = DeckBuilderNode(node_id="deck-a1", angle=_angle())
        result = await node.execute(ctx=None, deps=deps)
        deck = ResearchDeck.model_validate_json(result)

        assert deck.failed_sources == ["deep"]
        assert deck.tools_used == ["web", "arxiv"]
        assert len(deck.findings) == 2

    @pytest.mark.asyncio
    async def test_deck_builder_all_sources_fail_yields_drop_sentinel(self):
        deps = {"web": "EXCEPTION", "deep": "EXCEPTION", "arxiv": "EXCEPTION"}
        node = DeckBuilderNode(node_id="deck-a1", angle=_angle())
        result = await node.execute(ctx=None, deps=deps)
        payload = json.loads(result)
        assert payload[DROPPED_DECK_SENTINEL] is True
        assert set(payload["failed_sources"]) == {"web", "deep", "arxiv"}

    @pytest.mark.asyncio
    async def test_deck_builder_all_sources_succeed(self):
        finding = Finding(text="finding text", claims=[])
        findings_json = json.dumps([finding.model_dump(mode="json")])
        deps = {"web": findings_json, "deep": findings_json, "arxiv": findings_json}
        node = DeckBuilderNode(node_id="deck-a1", angle=_angle())
        result = await node.execute(ctx=None, deps=deps)
        deck = ResearchDeck.model_validate_json(result)
        assert deck.failed_sources == []
        assert len(deck.findings) == 3


class TestSlideSpecNode:
    @pytest.mark.asyncio
    async def test_slide_spec_no_invented_charts(self):
        """Deck without numeric_series -> SlideSpec.charts == []."""
        deck = ResearchDeck(
            angle=_angle(),
            findings=[Finding(text="no numbers here", claims=[])],
        )
        hallucinated_spec = SlideSpec(
            deck_ref="a1", layout="default", headline="H", bullets=["b"],
            charts=[{"type": "bar", "labels": ["x"], "series": []}],
        )
        client = AsyncMock()
        client.ask.return_value = _mock_message(structured_output=hallucinated_spec)

        node = SlideSpecNode(node_id="slide-a1", client=client)
        result = await node.execute(ctx=None, deps={"deck-a1": deck.model_dump_json()})
        spec = SlideSpec.model_validate_json(result)

        assert spec.charts == []

    @pytest.mark.asyncio
    async def test_slide_spec_keeps_charts_when_numeric_series_present(self):
        deck = ResearchDeck(
            angle=_angle(),
            findings=[Finding(text="has numbers", claims=[], numeric_series={"a": [1, 2]})],
        )
        chart_spec = SlideSpec(
            deck_ref="a1", layout="default", headline="H", bullets=["b"],
            charts=[{"type": "bar", "labels": ["x"], "series": [{"name": "a", "data": [1, 2]}]}],
        )
        client = AsyncMock()
        client.ask.return_value = _mock_message(structured_output=chart_spec)

        node = SlideSpecNode(node_id="slide-a1", client=client)
        result = await node.execute(ctx=None, deps={"deck-a1": deck.model_dump_json()})
        spec = SlideSpec.model_validate_json(result)

        assert len(spec.charts) == 1
