"""Tests for build_graph / flow_definition_to_graph (FEAT-529 Module 5, TASK-2886)."""

from __future__ import annotations

import pytest
from parrot.outputs.a2ui.adapters.flow import flow_definition_to_graph
from parrot.outputs.a2ui.builders import build_graph
from parrot.outputs.a2ui.catalog import DEFAULT_CATALOG_ID, ProducerOrigin
from parrot.outputs.a2ui.catalog.base import CatalogValidationError
from parrot.outputs.a2ui.catalog.viz_core import VIZ_CORE_CATALOG_ID
from parrot.outputs.a2ui.models import Action, EventAction


def _nodes():
    return [{"id": "a", "label": "Start"}, {"id": "b", "label": "End"}]


def _edges():
    return [{"from": "a", "to": "b"}]


class TestBuildGraphFillsPositions:
    def test_build_graph_fills_positions(self):
        envelope = build_graph(nodes=_nodes(), edges=_edges())
        comp = envelope.components[0]
        assert comp.model_extra["layout"]["positions"]["a"] is not None
        assert comp.model_extra["layout"]["positions"]["b"] is not None

    def test_compute_layout_false_leaves_positions_absent(self):
        envelope = build_graph(nodes=_nodes(), edges=_edges(), compute_layout=False)
        comp = envelope.components[0]
        assert "layout" not in comp.model_extra


class TestBuildGraphSetsVizCoreCatalogId:
    def test_build_graph_sets_viz_core_catalog_id(self):
        envelope = build_graph(nodes=_nodes(), edges=_edges())
        comp = envelope.components[0]
        assert comp.catalog_id == VIZ_CORE_CATALOG_ID
        assert envelope.catalog_id == DEFAULT_CATALOG_ID


class TestBuildGraphActionToolOriginOnly:
    def test_build_graph_action_tool_origin_only(self):
        action = Action(event=EventAction(name="select"))
        envelope = build_graph(nodes=_nodes(), edges=_edges(), action=action)  # default origin=TOOL, must not raise
        assert envelope.components[0].action is not None

        with pytest.raises(CatalogValidationError):
            build_graph(nodes=_nodes(), edges=_edges(), action=action, origin=ProducerOrigin.LLM)


class TestBuildGraphListedInAll:
    def test_build_graph_in_all(self):
        import parrot.outputs.a2ui.builders as builders_mod

        assert "build_graph" in builders_mod.__all__


class TestFlowDefinitionToGraphShapesAndEdges:
    def _flow_mapping(self) -> dict:
        return {
            "flow": "demo",
            "nodes": [
                {"id": "start", "type": "start"},
                {"id": "research", "type": "agent", "label": "Research"},
                {"id": "gate", "type": "decision"},
                {"id": "run_tool", "type": "tool"},
                {"id": "qa", "type": "agent"},
                {"id": "docs", "type": "agent"},
                {"id": "failure_handler", "type": "agent"},
                {"id": "end", "type": "end"},
            ],
            "edges": [
                {"from": "start", "to": "research", "condition": "always"},
                {"from": "research", "to": "gate", "condition": "on_success"},
                {"from": "gate", "to": "run_tool", "condition": "on_condition", "predicate": "score > 0.5"},
                {"from": "run_tool", "to": ["qa", "docs"], "condition": "on_success"},
                {"from": "run_tool", "to": "failure_handler", "condition": "on_error"},
                {"from": "qa", "to": "end", "condition": "always"},
                {"from": "docs", "to": "end", "condition": "always"},
            ],
        }

    def test_flow_definition_to_graph_shapes_and_edges(self):
        spec = flow_definition_to_graph(self._flow_mapping())

        shapes = {node.id: node.shape for node in spec.nodes}
        assert shapes["start"] == "circle"
        assert shapes["end"] == "circle"
        assert shapes["gate"] == "diamond"
        assert shapes["run_tool"] == "subroutine"
        assert shapes["research"] == "rounded"  # agent -> generic rounded

        # Fan-out: one edge per target.
        fan_out_edges = [e for e in spec.edges if e.from_ == "run_tool" and e.to in ("qa", "docs")]
        assert len(fan_out_edges) == 2

        # on_error -> dashed.
        error_edge = next(e for e in spec.edges if e.from_ == "run_tool" and e.to == "failure_handler")
        assert error_edge.kind == "dashed"

        # on_condition -> label == predicate.
        condition_edge = next(e for e in spec.edges if e.from_ == "gate" and e.to == "run_tool")
        assert condition_edge.label == "score > 0.5"

        # Default accessibleDescription generated.
        assert spec.accessible_description == (f"demo workflow: {len(spec.nodes)} steps, {len(spec.edges)} transitions")

    def test_flow_definition_to_graph_builds_a_valid_envelope(self):
        """Integration: the adapter's output builds through build_graph unmodified."""
        spec = flow_definition_to_graph(self._flow_mapping())
        envelope = build_graph(
            nodes=spec.nodes,
            edges=spec.edges,
            accessible_description=spec.accessible_description,
        )
        assert envelope.components[0].catalog_id == VIZ_CORE_CATALOG_ID
