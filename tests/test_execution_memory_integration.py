"""Unit tests for ExecutionMemory integration with AgentsFlow.

Tests verify that:
- ExecutionMemory is initialized correctly
- ResultRetrievalTool is registered with agents
- Results are automatically stored after execution
- Memory is cleared on each run_flow()
- Memory snapshot is included in CrewResult
"""
import asyncio
import pytest
from typing import Any

from parrot.bots.orchestration import AgentsFlow
from parrot.bots.orchestration.storage import ExecutionMemory
from parrot.bots.orchestration.tools import ResultRetrievalTool


class MockAgent:
    """Mock agent for testing."""

    def __init__(self, name: str, response: str = "Mock response"):
        self.name = name
        self._response = response
        self.is_configured = True
        self.tool_manager = MockToolManager()
        self._tools_registered = []

    async def configure(self):
        """Mock configure method."""
        pass

    async def ask(self, question: str = "", **kwargs):
        """Return mock response."""
        return self._response

    def register_tool(self, tool: Any):
        """Mock tool registration."""
        self._tools_registered.append(tool)


class MockToolManager:
    """Mock tool manager."""

    def __init__(self):
        self._tools = {}

    def add_tool(self, tool: Any, name: str):
        """Mock add tool."""
        self._tools[name] = tool

    def get_tool(self, name: str):
        """Mock get tool."""
        return self._tools.get(name)

    def list_tools(self):
        """Mock list tools."""
        return list(self._tools.keys())


@pytest.mark.asyncio
class TestExecutionMemoryIntegration:
    """Test ExecutionMemory integration with AgentsFlow."""

    async def test_memory_initialized_by_default(self):
        """Test that ExecutionMemory is initialized by default."""
        flow = AgentsFlow(name="test_flow")

        assert flow.enable_execution_memory is True
        assert flow.execution_memory is not None
        assert isinstance(flow.execution_memory, ExecutionMemory)
        assert flow.retrieval_tool is not None
        assert isinstance(flow.retrieval_tool, ResultRetrievalTool)

    async def test_memory_can_be_disabled(self):
        """Test that ExecutionMemory can be disabled."""
        flow = AgentsFlow(name="test_flow", enable_execution_memory=False)

        assert flow.enable_execution_memory is False
        assert flow.execution_memory is None
        assert flow.retrieval_tool is None

    async def test_memory_with_vectorization(self):
        """Test ExecutionMemory initialization with embedding model."""
        # Note: This test doesn't actually load the model,
        # just verifies the parameter is passed
        flow = AgentsFlow(
            name="test_flow",
            embedding_model="all-MiniLM-L6-v2",
            vector_dimension=384,
            vector_index_type="Flat"
        )

        assert flow.execution_memory is not None
        # Embedding model configuration would be tested in ExecutionMemory tests

    async def test_retrieval_tool_registered_with_agent(self):
        """Test that ResultRetrievalTool is registered with agents."""
        flow = AgentsFlow(name="test_flow")
        agent = MockAgent("TestAgent")

        flow.add_agent(agent)

        # Check that tool was registered
        assert len(agent._tools_registered) > 0
        assert any(isinstance(tool, ResultRetrievalTool) for tool in agent._tools_registered)

    async def test_retrieval_tool_not_registered_when_disabled(self):
        """Test that tool is not registered when memory is disabled."""
        flow = AgentsFlow(name="test_flow", enable_execution_memory=False)
        agent = MockAgent("TestAgent")

        flow.add_agent(agent)

        # Check that no retrieval tool was registered
        assert not any(isinstance(tool, ResultRetrievalTool) for tool in agent._tools_registered)

    async def test_result_storage_in_workflow(self):
        """Test that agent results are stored in ExecutionMemory."""
        flow = AgentsFlow(name="test_flow")

        # Create simple workflow: agent1 → agent2
        agent1 = MockAgent("Agent1", "Result from Agent1")
        agent2 = MockAgent("Agent2", "Result from Agent2")

        flow.add_agent(agent1)
        flow.add_agent(agent2)
        flow.task_flow(source=agent1, targets=agent2)

        # Execute workflow
        result = await flow.run_flow("Test input")

        # Verify results are stored in memory
        assert flow.execution_memory is not None
        assert "Agent1" in flow.execution_memory.results
        assert "Agent2" in flow.execution_memory.results

        # Verify execution order
        assert flow.execution_memory.execution_order == ["Agent1", "Agent2"]

        # Verify original query
        assert flow.execution_memory.original_query == "Test input"

        # Verify result content
        agent1_result = flow.execution_memory.get_results_by_agent("Agent1")
        assert agent1_result is not None
        assert "Result from Agent1" in agent1_result.content

    async def test_memory_cleared_on_each_run(self):
        """Test that memory is cleared on each run_flow() call."""
        flow = AgentsFlow(name="test_flow")

        agent = MockAgent("Agent1", "First run")
        flow.add_agent(agent)

        # First run
        await flow.run_flow("First input")
        assert flow.execution_memory.original_query == "First input"
        assert len(flow.execution_memory.results) == 1

        # Second run - memory should be cleared
        agent._response = "Second run"
        await flow.run_flow("Second input")
        assert flow.execution_memory.original_query == "Second input"
        assert len(flow.execution_memory.results) == 1  # Only second run results

    async def test_memory_snapshot_in_result(self):
        """Test that memory snapshot is included in CrewResult."""
        flow = AgentsFlow(name="test_flow")

        agent = MockAgent("Agent1", "Result")
        flow.add_agent(agent)

        result = await flow.run_flow("Test input")

        # Verify metadata includes execution_memory
        assert "execution_memory" in result.metadata
        memory_snapshot = result.metadata["execution_memory"]

        assert memory_snapshot is not None
        assert "original_query" in memory_snapshot
        assert "results" in memory_snapshot
        assert "execution_order" in memory_snapshot
        assert memory_snapshot["original_query"] == "Test input"

    async def test_no_memory_snapshot_when_disabled(self):
        """Test that no memory snapshot when memory disabled."""
        flow = AgentsFlow(name="test_flow", enable_execution_memory=False)

        agent = MockAgent("Agent1", "Result")
        flow.add_agent(agent)

        result = await flow.run_flow("Test input")

        # Verify metadata shows execution_memory as None
        assert "execution_memory" in result.metadata
        assert result.metadata["execution_memory"] is None

    async def test_agent_can_query_previous_results(self):
        """Test that agents can use ResultRetrievalTool to query previous results."""
        flow = AgentsFlow(name="test_flow")

        agent1 = MockAgent("DataCollector", "Collected data: [1, 2, 3]")
        agent2 = MockAgent("Analyzer", "Analysis complete")

        flow.add_agent(agent1)
        flow.add_agent(agent2)
        flow.task_flow(source=agent1, targets=agent2)

        await flow.run_flow("Collect and analyze")

        # Verify agent2 has access to retrieval tool
        retrieval_tool = None
        for tool in agent2._tools_registered:
            if isinstance(tool, ResultRetrievalTool):
                retrieval_tool = tool
                break

        assert retrieval_tool is not None

        # Test tool can list agents
        result = await retrieval_tool._execute(action="list_agents")
        assert "DataCollector" in result
        assert "Analyzer" in result

        # Test tool can get specific result
        result = await retrieval_tool._execute(
            action="get_agent_result",
            agent_id="DataCollector"
        )
        assert "Collected data: [1, 2, 3]" in result

    async def test_execution_metadata_stored(self):
        """Test that execution metadata is stored with results."""
        flow = AgentsFlow(name="test_flow")

        agent = MockAgent("Agent1", "Result")
        flow.add_agent(agent)

        await flow.run_flow("Test")

        agent_result = flow.execution_memory.get_results_by_agent("Agent1")
        assert agent_result is not None
        assert agent_result.metadata is not None
        assert "execution_time" in agent_result.metadata
        assert "execution_count" in agent_result.metadata

    async def test_parallel_execution_all_stored(self):
        """Test that parallel agent executions are all stored."""
        flow = AgentsFlow(name="test_flow")

        # Create fan-out pattern: source → [agent1, agent2, agent3]
        source = MockAgent("Source", "Data")
        agent1 = MockAgent("Agent1", "Result1")
        agent2 = MockAgent("Agent2", "Result2")
        agent3 = MockAgent("Agent3", "Result3")

        flow.add_agent(source)
        flow.add_agent(agent1)
        flow.add_agent(agent2)
        flow.add_agent(agent3)

        flow.task_flow(source=source, targets=[agent1, agent2, agent3])

        await flow.run_flow("Process")

        # All results should be stored
        assert "Source" in flow.execution_memory.results
        assert "Agent1" in flow.execution_memory.results
        assert "Agent2" in flow.execution_memory.results
        assert "Agent3" in flow.execution_memory.results

        # All should be in execution order
        assert len(flow.execution_memory.execution_order) == 4


if __name__ == "__main__":
    # Run tests
    pytest.main([__file__, "-v"])
