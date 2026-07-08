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

    @pytest.mark.asyncio
    async def test_blocks_denylisted_method(self):
        from parrot.integrations.msteams.commands.agent_commands import AgentCommandHandler

        agent = _make_agent()
        agent.ask = AsyncMock(return_value="should not run")
        handler = AgentCommandHandler(agent, _make_wrapper())
        ctx = _make_turn_context("/function ask")
        await handler.handle_function(ctx)
        agent.ask.assert_not_called()
        call_text = handler.wrapper.send_text.call_args[0][0]
        assert "cannot be invoked directly" in call_text

    @pytest.mark.asyncio
    async def test_blocks_private_method(self):
        from parrot.integrations.msteams.commands.agent_commands import AgentCommandHandler

        agent = _make_agent()
        agent._private_method = AsyncMock(return_value="should not run")
        handler = AgentCommandHandler(agent, _make_wrapper())
        ctx = _make_turn_context("/function _private_method")
        await handler.handle_function(ctx)
        agent._private_method.assert_not_called()
        call_text = handler.wrapper.send_text.call_args[0][0]
        assert "cannot be invoked directly" in call_text

    @pytest.mark.asyncio
    async def test_reports_error_from_method(self):
        from parrot.integrations.msteams.commands.agent_commands import AgentCommandHandler

        agent = _make_agent()
        agent.speech_report = AsyncMock(side_effect=RuntimeError("boom"))
        handler = AgentCommandHandler(agent, _make_wrapper())
        ctx = _make_turn_context("/function speech_report")
        await handler.handle_function(ctx)
        call_text = handler.wrapper.send_text.call_args[0][0]
        assert "boom" in call_text


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

    @pytest.mark.asyncio
    async def test_blocks_denylisted_method(self):
        from parrot.integrations.msteams.commands.agent_commands import AgentCommandHandler

        agent = _make_agent()
        agent.shutdown = AsyncMock(return_value="should not run")
        handler = AgentCommandHandler(agent, _make_wrapper())
        ctx = _make_turn_context("/call shutdown")
        await handler.handle_call(ctx)
        agent.shutdown.assert_not_called()
        call_text = handler.wrapper.send_text.call_args[0][0]
        assert "cannot be invoked directly" in call_text

    @pytest.mark.asyncio
    async def test_reports_error_from_method(self):
        from parrot.integrations.msteams.commands.agent_commands import AgentCommandHandler

        agent = _make_agent()
        agent.greet = AsyncMock(side_effect=RuntimeError("boom"))
        handler = AgentCommandHandler(agent, _make_wrapper())
        ctx = _make_turn_context("/call greet Alice")
        await handler.handle_call(ctx)
        call_text = handler.wrapper.send_text.call_args[0][0]
        assert "boom" in call_text


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

    @pytest.mark.asyncio
    async def test_reports_error_from_ask(self):
        from parrot.integrations.msteams.commands.agent_commands import AgentCommandHandler

        agent = _make_agent()
        agent.ask = AsyncMock(side_effect=RuntimeError("llm down"))
        handler = AgentCommandHandler(agent, _make_wrapper())
        ctx = _make_turn_context("/question What is the answer?")
        await handler.handle_question(ctx)
        call_text = handler.wrapper.send_text.call_args[0][0]
        assert "llm down" in call_text


class TestSendResult:
    @pytest.mark.asyncio
    async def test_prepends_prefix_to_text_response(self):
        from parrot.integrations.msteams.commands.agent_commands import AgentCommandHandler

        agent = _make_agent()
        wrapper = _make_wrapper()
        parsed = MagicMock(text="hello world")
        wrapper._parse_response = MagicMock(return_value=parsed)
        handler = AgentCommandHandler(agent, wrapper)
        ctx = _make_turn_context()
        await handler._send_result(ctx, "raw-result", prefix="**foo** result:\n\n")
        assert parsed.text == "**foo** result:\n\nhello world"
        wrapper._send_parsed_response.assert_called_once_with(parsed, ctx)

    @pytest.mark.asyncio
    async def test_no_prefix_leaves_text_unchanged(self):
        from parrot.integrations.msteams.commands.agent_commands import AgentCommandHandler

        agent = _make_agent()
        wrapper = _make_wrapper()
        parsed = MagicMock(text="hello world")
        wrapper._parse_response = MagicMock(return_value=parsed)
        handler = AgentCommandHandler(agent, wrapper)
        ctx = _make_turn_context()
        await handler._send_result(ctx, "raw-result")
        assert parsed.text == "hello world"


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


class TestHandleTool:
    @pytest.mark.asyncio
    async def test_lists_tools_when_no_name(self):
        from parrot.integrations.msteams.commands.agent_commands import AgentCommandHandler

        agent = _make_agent()
        agent.tool_manager._tools = {"weather": MagicMock(description="Get weather")}
        handler = AgentCommandHandler(agent, _make_wrapper())
        ctx = _make_turn_context("/tool")
        await handler.handle_tool(ctx)
        call_text = handler.wrapper.send_text.call_args[0][0]
        assert "weather" in call_text

    @pytest.mark.asyncio
    async def test_tool_not_found(self):
        from parrot.integrations.msteams.commands.agent_commands import AgentCommandHandler

        handler = AgentCommandHandler(_make_agent(), _make_wrapper())
        ctx = _make_turn_context("/tool nonexistent")
        await handler.handle_tool(ctx)
        call_text = handler.wrapper.send_text.call_args[0][0]
        assert "not found" in call_text

    @pytest.mark.asyncio
    async def test_invokes_agent_ask_with_tool(self):
        from parrot.integrations.msteams.commands.agent_commands import AgentCommandHandler

        agent = _make_agent()
        tool_mock = MagicMock(description="Get weather")
        agent.tool_manager.get_tool.return_value = tool_mock
        agent.ask = AsyncMock(return_value="Sunny")
        handler = AgentCommandHandler(agent, _make_wrapper())
        ctx = _make_turn_context("/tool weather New York")
        await handler.handle_tool(ctx)
        agent.ask.assert_called_once()
        prompt = agent.ask.call_args[0][0]
        assert "weather" in prompt
        assert "New York" in prompt


class TestHandleSkill:
    @pytest.mark.asyncio
    async def test_lists_skills_when_no_name(self):
        from parrot.integrations.msteams.commands.agent_commands import AgentCommandHandler

        agent = _make_agent()
        file_reg = MagicMock()
        skill_def = MagicMock()
        skill_def.name = "data_analysis"
        skill_def.description = "Analyze data"
        skill_def.triggers = ["/analyze"]
        file_reg.list_skills.return_value = [skill_def]
        agent._skill_file_registry = file_reg
        handler = AgentCommandHandler(agent, _make_wrapper())
        ctx = _make_turn_context("/skill")
        await handler.handle_skill(ctx)
        call_text = handler.wrapper.send_text.call_args[0][0]
        assert "data_analysis" in call_text

    @pytest.mark.asyncio
    async def test_skill_not_found(self):
        from parrot.integrations.msteams.commands.agent_commands import AgentCommandHandler

        agent = _make_agent()
        agent._skill_file_registry = None
        agent._skill_registry = None
        handler = AgentCommandHandler(agent, _make_wrapper())
        ctx = _make_turn_context("/skill nonexistent_skill")
        await handler.handle_skill(ctx)
        call_text = handler.wrapper.send_text.call_args[0][0]
        assert "not found" in call_text

    @pytest.mark.asyncio
    async def test_activates_file_skill(self):
        from parrot.integrations.msteams.commands.agent_commands import AgentCommandHandler

        agent = _make_agent()
        skill_def = MagicMock()
        skill_def.name = "data_analysis"
        file_reg = MagicMock()
        file_reg.get_by_name.return_value = skill_def
        agent._skill_file_registry = file_reg
        agent.ask = AsyncMock(return_value="analysis done")
        handler = AgentCommandHandler(agent, _make_wrapper())
        ctx = _make_turn_context("/skill data_analysis summarize sales")
        await handler.handle_skill(ctx)
        assert agent._active_skill is None  # cleaned up in finally
        agent.ask.assert_called_once()


class TestHandleHelp:
    @pytest.mark.asyncio
    async def test_returns_help_text(self):
        from parrot.integrations.msteams.commands.agent_commands import AgentCommandHandler

        handler = AgentCommandHandler(_make_agent(), _make_wrapper())
        ctx = _make_turn_context("/help")
        await handler.handle_help(ctx)
        call_text = handler.wrapper.send_text.call_args[0][0]
        assert "/function" in call_text
        assert "/tool" in call_text
        assert "/skill" in call_text


class TestHandleWhoami:
    @pytest.mark.asyncio
    async def test_returns_agent_and_user_info(self):
        from parrot.integrations.msteams.commands.agent_commands import AgentCommandHandler

        handler = AgentCommandHandler(_make_agent(), _make_wrapper())
        ctx = _make_turn_context("/whoami")
        await handler.handle_whoami(ctx)
        call_text = handler.wrapper.send_text.call_args[0][0]
        assert "Test Agent" in call_text
        assert "Test User" in call_text


class TestHandleClear:
    @pytest.mark.asyncio
    async def test_clears_conversation_state(self):
        from parrot.integrations.msteams.commands.agent_commands import AgentCommandHandler

        wrapper = _make_wrapper()
        handler = AgentCommandHandler(_make_agent(), wrapper)
        ctx = _make_turn_context("/clear")
        await handler.handle_clear(ctx)
        wrapper.conversation_state.clear_state.assert_called_once_with(ctx)
        wrapper.conversation_state.save_changes.assert_called_once()
        call_text = wrapper.send_text.call_args[0][0]
        assert "cleared" in call_text.lower()


class TestHandleCommands:
    @pytest.mark.asyncio
    async def test_lists_registered_commands(self):
        from parrot.integrations.msteams.commands.agent_commands import AgentCommandHandler
        from parrot.integrations.msteams.commands import MSTeamsCommandRouter

        wrapper = _make_wrapper()
        router = MSTeamsCommandRouter()
        wrapper._command_router = router
        handler = AgentCommandHandler(_make_agent(), wrapper)
        handler.register(router)
        ctx = _make_turn_context("/commands")
        await handler.handle_commands(ctx)
        call_text = wrapper.send_text.call_args[0][0]
        assert "/function" in call_text
        assert "/help" in call_text


class TestCustomCommands:
    def test_registers_custom_commands_from_config(self):
        from parrot.integrations.msteams.commands.agent_commands import AgentCommandHandler
        from parrot.integrations.msteams.commands import MSTeamsCommandRouter

        agent = _make_agent()
        agent.speech_report = AsyncMock()
        wrapper = _make_wrapper()
        wrapper.config.commands = {"report": "speech_report"}
        handler = AgentCommandHandler(agent, wrapper)
        router = MSTeamsCommandRouter()
        handler.register(router)
        assert "report" in router.registered_commands

    def test_skips_missing_methods(self):
        from parrot.integrations.msteams.commands.agent_commands import AgentCommandHandler
        from parrot.integrations.msteams.commands import MSTeamsCommandRouter

        agent = _make_agent()
        del agent.nonexistent_method  # ensure it doesn't exist
        wrapper = _make_wrapper()
        wrapper.config.commands = {"bad": "nonexistent_method"}
        handler = AgentCommandHandler(agent, wrapper)
        router = MSTeamsCommandRouter()
        handler.register(router)
        assert "bad" not in router.registered_commands

    @pytest.mark.asyncio
    async def test_custom_command_invokes_method_with_kwargs(self):
        from parrot.integrations.msteams.commands.agent_commands import AgentCommandHandler
        from parrot.integrations.msteams.commands import MSTeamsCommandRouter

        agent = _make_agent()
        agent.speech_report = AsyncMock(return_value={"ok": True})
        wrapper = _make_wrapper()
        wrapper.config.commands = {"report": "speech_report"}
        handler = AgentCommandHandler(agent, wrapper)
        router = MSTeamsCommandRouter()
        handler.register(router)

        ctx = _make_turn_context('/report report="hello" max_lines=2')
        await router.try_dispatch("/report", ctx)
        agent.speech_report.assert_called_once_with(report="hello", max_lines="2")


class TestWrapperIntegration:
    def test_router_created_without_oauth_manager(self):
        """The command router must be created even without oauth_manager."""
        from parrot.integrations.msteams.commands import MSTeamsCommandRouter

        # Simulate what __init__ should do after the change:
        # router is always created, agent commands always registered.
        router = MSTeamsCommandRouter()
        from parrot.integrations.msteams.commands.agent_commands import AgentCommandHandler

        handler = AgentCommandHandler(_make_agent(), _make_wrapper())
        handler.register(router)

        # Core commands must be present
        assert "function" in router.registered_commands
        assert "help" in router.registered_commands

        # Jira commands must NOT be present (no oauth_manager)
        assert "connect_jira" not in router.registered_commands
