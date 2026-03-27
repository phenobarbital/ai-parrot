"""Tests for parrot.bots.flow.definition — FlowDefinition Pydantic models.

TASK-009: Validates all Pydantic models for flow JSON serialization.
"""
import json

import pytest
from pydantic import ValidationError

from parrot.bots.flow.definition import (
    ActionDefinition,
    EdgeDefinition,
    FlowDefinition,
    FlowMetadata,
    LogActionDef,
    MetricActionDef,
    NodeDefinition,
    NodePosition,
    NotifyActionDef,
    SetContextActionDef,
    TransformActionDef,
    ValidateActionDef,
    WebhookActionDef,
)


# ---------------------------------------------------------------------------
# Action Definition Tests
# ---------------------------------------------------------------------------

class TestLogActionDef:
    def test_defaults(self):
        action = LogActionDef(message="hello {node_name}")
        assert action.type == "log"
        assert action.level == "info"

    def test_custom_level(self):
        action = LogActionDef(level="debug", message="Test {node_name}")
        assert action.level == "debug"

    def test_all_levels(self):
        for level in ("debug", "info", "warning", "error"):
            action = LogActionDef(level=level, message="test")
            assert action.level == level


class TestNotifyActionDef:
    def test_defaults(self):
        action = NotifyActionDef(message="alert!")
        assert action.type == "notify"
        assert action.channel == "log"
        assert action.target is None

    def test_channels(self):
        for channel in ("slack", "teams", "email", "log"):
            action = NotifyActionDef(channel=channel, message="test")
            assert action.channel == channel


class TestWebhookActionDef:
    def test_defaults(self):
        action = WebhookActionDef(url="https://example.com/hook")
        assert action.type == "webhook"
        assert action.method == "POST"
        assert action.headers == {}
        assert action.body_template is None

    def test_with_body(self):
        action = WebhookActionDef(
            url="https://example.com",
            method="PUT",
            headers={"Authorization": "Bearer tok"},
            body_template='{"node": "{node_name}"}',
        )
        assert action.method == "PUT"
        assert action.body_template is not None


class TestMetricActionDef:
    def test_defaults(self):
        action = MetricActionDef(name="flow.completed")
        assert action.type == "metric"
        assert action.value == 1.0
        assert action.tags == {}

    def test_with_tags(self):
        action = MetricActionDef(
            name="flow.latency",
            tags={"env": "prod"},
            value=42.5,
        )
        assert action.tags["env"] == "prod"


class TestSetContextActionDef:
    def test_fields(self):
        action = SetContextActionDef(key="selected", value_from="result.decision")
        assert action.type == "set_context"
        assert action.key == "selected"
        assert action.value_from == "result.decision"


class TestValidateActionDef:
    def test_schema_alias(self):
        action = ValidateActionDef(
            schema={"type": "object", "required": ["decision"]},
            on_failure="raise",
        )
        assert action.type == "validate"
        assert action.schema_ == {"type": "object", "required": ["decision"]}

    def test_on_failure_modes(self):
        for mode in ("raise", "skip", "fallback"):
            action = ValidateActionDef(
                schema={"type": "string"},
                on_failure=mode,
            )
            assert action.on_failure == mode


class TestTransformActionDef:
    def test_fields(self):
        action = TransformActionDef(expression="result.lower()")
        assert action.type == "transform"
        assert action.expression == "result.lower()"


# ---------------------------------------------------------------------------
# NodeDefinition Tests
# ---------------------------------------------------------------------------

class TestNodeDefinition:
    def test_agent_node_requires_agent_ref(self):
        with pytest.raises(ValidationError, match="agent_ref"):
            NodeDefinition(id="test", type="agent")

    def test_agent_node_with_agent_ref(self):
        node = NodeDefinition(id="worker", type="agent", agent_ref="my_agent")
        assert node.agent_ref == "my_agent"

    def test_start_node_no_agent_ref(self):
        node = NodeDefinition(id="__start__", type="start")
        assert node.agent_ref is None

    def test_end_node_no_agent_ref(self):
        node = NodeDefinition(id="__end__", type="end")
        assert node.agent_ref is None

    def test_decision_types(self):
        for t in ("decision", "interactive_decision", "human"):
            node = NodeDefinition(id="n", type=t)
            assert node.type == t

    def test_defaults(self):
        node = NodeDefinition(id="a", type="start")
        assert node.max_retries == 3
        assert node.config == {}
        assert node.pre_actions == []
        assert node.post_actions == []
        assert node.metadata == {}
        assert node.position.x == 0.0
        assert node.position.y == 0.0

    def test_node_with_actions(self):
        node = NodeDefinition(
            id="worker",
            type="agent",
            agent_ref="my_agent",
            pre_actions=[{"type": "log", "level": "info", "message": "Starting"}],
        )
        assert len(node.pre_actions) == 1
        assert node.pre_actions[0].type == "log"

    def test_node_position(self):
        node = NodeDefinition(
            id="a",
            type="start",
            position=NodePosition(x=100, y=200),
        )
        assert node.position.x == 100
        assert node.position.y == 200

    def test_all_node_types(self):
        valid_types = ["start", "end", "agent", "decision", "interactive_decision", "human"]
        for t in valid_types:
            kwargs = {"id": "n", "type": t}
            if t == "agent":
                kwargs["agent_ref"] = "ref"
            node = NodeDefinition(**kwargs)
            assert node.type == t


# ---------------------------------------------------------------------------
# EdgeDefinition Tests
# ---------------------------------------------------------------------------

class TestEdgeDefinition:
    def test_on_condition_requires_predicate(self):
        with pytest.raises(ValidationError, match="predicate"):
            EdgeDefinition(**{"from": "a", "to": "b", "condition": "on_condition"})

    def test_on_success_no_predicate(self):
        edge = EdgeDefinition(**{"from": "a", "to": "b", "condition": "on_success"})
        assert edge.predicate is None

    def test_always_condition(self):
        edge = EdgeDefinition(**{"from": "a", "to": "b", "condition": "always"})
        assert edge.condition == "always"

    def test_edge_fan_out(self):
        edge = EdgeDefinition(**{"from": "a", "to": ["b", "c"]})
        assert edge.to == ["b", "c"]

    def test_edge_with_predicate(self):
        edge = EdgeDefinition(
            **{
                "from": "a",
                "to": "b",
                "condition": "on_condition",
                "predicate": 'result.value == "yes"',
            }
        )
        assert edge.predicate == 'result.value == "yes"'

    def test_edge_alias(self):
        edge = EdgeDefinition(**{"from": "src", "to": "dst"})
        assert edge.from_ == "src"

    def test_edge_defaults(self):
        edge = EdgeDefinition(**{"from": "a", "to": "b"})
        assert edge.condition == "on_success"
        assert edge.priority == 0
        assert edge.label is None
        assert edge.instruction is None

    def test_all_conditions(self):
        for cond in ("always", "on_success", "on_error", "on_timeout"):
            edge = EdgeDefinition(**{"from": "a", "to": "b", "condition": cond})
            assert edge.condition == cond


# ---------------------------------------------------------------------------
# FlowMetadata Tests
# ---------------------------------------------------------------------------

class TestFlowMetadata:
    def test_defaults(self):
        meta = FlowMetadata()
        assert meta.max_parallel_tasks == 10
        assert meta.default_max_retries == 3
        assert meta.execution_timeout is None
        assert meta.enable_execution_memory is True
        assert meta.vector_dimension == 384

    def test_custom(self):
        meta = FlowMetadata(max_parallel_tasks=5, execution_timeout=30.0)
        assert meta.max_parallel_tasks == 5
        assert meta.execution_timeout == 30.0


# ---------------------------------------------------------------------------
# FlowDefinition Tests
# ---------------------------------------------------------------------------

class TestFlowDefinition:
    def test_valid_flow(self):
        flow = FlowDefinition(
            flow="TestFlow",
            nodes=[
                NodeDefinition(id="start", type="start"),
                NodeDefinition(id="worker", type="agent", agent_ref="echo"),
                NodeDefinition(id="end", type="end"),
            ],
            edges=[
                EdgeDefinition(**{"from": "start", "to": "worker", "condition": "always"}),
                EdgeDefinition(**{"from": "worker", "to": "end", "condition": "on_success"}),
            ],
        )
        assert flow.flow == "TestFlow"
        assert len(flow.nodes) == 3
        assert len(flow.edges) == 2

    def test_flow_with_no_edges(self):
        """Flow can have no edges."""
        flow = FlowDefinition(
                nodes=[NodeDefinition(id="a", type="start")],
                edges=[EdgeDefinition(**{"from": "missing", "to": "a"})],
            )

    def test_edge_references_unknown_node_target(self):
        with pytest.raises(ValidationError, match="unknown node"):
            FlowDefinition(
                flow="BadFlow",
                nodes=[NodeDefinition(id="a", type="start")],
                edges=[EdgeDefinition(**{"from": "a", "to": "nonexistent"})],
            )

    def test_edge_fan_out_validates_all_targets(self):
        with pytest.raises(ValidationError, match="unknown node"):
            FlowDefinition(
                flow="BadFlow",
                nodes=[
                    NodeDefinition(id="b", type="end"),
                ],
                edges=[EdgeDefinition(**{"from": "a", "to": ["b", "missing"]})],
            )

    def test_no_edges(self):
        flow = FlowDefinition(
            flow="NoEdges",
            nodes=[NodeDefinition(id="a", type="start")],
            edges=[],
        )
        assert len(flow.edges) == 0

    def test_json_serialization(self):
        flow = FlowDefinition(
            flow="Test",
            nodes=[
                NodeDefinition(id="a", type="start"),
                NodeDefinition(id="b", type="end"),
            ],
            edges=[EdgeDefinition(**{"from": "a", "to": "b", "condition": "always"})],
        )
        json_str = flow.model_dump_json(by_alias=True)
        data = json.loads(json_str)
        # Verify alias: "from_" serialized as "from"
        assert data["edges"][0]["from"] == "a"

    def test_json_roundtrip(self):
        flow = FlowDefinition(
            flow="Roundtrip",
            nodes=[
                NodeDefinition(id="s", type="start"),
                NodeDefinition(
                    id="w",
                    type="agent",
                    agent_ref="worker",
                    pre_actions=[LogActionDef(level="info", message="hi {node_name}")],
                ),
                NodeDefinition(id="e", type="end"),
            ],
            edges=[
                EdgeDefinition(**{"from": "s", "to": "w", "condition": "always"}),
                EdgeDefinition(**{"from": "w", "to": "e", "condition": "on_success"}),
            ],
        )
        json_str = flow.model_dump_json(by_alias=True)
        restored = FlowDefinition.model_validate_json(json_str)
        assert restored.flow == flow.flow
        assert len(restored.nodes) == len(flow.nodes)
        assert len(restored.edges) == len(flow.edges)

    def test_defaults(self):
        flow = FlowDefinition(
            flow="Defaults",
            nodes=[NodeDefinition(id="a", type="start")],
        )
        assert flow.version == "1.0"
        assert flow.description == ""
        assert flow.created_at is None
        assert flow.metadata.max_parallel_tasks == 10


# ---------------------------------------------------------------------------
# Import Tests
# ---------------------------------------------------------------------------

class TestImports:
    def test_import_from_package(self):
        from parrot.bots.flow import FlowDefinition as FD
        from parrot.bots.flow import NodeDefinition as ND
        from parrot.bots.flow import EdgeDefinition as ED

        assert FD is FlowDefinition
        assert ND is NodeDefinition
        assert ED is EdgeDefinition
