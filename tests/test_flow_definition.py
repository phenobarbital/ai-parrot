"""
Tests for FlowDefinition Pydantic models.

Tests validation rules, serialization, and edge cases for the
AgentsFlow JSON serialization schema.
"""
import pytest
from pydantic import ValidationError

from parrot.bots.flow.definition import (
    FlowDefinition,
    FlowMetadata,
    NodeDefinition,
    NodePosition,
    EdgeDefinition,
    ActionDefinition,
    LogActionDef,
    NotifyActionDef,
    WebhookActionDef,
    MetricActionDef,
    SetContextActionDef,
    ValidateActionDef,
    TransformActionDef,
)


class TestNodeDefinition:
    """Tests for NodeDefinition model."""

    def test_agent_node_requires_agent_ref(self):
        """Agent nodes must have agent_ref."""
        with pytest.raises(ValidationError) as exc_info:
            NodeDefinition(id="test", type="agent")

        assert "agent_ref" in str(exc_info.value)

    def test_start_node_no_agent_ref(self):
        """Start nodes don't require agent_ref."""
        node = NodeDefinition(id="__start__", type="start")
        assert node.agent_ref is None
        assert node.type == "start"

    def test_end_node_no_agent_ref(self):
        """End nodes don't require agent_ref."""
        node = NodeDefinition(id="__end__", type="end")
        assert node.agent_ref is None
        assert node.type == "end"

    def test_decision_node_no_agent_ref(self):
        """Decision nodes don't require agent_ref."""
        node = NodeDefinition(
            id="decision",
            type="decision",
            config={"mode": "cio", "agents": ["agent1", "agent2"]}
        )
        assert node.agent_ref is None

    def test_agent_node_with_agent_ref(self):
        """Agent nodes accept agent_ref."""
        node = NodeDefinition(
            id="worker",
            type="agent",
            agent_ref="my_agent"
        )
        assert node.agent_ref == "my_agent"

    def test_node_with_pre_actions(self):
        """Nodes can have pre actions."""
        node = NodeDefinition(
            id="worker",
            type="agent",
            agent_ref="my_agent",
            pre_actions=[
                {"type": "log", "level": "info", "message": "Starting {node_name}"}
            ]
        )
        assert len(node.pre_actions) == 1
        assert node.pre_actions[0].type == "log"
        assert node.pre_actions[0].message == "Starting {node_name}"

    def test_node_with_post_actions(self):
        """Nodes can have post actions."""
        node = NodeDefinition(
            id="worker",
            type="agent",
            agent_ref="my_agent",
            post_actions=[
                {"type": "webhook", "url": "https://example.com/hook"}
            ]
        )
        assert len(node.post_actions) == 1
        assert node.post_actions[0].type == "webhook"

    def test_node_with_multiple_actions(self):
        """Nodes can have multiple pre and post actions."""
        node = NodeDefinition(
            id="worker",
            type="agent",
            agent_ref="my_agent",
            pre_actions=[
                {"type": "log", "level": "info", "message": "Starting"},
                {"type": "metric", "name": "node.started", "value": 1.0}
            ],
            post_actions=[
                {"type": "log", "level": "info", "message": "Completed"},
                {"type": "notify", "channel": "slack", "message": "Done"}
            ]
        )
        assert len(node.pre_actions) == 2
        assert len(node.post_actions) == 2

    def test_node_position(self):
        """Nodes have position for UI."""
        node = NodeDefinition(
            id="worker",
            type="agent",
            agent_ref="my_agent",
            position=NodePosition(x=100, y=200)
        )
        assert node.position.x == 100
        assert node.position.y == 200

    def test_node_default_position(self):
        """Nodes have default position (0, 0)."""
        node = NodeDefinition(id="start", type="start")
        assert node.position.x == 0.0
        assert node.position.y == 0.0

    def test_node_with_instruction(self):
        """Nodes can have instruction override."""
        node = NodeDefinition(
            id="worker",
            type="agent",
            agent_ref="my_agent",
            instruction="Process this specific task"
        )
        assert node.instruction == "Process this specific task"

    def test_node_with_metadata(self):
        """Nodes can have arbitrary metadata."""
        node = NodeDefinition(
            id="worker",
            type="agent",
            agent_ref="my_agent",
            metadata={"priority": "high", "timeout": 30}
        )
        assert node.metadata["priority"] == "high"
        assert node.metadata["timeout"] == 30

    def test_all_node_types(self):
        """All valid node types are accepted."""
        types = ["start", "end", "agent", "decision", "interactive_decision", "human"]
        for node_type in types:
            kwargs = {"id": f"node_{node_type}", "type": node_type}
            if node_type == "agent":
                kwargs["agent_ref"] = "test_agent"
            node = NodeDefinition(**kwargs)
            assert node.type == node_type


class TestEdgeDefinition:
    """Tests for EdgeDefinition model."""

    def test_on_condition_requires_predicate(self):
        """on_condition edges must have predicate."""
        with pytest.raises(ValidationError) as exc_info:
            EdgeDefinition(**{"from": "a", "to": "b", "condition": "on_condition"})

        assert "predicate" in str(exc_info.value)

    def test_on_condition_with_predicate(self):
        """on_condition edges accept predicate."""
        edge = EdgeDefinition(**{
            "from": "a",
            "to": "b",
            "condition": "on_condition",
            "predicate": 'result.decision == "pizza"'
        })
        assert edge.predicate == 'result.decision == "pizza"'

    def test_on_success_no_predicate(self):
        """on_success edges don't require predicate."""
        edge = EdgeDefinition(**{
            "from": "a",
            "to": "b",
            "condition": "on_success"
        })
        assert edge.predicate is None
        assert edge.condition == "on_success"

    def test_on_error_no_predicate(self):
        """on_error edges don't require predicate."""
        edge = EdgeDefinition(**{
            "from": "a",
            "to": "b",
            "condition": "on_error"
        })
        assert edge.condition == "on_error"

    def test_always_condition(self):
        """Always condition works."""
        edge = EdgeDefinition(**{
            "from": "a",
            "to": "b",
            "condition": "always"
        })
        assert edge.condition == "always"

    def test_edge_default_condition(self):
        """Default condition is on_success."""
        edge = EdgeDefinition(**{"from": "a", "to": "b"})
        assert edge.condition == "on_success"

    def test_edge_single_target(self):
        """Edge can target single node."""
        edge = EdgeDefinition(**{"from": "a", "to": "b"})
        assert edge.to == "b"

    def test_edge_fan_out(self):
        """Edge can target multiple nodes (fan-out)."""
        edge = EdgeDefinition(**{"from": "a", "to": ["b", "c", "d"]})
        assert edge.to == ["b", "c", "d"]

    def test_edge_with_instruction(self):
        """Edge can have instruction for target."""
        edge = EdgeDefinition(**{
            "from": "a",
            "to": "b",
            "instruction": "Process the previous result"
        })
        assert edge.instruction == "Process the previous result"

    def test_edge_with_priority(self):
        """Edge can have priority."""
        edge = EdgeDefinition(**{
            "from": "a",
            "to": "b",
            "priority": 10
        })
        assert edge.priority == 10

    def test_edge_default_priority(self):
        """Default priority is 0."""
        edge = EdgeDefinition(**{"from": "a", "to": "b"})
        assert edge.priority == 0

    def test_edge_with_label(self):
        """Edge can have UI label."""
        edge = EdgeDefinition(**{
            "from": "a",
            "to": "b",
            "label": "Success path"
        })
        assert edge.label == "Success path"

    def test_edge_with_id(self):
        """Edge can have explicit ID."""
        edge = EdgeDefinition(**{
            "from": "a",
            "to": "b",
            "id": "edge_a_to_b"
        })
        assert edge.id == "edge_a_to_b"

    def test_edge_from_alias(self):
        """Edge uses 'from' alias for from_ field."""
        edge = EdgeDefinition(**{"from": "source", "to": "target"})
        assert edge.from_ == "source"

    def test_edge_serialization_with_alias(self):
        """Edge serializes with 'from' alias."""
        edge = EdgeDefinition(**{"from": "a", "to": "b"})
        json_data = edge.model_dump(by_alias=True)
        assert "from" in json_data
        assert json_data["from"] == "a"


class TestFlowDefinition:
    """Tests for FlowDefinition root model."""

    def test_valid_flow(self):
        """Complete valid flow parses successfully."""
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
            ]
        )
        assert flow.flow == "TestFlow"
        assert len(flow.nodes) == 3
        assert len(flow.edges) == 2

    def test_flow_with_no_edges(self):
        """Flow can have no edges."""
        flow = FlowDefinition(
            flow="SingleNode",
            nodes=[NodeDefinition(id="standalone", type="agent", agent_ref="test")]
        )
        assert len(flow.edges) == 0

    def test_edge_references_unknown_source_node(self):
        """Edge referencing unknown source node raises error."""
        with pytest.raises(ValidationError) as exc_info:
            FlowDefinition(
                flow="BadFlow",
                nodes=[NodeDefinition(id="a", type="start")],
                edges=[EdgeDefinition(**{"from": "nonexistent", "to": "a"})]
            )

        assert "nonexistent" in str(exc_info.value)
        assert "unknown node" in str(exc_info.value).lower()

    def test_edge_references_unknown_target_node(self):
        """Edge referencing unknown target node raises error."""
        with pytest.raises(ValidationError) as exc_info:
            FlowDefinition(
                flow="BadFlow",
                nodes=[NodeDefinition(id="a", type="start")],
                edges=[EdgeDefinition(**{"from": "a", "to": "nonexistent"})]
            )

        assert "nonexistent" in str(exc_info.value)

    def test_edge_references_unknown_fan_out_target(self):
        """Edge with unknown fan-out target raises error."""
        with pytest.raises(ValidationError) as exc_info:
            FlowDefinition(
                flow="BadFlow",
                nodes=[
                    NodeDefinition(id="a", type="start"),
                    NodeDefinition(id="b", type="end")
                ],
                edges=[EdgeDefinition(**{"from": "a", "to": ["b", "c"]})]
            )

        assert "c" in str(exc_info.value)

    def test_flow_default_version(self):
        """Flow has default version 1.0."""
        flow = FlowDefinition(
            flow="Test",
            nodes=[NodeDefinition(id="a", type="start")]
        )
        assert flow.version == "1.0"

    def test_flow_with_description(self):
        """Flow can have description."""
        flow = FlowDefinition(
            flow="Test",
            description="A test workflow",
            nodes=[NodeDefinition(id="a", type="start")]
        )
        assert flow.description == "A test workflow"

    def test_flow_with_metadata(self):
        """Flow can have custom metadata."""
        flow = FlowDefinition(
            flow="Test",
            metadata=FlowMetadata(
                max_parallel_tasks=5,
                execution_timeout=60.0
            ),
            nodes=[NodeDefinition(id="a", type="start")]
        )
        assert flow.metadata.max_parallel_tasks == 5
        assert flow.metadata.execution_timeout == 60.0

    def test_flow_default_metadata(self):
        """Flow has default metadata."""
        flow = FlowDefinition(
            flow="Test",
            nodes=[NodeDefinition(id="a", type="start")]
        )
        assert flow.metadata.max_parallel_tasks == 10
        assert flow.metadata.default_max_retries == 3
        assert flow.metadata.enable_execution_memory is True

    def test_json_serialization(self):
        """Flow serializes to JSON with aliases."""
        flow = FlowDefinition(
            flow="Test",
            nodes=[NodeDefinition(id="a", type="start")],
            edges=[EdgeDefinition(**{"from": "a", "to": "a", "condition": "always"})]
        )
        json_str = flow.model_dump_json(by_alias=True)
        # Check alias is used (no underscore in field name)
        assert '"from":"a"' in json_str or '"from": "a"' in json_str
        assert '"from_"' not in json_str  # Ensure underscore variant is NOT used

    def test_json_roundtrip(self):
        """Flow survives JSON roundtrip."""
        original = FlowDefinition(
            flow="RoundtripTest",
            version="2.0",
            description="Test description",
            nodes=[
                NodeDefinition(id="start", type="start"),
                NodeDefinition(
                    id="worker",
                    type="agent",
                    agent_ref="test_agent",
                    pre_actions=[{"type": "log", "level": "info", "message": "Hello"}]
                ),
            ],
            edges=[
                EdgeDefinition(**{
                    "from": "start",
                    "to": "worker",
                    "condition": "on_condition",
                    "predicate": "result.ok"
                })
            ]
        )

        # Serialize and deserialize
        json_str = original.model_dump_json(by_alias=True)
        restored = FlowDefinition.model_validate_json(json_str)

        assert restored.flow == original.flow
        assert restored.version == original.version
        assert restored.description == original.description
        assert len(restored.nodes) == len(original.nodes)
        assert len(restored.edges) == len(original.edges)
        assert restored.edges[0].predicate == "result.ok"


class TestActionDefinitions:
    """Tests for action definition models."""

    def test_log_action(self):
        """Log action parses correctly."""
        action = LogActionDef(level="debug", message="Test {node_name}")
        assert action.type == "log"
        assert action.level == "debug"
        assert action.message == "Test {node_name}"

    def test_log_action_default_level(self):
        """Log action defaults to info level."""
        action = LogActionDef(message="Test")
        assert action.level == "info"

    def test_notify_action(self):
        """Notify action parses correctly."""
        action = NotifyActionDef(
            channel="slack",
            message="Task completed",
            target="#alerts"
        )
        assert action.type == "notify"
        assert action.channel == "slack"
        assert action.target == "#alerts"

    def test_notify_action_default_channel(self):
        """Notify action defaults to log channel."""
        action = NotifyActionDef(message="Test")
        assert action.channel == "log"

    def test_webhook_action(self):
        """Webhook action parses correctly."""
        action = WebhookActionDef(
            url="https://example.com/hook",
            method="PUT",
            headers={"Authorization": "Bearer token"},
            body_template='{"result": "{result}"}'
        )
        assert action.type == "webhook"
        assert action.url == "https://example.com/hook"
        assert action.method == "PUT"
        assert action.headers["Authorization"] == "Bearer token"

    def test_webhook_action_defaults(self):
        """Webhook action has correct defaults."""
        action = WebhookActionDef(url="https://example.com/hook")
        assert action.method == "POST"
        assert action.headers == {}
        assert action.body_template is None

    def test_metric_action(self):
        """Metric action parses correctly."""
        action = MetricActionDef(
            name="flow.completed",
            tags={"flow": "test", "env": "prod"},
            value=1.0
        )
        assert action.type == "metric"
        assert action.name == "flow.completed"
        assert action.tags["env"] == "prod"

    def test_metric_action_default_value(self):
        """Metric action defaults to value 1.0."""
        action = MetricActionDef(name="counter")
        assert action.value == 1.0

    def test_set_context_action(self):
        """SetContext action parses correctly."""
        action = SetContextActionDef(
            key="last_decision",
            value_from="result.final_decision"
        )
        assert action.type == "set_context"
        assert action.key == "last_decision"
        assert action.value_from == "result.final_decision"

    def test_validate_action(self):
        """Validate action parses correctly."""
        action = ValidateActionDef(
            schema={"type": "object", "required": ["decision"]},
            on_failure="skip"
        )
        assert action.type == "validate"
        assert action.schema_["required"] == ["decision"]
        assert action.on_failure == "skip"

    def test_validate_action_defaults(self):
        """Validate action has correct defaults."""
        action = ValidateActionDef(schema={"type": "string"})
        assert action.on_failure == "raise"
        assert action.fallback_value is None

    def test_validate_action_schema_alias(self):
        """Validate action uses schema alias."""
        # When parsing from dict with 'schema' key
        data = {
            "type": "validate",
            "schema": {"type": "string"},
            "on_failure": "raise"
        }
        action = ValidateActionDef.model_validate(data)
        assert action.schema_ == {"type": "string"}

    def test_transform_action(self):
        """Transform action parses correctly."""
        action = TransformActionDef(expression="result.lower()")
        assert action.type == "transform"
        assert action.expression == "result.lower()"


class TestFlowMetadata:
    """Tests for FlowMetadata model."""

    def test_default_values(self):
        """FlowMetadata has sensible defaults."""
        meta = FlowMetadata()
        assert meta.max_parallel_tasks == 10
        assert meta.default_max_retries == 3
        assert meta.execution_timeout is None
        assert meta.truncation_length is None
        assert meta.enable_execution_memory is True
        assert meta.embedding_model is None
        assert meta.vector_dimension == 384
        assert meta.vector_index_type == "Flat"

    def test_custom_values(self):
        """FlowMetadata accepts custom values."""
        meta = FlowMetadata(
            max_parallel_tasks=5,
            default_max_retries=5,
            execution_timeout=120.0,
            truncation_length=500,
            enable_execution_memory=False,
            embedding_model="all-MiniLM-L6-v2",
            vector_dimension=768,
            vector_index_type="HNSW"
        )
        assert meta.max_parallel_tasks == 5
        assert meta.default_max_retries == 5
        assert meta.execution_timeout == 120.0
        assert meta.embedding_model == "all-MiniLM-L6-v2"

    def test_max_parallel_tasks_minimum(self):
        """max_parallel_tasks must be at least 1."""
        with pytest.raises(ValidationError):
            FlowMetadata(max_parallel_tasks=0)


class TestImports:
    """Test that imports work correctly."""

    def test_import_from_flow_module(self):
        """Can import definitions from parrot.bots.flow."""
        from parrot.bots.flow import (
            FlowDefinition,
            NodeDefinition,
            EdgeDefinition,
            FlowMetadata,
            ActionDefinition,
            LogActionDef,
        )

        # Verify they are the expected types
        assert FlowDefinition.__name__ == "FlowDefinition"
        assert NodeDefinition.__name__ == "NodeDefinition"
        assert EdgeDefinition.__name__ == "EdgeDefinition"
