"""Shared fixtures for flow-primitives test suite (TASK-921)."""
import pytest

from parrot.bots.flows.core import (
    AgentNode,
    FlowContext,
    NodeExecutionInfo,
    AgentTaskMachine,
)


class MockAgent:
    """Minimal AgentLike implementation for tests."""

    @property
    def name(self) -> str:
        return "test-agent"

    async def invoke(self, prompt: str, **kwargs):
        return f"response to: {prompt}"


@pytest.fixture
def mock_agent():
    """Return a mock AgentLike object."""
    return MockAgent()


@pytest.fixture
def agent_node(mock_agent):
    """Return an AgentNode wrapping mock_agent with node_id='node-1'."""
    return AgentNode(agent=mock_agent, node_id="node-1")


@pytest.fixture
def flow_context():
    """Return a FlowContext with initial_task='test task'."""
    return FlowContext(initial_task="test task")


@pytest.fixture
def node_execution_info():
    """Return a sample NodeExecutionInfo."""
    return NodeExecutionInfo(
        node_id="n1",
        node_name="agent-1",
        status="completed",
        execution_time=0.5,
    )
