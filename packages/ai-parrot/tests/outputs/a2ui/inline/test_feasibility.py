"""Per-component feasibility rules (FEAT-755 TASK-4764)."""

from __future__ import annotations

import pytest

from parrot.outputs.a2ui.inline.feasibility import FeasibilityResult, check_feasibility


class TestKPICard:
    @pytest.mark.parametrize("value", [42, 3.5, 0, "1.2M"])
    def test_scalar_feasible(self, value):
        assert check_feasibility("KPICard", {"label": "x", "value": value}, None) == FeasibilityResult(True)

    @pytest.mark.parametrize("config", [{}, {"value": None}, {"value": ""}, {"value": "  "}, {"value": {"path": "/p"}}])
    def test_missing(self, config):
        assert check_feasibility("KPICard", config, None) == FeasibilityResult(False, "kpicard_value_missing")


class TestTimeline:
    def test_titled_event_feasible(self):
        assert check_feasibility("Timeline", {"events": [{"title": "Launch"}]}, None).feasible

    @pytest.mark.parametrize(
        "config", [{"events": []}, {"events": [{"timestamp": "2024"}]}, {"events": [{"title": ""}]}, {}]
    )
    def test_missing(self, config):
        assert check_feasibility("Timeline", config, None) == FeasibilityResult(False, "timeline_events_missing")


class TestInfoCard:
    def test_title_feasible(self):
        assert check_feasibility("InfoCard", {"title": "Hi"}, None).feasible

    @pytest.mark.parametrize("config", [{}, {"title": ""}, {"title": " "}])
    def test_missing(self, config):
        assert check_feasibility("InfoCard", config, None) == FeasibilityResult(False, "infocard_title_missing")


class TestGraph:
    def test_valid(self):
        cfg = {"nodes": [{"id": "a"}, {"id": "b"}], "edges": [{"from": "a", "to": "b"}]}
        assert check_feasibility("Graph", cfg, None).feasible

    def test_nodes_only(self):
        assert check_feasibility("Graph", {"nodes": [{"id": "a"}]}, None).feasible

    def test_no_nodes(self):
        assert check_feasibility("Graph", {"nodes": []}, None) == FeasibilityResult(False, "graph_nodes_missing")

    def test_dangling(self):
        cfg = {"nodes": [{"id": "a"}], "edges": [{"from": "a", "to": "zz"}]}
        assert check_feasibility("Graph", cfg, None) == FeasibilityResult(False, "graph_edge_dangling")


class TestDispatch:
    def test_unknown_feasible(self):
        assert check_feasibility("Mermaid", {}, None) == FeasibilityResult(True)

    @pytest.mark.parametrize(
        "component,config",
        [
            ("KPICard", None),
            ("Timeline", {"events": None}),
            ("Timeline", {"events": "nope"}),
            ("Graph", {"nodes": "x"}),
            ("Graph", {"nodes": [1, 2]}),
            ("Graph", {"nodes": [{"id": "a"}], "edges": 5}),
            ("InfoCard", ["title"]),
        ],
    )
    def test_malformed_never_raises(self, component, config):
        result = check_feasibility(component, config, None)
        assert isinstance(result, FeasibilityResult)
        assert result.feasible is False
