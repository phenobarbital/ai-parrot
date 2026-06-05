"""Retrieval-routing no-regression guard (FEAT-224 G7, TASK-1489).

FEAT-224 must NOT change the existing keyword/LLM retrieval router. This pins a
representative set of deterministic, model-free keyword decisions produced by the
real ``IntentRouterMixin._fast_path``. If anyone later edits the keyword map or
fast-path logic, these assertions fail.
"""
from __future__ import annotations

import pytest

from parrot.registry.capabilities.models import RoutingType
from parrot.bots.mixins.intent_router import IntentRouterMixin


class _RetrievalAgent(IntentRouterMixin):
    pass


@pytest.fixture
def agent() -> _RetrievalAgent:
    return _RetrievalAgent()


# All strategies available, so any matched keyword resolves to its mapped type.
_ALL = list(RoutingType)


@pytest.mark.parametrize(
    "prompt,expected",
    [
        ("please search for the latest report", RoutingType.VECTOR_SEARCH),
        ("show data for Q1 sales", RoutingType.DATASET),
        ("run query on the customers table", RoutingType.DATASET),
        ("compare product A and B", RoutingType.TOOL_CALL),
        ("what is the difference between X and Y", RoutingType.TOOL_CALL),
        ("show the graph of dependencies", RoutingType.GRAPH_PAGEINDEX),
        ("open the faq", RoutingType.GRAPH_PAGEINDEX),
    ],
)
def test_fast_path_keyword_decisions_unchanged(agent, prompt, expected):
    decision = agent._fast_path(prompt, _ALL, [])
    assert decision is not None, f"expected a keyword match for: {prompt!r}"
    assert decision.routing_type == expected
    assert decision.confidence == 0.95  # fast-path confidence is a fixed contract


def test_fast_path_no_keyword_returns_none(agent):
    # A neutral prompt with no routing keyword -> no fast-path decision.
    assert agent._fast_path("hello there, how are you today", _ALL, []) is None


def test_fast_path_respects_available_strategies(agent):
    # Keyword matches DATASET, but DATASET is not offered -> no decision.
    only = [RoutingType.VECTOR_SEARCH]
    assert agent._fast_path("show data please", only, []) is None
