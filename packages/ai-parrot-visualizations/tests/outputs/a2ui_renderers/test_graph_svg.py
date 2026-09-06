"""Tests for the shared Graph SVG renderer (FEAT-529 Module 6, TASK-2887)."""

from __future__ import annotations

import re

import pytest
from parrot.outputs.a2ui.graph import MAX_STATIC_NODES, GraphTooLargeError
from parrot.outputs.a2ui_renderers._graph_svg import STATE_TO_STATUS, render_graph_svg

_HEX_COLOR_RE = re.compile(r"#[0-9a-fA-F]{3,8}\b")


def _base_props(**overrides) -> dict:
    props = {
        "kind": "flowchart",
        "direction": "TB",
        "nodes": [
            {"id": "a", "label": "Start", "shape": "circle", "state": "completed"},
            {"id": "b", "label": "Work", "state": "running"},
            {"id": "c", "label": "Failed step", "state": "failed"},
        ],
        "edges": [
            {"from": "a", "to": "b", "kind": "solid"},
            {"from": "b", "to": "c", "kind": "dashed", "label": "on error"},
        ],
        "accessibleDescription": "A tiny sample graph.",
    }
    props.update(overrides)
    return props


class TestGraphSvgUsesStatusTokens:
    def test_graph_svg_uses_status_tokens(self):
        svg = render_graph_svg(_base_props())
        assert svg.count("<g>") == 3  # one shape per node

        assert 'data-status="critical"' in svg
        assert "var(--accent-red)" in svg
        assert 'data-status="good"' in svg
        assert "var(--accent-green)" in svg
        assert 'data-status="primary"' in svg
        assert "var(--primary)" in svg

        assert _HEX_COLOR_RE.search(svg) is None

    def test_state_to_status_mapping(self):
        assert STATE_TO_STATUS == {
            "completed": "good",
            "waiting": "warning",
            "failed": "critical",
            "running": "primary",
            "pending": "neutral",
            "skipped": "neutral",
        }


class TestGraphSvgTitleFromDescription:
    def test_graph_svg_title_from_description(self):
        svg = render_graph_svg(_base_props())
        assert "<title>A tiny sample graph.</title>" in svg

    def test_graph_svg_title_generated_when_absent(self):
        props = _base_props()
        props["accessibleDescription"] = None
        svg = render_graph_svg(props)
        assert "<title>Graph of 3 nodes and 2 edges (flowchart)</title>" in svg

    def test_graph_svg_per_node_title_from_meta(self):
        props = _base_props()
        props["nodes"][0]["meta"] = {"owner": "team-a"}
        svg = render_graph_svg(props)
        assert "<title>owner=team-a</title>" in svg


class TestGraphSvgArrowheadsAndEdgeKinds:
    def test_graph_svg_arrowheads_and_edge_kinds(self):
        svg = render_graph_svg(_base_props())
        assert 'marker-end="url(#graph-arrow)"' in svg
        assert "stroke-dasharray=" in svg  # the dashed edge

        thick_props = _base_props(edges=[{"from": "a", "to": "b", "kind": "thick"}])
        thick_svg = render_graph_svg(thick_props)
        assert 'stroke-width="3"' in thick_svg


class TestGraphSvgComputesPositionsWhenAbsent:
    def test_computes_positions_when_absent(self):
        svg = render_graph_svg(_base_props())
        assert svg.count("<line") == 2

    def test_uses_supplied_positions_when_present(self):
        props = _base_props(
            layout={
                "engine": "manual",
                "positions": {"a": {"x": 0, "y": 0}, "b": {"x": 100, "y": 0}, "c": {"x": 200, "y": 0}},
            }
        )
        svg = render_graph_svg(props)
        assert svg.count("<g>") == 3


class TestGraphSvgGroupBoxes:
    def test_group_box_rendered(self):
        props = _base_props(groups=[{"id": "g1", "label": "Group A", "nodes": ["a", "b"]}])
        svg = render_graph_svg(props)
        assert "Group A" in svg
        assert 'stroke-dasharray="4,4"' in svg


class TestGraphSvgTooLargeRaises:
    def test_too_large_raises_when_positions_absent(self):
        nodes = [{"id": f"n{i}"} for i in range(MAX_STATIC_NODES + 1)]
        with pytest.raises(GraphTooLargeError):
            render_graph_svg({"kind": "flowchart", "direction": "TB", "nodes": nodes, "edges": []})
