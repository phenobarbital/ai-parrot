"""Tests for AgentCommandHandler — core handlers."""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, PropertyMock, patch


def _make_turn_context(text: str = ""):
    """Build a minimal mock TurnContext for agent command tests."""
    ctx = MagicMock()
    ctx.activity.text = text
    ctx.activity.from_property.id = "user-123"
    ctx.activity.from_property.name = "Test User"
    ctx.activity.conversation.id = "conv-456"
    ctx.activity.recipient.id = "bot-789"
    ctx.activity.recipient.name = "TestBot"
    ctx.activity.entities = []
    ctx.send_activity = AsyncMock()
    return ctx


def _make_agent(**overrides):
    """Build a mock agent with standard attributes."""
    agent = MagicMock()
    agent.agent_id = "test-agent"
    agent.name = "Test Agent"
    agent.description = "A test agent"
    agent.model = "gpt-4"
    agent.tool_manager = MagicMock()
    agent.tool_manager.get_tool.return_value = None
    agent.tool_manager.list_tools.return_value = []
    agent.tool_manager._tools = {}
    for key, val in overrides.items():
        setattr(agent, key, val)
    return agent


def _make_wrapper(agent=None):
    """Build a mock wrapper with standard response helpers."""
    wrapper = MagicMock()
    wrapper.config = MagicMock()
    wrapper.config.commands = {}
    wrapper._remove_mentions = MagicMock(side_effect=lambda act, text: text)
    wrapper._parse_response = MagicMock(return_value=MagicMock(text="result", documents=[], media=[]))
    wrapper._send_parsed_response = AsyncMock()
    wrapper.send_text = AsyncMock()
    wrapper.send_card = AsyncMock()
    wrapper.send_typing = AsyncMock()
    wrapper.conversation_state = MagicMock()
    wrapper.conversation_state.clear_state = AsyncMock()
    wrapper.conversation_state.save_changes = AsyncMock()
    return wrapper


class TestHandleFunction:
    @pytest.mark.asyncio
    async def test_usage_message_when_no_method(self):
        from parrot.integrations.msteams.commands.agent_commands import AgentCommandHandler

        handler = AgentCommandHandler(_make_agent(), _make_wrapper())
        ctx = _make_turn_context("/function")
        await handler.handle_function(ctx)
        handler.wrapper.send_text.assert_called_once()
        call_text = handler.wrapper.send_text.call_args[0][0]
        assert "Usage" in call_text

    @pytest.mark.asyncio
    async def test_method_not_found(self):
        from parrot.integrations.msteams.commands.agent_commands import AgentCommandHandler

        agent = _make_agent()
        del agent.nonexistent_method  # ensure it doesn't exist
        handler = AgentCommandHandler(agent, _make_wrapper())
        ctx = _make_turn_context("/function nonexistent_method")
        await handler.handle_function(ctx)
        call_text = handler.wrapper.send_text.call_args[0][0]
        assert "not found" in call_text

    @pytest.mark.asyncio
    async def test_calls_async_method_with_kwargs(self):
        from parrot.integrations.msteams.commands.agent_commands import AgentCommandHandler

        agent = _make_agent()
        agent.speech_report = AsyncMock(return_value={"result": "ok"})
        handler = AgentCommandHandler(agent, _make_wrapper())
        ctx = _make_turn_context('/function speech_report report="hello world" max_lines=2')
        await handler.handle_function(ctx)
        agent.speech_report.assert_called_once_with(report="hello world", max_lines="2")

    @pytest.mark.asyncio
    async def test_calls_sync_method(self):
        from parrot.integrations.msteams.commands.agent_commands import AgentCommandHandler

        agent = _make_agent()
        agent.get_info = MagicMock(return_value="info")
        handler = AgentCommandHandler(agent, _make_wrapper())
        ctx = _make_turn_context("/function get_info")
        await handler.handle_function(ctx)
        agent.get_info.assert_called_once()


class TestHandleCall:
    @pytest.mark.asyncio
    async def test_calls_method_with_positional_args(self):
        from parrot.integrations.msteams.commands.agent_commands import AgentCommandHandler

        agent = _make_agent()
        agent.greet = AsyncMock(return_value="hi")
        handler = AgentCommandHandler(agent, _make_wrapper())
        ctx = _make_turn_context("/call greet Alice")
        await handler.handle_call(ctx)
        agent.greet.assert_called_once_with("Alice")


class TestHandleQuestion:
    @pytest.mark.asyncio
    async def test_calls_agent_ask_without_tools(self):
        from parrot.integrations.msteams.commands.agent_commands import AgentCommandHandler

        agent = _make_agent()
        agent.ask = AsyncMock(return_value="42")
        handler = AgentCommandHandler(agent, _make_wrapper())
        ctx = _make_turn_context("/question What is the answer?")
        await handler.handle_question(ctx)
        agent.ask.assert_called_once()
        call_kwargs = agent.ask.call_args
        assert call_kwargs.kwargs.get("use_tools") is False


class TestRegister:
    def test_registers_all_core_commands(self):
        from parrot.integrations.msteams.commands.agent_commands import AgentCommandHandler
        from parrot.integrations.msteams.commands import MSTeamsCommandRouter

        handler = AgentCommandHandler(_make_agent(), _make_wrapper())
        router = MSTeamsCommandRouter()
        handler.register(router)

        expected = {
            "function", "call", "tool", "skill", "commands",
            "help", "clear", "whoami", "question",
        }
        assert expected.issubset(set(router.registered_commands))
