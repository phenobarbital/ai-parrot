"""
Unit Tests for AgentsFlow
============================
Comprehensive test suite for the FSM-based Agent Crew system.
"""
from datetime import datetime
import asyncio
from unittest.mock import AsyncMock, MagicMock
import pytest


from parrot.bots.orchestration.fsm import (
    AgentsFlow,
    AgentTaskMachine,
    FlowNode,
    FlowTransition,
    TransitionCondition,
    AgentContext
)


# Fixtures
# ========

@pytest.fixture
def mock_agent():
    """Create a mock agent for testing."""
    agent = AsyncMock()
    agent.name = "test_agent"
    agent.tool_manager = MagicMock()
    agent.tool_manager.get_tool = MagicMock(return_value=None)
    agent.configure = AsyncMock()
    agent.ask = AsyncMock(return_value=type('Response', (), {
        'content': 'Test response'
    })())
    return agent


@pytest.fixture
def mock_agents():
    """Create multiple mock agents."""
    agents = {}
    for name in ['agent1', 'agent2', 'agent3']:
        agent = AsyncMock()
        agent.name = name
        agent.tool_manager = MagicMock()
        agent.tool_manager.get_tool = MagicMock(return_value=None)
        agent.configure = AsyncMock()
        agent.ask = AsyncMock(return_value=type('Response', (), {
            'content': f'{name} response'
        })())
        agents[name] = agent
    return agents


@pytest.fixture
def crew():
    """Create an AgentsFlow instance."""
    return AgentsFlow(name="TestCrew")


# Test: State Machine
# ====================

def test_state_machine_initialization():
    """Test AgentTaskMachine initialization."""
    fsm = AgentTaskMachine(agent_name="test")
    assert fsm.current_state == fsm.idle
    assert fsm.agent_name == "test"


def test_state_machine_transitions():
    """Test state machine transitions."""
    fsm = AgentTaskMachine(agent_name="test")

    # idle → ready
    fsm.schedule()
    assert fsm.current_state == fsm.ready

    # ready → running
    fsm.start()
    assert fsm.current_state == fsm.running

    # running → completed
    fsm.succeed()
    assert fsm.current_state == fsm.completed


def test_state_machine_failure():
    """Test failure transitions."""
    fsm = AgentTaskMachine(agent_name="test")

    # Can fail from any state
    fsm.fail()
    assert fsm.current_state == fsm.failed


def test_state_machine_retry():
    """Test retry after failure."""
    fsm = AgentTaskMachine(agent_name="test")

    fsm.schedule()
    fsm.start()
    fsm.fail()
    assert fsm.current_state == fsm.failed

    # Retry brings back to ready
    fsm.retry()
    assert fsm.current_state == fsm.ready


# Test: AgentsFlow Basic Operations
# ====================================

def test_crew_initialization():
    """Test crew initialization."""
    crew = AgentsFlow(name="TestCrew", max_parallel_tasks=5)
    assert crew.name == "TestCrew"
    assert crew.max_parallel_tasks == 5
    assert len(crew.nodes) == 0


def test_add_agent(crew, mock_agent):
    """Test adding an agent to crew."""
    node = crew.add_agent(mock_agent)

    assert isinstance(node, FlowNode)
    assert mock_agent.name in crew.nodes
    assert crew.nodes[mock_agent.name].agent == mock_agent


def test_add_multiple_agents(crew, mock_agents):
    """Test adding multiple agents."""
    for agent in mock_agents.values():
        crew.add_agent(agent)

    assert len(crew.nodes) == 3
    assert all(name in crew.nodes for name in mock_agents.keys())


def test_agent_ref_resolution(crew, mock_agent):
    """Test resolving different agent reference types."""
    crew.add_agent(mock_agent)

    # String reference
    assert crew._resolve_agent_ref("test_agent") == "test_agent"

    # Agent object reference
    assert crew._resolve_agent_ref(mock_agent) == "test_agent"


# Test: Flow Definition
# ======================

def test_task_flow_basic(crew, mock_agents):
    """Test basic task flow definition."""
    crew.add_agent(mock_agents['agent1'])
    crew.add_agent(mock_agents['agent2'])

    crew.task_flow(mock_agents['agent1'], mock_agents['agent2'])

    node1 = crew.nodes['agent1']
    node2 = crew.nodes['agent2']

    assert len(node1.outgoing_transitions) == 1
    assert 'agent2' in node1.outgoing_transitions[0].targets
    assert 'agent1' in node2.dependencies


def test_task_flow_multiple_targets(crew, mock_agents):
    """Test flow with multiple targets (fan-out)."""
    for agent in mock_agents.values():
        crew.add_agent(agent)

    crew.task_flow(
        mock_agents['agent1'],
        [mock_agents['agent2'], mock_agents['agent3']]
    )

    node1 = crew.nodes['agent1']
    assert len(node1.outgoing_transitions) == 1
    assert 'agent2' in node1.outgoing_transitions[0].targets
    assert 'agent3' in node1.outgoing_transitions[0].targets


def test_task_flow_multiple_sources(crew, mock_agents):
    """Test flow with multiple sources (fan-in)."""
    for agent in mock_agents.values():
        crew.add_agent(agent)

    crew.task_flow(
        [mock_agents['agent1'], mock_agents['agent2']],
        mock_agents['agent3']
    )

    node3 = crew.nodes['agent3']
    assert 'agent1' in node3.dependencies
    assert 'agent2' in node3.dependencies


def test_task_flow_with_instruction(crew, mock_agents):
    """Test flow with custom instruction."""
    crew.add_agent(mock_agents['agent1'])
    crew.add_agent(mock_agents['agent2'])

    crew.task_flow(
        mock_agents['agent1'],
        mock_agents['agent2'],
        instruction="Custom instruction for agent2"
    )

    node1 = crew.nodes['agent1']
    transition = node1.outgoing_transitions[0]
    assert transition.instruction == "Custom instruction for agent2"


def test_task_flow_with_prompt_builder(crew, mock_agents):
    """Test flow with prompt builder."""
    crew.add_agent(mock_agents['agent1'])
    crew.add_agent(mock_agents['agent2'])

    def builder(ctx, deps):
        return "Custom prompt"

    crew.task_flow(
        mock_agents['agent1'],
        mock_agents['agent2'],
        prompt_builder=builder
    )

    node1 = crew.nodes['agent1']
    transition = node1.outgoing_transitions[0]
    assert transition.prompt_builder == builder


# Test: Conditional Transitions
# ==============================

def test_on_success_transition(crew, mock_agents):
    """Test ON_SUCCESS transition."""
    crew.add_agent(mock_agents['agent1'])
    crew.add_agent(mock_agents['agent2'])

    crew.on_success(mock_agents['agent1'], mock_agents['agent2'])

    node1 = crew.nodes['agent1']
    transition = node1.outgoing_transitions[0]
    assert transition.condition == TransitionCondition.ON_SUCCESS


def test_on_error_transition(crew, mock_agents):
    """Test ON_ERROR transition."""
    crew.add_agent(mock_agents['agent1'])
    crew.add_agent(mock_agents['agent2'])

    crew.on_error(mock_agents['agent1'], mock_agents['agent2'])

    node1 = crew.nodes['agent1']
    transition = node1.outgoing_transitions[0]
    assert transition.condition == TransitionCondition.ON_ERROR


def test_on_condition_transition(crew, mock_agents):
    """Test ON_CONDITION transition."""
    crew.add_agent(mock_agents['agent1'])
    crew.add_agent(mock_agents['agent2'])

    predicate = lambda result: "success" in result.lower()

    crew.on_condition(
        mock_agents['agent1'],
        mock_agents['agent2'],
        predicate=predicate
    )

    node1 = crew.nodes['agent1']
    transition = node1.outgoing_transitions[0]
    assert transition.condition == TransitionCondition.ON_CONDITION
    assert transition.predicate == predicate


@pytest.mark.asyncio
async def test_transition_activation_on_success():
    """Test transition activation on success."""
    transition = FlowTransition(
        source="agent1",
        targets={"agent2"},
        condition=TransitionCondition.ON_SUCCESS
    )

    # Should activate on success (no error)
    assert await transition.should_activate("result", error=None) is True

    # Should not activate on error
    assert await transition.should_activate("result", error=Exception()) is False


@pytest.mark.asyncio
async def test_transition_activation_on_error():
    """Test transition activation on error."""
    transition = FlowTransition(
        source="agent1",
        targets={"agent2"},
        condition=TransitionCondition.ON_ERROR
    )

    # Should not activate on success
    assert await transition.should_activate("result", error=None) is False

    # Should activate on error
    assert await transition.should_activate("result", error=Exception()) is True


@pytest.mark.asyncio
async def test_transition_activation_on_condition():
    """Test transition activation with predicate."""
    predicate = lambda result: "pass" in result.lower()

    transition = FlowTransition(
        source="agent1",
        targets={"agent2"},
        condition=TransitionCondition.ON_CONDITION,
        predicate=predicate
    )

    assert await transition.should_activate("PASS", error=None) is True
    assert await transition.should_activate("FAIL", error=None) is False


@pytest.mark.asyncio
async def test_transition_activation_async_predicate():
    """Test transition with async predicate."""
    async def async_predicate(result):
        await asyncio.sleep(0.01)
        return "async" in result.lower()

    transition = FlowTransition(
        source="agent1",
        targets={"agent2"},
        condition=TransitionCondition.ON_CONDITION,
        predicate=async_predicate
    )

    assert await transition.should_activate("ASYNC result", error=None) is True
    assert await transition.should_activate("SYNC result", error=None) is False


# Test: Prompt Building
# ======================

@pytest.mark.asyncio
async def test_prompt_builder_static_instruction():
    """Test prompt building with static instruction."""
    transition = FlowTransition(
        source="agent1",
        targets={"agent2"},
        instruction="Static instruction"
    )

    ctx = AgentContext(
        user_id="user1",
        session_id="session1",
        original_query="Original query"
    )

    prompt = await transition.build_prompt(ctx, {})
    assert prompt == "Static instruction"


@pytest.mark.asyncio
async def test_prompt_builder_function():
    """Test prompt building with function."""
    def builder(ctx, deps):
        return f"Query: {ctx.original_query}"

    transition = FlowTransition(
        source="agent1",
        targets={"agent2"},
        prompt_builder=builder
    )

    ctx = AgentContext(
        user_id="user1",
        session_id="session1",
        original_query="Test query"
    )

    prompt = await transition.build_prompt(ctx, {})
    assert prompt == "Query: Test query"


@pytest.mark.asyncio
async def test_prompt_builder_with_dependencies():
    """Test prompt building with dependency results."""
    def builder(ctx, deps):
        agent1_result = deps.get('agent1', 'none')
        return f"Process: {agent1_result}"

    transition = FlowTransition(
        source="agent1",
        targets={"agent2"},
        prompt_builder=builder
    )

    ctx = AgentContext(
        user_id="user1",
        session_id="session1",
        original_query="Test"
    )

    deps = {'agent1': 'Result from agent1'}

    prompt = await transition.build_prompt(ctx, deps)
    assert "Result from agent1" in prompt


@pytest.mark.asyncio
async def test_prompt_builder_async():
    """Test async prompt builder."""
    async def async_builder(ctx, deps):
        await asyncio.sleep(0.01)
        return "Async prompt"

    transition = FlowTransition(
        source="agent1",
        targets={"agent2"},
        prompt_builder=async_builder
    )

    ctx = AgentContext(
        user_id="user1",
        session_id="session1",
        original_query="Test"
    )

    prompt = await transition.build_prompt(ctx, {})
    assert prompt == "Async prompt"


# Test: Workflow Execution
# =========================

@pytest.mark.asyncio
async def test_simple_sequential_execution(crew, mock_agents):
    """Test simple sequential workflow execution."""
    crew.add_agent(mock_agents['agent1'])
    crew.add_agent(mock_agents['agent2'])

    crew.task_flow(mock_agents['agent1'], mock_agents['agent2'])

    result = await crew.run_flow("Test task")

    assert result['success'] is True
    assert 'agent1' in result['completed']
    assert 'agent2' in result['completed']
    assert len(result['completed']) == 2


@pytest.mark.asyncio
async def test_parallel_execution(crew, mock_agents):
    """Test parallel execution of independent agents."""
    # Add three agents with no dependencies (will run in parallel)
    crew.add_agent(mock_agents['agent1'])
    crew.add_agent(mock_agents['agent2'])
    crew.add_agent(mock_agents['agent3'])

    result = await crew.run_flow("Test task")

    assert result['success'] is True
    assert len(result['completed']) == 3


@pytest.mark.asyncio
async def test_fan_out_fan_in(crew, mock_agents):
    """Test fan-out and fan-in pattern."""
    # Create agents
    for agent in mock_agents.values():
        crew.add_agent(agent)

    # agent1 → [agent2, agent3] → final
    final_agent = AsyncMock()
    final_agent.name = "final"
    final_agent.configure = AsyncMock()
    final_agent.ask = AsyncMock(return_value=type('Response', (), {
        'content': 'final result'
    })())
    crew.add_agent(final_agent)

    crew.task_flow(mock_agents['agent1'], [mock_agents['agent2'], mock_agents['agent3']])
    crew.task_flow([mock_agents['agent2'], mock_agents['agent3']], final_agent)

    result = await crew.run_flow("Test task")

    assert result['success'] is True
    assert len(result['completed']) == 4


@pytest.mark.asyncio
async def test_error_handling_transition(crew, mock_agents):
    """Test error handling with ON_ERROR transition."""
    # Make agent2 fail
    failing_agent = AsyncMock()
    failing_agent.name = "failing_agent"
    failing_agent.configure = AsyncMock()
    failing_agent.ask = AsyncMock(side_effect=Exception("Intentional failure"))

    crew.add_agent(mock_agents['agent1'])
    crew.add_agent(failing_agent)
    crew.add_agent(mock_agents['agent2'])  # Error handler

    crew.task_flow(mock_agents['agent1'], failing_agent)
    crew.on_error(failing_agent, mock_agents['agent2'])

    result = await crew.run_flow("Test task")

    assert 'failing_agent' in result['failed']
    assert 'agent2' in result['completed']  # Error handler ran


@pytest.mark.asyncio
async def test_retry_flow_with_error_handler_loop(crew):
    """Ensure retry loops with error handlers don't deadlock the FSM."""

    def build_agent(name, ask_side_effect=None, response_content=None):
        agent = AsyncMock()
        agent.name = name
        agent.tool_manager = MagicMock()
        agent.tool_manager.get_tool = MagicMock(return_value=None)

        async def configure_stub():
            agent.is_configured = True

        agent.is_configured = False
        agent.configure = AsyncMock(side_effect=configure_stub)

        if ask_side_effect is not None:
            agent.ask = AsyncMock(side_effect=ask_side_effect)
        else:
            agent.ask = AsyncMock(return_value=type('Response', (), {
                'content': response_content or f'{name} response'
            })())

        return agent

    researcher = build_agent('researcher', response_content='Research complete')

    analysis_attempts = {'count': 0}

    async def analyzer_execution(*args, **kwargs):
        analysis_attempts['count'] += 1
        if analysis_attempts['count'] == 1:
            raise Exception('Analysis failed')
        return type('Response', (), {'content': 'Analysis success'})()

    analyzer = build_agent('analyzer', ask_side_effect=analyzer_execution)
    writer = build_agent('writer', response_content='Writer done')
    error_handler = build_agent('error_handler', response_content='Error resolved')

    crew.add_agent(researcher)
    crew.add_agent(analyzer)
    crew.add_agent(writer)
    crew.add_agent(error_handler)

    crew.task_flow(researcher, analyzer)
    crew.task_flow(analyzer, writer)
    crew.on_error(analyzer, error_handler, instruction="Fix it")
    crew.task_flow(error_handler, analyzer)

    result = await crew.run_flow('Test retry with handler')

    assert result['success'] is True
    assert 'writer' in result['completed']
    assert analysis_attempts['count'] == 2
    # Error handler should run once and succeed
    assert 'error_handler' in result['completed']


@pytest.mark.asyncio
async def test_retry_logic(crew):
    """Test automatic retry on failure."""
    attempt_count = {'value': 0}

    async def flaky_execution(*args, **kwargs):
        attempt_count['value'] += 1
        if attempt_count['value'] < 3:
            raise Exception(f"Attempt {attempt_count['value']} failed")
        return type('Response', (), {'content': 'Success after retries'})()

    flaky_agent = AsyncMock()
    flaky_agent.name = "flaky"
    flaky_agent.configure = AsyncMock()
    flaky_agent.ask = AsyncMock(side_effect=flaky_execution)

    crew.add_agent(flaky_agent, max_retries=3)

    result = await crew.run_flow("Test task")

    # Should succeed after retries
    assert result['success'] is True
    assert 'flaky' in result['completed']
    assert attempt_count['value'] == 3


# Test: Workflow Validation
# ==========================

@pytest.mark.asyncio
async def test_workflow_validation_success(crew, mock_agents):
    """Test workflow validation with valid flow."""
    crew.add_agent(mock_agents['agent1'])
    crew.add_agent(mock_agents['agent2'])
    crew.task_flow(mock_agents['agent1'], mock_agents['agent2'])

    is_valid = await crew.validate_workflow()
    assert is_valid is True


@pytest.mark.asyncio
async def test_workflow_validation_circular_dependency(crew, mock_agents):
    """Test workflow validation detects circular dependencies."""
    crew.add_agent(mock_agents['agent1'])
    crew.add_agent(mock_agents['agent2'])

    # Create circular dependency
    crew.task_flow(mock_agents['agent1'], mock_agents['agent2'])
    crew.task_flow(mock_agents['agent2'], mock_agents['agent1'])

    with pytest.raises(ValueError, match="Circular dependency"):
        await crew.validate_workflow()


# Test: Visualization and Stats
# ==============================

def test_workflow_visualization(crew, mock_agents):
    """Test workflow visualization generation."""
    crew.add_agent(mock_agents['agent1'])
    crew.add_agent(mock_agents['agent2'])
    crew.task_flow(mock_agents['agent1'], mock_agents['agent2'])

    mermaid = crew.visualize_workflow()

    assert "graph TD" in mermaid
    assert "agent1" in mermaid
    assert "agent2" in mermaid


def test_workflow_stats(crew, mock_agents):
    """Test workflow statistics."""
    crew.add_agent(mock_agents['agent1'])
    crew.add_agent(mock_agents['agent2'])

    stats = crew.get_workflow_stats()

    assert stats['total_agents'] == 2
    assert 'states' in stats


# Test: Edge Cases
# =================

@pytest.mark.asyncio
async def test_empty_workflow():
    """Test execution with no agents."""
    crew = AgentsFlow()

    with pytest.raises(ValueError, match="No entry point"):
        await crew.run_flow("Test task")


@pytest.mark.asyncio
async def test_workflow_timeout(crew, mock_agents):
    """Test workflow execution timeout."""
    slow_agent = AsyncMock()
    slow_agent.name = "slow"
    slow_agent.configure = AsyncMock()

    async def slow_execution(*args, **kwargs):
        await asyncio.sleep(2)
        return type('Response', (), {'content': 'Done'})()

    slow_agent.ask = AsyncMock(side_effect=slow_execution)

    crew_with_timeout = AgentsFlow(execution_timeout=0.5)
    crew_with_timeout.add_agent(slow_agent)

    with pytest.raises(TimeoutError):
        await crew_with_timeout.run_flow("Test task")


@pytest.mark.asyncio
async def test_max_iterations_exceeded(crew, mock_agents):
    """Test workflow exceeding max iterations."""
    # Create a workflow that can never complete
    crew.add_agent(mock_agents['agent1'])
    crew.add_agent(mock_agents['agent2'])

    # Both agents depend on each other (impossible to satisfy)
    crew.nodes['agent1'].dependencies.add('agent2')
    crew.nodes['agent2'].dependencies.add('agent1')

    with pytest.raises(RuntimeError, match="max iterations"):
        await crew.run_flow("Test task", max_iterations=5)


# Test: Priority-Based Transitions
# =================================

def test_transition_priority_ordering(crew, mock_agents):
    """Test that transitions are ordered by priority."""
    crew.add_agent(mock_agents['agent1'])
    crew.add_agent(mock_agents['agent2'])
    crew.add_agent(mock_agents['agent3'])

    # Add transitions with different priorities
    crew.task_flow(mock_agents['agent1'], mock_agents['agent2'], priority=5)
    crew.task_flow(mock_agents['agent1'], mock_agents['agent3'], priority=10)

    node = crew.nodes['agent1']

    # Higher priority should come first
    assert node.outgoing_transitions[0].priority == 10
    assert node.outgoing_transitions[1].priority == 5


if __name__ == "__main__":
    # Run tests with pytest
    pytest.main([__file__, "-v", "--tb=short"])
