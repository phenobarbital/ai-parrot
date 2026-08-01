"""Tests for AgentsFlow.to_definition() / FlowContext.to_snapshot() (TASK-2052).

Covers the flow-layer half of Module 7: programmatic graph → FlowDefinition
export (round-trip via from_definition), unregistered-node/callable-predicate
export errors, and the FlowContext → ContextSnapshot mapping.
"""
import pytest
from parrot.bots.flows.core.checkpoint import FlowNotExportableError
from parrot.bots.flows.core.checkpoint.serializer import FlowStateSerializer
from parrot.bots.flows.core.context import FlowContext
from parrot.bots.flows.core.node import AgentNode, EndNode, Node, StartNode
from parrot.bots.flows.core.result import NodeExecutionInfo
from parrot.bots.flows.flow.definition import FlowMetadata
from parrot.bots.flows.flow.flow import AgentsFlow

# ---------------------------------------------------------------------------
# Stubs (mirrors packages/ai-parrot/tests/bots/flows/test_from_definition.py)
# ---------------------------------------------------------------------------


class FakeAgent:
    """Minimal AgentLike stub."""

    def __init__(self, name: str) -> None:
        self._name = name

    @property
    def name(self) -> str:
        return self._name

    async def invoke(self, prompt: str, **kwargs: object) -> object:
        return "ok"

    async def ask(self, question: str = "", **kwargs: object) -> object:
        return type("R", (), {"content": "ok"})()


class StubRegistry:
    """Minimal AgentRegistry stub using get_bot_instance (sync)."""

    def __init__(self, agents: dict) -> None:
        self._agents = agents

    def get_bot_instance(self, name: str) -> object:
        return self._agents.get(name)


class RogueNode(Node):
    """An unregistered custom Node subclass — never in NODE_REGISTRY."""

    @property
    def name(self) -> str:
        return self.node_id

    async def execute(self, ctx, deps, **kwargs):
        return None


# ---------------------------------------------------------------------------
# to_definition() — round-trip
# ---------------------------------------------------------------------------


def _make_programmatic_flow(agent: FakeAgent) -> AgentsFlow:
    flow = AgentsFlow(name="prog-flow")
    flow.add_node(StartNode(node_id="start"))
    flow.add_node(AgentNode(agent=agent, node_id="worker"))
    flow.add_node(EndNode(node_id="end"))
    flow.add_edge("start", "worker", condition="always")
    flow.add_edge("worker", "end", condition="on_success")
    return flow


def test_to_definition_roundtrip():
    agent = FakeAgent("agent_a")
    flow = _make_programmatic_flow(agent)

    definition = flow.to_definition()

    assert definition.flow == "prog-flow"
    assert {n.id for n in definition.nodes} == {"start", "worker", "end"}

    node_by_id = {n.id: n for n in definition.nodes}
    assert node_by_id["start"].type == "start"
    assert node_by_id["worker"].type == "agent"
    assert node_by_id["worker"].agent_ref == "agent_a"
    assert node_by_id["end"].type == "end"

    edge_pairs = {(e.from_, e.to, e.condition) for e in definition.edges}
    assert ("start", "worker", "always") in edge_pairs
    assert ("worker", "end", "on_success") in edge_pairs

    registry = StubRegistry({"agent_a": agent})
    rebuilt = AgentsFlow.from_definition(definition, agent_registry=registry)
    materialized = rebuilt._materialize_nodes()

    assert set(materialized) == {"start", "worker", "end"}
    assert materialized["worker"].dependencies == {"start"}
    assert materialized["end"].dependencies == {"worker"}
    assert materialized["start"].successors == {"worker"}


def test_to_definition_is_pure_export_no_mutation():
    agent = FakeAgent("agent_a")
    flow = _make_programmatic_flow(agent)
    nodes_before = dict(flow._nodes)
    edges_before = list(flow._edges)

    flow.to_definition()

    assert flow._nodes == nodes_before
    assert flow._edges == edges_before


def test_to_definition_returns_bound_definition_unchanged():
    agent = FakeAgent("agent_a")
    flow = _make_programmatic_flow(agent)
    definition = flow.to_definition()

    registry = StubRegistry({"agent_a": agent})
    rebuilt = AgentsFlow.from_definition(definition, agent_registry=registry)

    # A definition-bound flow's to_definition() returns the bound definition
    # unchanged (no re-derivation from empty _nodes/_edges).
    assert rebuilt.to_definition() is definition


def test_to_definition_unregistered_node_raises():
    flow = AgentsFlow(name="rogue-flow")
    flow.add_node(RogueNode(node_id="rogue"))

    with pytest.raises(FlowNotExportableError, match="rogue"):
        flow.to_definition()


def test_to_definition_agent_without_resolvable_name_raises():
    class NamelessAgent:
        name = None

        async def invoke(self, prompt, **kwargs):
            return "ok"

    flow = AgentsFlow(name="nameless-flow")
    flow.add_node(AgentNode(agent=NamelessAgent(), node_id="worker"))

    with pytest.raises(FlowNotExportableError, match="worker"):
        flow.to_definition()


def test_to_definition_callable_predicate_raises():
    flow = AgentsFlow(name="callable-predicate-flow")
    flow.add_node(StartNode(node_id="start"))
    flow.add_node(EndNode(node_id="end"))
    flow.add_edge("start", "end", predicate=lambda result: True)

    with pytest.raises(FlowNotExportableError, match="callable"):
        flow.to_definition()


# ---------------------------------------------------------------------------
# FlowContext.to_snapshot()
# ---------------------------------------------------------------------------


@pytest.fixture
def serializer() -> FlowStateSerializer:
    return FlowStateSerializer()


@pytest.fixture
def flow_context() -> FlowContext:
    ctx = FlowContext(initial_task="do the thing")
    ctx.mark_completed(
        "node-a",
        result={"answer": 42},
        response="raw-response",
        metadata=NodeExecutionInfo(
            node_id="node-a", node_name="node-a", status="completed"
        ),
    )
    ctx.mark_failed("node-b", ValueError("boom"))
    ctx.shared_data["foo"] = "bar"
    return ctx


def test_context_snapshot_excludes_runtime_bindings(flow_context, serializer):
    snap = flow_context.to_snapshot(serializer=serializer)
    assert not hasattr(snap, "agent_registry")
    assert not hasattr(snap, "synthesis_client")
    assert not hasattr(snap, "trace_context")


def test_context_snapshot_maps_fields(flow_context, serializer):
    snap = flow_context.to_snapshot(serializer=serializer)

    assert snap.initial_task == "do the thing"
    assert snap.results.get("node-a") == {"answer": 42}
    assert snap.responses is None  # default: results-only
    assert snap.completed_tasks == ["node-a"]
    assert snap.completion_order == ["node-a"]
    assert snap.shared_data == {"foo": "bar"}
    assert snap.errors["node-b"]["type"] == "ValueError"
    assert snap.errors["node-b"]["message"] == "boom"


def test_context_snapshot_include_responses(flow_context, serializer):
    snap = flow_context.to_snapshot(serializer=serializer, include_responses=True)
    assert snap.responses is not None
    assert snap.responses.get("node-a") == "raw-response"


# ---------------------------------------------------------------------------
# FlowMetadata checkpoint block — backwards compatibility
# ---------------------------------------------------------------------------


def test_flow_metadata_checkpoint_defaults_are_backwards_compatible():
    meta = FlowMetadata()
    assert meta.checkpoint is False
    assert meta.checkpoint_retention is None
    assert meta.checkpoint_history is None
    assert meta.checkpoint_include_responses is False
    assert meta.durable is False


def test_flow_metadata_checkpoint_block_configurable():
    meta = FlowMetadata(
        checkpoint=True,
        checkpoint_retention=3600,
        checkpoint_history=5,
        checkpoint_include_responses=True,
        durable=True,
    )
    assert meta.checkpoint is True
    assert meta.checkpoint_retention == 3600
    assert meta.checkpoint_history == 5
    assert meta.checkpoint_include_responses is True
    assert meta.durable is True
