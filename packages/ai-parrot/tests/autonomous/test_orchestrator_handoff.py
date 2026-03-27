import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime

from parrot.core.exceptions import HumanInteractionInterrupt
from parrot.autonomous.orchestrator import AutonomousOrchestrator, ExecutionRequest, ExecutionTarget, ExecutionResult
from parrot.models.responses import AIMessage

@pytest.fixture
def mock_agent():
    agent = AsyncMock()
    agent.resume = AsyncMock()
    return agent

@pytest.fixture
def mock_bot_manager(mock_agent):
    manager = MagicMock()
    manager._bots = {"test_agent": mock_agent}
    return manager

@pytest.fixture
def orchestrator(mock_bot_manager):
    return AutonomousOrchestrator(bot_manager=mock_bot_manager)

@pytest.mark.asyncio
async def test_orchestrator_catches_interrupt_and_returns_paused_state(orchestrator, mock_agent):
    # Setup agent to raise HumanInteractionInterrupt
    interrupt = HumanInteractionInterrupt("Need your approval", "Please confirm.")
    interrupt.session_id = "test-session"
    interrupt.tool_call_id = "call_abc"
    interrupt.agent_name = "test_agent"
    interrupt.messages = [{"role": "user", "content": "hello"}]
    mock_agent.ask.side_effect = interrupt
    
    request = ExecutionRequest(
        target_type=ExecutionTarget.AGENT,
        target_id="test_agent",
        task="Do some work",
        session_id="test-session"
    )
    
    result = await orchestrator._execute(request)
    
    assert result.success is False
    assert result.error == "Waiting for Human Interaction"
    assert result.metadata["status"] == "paused"
    assert result.metadata["prompt"] == "Need your approval"
    assert result.metadata["state"]["session_id"] == "test-session"
    assert result.metadata["state"]["tool_call_id"] == "call_abc"
    assert result.metadata["state"]["agent_name"] == "test_agent"
    assert result.metadata["state"]["messages"] == [{"role": "user", "content": "hello"}]

@pytest.mark.asyncio
async def test_resume_agent_success(orchestrator, mock_agent):
    # Setup agent.resume to return an AIMessage
    mock_agent.resume.return_value = AIMessage(content="Work finished", role="assistant")
    
    state = {
        "session_id": "test-session",
        "tool_call_id": "call_abc",
        "agent_name": "test_agent",
        "messages": []
    }
    
    result = await orchestrator.resume_agent(
        session_id="test-session",
        user_input="Yes, go ahead.",
        state=state
    )
    
    mock_agent.resume.assert_awaited_once_with("test-session", "Yes, go ahead.", state)
    assert result.success is True
    assert result.result.content == "Work finished"
    assert result.target_id == "test_agent"
    assert result.target_type == ExecutionTarget.AGENT

@pytest.mark.asyncio
async def test_resume_agent_missing_agent_name(orchestrator):
    state = {"session_id": "test-session"}
    
    with pytest.raises(ValueError, match="State must contain 'agent_name'"):
        await orchestrator.resume_agent("test-session", "yes", state)

@pytest.mark.asyncio
async def test_resume_agent_catches_interrupt_again(orchestrator, mock_agent):
    # If resuming leads to another handoff
    interrupt = HumanInteractionInterrupt("Need more info", "What is the token?")
    interrupt.session_id = "test-session"
    interrupt.tool_call_id = "call_def"
    interrupt.agent_name = "test_agent"
    interrupt.messages = []
    
    mock_agent.resume.side_effect = interrupt
    
    state = {
        "session_id": "test-session",
        "tool_call_id": "call_abc",
        "agent_name": "test_agent",
        "messages": []
    }
    
    result = await orchestrator.resume_agent(
        session_id="test-session",
        user_input="Yes, go ahead.",
        state=state
    )
    
    assert result.success is False
    assert result.metadata["status"] == "paused"
    assert result.metadata["prompt"] == "Need more info"
    assert result.metadata["state"]["tool_call_id"] == "call_def"
