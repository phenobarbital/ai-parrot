"""Unit tests for AgentsFlow.from_definition() — FEAT-163 TASK-1068.

Tests verify:
- from_definition returns a configured AgentsFlow with _definition and
  _resolved_agents populated.
- AgentNotFoundError is raised for unknown agent_ref values.
- ValueError is raised for unknown node_type values.
- Start/end nodes (no agent_ref) are skipped during agent resolution.
- _materialize_nodes() builds fresh Node instances from _resolved_agents.
- from_definition raises ValueError when agent_registry is None.
"""
import pytest

from parrot.bots.flows.flow import AgentsFlow, NODE_REGISTRY
from parrot.bots.flows.core.context import AgentNotFoundError
from parrot.bots.flows.flow.definition import (
    FlowDefinition,
    NodeDefinition,
    EdgeDefinition,
)


# ---------------------------------------------------------------------------
# Stubs
# ---------------------------------------------------------------------------


class FakeAgent:
    """Minimal AgentLike stub for registry tests."""

    def __init__(self, name: str, response: str = "ok") -> None:
        self._name = name
        self._response = response

    @property
    def name(self) -> str:
        return self._name

    async def invoke(self, prompt: str, **kwargs: object) -> object:
        return self._response

    async def ask(self, question: str = "", **kwargs: object) -> object:
        return type("R", (), {"content": self._response})()


class StubRegistry:
    """Minimal AgentRegistry stub using get_bot_instance (sync, like the real registry)."""

    def __init__(self, agents: dict) -> None:
        self._agents = agents

    def get_bot_instance(self, name: str) -> object:
        """Return the agent if registered, else None (mirrors AgentRegistry.get_bot_instance)."""
        return self._agents.get(name)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_linear_def() -> FlowDefinition:
    """Linear flow: start → agent_a → agent_b."""
    return FlowDefinition(
        flow="linear",
        nodes=[
            NodeDefinition(id="start", type="start"),
            NodeDefinition(id="n1", type="agent", agent_ref="agent_a"),
            NodeDefinition(id="n2", type="agent", agent_ref="agent_b"),
        ],
        edges=[
            EdgeDefinition(**{"from": "start", "to": "n1", "condition": "always"}),
            EdgeDefinition(**{"from": "n1", "to": "n2", "condition": "always"}),
        ],
    )


def _make_stub_registry() -> StubRegistry:
    return StubRegistry({
        "agent_a": FakeAgent("agent_a"),
        "agent_b": FakeAgent("agent_b"),
    })


# ---------------------------------------------------------------------------
# Tests: from_definition happy path
# ---------------------------------------------------------------------------


class TestFromDefinitionHappyPath:
    def test_returns_agents_flow_instance(self) -> None:
        reg = _make_stub_registry()
        flow = AgentsFlow.from_definition(_make_linear_def(), agent_registry=reg)
        assert isinstance(flow, AgentsFlow)

    def test_definition_stored_on_instance(self) -> None:
        reg = _make_stub_registry()
        defn = _make_linear_def()
        flow = AgentsFlow.from_definition(defn, agent_registry=reg)
        assert flow._definition is defn

    def test_agent_registry_stored_on_instance(self) -> None:
        reg = _make_stub_registry()
        flow = AgentsFlow.from_definition(_make_linear_def(), agent_registry=reg)
        assert flow._agent_registry is reg

    def test_resolved_agents_keyed_by_node_id(self) -> None:
        reg = _make_stub_registry()
        flow = AgentsFlow.from_definition(_make_linear_def(), agent_registry=reg)
        assert "n1" in flow._resolved_agents
        assert "n2" in flow._resolved_agents
        assert flow._resolved_agents["n1"].name == "agent_a"
        assert flow._resolved_agents["n2"].name == "agent_b"

    def test_non_agent_nodes_not_in_resolved_agents(self) -> None:
        """start/end nodes have no agent_ref and should not appear in _resolved_agents."""
        reg = _make_stub_registry()
        flow = AgentsFlow.from_definition(_make_linear_def(), agent_registry=reg)
        assert "start" not in flow._resolved_agents

    def test_flow_name_from_definition(self) -> None:
        reg = _make_stub_registry()
        flow = AgentsFlow.from_definition(_make_linear_def(), agent_registry=reg)
        assert flow.name == "linear"


# ---------------------------------------------------------------------------
# Tests: from_definition error paths
# ---------------------------------------------------------------------------


class TestFromDefinitionErrors:
    def test_raises_value_error_when_no_registry(self) -> None:
        with pytest.raises(ValueError, match="agent_registry"):
            AgentsFlow.from_definition(_make_linear_def(), agent_registry=None)

    def test_raises_agent_not_found_for_missing_ref(self) -> None:
        """Registry only knows agent_a; agent_b ref raises AgentNotFoundError."""
        partial_reg = StubRegistry({"agent_a": FakeAgent("agent_a")})
        with pytest.raises(AgentNotFoundError, match="n2"):
            AgentsFlow.from_definition(_make_linear_def(), agent_registry=partial_reg)

    def test_raises_value_error_for_unknown_node_type(self) -> None:
        """A node with node_type not in NODE_REGISTRY raises ValueError."""
        defn = FlowDefinition(
            flow="bad-type",
            nodes=[
                NodeDefinition(id="n1", type="start"),
            ],
            edges=[],
        )
        # Patch NODE_REGISTRY to have a node type that the FlowDefinition doesn't accept.
        # NodeDefinition's type field is a Literal — so use a valid literal with no registry entry.
        # Actually "human" is valid in NodeDefinition.type but not registered in NODE_REGISTRY.
        defn2 = FlowDefinition(
            flow="human-type",
            nodes=[
                NodeDefinition(id="h1", type="human"),
            ],
            edges=[],
        )
        reg = _make_stub_registry()
        # "human" is in NodeDefinition.type Literal but NOT in NODE_REGISTRY.
        assert "human" not in NODE_REGISTRY
        with pytest.raises(ValueError, match="human"):
            AgentsFlow.from_definition(defn2, agent_registry=reg)


# ---------------------------------------------------------------------------
# Tests: _materialize_nodes integration
# ---------------------------------------------------------------------------


class TestMaterializeNodesWithDefinition:
    def test_materialize_returns_nodes_for_each_def(self) -> None:
        reg = _make_stub_registry()
        flow = AgentsFlow.from_definition(_make_linear_def(), agent_registry=reg)
        nodes = flow._materialize_nodes()
        # All three node IDs present.
        assert "start" in nodes
        assert "n1" in nodes
        assert "n2" in nodes

    def test_materialize_agent_node_has_correct_agent(self) -> None:
        reg = _make_stub_registry()
        flow = AgentsFlow.from_definition(_make_linear_def(), agent_registry=reg)
        nodes = flow._materialize_nodes()
        assert nodes["n1"].agent.name == "agent_a"
        assert nodes["n2"].agent.name == "agent_b"

    def test_materialize_wires_dependencies(self) -> None:
        reg = _make_stub_registry()
        flow = AgentsFlow.from_definition(_make_linear_def(), agent_registry=reg)
        nodes = flow._materialize_nodes()
        # n1 depends on start; n2 depends on n1.
        assert "start" in nodes["n1"].dependencies
        assert "n1" in nodes["n2"].dependencies

    def test_materialize_fresh_fsm_each_call(self) -> None:
        """Each call to _materialize_nodes returns different Node objects."""
        reg = _make_stub_registry()
        flow = AgentsFlow.from_definition(_make_linear_def(), agent_registry=reg)
        nodes1 = flow._materialize_nodes()
        nodes2 = flow._materialize_nodes()
        assert nodes1["n1"] is not nodes2["n1"]  # fresh instances
        assert nodes1["n1"].fsm is not nodes2["n1"].fsm  # independent FSMs
