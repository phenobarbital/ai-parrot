"""Unit tests for `parrot.flows.thales.definition` (FEAT-425 TASK-2231).

Note (see `definition.py`'s module docstring): the original spec called for
a pure `build_thales_definition(angles, config) -> FlowDefinition` handed to
`AgentsFlow.from_definition(node_factories=...)`. Verified against `dev`,
that contradicts the original "never touch NODE_REGISTRY" plan — and a
second round of verification found `checkpoint=True` requires registry
membership regardless of assembly mode. Per user decisions (Option B, then
Option C), this module builds an `AgentsFlow` PROGRAMMATICALLY
(`add_node`/`add_edge`) AND registers every Thales node type idempotently
(mirroring `parrot.flows.dev_loop`). These tests check node/edge counts on
the assembled graph instead of on a `FlowDefinition`.
"""

import json
from unittest.mock import AsyncMock, MagicMock

from parrot.bots.flows.flow.cel_evaluator import CELPredicateEvaluator
from parrot.flows.thales.definition import (
    _DECK_NOT_DROPPED_CEL,
    ThalesNodeDeps,
    assemble_thales_flow,
    build_thales_nodes_and_edges,
)
from parrot.flows.thales.models import ResearchAngle, ThalesConfig
from parrot.flows.thales.nodes.deck_builder import DROPPED_DECK_SENTINEL


def _angles(n: int) -> list[ResearchAngle]:
    return [
        ResearchAngle(angle_id=f"a{i}", title=f"t{i}", question="q", rationale="r")
        for i in range(n)
    ]


def _deps() -> ThalesNodeDeps:
    return ThalesNodeDeps(
        client=AsyncMock(),
        store=MagicMock(),
        toolkit=AsyncMock(),
        user_id="u1", agent_id="thales", session_id="s1",
        accessed_date="2026-08-17",
    )


class TestBuildThalesNodesAndEdges:
    def test_build_definition_shape(self):
        cfg = ThalesConfig(thesis="t", num_decks=10)
        nodes, _edges = build_thales_nodes_and_edges(_angles(10), cfg, _deps())

        node_ids = {n.node_id for n in nodes}
        research = [nid for nid in node_ids if nid.startswith("research-")]
        assert len(research) == 30  # 10 angles x 3 sources

        assert "bibliography" in node_ids
        assert "exec_summary" in node_ids
        assert "final_document" in node_ids
        assert "infographic" in node_ids
        assert "start" in node_ids
        assert "end" in node_ids

        # 10 deck + 10 slide_spec + 10 slide_render nodes.
        assert len([nid for nid in node_ids if nid.startswith("deck-")]) == 10
        assert len([nid for nid in node_ids if nid.startswith("slide-spec-")]) == 10
        assert len([nid for nid in node_ids if nid.startswith("slide-render-")]) == 10

        # Total: 1 start + 30 research + 10 deck + 10 slide_spec + 10 slide_render
        #        + bibliography + exec_summary + final_document + infographic + 1 end
        assert len(nodes) == 1 + 30 + 10 + 10 + 10 + 4 + 1

    def test_build_definition_deterministic(self):
        cfg = ThalesConfig(thesis="t")
        nodes_a, edges_a = build_thales_nodes_and_edges(_angles(10), cfg, _deps())
        nodes_b, edges_b = build_thales_nodes_and_edges(_angles(10), cfg, _deps())

        assert sorted(n.node_id for n in nodes_a) == sorted(n.node_id for n in nodes_b)
        # Compare (from, to, condition) triples — predicates are function
        # objects (not orderable/comparable across separate builds) but the
        # SAME module-level function is reused deterministically each time,
        # so identity-based equality on the full tuples still holds too.
        assert [(e.from_, e.to, e.condition) for e in edges_a] == [
            (e.from_, e.to, e.condition) for e in edges_b
        ]
        assert edges_a == edges_b

    def test_respects_config_sources(self):
        cfg = ThalesConfig(thesis="t", num_decks=10, sources=["web"])
        nodes, _edges = build_thales_nodes_and_edges(_angles(10), cfg, _deps())
        research = [n.node_id for n in nodes if n.node_id.startswith("research-")]
        assert len(research) == 10  # 10 angles x 1 source
        assert all("research-web-" in nid for nid in research)

    def test_deck_builder_has_both_success_and_error_edges(self):
        cfg = ThalesConfig(thesis="t", num_decks=10)
        nodes, edges = build_thales_nodes_and_edges(_angles(1), cfg, _deps())
        research_ids = [n.node_id for n in nodes if n.node_id.startswith("research-")]
        deck_edges = [e for e in edges if e.to == "deck-a0"]
        # 3 sources x 2 conditions (on_success + on_error) = 6 edges.
        assert len(deck_edges) == len(research_ids) * 2
        conditions = {e.condition for e in deck_edges}
        assert conditions == {"on_success", "on_error"}


class TestDeckNotDroppedPredicate:
    """`_DECK_NOT_DROPPED_CEL` must be a CEL expression STRING (not a Python
    callable) — `AgentsFlow.to_definition()`, which `checkpoint=True` calls
    unconditionally as a fail-fast export check, only round-trips CEL
    strings. Evaluated the same way the engine's scheduler does, via
    `CELPredicateEvaluator`.
    """

    def test_is_a_string_not_a_callable(self):
        assert isinstance(_DECK_NOT_DROPPED_CEL, str)

    def test_real_deck_passes(self):
        evaluator = CELPredicateEvaluator(_DECK_NOT_DROPPED_CEL)
        assert evaluator('{"angle": {}, "findings": []}') is True

    def test_dropped_sentinel_blocks(self):
        evaluator = CELPredicateEvaluator(_DECK_NOT_DROPPED_CEL)
        payload = json.dumps({DROPPED_DECK_SENTINEL: True, "failed_sources": ["web"]})
        assert evaluator(payload) is False


class TestAssembleThalesFlow:
    def test_assembles_agents_flow_with_all_nodes_and_edges(self):
        cfg = ThalesConfig(thesis="t", num_decks=10)
        flow = assemble_thales_flow(_angles(2), cfg, _deps(), flow_id="run-1")
        # Internal state — verify wiring landed on the AgentsFlow instance.
        assert len(flow._nodes) > 0
        assert len(flow._edges) > 0
        assert "start" in flow._nodes
        assert "end" in flow._nodes

    def test_flow_exports_to_definition_for_checkpointing(self):
        """`checkpoint=True` calls `to_definition()` as a fail-fast export
        check (FEAT-399) — every node type must round-trip through
        NODE_REGISTRY and every predicate must be a CEL string, or this
        raises `FlowNotExportableError` before a single node ever runs.
        """
        cfg = ThalesConfig(thesis="t", num_decks=10)
        flow = assemble_thales_flow(_angles(2), cfg, _deps(), flow_id="run-2")
        definition = flow.to_definition()
        assert definition.flow == "thales"
        assert len(definition.nodes) == len(flow._nodes)
