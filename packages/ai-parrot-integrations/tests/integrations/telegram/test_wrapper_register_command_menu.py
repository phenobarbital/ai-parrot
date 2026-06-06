"""
Unit tests for TelegramAgentWrapper.register_command_menu() (FEAT-220 TASK-1442).

Verifies the new public coroutine that publishes the bot's command menu to
Telegram (setMyCommands + chat menu button).  A lightweight fake Bot records
every API call so assertions stay fast and dependency-free.

Shared helpers (``FakeBot``, ``BoomBot``, ``make_wrapper``) live in
``conftest.py`` — imported here via local aliases to keep the test body concise.
"""
import pytest
from unittest.mock import MagicMock
from aiogram.types import BotCommand

from .conftest import FakeBot as _FakeBot, BoomBot as _BoomBot, make_wrapper as _make_wrapper


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestRegisterCommandMenu:
    """Unit tests for TelegramAgentWrapper.register_command_menu()."""

    async def test_happy_path_sets_commands_and_button(self, monkeypatch):
        """Happy path: set_my_commands called with full list, menu button set."""
        bot = _FakeBot()
        cmds = [
            BotCommand(command="start", description="Start conversation"),
            BotCommand(command="connect_jira", description="Connect Jira account"),
        ]
        wrapper = _make_wrapper(monkeypatch, bot, cmds)

        await wrapper.register_command_menu()

        assert bot.set_calls, "set_my_commands should have been called"
        assert bot.set_calls[-1] == cmds
        assert bot.menu_button_set is True

    def test_method_exists_and_is_coroutine(self):
        """register_command_menu must be an async method on TelegramAgentWrapper."""
        import inspect
        from parrot.integrations.telegram.wrapper import TelegramAgentWrapper

        assert hasattr(TelegramAgentWrapper, "register_command_menu")
        assert inspect.iscoroutinefunction(TelegramAgentWrapper.register_command_menu)

    async def test_clears_stale_scopes_before_setting(self, monkeypatch):
        """All three BotCommandScope* scopes must be cleared before setting."""
        bot = _FakeBot()
        cmds = [BotCommand(command="start", description="Start")]
        wrapper = _make_wrapper(monkeypatch, bot, cmds)

        await wrapper.register_command_menu()

        assert "BotCommandScopeDefault" in bot.deleted_scopes
        assert "BotCommandScopeAllPrivateChats" in bot.deleted_scopes
        assert "BotCommandScopeAllGroupChats" in bot.deleted_scopes

    async def test_jira_commands_included_in_set_call(self, monkeypatch):
        """When Jira commands are in the list, they flow through to set_my_commands."""
        bot = _FakeBot()
        cmds = [
            BotCommand(command="start", description="Start"),
            BotCommand(command="connect_jira", description="Connect Jira account"),
            BotCommand(command="disconnect_jira", description="Disconnect Jira"),
            BotCommand(command="jira_status", description="Jira status"),
        ]
        wrapper = _make_wrapper(monkeypatch, bot, cmds)

        await wrapper.register_command_menu()

        names = [c.command for c in bot.set_calls[-1]]
        assert "connect_jira" in names
        assert "disconnect_jira" in names
        assert "jira_status" in names

    async def test_batch_failure_falls_back_to_individual(self, monkeypatch):
        """On batch 400, falls back to per-command registration; valid commands registered."""
        bot = _FakeBot(fail_batch=True)
        cmds = [
            BotCommand(command="start", description="Start"),
            BotCommand(command="help", description="Help"),
        ]
        wrapper = _make_wrapper(monkeypatch, bot, cmds)

        await wrapper.register_command_menu()

        # Fallback should have produced at least one successful set call.
        assert bot.set_calls, "Per-command fallback should have registered commands"

    async def test_empty_list_skips_set_my_commands(self, monkeypatch):
        """Empty get_bot_commands() → warning logged, no set_my_commands call."""
        bot = _FakeBot()
        wrapper = _make_wrapper(monkeypatch, bot, [])

        await wrapper.register_command_menu()

        assert bot.set_calls == [], "set_my_commands must not be called for empty list"
        wrapper.logger.warning.assert_called()

    async def test_api_error_is_swallowed_and_does_not_raise(self, monkeypatch):
        """A Telegram transport error must be logged and never raised."""
        bot = _BoomBot()
        cmds = [BotCommand(command="start", description="Start")]
        wrapper = _make_wrapper(monkeypatch, bot, cmds)

        # Must not raise — bot startup must be unaffected.
        await wrapper.register_command_menu()

    async def test_sets_menu_button_on_happy_path(self, monkeypatch):
        """set_chat_menu_button(MenuButtonCommands()) must be called."""
        bot = _FakeBot()
        cmds = [BotCommand(command="start", description="Start")]
        wrapper = _make_wrapper(monkeypatch, bot, cmds)

        await wrapper.register_command_menu()

        assert bot.menu_button_set is True

    async def test_menu_button_failure_is_swallowed(self, monkeypatch):
        """set_chat_menu_button failure must not propagate."""
        class _ButtonBoom(_FakeBot):
            async def set_chat_menu_button(self, menu_button=None) -> None:
                raise RuntimeError("button error")

        bot = _ButtonBoom()
        cmds = [BotCommand(command="start", description="Start")]
        wrapper = _make_wrapper(monkeypatch, bot, cmds)

        # Must not raise.
        await wrapper.register_command_menu()
        assert bot.set_calls  # main set_my_commands still happened

    async def test_register_menu_flag_not_checked_inside_method(self, monkeypatch):
        """The method does NOT gate on config.register_menu (caller's responsibility)."""
        bot = _FakeBot()
        cmds = [BotCommand(command="start", description="Start")]
        wrapper = _make_wrapper(monkeypatch, bot, cmds)
        # Deliberately set register_menu=False on the wrapper config to prove
        # the method ignores it (caller should gate, not callee).
        wrapper.config = MagicMock()
        wrapper.config.register_menu = False

        await wrapper.register_command_menu()

        # Should still register (flag is caller's concern, not the method's).
        assert bot.set_calls
