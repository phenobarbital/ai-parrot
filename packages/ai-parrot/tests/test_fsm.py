"""Unit Tests for canonical FSM primitives (FEAT-196 TASK-1314 rewrite).

Rewrites the legacy test_fsm.py (which imported from the deleted
parrot.bots.flow.fsm) against the canonical components:
  - parrot.bots.flows.core.fsm.AgentTaskMachine
  - parrot.bots.flows.core.fsm.TransitionCondition
  - parrot.bots.flows.core.transition.FlowTransition
  - parrot.bots.flows.flow.flow.AgentsFlow (new DAG executor)
  - parrot.bots.flows.core.node.StartNode, EndNode, AgentNode
"""
import asyncio
from unittest.mock import AsyncMock, MagicMock
import pytest

from parrot.bots.flows.core.fsm import AgentTaskMachine, TransitionCondition
from parrot.bots.flows.core.transition import FlowTransition
from parrot.bots.flows.core.node import StartNode, EndNode, AgentNode
from parrot.bots.flows.flow.flow import AgentsFlow


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def fsm():
    """Create an AgentTaskMachine instance."""
    return AgentTaskMachine(agent_name="test_agent")


@pytest.fixture
def agentsflow():
    """Create a new AgentsFlow instance."""
    return AgentsFlow(name="TestFlow")


# ---------------------------------------------------------------------------
# Test: AgentTaskMachine (FSM)
# ---------------------------------------------------------------------------


def test_state_machine_initialization(fsm):
    """AgentTaskMachine initialises in idle state."""
    assert fsm.current_state == fsm.idle
    assert fsm.agent_name == "test_agent"


def test_state_machine_transitions_idle_to_completed(fsm):
    """AgentTaskMachine transitions idle -> ready -> running -> completed."""
    fsm.schedule()
    assert fsm.current_state == fsm.ready

    fsm.start()
    assert fsm.current_state == fsm.running

    fsm.succeed()
    assert fsm.current_state == fsm.completed


def test_state_machine_failure(fsm):
    """AgentTaskMachine transitions to failed on fail()."""
    fsm.fail()
    assert fsm.current_state == fsm.failed


def test_state_machine_retry_after_failure(fsm):
    """AgentTaskMachine: failed -> retry -> ready."""
    fsm.schedule()
    fsm.start()
    fsm.fail()
    assert fsm.current_state == fsm.failed

    fsm.retry()
    assert fsm.current_state == fsm.ready


def test_state_machine_with_name():
    """AgentTaskMachine stores the agent_name."""
    m = AgentTaskMachine(agent_name="my_agent")
    assert m.agent_name == "my_agent"


def test_transition_condition_enum_values():
    """TransitionCondition has expected enum members."""
    assert hasattr(TransitionCondition, "ALWAYS")
    assert hasattr(TransitionCondition, "ON_SUCCESS")
    assert hasattr(TransitionCondition, "ON_ERROR")
    assert hasattr(TransitionCondition, "ON_CONDITION")


# ---------------------------------------------------------------------------
# Test: FlowTransition
# ---------------------------------------------------------------------------


def test_flow_transition_creation():
    """FlowTransition can be created with source, targets and condition."""
    t = FlowTransition(
        source="agent_a",
        targets={"agent_b"},
        condition=TransitionCondition.ALWAYS,
    )
    assert t.source == "agent_a"
    assert "agent_b" in t.targets
    assert t.condition == TransitionCondition.ALWAYS


def test_flow_transition_default_condition():
    """FlowTransition defaults to ON_SUCCESS condition."""
    t = FlowTransition(source="agent_a", targets={"agent_x"})
    assert t.condition == TransitionCondition.ON_SUCCESS


def test_flow_transition_multiple_targets():
    """FlowTransition supports multiple targets (fan-out)."""
    t = FlowTransition(source="agent_a", targets={"a", "b", "c"})
    assert len(t.targets) == 3
    assert "a" in t.targets
    assert "b" in t.targets
    assert "c" in t.targets


# ---------------------------------------------------------------------------
# Test: StartNode / EndNode
# ---------------------------------------------------------------------------


def test_start_node_instantiation():
    """StartNode is instantiable with a node_id."""
    node = StartNode(node_id="start")
    assert node.node_id == "start"
    assert node.name == "start"


def test_end_node_instantiation():
    """EndNode is instantiable with a node_id."""
    node = EndNode(node_id="end")
    assert node.node_id == "end"
    assert node.name == "end"


def test_start_end_node_inherit_node():
    """StartNode and EndNode are Node subclasses."""
    from parrot.bots.flows.core.node import Node  # noqa: PLC0415
    assert issubclass(StartNode, Node)
    assert issubclass(EndNode, Node)


# ---------------------------------------------------------------------------
# Test: AgentsFlow (new DAG executor)
# ---------------------------------------------------------------------------


def test_agentsflow_creation(agentsflow):
    """AgentsFlow initialises with name and empty node set."""
    assert agentsflow.name == "TestFlow"
    assert len(agentsflow._nodes) == 0


def test_agentsflow_add_node(agentsflow):
    """AgentsFlow.add_node() registers a Node instance."""
    node = StartNode(node_id="test_start")
    agentsflow.add_node(node)
    assert "test_start" in agentsflow._nodes


def test_agentsflow_add_multiple_nodes(agentsflow):
    """AgentsFlow.add_node() handles multiple nodes."""
    agentsflow.add_node(StartNode(node_id="n1"))
    agentsflow.add_node(EndNode(node_id="n2"))
    agentsflow.add_node(StartNode(node_id="n3"))
    assert len(agentsflow._nodes) == 3


def test_agentsflow_add_duplicate_node_raises(agentsflow):
    """add_node() raises ValueError for a duplicate node_id."""
    agentsflow.add_node(StartNode(node_id="dup"))
    with pytest.raises(ValueError, match="already added"):
        agentsflow.add_node(StartNode(node_id="dup"))


def test_agentsflow_name_stored(agentsflow):
    """AgentsFlow.name is stored correctly."""
    assert agentsflow.name == "TestFlow"


def test_agentsflow_imports_clean():
    """AgentsFlow imports succeed without legacy parrot.bots.flow.fsm."""
    from parrot.bots.flows.flow.flow import AgentsFlow as _AF  # noqa: PLC0415
    assert _AF is not None


def test_agentsflow_core_node_imports():
    """Canonical node types are importable without legacy paths."""
    from parrot.bots.flows.core.node import (  # noqa: PLC0415
        Node, AgentNode, StartNode, EndNode,
    )
    assert Node is not None
    assert AgentNode is not None
    assert StartNode is not None
    assert EndNode is not None


@pytest.mark.asyncio
async def test_agentsflow_run_empty_flow():
    """AgentsFlow.run_flow() returns a FlowResult even for an empty flow."""
    from parrot.bots.flows.core.result import FlowResult  # noqa: PLC0415
    flow = AgentsFlow(name="EmptyFlow")
    result = await flow.run_flow()
    assert isinstance(result, FlowResult)
