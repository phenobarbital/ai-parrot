"""Regression tests for the declarative-definition fixes.

Each of these guards a bug that made machine-generated definitions unsafe:

* ``NodeDefinition.config`` was never read, so ``decision`` and
  ``interactive_decision`` could not be expressed in JSON at all;
* the definition models accepted unknown keys silently;
* ``CrewDefinition`` had no validators, so a bad ``flow_relations``
  reference deleted an edge instead of failing.
"""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from parrot.bots.flows.flow.definition import (
    ActionDefinition,
    EdgeDefinition,
    FlowDefinition,
    NodeDefinition,
)
from parrot.bots.flows.flow.flow import (
    NODE_CONFIG_MODELS,
    NODE_REGISTRY,
    AgentsFlow,
    register_node,
)
from parrot.models.crew_definition import (
    AgentDefinition,
    CrewDefinition,
    FlowRelation,
    ToolNodeDefinition,
)


class _StubRegistry:
    def get_bot_instance(self, name):  # pragma: no cover - never called here
        return None


# ── NodeDefinition.config now drives construction ────────────────────────────

def _definition(*nodes: NodeDefinition) -> FlowDefinition:
    return FlowDefinition(
        flow="t",
        nodes=[
            NodeDefinition(id="__start__", type="start"),
            *nodes,
            NodeDefinition(id="__end__", type="end"),
        ],
        edges=[],
    )


def test_decision_node_builds_from_a_pure_definition():
    """Previously raised ValidationError for the missing decision_config."""
    definition = _definition(
        NodeDefinition(
            id="vote",
            type="decision",
            config={"mode": "ballot", "decision_type": "binary", "minimum_votes": 2},
        )
    )
    flow = AgentsFlow.from_definition(definition, agent_registry=_StubRegistry())
    node = flow._materialize_nodes()["vote"]
    assert node.decision_config.mode.value == "ballot"
    assert node.decision_config.minimum_votes == 2


def test_interactive_decision_node_builds_from_a_pure_definition():
    definition = _definition(
        NodeDefinition(
            id="ask",
            type="interactive_decision",
            config={"question": "Publish?", "options": ["yes", "no"]},
        )
    )
    flow = AgentsFlow.from_definition(definition, agent_registry=_StubRegistry())
    node = flow._materialize_nodes()["ask"]
    assert node.question == "Publish?"
    assert node.options == ["yes", "no"]


def test_invalid_config_names_the_node_and_the_expected_model():
    definition = _definition(
        NodeDefinition(id="vote", type="decision", config={"mode": "ballot"})
    )
    flow = AgentsFlow.from_definition(definition, agent_registry=_StubRegistry())
    with pytest.raises(ValueError, match="Invalid 'config' for node 'vote'"):
        flow._materialize_nodes()


def test_max_retries_reaches_the_node_instance():
    """The field existed on the definition but on no Node, so it read as 0."""
    definition = _definition(
        NodeDefinition(
            id="vote",
            type="decision",
            max_retries=4,
            config={"mode": "ballot", "decision_type": "binary"},
        )
    )
    flow = AgentsFlow.from_definition(definition, agent_registry=_StubRegistry())
    assert flow._materialize_nodes()["vote"].max_retries == 4


def test_config_models_are_registered_for_the_built_in_types():
    assert {"decision", "interactive_decision", "synthesis"} <= set(NODE_CONFIG_MODELS)


def test_register_node_still_accepts_a_bare_call():
    """The config_model parameter is keyword-only and optional."""
    from parrot.bots.flows.core.node import Node

    class _Custom(Node):
        @property
        def name(self) -> str:
            return self.node_id

    try:
        register_node("test.bare_registration")(_Custom)
        assert NODE_REGISTRY["test.bare_registration"] is _Custom
        assert "test.bare_registration" not in NODE_CONFIG_MODELS
    finally:
        NODE_REGISTRY.pop("test.bare_registration", None)


def test_register_node_rejects_a_non_model_config():
    from parrot.bots.flows.core.node import Node

    with pytest.raises(TypeError, match="BaseModel subclass"):
        register_node("test.bad_config", config_model=dict)


# ── definitions are closed ───────────────────────────────────────────────────

@pytest.mark.parametrize(
    "model,payload",
    [
        (NodeDefinition, {"id": "a", "type": "agent", "agent_ref": "x", "bogus": 1}),
        (EdgeDefinition, {"from": "a", "to": "b", "bogus": 1}),
        (
            FlowDefinition,
            {"flow": "f", "nodes": [{"id": "a", "type": "start"}], "bogus": 1},
        ),
        (CrewDefinition, {"name": "c", "agents": [], "tasks": []}),
        (AgentDefinition, {"agent_id": "a", "bogus": 1}),
        (ToolNodeDefinition, {"node_id": "n", "tool": "t", "bogus": 1}),
        (FlowRelation, {"source": "a", "target": "b", "bogus": 1}),
    ],
)
def test_unknown_keys_are_rejected(model, payload):
    with pytest.raises(ValidationError):
        model.model_validate(payload)


def test_action_union_is_discriminated():
    """Without a discriminator the schema is an unhelpful anyOf."""
    from pydantic import TypeAdapter

    schema = TypeAdapter(ActionDefinition).json_schema()
    assert "oneOf" in schema
    assert schema.get("discriminator", {}).get("propertyName") == "type"


def test_human_node_type_is_not_advertised():
    """It was described in the field docs but never registered."""
    assert "human" not in NODE_REGISTRY
    assert "human" not in (NodeDefinition.model_fields["type"].description or "")


# ── CrewDefinition validators ────────────────────────────────────────────────

def _crew(**overrides) -> CrewDefinition:
    payload = {
        "name": "c",
        "agents": [
            AgentDefinition(agent_id="a", name="Researcher"),
            AgentDefinition(agent_id="b"),
        ],
    }
    payload.update(overrides)
    return CrewDefinition(**payload)


def test_relations_resolve_against_the_effective_display_name():
    crew = _crew(flow_relations=[FlowRelation(source="Researcher", target="b")])
    assert crew.member_names() == ["Researcher", "b"]


def test_relation_to_an_unknown_member_is_rejected():
    """It used to be skipped silently, deleting the edge."""
    with pytest.raises(ValidationError, match="unknown crew members"):
        _crew(flow_relations=[FlowRelation(source="a", target="b")])


def test_relation_cycle_is_rejected():
    with pytest.raises(ValidationError, match="Cycle detected"):
        _crew(
            flow_relations=[
                FlowRelation(source="Researcher", target="b"),
                FlowRelation(source="b", target="Researcher"),
            ]
        )


def test_tool_nodes_are_valid_relation_endpoints():
    crew = _crew(
        tool_nodes=[ToolNodeDefinition(node_id="publish", tool="rest_api")],
        flow_relations=[FlowRelation(source="Researcher", target="publish")],
    )
    assert "publish" in crew.member_names()


def test_dotted_tool_node_id_is_rejected():
    """A dot is ambiguous inside {nodes.<node_name>.output}."""
    with pytest.raises(ValidationError, match="must not contain"):
        ToolNodeDefinition(node_id="a.b", tool="t")


def test_fan_out_relations_are_accepted():
    crew = _crew(
        agents=[
            AgentDefinition(agent_id="a"),
            AgentDefinition(agent_id="b"),
            AgentDefinition(agent_id="c"),
        ],
        flow_relations=[FlowRelation(source="a", target=["b", "c"])],
    )
    assert len(crew.flow_relations) == 1
