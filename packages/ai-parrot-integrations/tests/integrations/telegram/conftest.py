"""
Shared test fixtures and helpers for Telegram integration tests.

Centralises the ``_FakeBot`` fake and ``_make_wrapper`` factory that were
previously duplicated across ``test_wrapper_register_command_menu.py`` and
``test_integration_menu_parity.py``.
"""
import pytest
from unittest.mock import MagicMock
from aiogram.types import BotCommand


# ---------------------------------------------------------------------------
# Shared fake Bot implementations
# ---------------------------------------------------------------------------


class FakeBot:
    """Records Bot API calls; optionally fails the first batch set_my_commands.

    Attributes:
        fail_batch: When True the first ``set_my_commands`` call raises a
            ``RuntimeError`` to simulate a Telegram 400 response.
        set_calls: Ordered list of command lists passed to ``set_my_commands``.
        deleted_scopes: List of scope class names passed to ``delete_my_commands``.
        menu_button_set: Whether ``set_chat_menu_button`` was called.
    """

    def __init__(self, fail_batch: bool = False) -> None:
        self.fail_batch = fail_batch
        self._batch_done = False
        self.set_calls: list[list[BotCommand]] = []
        self.deleted_scopes: list[str] = []
        self.menu_button_set: bool = False

    async def delete_my_commands(self, scope=None) -> None:
        self.deleted_scopes.append(type(scope).__name__)

    async def set_my_commands(self, commands, scope=None) -> None:
        if self.fail_batch and not self._batch_done:
            self._batch_done = True
            raise RuntimeError("400 Bad Request: invalid command")
        self.set_calls.append(list(commands))

    async def set_chat_menu_button(self, menu_button=None) -> None:
        self.menu_button_set = True


class BoomBot(FakeBot):
    """Raises on every Bot API call to exercise swallow-all behavior."""

    async def set_my_commands(self, commands, scope=None) -> None:
        raise RuntimeError("network down")

    async def delete_my_commands(self, scope=None) -> None:
        raise RuntimeError("network down")

    async def set_chat_menu_button(self, menu_button=None) -> None:
        raise RuntimeError("network down")


# ---------------------------------------------------------------------------
# Wrapper factory
# ---------------------------------------------------------------------------


def make_wrapper(monkeypatch, bot: FakeBot, commands: list[BotCommand]):
    """Build a minimal TelegramAgentWrapper with mocked dependencies.

    Constructs the wrapper via ``__new__`` (avoids real aiogram / Redis init)
    then patches ``bot`` and ``get_bot_commands`` so the test controls
    exactly what the method under test sees.

    Args:
        monkeypatch: pytest monkeypatch fixture.
        bot: Fake Bot instance to install as ``wrapper.bot``.
        commands: List of ``BotCommand`` that ``get_bot_commands()`` returns.

    Returns:
        Configured ``TelegramAgentWrapper`` instance.
    """
    from parrot.integrations.telegram.wrapper import TelegramAgentWrapper

    wrapper = TelegramAgentWrapper.__new__(TelegramAgentWrapper)
    wrapper.bot = bot
    wrapper.logger = MagicMock()
    wrapper._platform_commands = []
    wrapper._agent_commands = []
    monkeypatch.setattr(wrapper, "get_bot_commands", lambda: commands)
    return wrapper
