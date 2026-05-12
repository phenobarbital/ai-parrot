"""Unit tests for NODE_REGISTRY, @register_node, AgentsFlow skeleton, CompletionEvent.

FEAT-163 TASK-1065 acceptance criteria:
- NODE_REGISTRY["agent"] is AgentNode.
- NODE_REGISTRY["start"] is StartNode.
- NODE_REGISTRY["end"] is EndNode.
- register_node raises ValueError on duplicate.
- register_node raises TypeError for non-Node class.
- AgentsFlow.add_node stores node by node_id.
- Duplicate node_id raises ValueError.
- run_flow raises NotImplementedError("TASK-1067").
- from_definition raises NotImplementedError("TASK-1068").
- AgentsFlow inherits PersistenceMixin, NOT SynthesisMixin.
- CompletionEvent constructs correctly.
"""
import pytest

from parrot.bots.flows.flow import (
    AgentsFlow,
    CompletionEvent,
    NODE_REGISTRY,
    register_node,
)
from parrot.bots.flows.core.node import AgentNode, EndNode, Node, StartNode
from parrot.bots.flows.core.storage import PersistenceMixin, SynthesisMixin


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class FakeAgent:
    """Minimal AgentLike for tests — @property name required by AgentLike protocol."""

    @property
    def name(self) -> str:
        return "fake"

    async def invoke(self, prompt: str, **kwargs: object) -> object:
        return prompt

    async def ask(self, question: str = "", **kwargs: object) -> object:
        return question


# ---------------------------------------------------------------------------
# NODE_REGISTRY
# ---------------------------------------------------------------------------


class TestNodeRegistry:
    def test_agent_type_registered(self) -> None:
        assert NODE_REGISTRY["agent"] is AgentNode

    def test_start_type_registered(self) -> None:
        assert NODE_REGISTRY["start"] is StartNode

    def test_end_type_registered(self) -> None:
        assert NODE_REGISTRY["end"] is EndNode

    def test_register_node_decorator_works(self) -> None:
        @register_node("custom-test-type-1065")
        class CustomNode(Node):
            @property
            def name(self) -> str:
                return "custom"

        assert NODE_REGISTRY["custom-test-type-1065"] is CustomNode
        # Cleanup so repeated test runs don't pollute the registry.
        del NODE_REGISTRY["custom-test-type-1065"]

    def test_register_node_rejects_duplicate(self) -> None:
        with pytest.raises(ValueError, match="already registered"):
            register_node("agent")(AgentNode)  # "agent" is already taken

    def test_register_node_rejects_non_node_class(self) -> None:
        with pytest.raises(TypeError):
            register_node("bogus-test-1065")(int)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# AgentsFlow skeleton
# ---------------------------------------------------------------------------


class TestAgentsFlowInheritance:
    def test_inherits_persistence_mixin(self) -> None:
        assert issubclass(AgentsFlow, PersistenceMixin)

    def test_does_not_inherit_synthesis_mixin(self) -> None:
        assert not issubclass(AgentsFlow, SynthesisMixin)


class TestAgentsFlowAddNode:
    def test_add_node_stores_by_node_id(self) -> None:
        flow = AgentsFlow("test-add")
        node = AgentNode(agent=FakeAgent(), node_id="n1")
        flow.add_node(node)
        assert flow._nodes["n1"] is node

    def test_add_node_duplicate_raises(self) -> None:
        flow = AgentsFlow("test-dup")
        node1 = AgentNode(agent=FakeAgent(), node_id="dup")
        node2 = AgentNode(agent=FakeAgent(), node_id="dup")
        flow.add_node(node1)
        with pytest.raises(ValueError, match="already added"):
            flow.add_node(node2)


class TestAgentsFlowPlaceholders:
    async def test_run_flow_raises_not_implemented(self) -> None:
        flow = AgentsFlow("test-run")
        with pytest.raises(NotImplementedError, match="TASK-1067"):
            await flow.run_flow()

    def test_from_definition_raises_not_implemented(self) -> None:
        with pytest.raises(NotImplementedError, match="TASK-1068"):
            AgentsFlow.from_definition(None)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# CompletionEvent
# ---------------------------------------------------------------------------


class TestCompletionEvent:
    def test_construct_with_result(self) -> None:
        ev = CompletionEvent(node_id="n1", result="output")
        assert ev.node_id == "n1"
        assert ev.result == "output"
        assert ev.error is None

    def test_construct_with_error(self) -> None:
        err = RuntimeError("boom")
        ev = CompletionEvent(node_id="n2", error=err)
        assert ev.error is err
        assert ev.result is None

    def test_default_result_and_error_none(self) -> None:
        ev = CompletionEvent(node_id="n3")
        assert ev.result is None
        assert ev.error is None
