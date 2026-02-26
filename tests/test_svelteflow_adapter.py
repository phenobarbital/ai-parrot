"""Tests for parrot.bots.flow.svelteflow — SvelteFlow bidirectional adapter.

TASK-014: to_svelteflow / from_svelteflow conversion and roundtrip.
"""
import pytest

from parrot.bots.flow.definition import (
    EdgeDefinition,
    FlowDefinition,
    LogActionDef,
    NodeDefinition,
    NodePosition,
)
from parrot.bots.flow.svelteflow import from_svelteflow, to_svelteflow


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def sample_flow() -> FlowDefinition:
    return FlowDefinition(
        flow="TestFlow",
        version="1.0",
        nodes=[
            NodeDefinition(
                id="start",
                type="start",
                label="Begin",
                position=NodePosition(x=100, y=200),
            ),
            NodeDefinition(
                id="worker",
                type="agent",
                agent_ref="my_agent",
                label="Process",
                position=NodePosition(x=300, y=200),
                pre_actions=[
                    LogActionDef(level="info", message="Starting {node_name}")
                ],
            ),
            NodeDefinition(
                id="end",
                type="end",
                position=NodePosition(x=500, y=200),
            ),
        ],
        edges=[
            EdgeDefinition(
                **{"from": "start", "to": "worker", "condition": "always"}
            ),
            EdgeDefinition(
                **{
                    "from": "worker",
                    "to": "end",
                    "condition": "on_condition",
                    "predicate": 'result.status == "ok"',
                }
            ),
        ],
    )


# ---------------------------------------------------------------------------
# to_svelteflow Tests
# ---------------------------------------------------------------------------

class TestToSvelteflow:
    def test_node_structure(self, sample_flow: FlowDefinition):
        result = to_svelteflow(sample_flow)
        assert "nodes" in result
        assert len(result["nodes"]) == 3

        worker = next(n for n in result["nodes"] if n["id"] == "worker")
        assert worker["type"] == "agent"
        assert worker["position"] == {"x": 300, "y": 200}
        assert worker["data"]["label"] == "Process"
        assert worker["data"]["agent_ref"] == "my_agent"

    def test_edge_structure(self, sample_flow: FlowDefinition):
        result = to_svelteflow(sample_flow)
        assert "edges" in result
        assert len(result["edges"]) == 2

        edge = next(e for e in result["edges"] if e["source"] == "worker")
        assert edge["target"] == "end"
        assert edge["data"]["condition"] == "on_condition"
        assert edge["data"]["predicate"] == 'result.status == "ok"'

    def test_fanout_edges_expanded(self):
        flow = FlowDefinition(
            flow="FanOut",
            nodes=[
                NodeDefinition(id="a", type="start"),
                NodeDefinition(id="b", type="end"),
                NodeDefinition(id="c", type="end"),
            ],
            edges=[
                EdgeDefinition(
                    **{"from": "a", "to": ["b", "c"], "condition": "always"}
                )
            ],
        )
        result = to_svelteflow(flow)
        assert len(result["edges"]) == 2
        targets = {e["target"] for e in result["edges"]}
        assert targets == {"b", "c"}

    def test_actions_preserved(self, sample_flow: FlowDefinition):
        result = to_svelteflow(sample_flow)
        worker = next(n for n in result["nodes"] if n["id"] == "worker")
        assert len(worker["data"]["pre_actions"]) == 1
        assert worker["data"]["pre_actions"][0]["type"] == "log"

    def test_edge_id_generation(self, sample_flow: FlowDefinition):
        result = to_svelteflow(sample_flow)
        for edge in result["edges"]:
            assert edge["id"] is not None
            assert "->" in edge["id"] or edge["id"]

    def test_node_defaults_label(self):
        flow = FlowDefinition(
            flow="NoLabel",
            nodes=[NodeDefinition(id="my_node", type="start")],
            edges=[],
        )
        result = to_svelteflow(flow)
        # When label is None, should fall back to id
        assert result["nodes"][0]["data"]["label"] == "my_node"


# ---------------------------------------------------------------------------
# from_svelteflow Tests
# ---------------------------------------------------------------------------

class TestFromSvelteflow:
    def test_parse_basic(self):
        sf_data = {
            "nodes": [
                {
                    "id": "start",
                    "type": "start",
                    "position": {"x": 0, "y": 0},
                    "data": {"label": "Start"},
                },
                {
                    "id": "end",
                    "type": "end",
                    "position": {"x": 200, "y": 0},
                    "data": {"label": "End"},
                },
            ],
            "edges": [
                {
                    "id": "e1",
                    "source": "start",
                    "target": "end",
                    "data": {"condition": "always"},
                }
            ],
        }
        flow = from_svelteflow(sf_data, "ParsedFlow")
        assert flow.flow == "ParsedFlow"
        assert len(flow.nodes) == 2
        assert len(flow.edges) == 1
        assert flow.edges[0].from_ == "start"
        assert flow.edges[0].to == "end"

    def test_preserves_agent_ref(self):
        sf_data = {
            "nodes": [
                {
                    "id": "w",
                    "type": "agent",
                    "position": {"x": 0, "y": 0},
                    "data": {"label": "Worker", "agent_ref": "my_agent"},
                }
            ],
            "edges": [],
        }
        flow = from_svelteflow(sf_data, "AgentFlow")
        assert flow.nodes[0].agent_ref == "my_agent"

    def test_preserves_condition_and_predicate(self):
        sf_data = {
            "nodes": [
                {"id": "a", "type": "start", "position": {"x": 0, "y": 0}, "data": {}},
                {"id": "b", "type": "end", "position": {"x": 0, "y": 0}, "data": {}},
            ],
            "edges": [
                {
                    "id": "e1",
                    "source": "a",
                    "target": "b",
                    "data": {
                        "condition": "on_condition",
                        "predicate": 'result == "yes"',
                    },
                }
            ],
        }
        flow = from_svelteflow(sf_data, "CondFlow")
        assert flow.edges[0].condition == "on_condition"
        assert flow.edges[0].predicate == 'result == "yes"'

    def test_fanout_regrouped(self):
        sf_data = {
            "nodes": [
                {"id": "s", "type": "start", "position": {"x": 0, "y": 0}, "data": {}},
                {"id": "t1", "type": "end", "position": {"x": 0, "y": 0}, "data": {}},
                {"id": "t2", "type": "end", "position": {"x": 0, "y": 0}, "data": {}},
            ],
            "edges": [
                {
                    "id": "e1",
                    "source": "s",
                    "target": "t1",
                    "data": {"condition": "always"},
                },
                {
                    "id": "e2",
                    "source": "s",
                    "target": "t2",
                    "data": {"condition": "always"},
                },
            ],
        }
        flow = from_svelteflow(sf_data, "FanOutRegroup")
        # Should be grouped into single edge with to as list
        assert len(flow.edges) == 1
        assert isinstance(flow.edges[0].to, list)
        assert set(flow.edges[0].to) == {"t1", "t2"}


# ---------------------------------------------------------------------------
# Roundtrip Tests
# ---------------------------------------------------------------------------

class TestRoundtrip:
    def test_lossless_roundtrip(self, sample_flow: FlowDefinition):
        sf = to_svelteflow(sample_flow)
        restored = from_svelteflow(sf, sample_flow.flow)

        assert restored.flow == sample_flow.flow
        assert len(restored.nodes) == len(sample_flow.nodes)
        assert len(restored.edges) == len(sample_flow.edges)

        for orig, rest in zip(sample_flow.nodes, restored.nodes):
            assert rest.id == orig.id
            assert rest.type == orig.type
            assert rest.agent_ref == orig.agent_ref

    def test_edge_conditions_preserved(self, sample_flow: FlowDefinition):
        sf = to_svelteflow(sample_flow)
        restored = from_svelteflow(sf, sample_flow.flow)

        orig_cond = next(e for e in sample_flow.edges if e.condition == "on_condition")
        rest_cond = next(e for e in restored.edges if e.condition == "on_condition")
        assert rest_cond.predicate == orig_cond.predicate

    def test_positions_preserved(self, sample_flow: FlowDefinition):
        sf = to_svelteflow(sample_flow)
        restored = from_svelteflow(sf, sample_flow.flow)

        for orig, rest in zip(sample_flow.nodes, restored.nodes):
            assert rest.position.x == orig.position.x
            assert rest.position.y == orig.position.y

    def test_actions_roundtrip(self, sample_flow: FlowDefinition):
        sf = to_svelteflow(sample_flow)
        restored = from_svelteflow(sf, sample_flow.flow)

        orig_worker = next(n for n in sample_flow.nodes if n.id == "worker")
        rest_worker = next(n for n in restored.nodes if n.id == "worker")

        assert len(rest_worker.pre_actions) == len(orig_worker.pre_actions)
        assert rest_worker.pre_actions[0].type == "log"
        assert rest_worker.pre_actions[0].message == orig_worker.pre_actions[0].message


# ---------------------------------------------------------------------------
# Import Tests
# ---------------------------------------------------------------------------

class TestImports:
    def test_import_from_package(self):
        from parrot.bots.flow import from_svelteflow as fs
        from parrot.bots.flow import to_svelteflow as ts

        assert ts is to_svelteflow
        assert fs is from_svelteflow
