"""Integration tests for the AI-Parrot CLI agent REPL (FEAT-168).

Tests cover the full pipeline from Click command through agent loading,
REPL interaction, slash commands, and response rendering.

All tests use mocks — no running server or real LLM API keys are required.
"""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from click.testing import CliRunner

from parrot.cli.agent_repl import agent as agent_cmd
from parrot.cli.commands import SlashCommandDispatcher
from parrot.cli.loaders import AgentLoadError, StandaloneAgentLoader
from parrot.cli.repl import AgentREPL, REPLConfig
from parrot.models.outputs import OutputMode


# ---------------------------------------------------------------------------
# Unit tests — ResponseRenderer
# ---------------------------------------------------------------------------


class TestResponseRenderer:
    """Unit tests for ResponseRenderer."""

    def test_render_markdown(self, mock_agent_response, renderer):
        """Rendering markdown output should not raise.

        Args:
            mock_agent_response: Fixture providing markdown AIMessage mock.
            renderer: Fixture providing a quiet ResponseRenderer.
        """
        renderer.render(mock_agent_response)  # must not raise

    def test_render_tool_calls(self, response_with_tools, renderer):
        """Rendering tool calls should display tool panels without raising.

        Args:
            response_with_tools: Fixture providing AIMessage with tool calls.
            renderer: Fixture providing a quiet ResponseRenderer.
        """
        renderer.render(response_with_tools)  # must not raise

    def test_render_error(self, renderer):
        """Rendering an exception should display an error panel without raising.

        Args:
            renderer: Fixture providing a quiet ResponseRenderer.
        """
        renderer.render_error(ValueError("test error"))

    def test_render_table(self, renderer):
        """Rendering a table should produce output without raising.

        Args:
            renderer: Fixture providing a quiet ResponseRenderer.
        """
        renderer.render_table(
            headers=["Name", "Tools"],
            rows=[["agent1", "3"], ["agent2", "5"]],
        )

    def test_render_none_output(self, renderer):
        """Rendering a message with None output should not raise.

        Args:
            renderer: Fixture providing a quiet ResponseRenderer.
        """
        msg = MagicMock()
        msg.output = None
        msg.response = "fallback"
        msg.tool_calls = []
        msg.usage = None
        renderer.render(msg)


# ---------------------------------------------------------------------------
# Unit tests — SlashCommandDispatcher
# ---------------------------------------------------------------------------


class TestSlashCommandDispatcher:
    """Unit tests for SlashCommandDispatcher."""

    def test_completions_include_builtins(self):
        """get_completions() must include all built-in commands.

        Verifies /tools and /help are present.
        """
        dispatcher = SlashCommandDispatcher()
        completions = dispatcher.get_completions()
        assert "/tools" in completions
        assert "/help" in completions
        assert "/quit" in completions
        assert "/export" in completions
        assert "/stream" in completions
        assert "/clear" in completions
        assert "/info" in completions

    @pytest.mark.asyncio
    async def test_dispatch_non_slash_returns_false(self, mock_agent, repl_config, renderer):
        """Non-slash input must return False from dispatch_async().

        Args:
            mock_agent: Fixture providing mock bot.
            repl_config: Fixture providing test config.
            renderer: Fixture providing quiet renderer.
        """
        dispatcher = SlashCommandDispatcher()
        repl = AgentREPL(mock_agent, repl_config, renderer)
        assert await dispatcher.dispatch_async("hello world", repl) is False

    @pytest.mark.asyncio
    async def test_dispatch_slash_returns_true(self, mock_agent, repl_config, renderer):
        """Slash input must return True from dispatch_async().

        Even unknown commands return True (they are "consumed" as slash commands).

        Args:
            mock_agent: Fixture providing mock bot.
            repl_config: Fixture providing test config.
            renderer: Fixture providing quiet renderer.
        """
        dispatcher = SlashCommandDispatcher()
        repl = AgentREPL(mock_agent, repl_config, renderer)
        # /help is a known command — True
        result = await dispatcher.dispatch_async("/help", repl)
        assert result is True

    @pytest.mark.asyncio
    async def test_dispatch_unknown_command(self, mock_agent, repl_config, renderer):
        """Unknown slash commands should return True without raising.

        Args:
            mock_agent: Fixture providing mock bot.
            repl_config: Fixture providing test config.
            renderer: Fixture providing quiet renderer.
        """
        dispatcher = SlashCommandDispatcher()
        repl = AgentREPL(mock_agent, repl_config, renderer)
        result = await dispatcher.dispatch_async("/nonexistent_command", repl)
        assert result is True  # consumed as a slash command


# ---------------------------------------------------------------------------
# Unit tests — REPLConfig
# ---------------------------------------------------------------------------


class TestREPLConfig:
    """Unit tests for REPLConfig."""

    def test_config_defaults(self):
        """Default config should have streaming=True, user_id='cli-user'."""
        config = REPLConfig(agent_name="test")
        assert config.streaming is True
        assert config.user_id == "cli-user"
        assert config.session_id  # auto-generated UUID
        assert config.server_url is None

    def test_config_override(self):
        """Config should accept custom values.

        Verifies streaming and server_url can be overridden.
        """
        config = REPLConfig(
            agent_name="my_agent",
            streaming=False,
            server_url="http://localhost:8080",
        )
        assert config.streaming is False
        assert config.server_url == "http://localhost:8080"


# ---------------------------------------------------------------------------
# Unit tests — StandaloneAgentLoader
# ---------------------------------------------------------------------------


class TestStandaloneAgentLoader:
    """Unit tests for StandaloneAgentLoader."""

    @pytest.mark.asyncio
    async def test_load_existing_agent(self, mock_agent):
        """Loading a known agent should return the bot instance.

        Args:
            mock_agent: Fixture providing mock bot.
        """
        loader = StandaloneAgentLoader()
        with patch("parrot.cli.loaders.agent_registry") as mock_reg:
            mock_reg.get_instance = AsyncMock(return_value=mock_agent)
            mock_reg._registered_agents = {"test_agent": MagicMock()}
            bot = await loader.load("test_agent")
            assert bot is mock_agent

    @pytest.mark.asyncio
    async def test_load_unknown_agent_raises(self):
        """Loading an unknown agent must raise AgentLoadError with suggestions."""
        loader = StandaloneAgentLoader()
        with patch("parrot.cli.loaders.agent_registry") as mock_reg:
            mock_reg.get_instance = AsyncMock(return_value=None)
            mock_reg._registered_agents = {"security_agent": MagicMock()}
            with pytest.raises(AgentLoadError) as exc_info:
                await loader.load("secrity_agent")
            assert "security_agent" in exc_info.value.suggestions

    @pytest.mark.asyncio
    async def test_load_unknown_agent_no_suggestions(self):
        """AgentLoadError should be raised even with no fuzzy suggestions.

        Tests empty registry case.
        """
        loader = StandaloneAgentLoader()
        with patch("parrot.cli.loaders.agent_registry") as mock_reg:
            mock_reg.get_instance = AsyncMock(return_value=None)
            mock_reg._registered_agents = {}
            with pytest.raises(AgentLoadError):
                await loader.load("nonexistent")

    @pytest.mark.asyncio
    async def test_list_agents(self):
        """list_agents() should return BotMetadata values from registry.

        Verifies return type is a list.
        """
        loader = StandaloneAgentLoader()
        meta1 = MagicMock()
        meta1.name = "agent1"
        with patch("parrot.cli.loaders.agent_registry") as mock_reg:
            mock_reg._registered_agents = {"agent1": meta1}
            result = await loader.list_agents()
            assert result == [meta1]


# ---------------------------------------------------------------------------
# Integration tests — AgentREPL.send()
# ---------------------------------------------------------------------------


class TestAgentREPLSend:
    """Integration tests for AgentREPL send() and history tracking."""

    @pytest.mark.asyncio
    async def test_send_calls_ask(self, mock_agent, repl_config, renderer):
        """send() should call bot.ask() with correct parameters.

        Args:
            mock_agent: Fixture providing mock bot.
            repl_config: Fixture providing test config.
            renderer: Fixture providing quiet renderer.
        """
        repl = AgentREPL(mock_agent, repl_config, renderer)
        await repl.send("hello")
        mock_agent.ask.assert_called_once()
        call_kwargs = mock_agent.ask.call_args
        assert call_kwargs.kwargs.get("output_mode") == OutputMode.TERMINAL or \
               (len(call_kwargs.args) > 3 and call_kwargs.args[3] == OutputMode.TERMINAL)

    @pytest.mark.asyncio
    async def test_send_tracks_history(self, mock_agent, repl_config, renderer):
        """send() should append a ConversationTurn to repl.history.

        Args:
            mock_agent: Fixture providing mock bot.
            repl_config: Fixture providing test config.
            renderer: Fixture providing quiet renderer.
        """
        repl = AgentREPL(mock_agent, repl_config, renderer)
        await repl.send("hello")
        assert len(repl.history) == 1
        assert repl.history[0].query == "hello"

    @pytest.mark.asyncio
    async def test_send_session_id_passed(self, mock_agent, repl_config, renderer):
        """send() must pass session_id from config to bot.ask().

        Args:
            mock_agent: Fixture providing mock bot.
            repl_config: Fixture providing test config.
            renderer: Fixture providing quiet renderer.
        """
        repl = AgentREPL(mock_agent, repl_config, renderer)
        await repl.send("test")
        call_kwargs = mock_agent.ask.call_args.kwargs
        assert call_kwargs.get("session_id") == repl.config.session_id


# ---------------------------------------------------------------------------
# Integration tests — AgentREPL.send_stream()
# ---------------------------------------------------------------------------


class TestAgentREPLStream:
    """Integration tests for AgentREPL send_stream() and streaming rendering."""

    @pytest.mark.asyncio
    async def test_send_stream_renders_chunks(self, mock_agent, renderer):
        """send_stream() should call renderer streaming methods and track history.

        Verifies render_stream_start(), render_stream_chunk(), render_stream_end()
        are all called, and that a ConversationTurn is appended to history.

        Args:
            mock_agent: Fixture providing mock bot with ask_stream mock.
            renderer: Fixture providing quiet renderer.
        """
        config = REPLConfig(
            agent_name="test_agent",
            streaming=True,
            session_id="test-session-stream",
            user_id="test-user",
        )
        repl = AgentREPL(mock_agent, config, renderer)

        stream_start_calls = []
        stream_end_calls = []
        stream_chunk_calls = []

        original_start = renderer.render_stream_start
        original_end = renderer.render_stream_end
        original_chunk = renderer.render_stream_chunk

        def _track_start():
            stream_start_calls.append(True)
            original_start()

        def _track_end(response=None):
            stream_end_calls.append(True)
            original_end(response)

        def _track_chunk(text):
            stream_chunk_calls.append(text)
            original_chunk(text)

        renderer.render_stream_start = _track_start
        renderer.render_stream_end = _track_end
        renderer.render_stream_chunk = _track_chunk

        await repl.send_stream("hello streaming")

        assert len(stream_start_calls) == 1, "render_stream_start() must be called once"
        assert len(stream_end_calls) == 1, "render_stream_end() must be called once"
        assert len(stream_chunk_calls) >= 1, "render_stream_chunk() must be called at least once"
        assert len(repl.history) == 1, "One ConversationTurn must be appended to history"
        assert repl.history[0].query == "hello streaming"


# ---------------------------------------------------------------------------
# Integration tests — Slash commands via dispatch_async
# ---------------------------------------------------------------------------


class TestSlashCommandsAsync:
    """Integration tests for async slash command execution."""

    @pytest.mark.asyncio
    async def test_stream_toggle(self, mock_agent, repl_config, renderer):
        """'/stream' should toggle config.streaming.

        Args:
            mock_agent: Fixture providing mock bot.
            repl_config: Fixture providing test config.
            renderer: Fixture providing quiet renderer.
        """
        repl = AgentREPL(mock_agent, repl_config, renderer)
        initial = repl.config.streaming  # False from fixture
        await repl.dispatcher.dispatch_async("/stream", repl)
        assert repl.config.streaming != initial

    @pytest.mark.asyncio
    async def test_clear_new_session(self, mock_agent, repl_config, renderer):
        """'/clear' should change session_id and clear history.

        Args:
            mock_agent: Fixture providing mock bot.
            repl_config: Fixture providing test config.
            renderer: Fixture providing quiet renderer.
        """
        repl = AgentREPL(mock_agent, repl_config, renderer)
        old_id = repl.config.session_id
        # Add a turn to history
        await repl.send("hello")
        assert len(repl.history) == 1
        # Now clear
        await repl.dispatcher.dispatch_async("/clear", repl)
        assert repl.config.session_id != old_id
        assert len(repl.history) == 0

    @pytest.mark.asyncio
    async def test_tools_command(self, mock_agent, repl_config, renderer):
        """'/tools' should call bot.get_available_tools() without error.

        Args:
            mock_agent: Fixture providing mock bot.
            repl_config: Fixture providing test config.
            renderer: Fixture providing quiet renderer.
        """
        repl = AgentREPL(mock_agent, repl_config, renderer)
        await repl.dispatcher.dispatch_async("/tools", repl)
        mock_agent.get_available_tools.assert_called_once()

    @pytest.mark.asyncio
    async def test_quit_raises_system_exit(self, mock_agent, repl_config, renderer):
        """'/quit' should raise SystemExit.

        Args:
            mock_agent: Fixture providing mock bot.
            repl_config: Fixture providing test config.
            renderer: Fixture providing quiet renderer.
        """
        repl = AgentREPL(mock_agent, repl_config, renderer)
        with pytest.raises(SystemExit):
            await repl.dispatcher.dispatch_async("/quit", repl)

    @pytest.mark.asyncio
    async def test_exit_alias_quit(self, mock_agent, repl_config, renderer):
        """'/exit' should be an alias for '/quit' and raise SystemExit.

        Args:
            mock_agent: Fixture providing mock bot.
            repl_config: Fixture providing test config.
            renderer: Fixture providing quiet renderer.
        """
        repl = AgentREPL(mock_agent, repl_config, renderer)
        with pytest.raises(SystemExit):
            await repl.dispatcher.dispatch_async("/exit", repl)


# ---------------------------------------------------------------------------
# Integration tests — /export roundtrip
# ---------------------------------------------------------------------------


class TestExportRoundtrip:
    """Integration tests for the /export slash command."""

    @pytest.mark.asyncio
    async def test_export_creates_json_file(self, mock_agent, repl_config, renderer, tmp_path):
        """'/export path' should create a valid JSON file with conversation turns.

        Args:
            mock_agent: Fixture providing mock bot.
            repl_config: Fixture providing test config.
            renderer: Fixture providing quiet renderer.
            tmp_path: pytest tmp_path fixture.
        """
        repl = AgentREPL(mock_agent, repl_config, renderer)
        # Add a conversation turn
        await repl.send("What is 2+2?")
        # Export
        export_path = str(tmp_path / "conversation.json")
        await repl.dispatcher.dispatch_async(f"/export {export_path}", repl)
        # Verify file
        assert Path(export_path).exists()
        with open(export_path) as f:
            data = json.load(f)
        assert "session_id" in data
        assert "turns" in data
        assert len(data["turns"]) == 1
        assert data["turns"][0]["query"] == "What is 2+2?"

    @pytest.mark.asyncio
    async def test_export_empty_history(self, mock_agent, repl_config, renderer, tmp_path):
        """'/export' with empty history should not create a file.

        Args:
            mock_agent: Fixture providing mock bot.
            repl_config: Fixture providing test config.
            renderer: Fixture providing quiet renderer.
            tmp_path: pytest tmp_path fixture.
        """
        repl = AgentREPL(mock_agent, repl_config, renderer)
        export_path = str(tmp_path / "empty.json")
        # No history
        await repl.dispatcher.dispatch_async(f"/export {export_path}", repl)
        assert not Path(export_path).exists()


# ---------------------------------------------------------------------------
# Integration tests — Click command (CliRunner)
# ---------------------------------------------------------------------------


class TestCLICommandAgent:
    """Integration tests for the 'parrot agent' Click command via CliRunner."""

    def test_list_flag_exits_zero(self):
        """'parrot agent --list' should exit with code 0 and show a table."""
        runner = CliRunner()
        mock_meta = MagicMock()
        mock_meta.name = "test_agent"
        mock_meta.factory = MagicMock(__name__="TestBot")
        mock_meta.tags = {"nlp"}

        with patch("parrot.cli.agent_repl.StandaloneAgentLoader") as mock_cls:
            mock_loader = AsyncMock()
            mock_loader.list_agents = AsyncMock(return_value=[mock_meta])
            mock_cls.return_value = mock_loader
            result = runner.invoke(agent_cmd, ["--list"])
        assert result.exit_code == 0

    def test_unknown_agent_exits_one(self):
        """'parrot agent unknown_name' should exit with code 1."""
        runner = CliRunner()
        with patch("parrot.cli.agent_repl.StandaloneAgentLoader") as mock_cls:
            mock_loader = AsyncMock()
            mock_loader.load = AsyncMock(
                side_effect=AgentLoadError("unknown_name", suggestions=[])
            )
            mock_cls.return_value = mock_loader
            result = runner.invoke(agent_cmd, ["unknown_name"])
        assert result.exit_code == 1

    def test_list_empty_registry(self):
        """'parrot agent --list' with no agents should exit zero with a message."""
        runner = CliRunner()
        with patch("parrot.cli.agent_repl.StandaloneAgentLoader") as mock_cls:
            mock_loader = AsyncMock()
            mock_loader.list_agents = AsyncMock(return_value=[])
            mock_cls.return_value = mock_loader
            result = runner.invoke(agent_cmd, ["--list"])
        assert result.exit_code == 0
