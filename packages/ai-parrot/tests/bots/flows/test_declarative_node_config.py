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
    """A genuine typo used to be skipped silently, deleting the edge."""
    with pytest.raises(ValidationError, match="unknown crew members"):
        _crew(flow_relations=[FlowRelation(source="Researchr", target="b")])


def test_relation_by_agent_id_is_accepted_and_normalised():
    """An agent_id reference is a legitimate, long-stored spelling.

    ``crew.agents`` is keyed by ``name or agent_id``, so a relation written
    against the ``agent_id`` of an agent that also has a ``name`` used to
    resolve to nothing and lose the edge. Rejecting it instead would make
    every crew stored that way unloadable; normalising it to the canonical
    display name wires the edge the author meant.
    """
    crew = _crew(flow_relations=[FlowRelation(source="a", target="b")])
    assert crew.flow_relations[0].source == "Researcher"
    assert crew.flow_relations[0].target == "b"


def test_normalisation_handles_list_endpoints():
    crew = _crew(
        tool_nodes=[ToolNodeDefinition(node_id="publish", tool="rest_api")],
        flow_relations=[FlowRelation(source=["a", "b"], target=["publish"])],
    )
    assert crew.flow_relations[0].source == ["Researcher", "b"]
    assert crew.flow_relations[0].target == ["publish"]


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


# ── code-review fixes (PR #1186) ─────────────────────────────────────────────

class _StubAgent:
    def __init__(self, name: str) -> None:
        self.name = name


class _PopulatedRegistry:
    """A registry that actually resolves the names a definition declares."""

    def __init__(self, *names: str) -> None:
        self._agents = {name: _StubAgent(name) for name in names}

    def get_bot_instance(self, name):
        return self._agents.get(name)

    def get(self, name):
        return self._agents.get(name)


def test_max_retries_defaults_to_no_retries():
    """0, matching Node.max_retries.

    The field predates the machinery that reads it. Defaulting to 3 now that
    it IS read would hand three silent re-executions — extra LLM spend and
    repeated tool side effects — to every already-stored definition that
    never asked for them.
    """
    assert NodeDefinition(id="n", type="synthesis").max_retries == 0

    definition = _definition(NodeDefinition(id="s", type="synthesis"))
    flow = AgentsFlow.from_definition(definition, agent_registry=_StubRegistry())
    assert flow._materialize_nodes()["s"].max_retries == 0


def test_decision_node_receives_its_resolved_voters():
    """A vote with no voters decides nothing; agents cannot travel in JSON."""
    definition = _definition(
        NodeDefinition(
            id="vote",
            type="decision",
            config={
                "mode": "ballot",
                "decision_type": "binary",
                "agent_refs": ["writer_agent", "researcher_agent"],
            },
        )
    )
    registry = _PopulatedRegistry("writer_agent", "researcher_agent")
    flow = AgentsFlow.from_definition(definition, agent_registry=registry)
    node = flow._materialize_nodes()["vote"]
    assert set(node.agents) == {"writer_agent", "researcher_agent"}
    assert node.agents["writer_agent"].name == "writer_agent"


def test_unresolvable_decision_voter_fails_loudly():
    from parrot.bots.flows.core.context import AgentNotFoundError

    definition = _definition(
        NodeDefinition(
            id="vote",
            type="decision",
            config={
                "mode": "ballot",
                "decision_type": "binary",
                "agent_refs": ["ghost_agent"],
            },
        )
    )
    with pytest.raises(AgentNotFoundError, match="ghost_agent"):
        AgentsFlow.from_definition(
            definition, agent_registry=_PopulatedRegistry("writer_agent")
        )


# ── FlowLoader materialization ───────────────────────────────────────────────

def test_loader_builds_a_real_decision_node():
    """It used to route 'decision' through _resolve_agent and raise LookupError.

    A decision node carries no agent_ref (several agents vote, not one), and
    BlueprintNode forbids setting one — so every authored decision node was
    unloadable through FlowLoader.
    """
    from parrot.bots.flows.flow.flow import DecisionNode
    from parrot.bots.flows.flow.loader import FlowLoader

    definition = _definition(
        NodeDefinition(
            id="vote",
            type="decision",
            config={
                "mode": "ballot",
                "decision_type": "binary",
                "agent_refs": ["writer_agent"],
            },
        )
    )
    flow = FlowLoader.to_agents_flow(
        definition, agent_registry=_PopulatedRegistry("writer_agent")
    )
    node = flow._nodes["vote"]
    assert isinstance(node, DecisionNode)
    assert node.decision_config.mode.value == "ballot"
    assert set(node.agents) == {"writer_agent"}


def test_loader_builds_a_synthesis_node():
    from parrot.bots.flows.flow.flow import SynthesisNode
    from parrot.bots.flows.flow.loader import FlowLoader

    definition = _definition(NodeDefinition(id="sum", type="synthesis"))
    flow = FlowLoader.to_agents_flow(definition, agent_registry=_PopulatedRegistry())
    assert isinstance(flow._nodes["sum"], SynthesisNode)


def test_loader_explains_why_it_cannot_build_a_tool_node():
    """PlanToolNode needs a live ToolManager the loader has no seam to inject."""
    from parrot.bots.flows.flow.loader import FlowLoader

    definition = _definition(
        NodeDefinition(id="fetch", type="tool", config={"tool": "rest_api"})
    )
    with pytest.raises(ValueError, match="node_factories"):
        FlowLoader.to_agents_flow(definition, agent_registry=_PopulatedRegistry())
