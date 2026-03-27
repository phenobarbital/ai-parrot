"""Tests for AgentsFlow branched DAG workflows.

Validates that branched (exclusive-choice) flows complete correctly
when only one branch fires, without getting stuck on unreachable EndNodes.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from parrot.bots.flow.fsm import (
    AgentsFlow,
    FlowNode,
    AgentTaskMachine,
    TransitionCondition,
)
from parrot.bots.flow.nodes import StartNode, EndNode


class FakeAgent:
    """Minimal duck-typed agent for testing."""

    is_configured: bool = True

    def __init__(self, name: str, response: str = "ok"):
        self._name = name
        self._response = response
        self.tool_manager = MagicMock()
        self.tool_manager.list_tools.return_value = []

    @property
    def name(self) -> str:
        return self._name

    async def ask(self, question: str = "", **ctx) -> str:
        return self._response

    async def configure(self) -> None:
        pass


class TestIsUnreachable:
    """Unit tests for _is_unreachable helper."""

    def _make_flow(self):
        return AgentsFlow(name="test", enable_execution_memory=False)

    def test_unreachable_when_deps_done_not_scheduled(self):
        """Node is unreachable if all deps are completed and transitions processed."""
        flow = self._make_flow()
        agent_a = FakeAgent("A")
        agent_b = FakeAgent("B")

        node_a = flow.add_agent(agent_a)
        node_b = flow.add_agent(agent_b)

        # B depends on A
        node_b.dependencies.add("A")

        # A completed and processed transitions (but never scheduled B)
        node_a.fsm = AgentTaskMachine(agent_name="A")
        node_a.fsm.schedule()
        node_a.fsm.start()
        node_a.fsm.succeed()
        node_a.transitions_processed = True

        # B is still idle
        assert node_b.fsm.current_state == node_b.fsm.idle
        assert flow._is_unreachable(node_b) is True

    def test_not_unreachable_when_deps_not_done(self):
        """Node is NOT unreachable if deps haven't finished processing."""
        flow = self._make_flow()
        agent_a = FakeAgent("A")
        agent_b = FakeAgent("B")

        node_a = flow.add_agent(agent_a)
        node_b = flow.add_agent(agent_b)
        node_b.dependencies.add("A")

        # A is still running
        node_a.transitions_processed = False

        assert flow._is_unreachable(node_b) is False

    def test_not_unreachable_when_no_deps(self):
        """Node with no dependencies is never unreachable."""
        flow = self._make_flow()
        agent = FakeAgent("root")
        node = flow.add_agent(agent)
        assert flow._is_unreachable(node) is False


class TestBranchedDAGCompletion:
    """Integration-level tests for branched DAG workflow completion."""

    def _make_flow(self):
        return AgentsFlow(name="test", enable_execution_memory=False)

    def test_workflow_complete_with_unreachable_terminal(self):
        """Workflow completes when one branch's EndNode is unreachable."""
        flow = self._make_flow()

        # Build: start → decision → (pizza_agent → end_pizza | sushi_agent → end_sushi)
        start = StartNode(name="__start__")
        decision = FakeAgent("decision")
        pizza = FakeAgent("pizza")
        sushi = FakeAgent("sushi")
        end_pizza_node = EndNode(name="end_pizza")
        end_sushi_node = EndNode(name="end_sushi")

        flow.add_agent(start, agent_id="__start__")
        flow.add_agent(decision)
        flow.add_agent(pizza)
        flow.add_agent(sushi)
        flow.add_agent(end_pizza_node, agent_id="end_pizza")
        flow.add_agent(end_sushi_node, agent_id="end_sushi")

        # Wire transitions
        flow.task_flow("__start__", "decision", condition=TransitionCondition.ALWAYS)
        flow.task_flow("decision", "pizza", condition=TransitionCondition.ON_CONDITION,
                       predicate=lambda r: True)
        flow.task_flow("decision", "sushi", condition=TransitionCondition.ON_CONDITION,
                       predicate=lambda r: False)
        flow.task_flow("pizza", "end_pizza")
        flow.task_flow("sushi", "end_sushi")

        # Simulate: start, decision, pizza, end_pizza all completed
        for name in ("__start__", "decision", "pizza", "end_pizza"):
            node = flow.nodes[name]
            node.fsm = AgentTaskMachine(agent_name=name)
            node.fsm.schedule()
            node.fsm.start()
            node.fsm.succeed()
            node.transitions_processed = True

        # sushi and end_sushi remain idle (never activated)
        # decision's transitions were processed but sushi predicate returned False
        flow.nodes["sushi"].fsm = AgentTaskMachine(agent_name="sushi")
        flow.nodes["end_sushi"].fsm = AgentTaskMachine(agent_name="end_sushi")

        assert flow._is_workflow_complete() is True

    def test_workflow_not_complete_when_branch_still_running(self):
        """Workflow is NOT complete when a reachable terminal node hasn't finished."""
        flow = self._make_flow()

        pizza = FakeAgent("pizza")
        end_pizza_node = EndNode(name="end_pizza")

        flow.add_agent(pizza)
        flow.add_agent(end_pizza_node, agent_id="end_pizza")
        flow.task_flow("pizza", "end_pizza")

        # pizza completed
        node_pizza = flow.nodes["pizza"]
        node_pizza.fsm = AgentTaskMachine(agent_name="pizza")
        node_pizza.fsm.schedule()
        node_pizza.fsm.start()
        node_pizza.fsm.succeed()
        node_pizza.transitions_processed = True

        # end_pizza is still idle and IS reachable (pizza completed + transitions processed
        # but end_pizza's dep is pizza which completed, so it's reachable — BUT
        # _is_unreachable checks transitions_processed, meaning pizza processed transitions.
        # Since pizza DID complete and has transitions to end_pizza, end_pizza SHOULD have
        # been scheduled. If it's still idle, it means _activate_transition failed or
        # hasn't run yet.
        # For this test: pizza has NOT processed transitions yet.
        node_pizza.transitions_processed = False

        assert flow._is_workflow_complete() is False
