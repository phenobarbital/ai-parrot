"""
Integration tests for Telegram command menu parity (FEAT-220 TASK-1444).

Verifies that the ``IntegrationBotManager`` startup path publishes the command
menu (including Jira/platform commands) via ``TelegramAgentWrapper.
register_command_menu()``, closing the parity gap with ``TelegramBotManager``.

These tests build the wrapper directly (without running the full
``_start_telegram_bot`` flow) to assert that ``register_command_menu()`` on
the integration path publishes the expected commands.
"""
import pytest
from unittest.mock import MagicMock
from aiogram.types import BotCommand


# ---------------------------------------------------------------------------
# Fake Bot that records API calls
# ---------------------------------------------------------------------------


class _FakeBot:
    """Records Bot API calls without hitting Telegram."""

    def __init__(self) -> None:
        self.set_calls: list[list[BotCommand]] = []
        self.deleted_scopes: list[str] = []
        self.menu_button_set: bool = False

    async def delete_my_commands(self, scope=None) -> None:
        self.deleted_scopes.append(type(scope).__name__)

    async def set_my_commands(self, commands, scope=None) -> None:
        self.set_calls.append(list(commands))

    async def set_chat_menu_button(self, menu_button=None) -> None:
        self.menu_button_set = True


# ---------------------------------------------------------------------------
# Helper: build a minimal TelegramAgentWrapper via __new__
# ---------------------------------------------------------------------------


def _make_wrapper(monkeypatch, bot, commands):
    """Build a minimal TelegramAgentWrapper for testing register_command_menu.

    Args:
        monkeypatch: pytest monkeypatch fixture.
        bot: Fake Bot instance.
        commands: List of BotCommand that get_bot_commands() returns.

    Returns:
        Configured TelegramAgentWrapper instance.
    """
    from parrot.integrations.telegram.wrapper import TelegramAgentWrapper

    wrapper = TelegramAgentWrapper.__new__(TelegramAgentWrapper)
    wrapper.bot = bot
    wrapper.logger = MagicMock()
    wrapper._platform_commands = []
    wrapper._agent_commands = []
    monkeypatch.setattr(wrapper, "get_bot_commands", lambda: commands)
    return wrapper


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestIntegrationMenuParity:
    """Integration-level tests for command menu parity (FEAT-220).

    Each test builds a wrapper as the integration path does and verifies the
    published menu contains the expected commands.  The wrapper is tested in
    isolation (no real polling, no real Redis) to keep the suite fast.
    """

    async def test_published_list_includes_jira_commands(self, monkeypatch):
        """Jira platform commands flow through register_command_menu.

        When ``_register_jira_commands`` adds entries to ``_platform_commands``,
        they must appear in the list published by ``register_command_menu()``.
        """
        bot = _FakeBot()
        jira_cmds = [
            BotCommand(command="start", description="Start conversation"),
            BotCommand(command="connect_jira", description="Connect Jira account"),
            BotCommand(command="disconnect_jira", description="Disconnect Jira"),
            BotCommand(command="jira_status", description="Show Jira status"),
        ]
        wrapper = _make_wrapper(monkeypatch, bot, jira_cmds)

        await wrapper.register_command_menu()

        assert bot.set_calls, "set_my_commands should have been called"
        published = bot.set_calls[-1]
        names = {c.command for c in published}
        assert {"connect_jira", "disconnect_jira", "jira_status"} <= names, (
            "Jira commands must appear in published menu on the integration path"
        )

    async def test_register_command_menu_called_via_config_gate(self, monkeypatch):
        """Config gate (register_menu=True) passes through to register_command_menu.

        Simulates the IntegrationBotManager gate:
        ``if config.register_menu: await wrapper.register_command_menu()``
        """
        from parrot.integrations.telegram.models import TelegramAgentConfig

        bot = _FakeBot()
        cmds = [BotCommand(command="start", description="Start")]
        wrapper = _make_wrapper(monkeypatch, bot, cmds)

        config = TelegramAgentConfig(
            name="testbot",
            chatbot_id="test",
            bot_token="1234567890:test",
            register_menu=True,
        )

        # Mirror the gate logic from IntegrationBotManager._start_telegram_bot.
        if config.register_menu:
            try:
                await wrapper.register_command_menu()
            except Exception:
                pass  # should not happen

        assert bot.set_calls, "Menu should be published when register_menu=True"

    async def test_register_command_menu_skipped_via_config_gate(self, monkeypatch):
        """Config gate (register_menu=False) suppresses menu publication."""
        from parrot.integrations.telegram.models import TelegramAgentConfig

        bot = _FakeBot()
        cmds = [BotCommand(command="start", description="Start")]
        wrapper = _make_wrapper(monkeypatch, bot, cmds)

        config = TelegramAgentConfig(
            name="testbot",
            chatbot_id="test",
            bot_token="1234567890:test",
            register_menu=False,
        )

        if config.register_menu:
            await wrapper.register_command_menu()

        assert bot.set_calls == [], "Menu must NOT be published when register_menu=False"

    async def test_menu_button_set_on_integration_path(self, monkeypatch):
        """MenuButtonCommands is set during register_command_menu on integration path."""
        bot = _FakeBot()
        cmds = [BotCommand(command="start", description="Start")]
        wrapper = _make_wrapper(monkeypatch, bot, cmds)

        await wrapper.register_command_menu()

        assert bot.menu_button_set is True, (
            "set_chat_menu_button(MenuButtonCommands()) must be called"
        )

    async def test_scopes_cleared_on_integration_path(self, monkeypatch):
        """Stale command scopes are cleared before publishing on integration path."""
        bot = _FakeBot()
        cmds = [BotCommand(command="start", description="Start")]
        wrapper = _make_wrapper(monkeypatch, bot, cmds)

        await wrapper.register_command_menu()

        assert "BotCommandScopeDefault" in bot.deleted_scopes
        assert "BotCommandScopeAllPrivateChats" in bot.deleted_scopes
        assert "BotCommandScopeAllGroupChats" in bot.deleted_scopes

    async def test_integration_path_source_has_register_menu_call(self):
        """Structural guard: _start_telegram_bot source contains the menu gate.

        If someone refactors and removes the call, this test catches it
        without needing to run the full aiogram/Redis/HITL stack.
        """
        import inspect
        from parrot.integrations.manager import IntegrationBotManager

        src = inspect.getsource(IntegrationBotManager._start_telegram_bot)
        assert "register_menu" in src, (
            "IntegrationBotManager._start_telegram_bot must gate on "
            "config.register_menu (FEAT-220)"
        )
        assert "register_command_menu" in src, (
            "IntegrationBotManager._start_telegram_bot must call "
            "wrapper.register_command_menu() (FEAT-220)"
        )
