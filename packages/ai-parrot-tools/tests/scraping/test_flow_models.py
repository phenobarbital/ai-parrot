"""Tests for ScrapingFlow / FlowNode / FlowResult — FEAT-222 TASK-1449."""
import pytest

from parrot_tools.scraping.flow_models import FlowNode, FlowResult, ScrapingFlow


# ── FlowNode ──────────────────────────────────────────────────────────

class TestFlowNode:
    def test_defaults(self):
        node = FlowNode(id="a", plan_ref="plan-a")
        assert node.inputs == {}
        assert node.session == "default"
        assert node.on_error == "abort"
        assert node.max_retries == 3

    def test_explicit_fields(self):
        node = FlowNode(
            id="b", plan_ref="p", inputs={"url": "a.product_url"},
            session="auth", on_error="retry", max_retries=5,
        )
        assert node.inputs == {"url": "a.product_url"}
        assert node.session == "auth"
        assert node.on_error == "retry"
        assert node.max_retries == 5

    def test_max_retries_min(self):
        with pytest.raises(ValueError):
            FlowNode(id="b", plan_ref="p", max_retries=0)


# ── ScrapingFlow ──────────────────────────────────────────────────────

class TestScrapingFlow:
    def test_valid_linear_dag(self):
        flow = ScrapingFlow(name="test", nodes=[
            FlowNode(id="a", plan_ref="plan-a"),
            FlowNode(id="b", plan_ref="plan-b", inputs={"url": "a.product_url"}),
        ])
        order = flow.topological_order()
        assert [n.id for n in order] == ["a", "b"]

    def test_order_independent_of_declaration(self):
        # 'b' declared before 'a' but depends on 'a'.
        flow = ScrapingFlow(name="test", nodes=[
            FlowNode(id="b", plan_ref="p", inputs={"url": "a.field"}),
            FlowNode(id="a", plan_ref="p"),
        ])
        order = [n.id for n in flow.topological_order()]
        assert order.index("a") < order.index("b")

    def test_cycle_detection(self):
        with pytest.raises(ValueError, match="cycle"):
            ScrapingFlow(name="test", nodes=[
                FlowNode(id="a", plan_ref="p", inputs={"x": "b.field"}),
                FlowNode(id="b", plan_ref="p", inputs={"x": "a.field"}),
            ])

    def test_self_cycle_detection(self):
        with pytest.raises(ValueError, match="cycle"):
            ScrapingFlow(name="test", nodes=[
                FlowNode(id="a", plan_ref="p", inputs={"x": "a.field"}),
            ])

    def test_dangling_ref(self):
        with pytest.raises(ValueError, match="nonexistent"):
            ScrapingFlow(name="test", nodes=[
                FlowNode(id="a", plan_ref="p", inputs={"x": "nonexistent.field"}),
            ])

    def test_duplicate_ids(self):
        with pytest.raises(ValueError, match="Duplicate"):
            ScrapingFlow(name="test", nodes=[
                FlowNode(id="a", plan_ref="p"),
                FlowNode(id="a", plan_ref="q"),
            ])

    def test_empty_nodes_rejected(self):
        with pytest.raises(ValueError):
            ScrapingFlow(name="empty", nodes=[])

    def test_topological_order_returns_fresh_list(self):
        flow = ScrapingFlow(name="t", nodes=[FlowNode(id="a", plan_ref="p")])
        o1 = flow.topological_order()
        o1.clear()  # mutating the returned list must not corrupt the cache
        assert [n.id for n in flow.topological_order()] == ["a"]

    def test_diamond_dag(self):
        flow = ScrapingFlow(name="test", nodes=[
            FlowNode(id="root", plan_ref="p"),
            FlowNode(id="left", plan_ref="p", inputs={"x": "root.field"}),
            FlowNode(id="right", plan_ref="p", inputs={"x": "root.field"}),
            FlowNode(id="sink", plan_ref="p",
                     inputs={"a": "left.field", "b": "right.field"}),
        ])
        order = flow.topological_order()
        ids = [n.id for n in order]
        assert ids[0] == "root"
        assert ids[-1] == "sink"
        assert ids.index("left") < ids.index("sink")
        assert ids.index("right") < ids.index("sink")

    def test_field_index_ref_parsing(self):
        # Fan-out style refs ("node.field[*]") only need their source node.
        flow = ScrapingFlow(name="t", nodes=[
            FlowNode(id="search", plan_ref="p"),
            FlowNode(id="detail", plan_ref="p",
                     inputs={"url": "search.flights[*]"}),
        ])
        order = [n.id for n in flow.topological_order()]
        assert order == ["search", "detail"]

    def test_multiple_inputs_from_same_source(self):
        flow = ScrapingFlow(name="t", nodes=[
            FlowNode(id="a", plan_ref="p"),
            FlowNode(id="b", plan_ref="p",
                     inputs={"x": "a.f1", "y": "a.f2"}),
        ])
        order = [n.id for n in flow.topological_order()]
        assert order == ["a", "b"]


# ── FlowResult ────────────────────────────────────────────────────────

class TestFlowResult:
    def test_defaults(self):
        r = FlowResult(flow_name="f")
        assert r.success is True
        assert r.node_results == {}
        assert r.nodes_completed == 0
        assert r.checkpoint_path is None
        assert r.resumed_from is None

    def test_stores_node_results(self):
        r = FlowResult(
            flow_name="f",
            node_results={"a": {"url": "x"}},
            nodes_completed=1,
            nodes_total=2,
            elapsed_seconds=1.5,
        )
        assert r.node_results["a"]["url"] == "x"
        assert r.nodes_completed == 1
        assert r.nodes_total == 2
        assert r.elapsed_seconds == 1.5
