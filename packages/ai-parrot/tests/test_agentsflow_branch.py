"""Tests for AgentsFlow DAG construction and FSM state transitions (FEAT-196 TASK-1314 rewrite).

Rewrites the legacy test_agentsflow_branch.py (which tested the old AgentsFlow API
from deleted parrot.bots.flow.fsm) against the canonical components:
  - parrot.bots.flows.flow.flow.AgentsFlow (new DAG executor with add_node())
  - parrot.bots.flows.core.fsm.AgentTaskMachine + TransitionCondition
  - parrot.bots.flows.core.node.StartNode, EndNode, AgentNode

Key difference: new AgentsFlow uses add_node(Node) not add_agent(agent).
"""
import pytest
from unittest.mock import MagicMock

from parrot.bots.flows.core.fsm import AgentTaskMachine, TransitionCondition
from parrot.bots.flows.core.node import StartNode, EndNode
from parrot.bots.flows.flow.flow import AgentsFlow


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


class TestAgentsFlowConstruction:
    """Unit tests for AgentsFlow graph construction."""

    def _make_flow(self):
        return AgentsFlow(name="test")

    def test_flow_starts_empty(self):
        """AgentsFlow starts with no nodes."""
        flow = self._make_flow()
        assert len(flow._nodes) == 0

    def test_add_node_registers_node(self):
        """add_node() registers a Node instance by node_id."""
        flow = self._make_flow()
        start = StartNode(node_id="start")
        flow.add_node(start)
        assert "start" in flow._nodes

    def test_add_duplicate_node_raises(self):
        """add_node() raises ValueError if node_id already registered."""
        flow = self._make_flow()
        start = StartNode(node_id="start")
        flow.add_node(start)
        with pytest.raises(ValueError, match="already added"):
            flow.add_node(StartNode(node_id="start"))

    def test_flow_name_stored(self):
        """AgentsFlow.name is stored correctly."""
        flow = AgentsFlow(name="MyFlow")
        assert flow.name == "MyFlow"

    def test_add_multiple_nodes(self):
        """add_node() handles multiple distinct nodes."""
        flow = self._make_flow()
        flow.add_node(StartNode(node_id="start"))
        flow.add_node(EndNode(node_id="end"))
        assert len(flow._nodes) == 2
        assert "start" in flow._nodes
        assert "end" in flow._nodes


class TestAgentTaskMachineInBranchedFlow:
    """Tests for AgentTaskMachine FSM behavior as used in branched flows."""

    def _new_fsm(self, name: str) -> AgentTaskMachine:
        return AgentTaskMachine(agent_name=name)

    def test_fsm_idle_by_default(self):
        """AgentTaskMachine starts in idle state."""
        fsm = self._new_fsm("A")
        assert fsm.current_state == fsm.idle

    def test_fsm_succeed_path(self):
        """AgentTaskMachine can go idle→ready→running→completed."""
        fsm = self._new_fsm("A")
        fsm.schedule()
        fsm.start()
        fsm.succeed()
        assert fsm.current_state == fsm.completed

    def test_fsm_fail_path(self):
        """AgentTaskMachine can fail from any state."""
        fsm = self._new_fsm("B")
        fsm.fail()
        assert fsm.current_state == fsm.failed

    def test_fsm_retry_after_failure(self):
        """AgentTaskMachine can retry after failure."""
        fsm = self._new_fsm("C")
        fsm.schedule()
        fsm.start()
        fsm.fail()
        fsm.retry()
        assert fsm.current_state == fsm.ready


class TestTransitionCondition:
    """Tests for TransitionCondition enum values."""

    def test_always_exists(self):
        assert hasattr(TransitionCondition, "ALWAYS")

    def test_on_success_exists(self):
        assert hasattr(TransitionCondition, "ON_SUCCESS")

    def test_on_error_exists(self):
        assert hasattr(TransitionCondition, "ON_ERROR")

    def test_on_condition_exists(self):
        """ON_CONDITION (predicate-based) is available."""
        assert hasattr(TransitionCondition, "ON_CONDITION")


class TestAgentsFlowNodes:
    """Tests that StartNode and EndNode work with AgentsFlow."""

    def test_start_node_can_be_added(self):
        """StartNode can be registered in AgentsFlow."""
        flow = AgentsFlow(name="t")
        flow.add_node(StartNode(node_id="__start__"))
        assert "__start__" in flow._nodes

    def test_end_node_can_be_added(self):
        """EndNode can be registered in AgentsFlow."""
        flow = AgentsFlow(name="t")
        flow.add_node(EndNode(node_id="__end__"))
        assert "__end__" in flow._nodes

    def test_start_end_node_types_correct(self):
        """StartNode and EndNode are distinct types."""
        assert StartNode is not EndNode

    def test_nodes_registry_with_start_and_end(self):
        """Flow with start and end nodes has exactly 2 nodes."""
        flow = AgentsFlow(name="t")
        flow.add_node(StartNode(node_id="s"))
        flow.add_node(EndNode(node_id="e"))
        assert len(flow._nodes) == 2


@pytest.mark.asyncio
async def test_agentsflow_run_returns_flowresult():
    """AgentsFlow.run_flow() returns a FlowResult for an empty flow."""
    from parrot.bots.flows.core.result import FlowResult  # noqa: PLC0415
    flow = AgentsFlow(name="BranchTest")
    result = await flow.run_flow("test")
    assert isinstance(result, FlowResult)
