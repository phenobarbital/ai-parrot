"""Tests for AutonomousOrchestrator HITL interrupt handling.

Covers:
- Legacy interrupt handling (pre-existing tests)
- policy_id short-circuit in _execute and resume_agent (TASK-1284)
"""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime

from parrot.core.exceptions import HumanInteractionInterrupt
from parrot.autonomous.orchestrator import AutonomousOrchestrator, ExecutionRequest, ExecutionTarget, ExecutionResult
from parrot.human.models import InteractionResult, InteractionStatus
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


# ── TASK-1284: policy_id short-circuit tests ─────────────────────────────────


def _make_hitl_result(msg: str) -> InteractionResult:
    return InteractionResult(
        interaction_id="iid-sc",
        status=InteractionStatus.COMPLETED,
        consolidated_value="done",
        action_metadata={"message": msg},
    )


class TestPolicyIdShortCircuit:
    """Tests for the manager-result short-circuit added in TASK-1284."""

    @pytest.mark.asyncio
    async def test_execute_returns_message_when_result_exists(self, orchestrator, mock_agent):
        """_execute short-circuits and returns action_metadata message immediately."""
        interrupt = HumanInteractionInterrupt(
            "Deploy prod?",
            interaction_id="iid-sc",
            policy_id="pol-1",
        )
        mock_agent.ask.side_effect = interrupt

        mock_mgr = AsyncMock()
        mock_mgr.get_result = AsyncMock(return_value=_make_hitl_result("Ticket TKT-1 opened."))

        request = ExecutionRequest(
            target_type=ExecutionTarget.AGENT,
            target_id="test_agent",
            task="Deploy",
            session_id="s1",
        )

        with patch("parrot.human.get_default_human_manager", return_value=mock_mgr):
            result = await orchestrator._execute(request)

        assert result.success is True
        assert result.result == "Ticket TKT-1 opened."
        assert result.metadata.get("hitl_short_circuit") is True

    @pytest.mark.asyncio
    async def test_execute_falls_back_to_suspend_when_no_result(self, orchestrator, mock_agent):
        """_execute falls back to suspend when manager returns None."""
        interrupt = HumanInteractionInterrupt(
            "Deploy prod?",
            interaction_id="iid-sc",
            policy_id="pol-1",
        )
        mock_agent.ask.side_effect = interrupt

        mock_mgr = AsyncMock()
        mock_mgr.get_result = AsyncMock(return_value=None)

        request = ExecutionRequest(
            target_type=ExecutionTarget.AGENT,
            target_id="test_agent",
            task="Deploy",
            session_id="s1",
        )

        with patch("parrot.human.get_default_human_manager", return_value=mock_mgr):
            result = await orchestrator._execute(request)

        assert result.success is False
        assert result.metadata["status"] == "paused"

    @pytest.mark.asyncio
    async def test_legacy_interrupt_without_policy_id_still_suspends(self, orchestrator, mock_agent):
        """Interrupt without policy_id bypasses short-circuit entirely."""
        interrupt = HumanInteractionInterrupt("Legacy prompt")
        mock_agent.ask.side_effect = interrupt

        request = ExecutionRequest(
            target_type=ExecutionTarget.AGENT,
            target_id="test_agent",
            task="Do work",
            session_id="s2",
        )

        # No patch needed — policy_id is None so short-circuit branch skipped
        result = await orchestrator._execute(request)

        assert result.success is False
        assert result.metadata["status"] == "paused"

    @pytest.mark.asyncio
    async def test_short_circuit_exception_does_not_crash(self, orchestrator, mock_agent, caplog):
        """Exception inside short-circuit branch logs and falls through to suspend."""
        interrupt = HumanInteractionInterrupt(
            "Deploy?",
            interaction_id="iid-err",
            policy_id="pol-err",
        )
        mock_agent.ask.side_effect = interrupt

        mock_mgr = AsyncMock()
        mock_mgr.get_result = AsyncMock(side_effect=RuntimeError("Redis down"))

        request = ExecutionRequest(
            target_type=ExecutionTarget.AGENT,
            target_id="test_agent",
            task="Deploy",
            session_id="s3",
        )

        import logging
        with patch("parrot.human.get_default_human_manager", return_value=mock_mgr):
            with caplog.at_level(logging.ERROR):
                result = await orchestrator._execute(request)

        # Must not crash — falls through to suspend
        assert result.success is False
        assert result.metadata["status"] == "paused"

    @pytest.mark.asyncio
    async def test_resume_agent_short_circuits_on_policy_id_result(self, orchestrator, mock_agent):
        """resume_agent also short-circuits when a result exists in the manager."""
        interrupt = HumanInteractionInterrupt(
            "Still waiting?",
            interaction_id="iid-r",
            policy_id="pol-r",
        )
        mock_agent.resume.side_effect = interrupt

        mock_mgr = AsyncMock()
        mock_mgr.get_result = AsyncMock(return_value=_make_hitl_result("Auto-approved by policy."))

        state = {
            "session_id": "s4",
            "tool_call_id": "call_x",
            "agent_name": "test_agent",
            "messages": [],
        }

        with patch("parrot.human.get_default_human_manager", return_value=mock_mgr):
            result = await orchestrator.resume_agent("s4", "yes", state)

        assert result.success is True
        assert result.result == "Auto-approved by policy."
        assert result.metadata.get("hitl_short_circuit") is True
