"""Tests for database bot class fallback behavior."""

from types import SimpleNamespace
from unittest.mock import MagicMock

from parrot.bots.basic import BasicBot
from parrot.manager.manager import BotManager


def _manager() -> BotManager:
    manager = BotManager.__new__(BotManager)
    manager.logger = MagicMock()
    return manager


def test_resolve_database_bot_class_defaults_when_none() -> None:
    manager = _manager()
    manager.get_bot_class = MagicMock()
    bot_model = SimpleNamespace(name="data-insights-assistant", bot_class=None)

    resolved_class = manager._resolve_database_bot_class(bot_model)

    assert resolved_class is BasicBot
    manager.get_bot_class.assert_not_called()
    manager.logger.warning.assert_called_once()


def test_resolve_database_bot_class_defaults_when_blank() -> None:
    manager = _manager()
    manager.get_bot_class = MagicMock()
    bot_model = SimpleNamespace(name="data-insights-assistant", bot_class="  ")

    resolved_class = manager._resolve_database_bot_class(bot_model)

    assert resolved_class is BasicBot
    manager.get_bot_class.assert_not_called()
    manager.logger.warning.assert_called_once()


def test_resolve_database_bot_class_defaults_when_unresolved() -> None:
    manager = _manager()
    manager.get_bot_class = MagicMock(return_value=None)
    bot_model = SimpleNamespace(name="data-insights-assistant", bot_class="MissingBot")

    resolved_class = manager._resolve_database_bot_class(bot_model)

    assert resolved_class is BasicBot
    manager.get_bot_class.assert_called_once_with("MissingBot")
    manager.logger.error.assert_called_once()


def test_resolve_database_bot_class_uses_resolved_class() -> None:
    manager = _manager()
    manager.get_bot_class = MagicMock(return_value=BasicBot)
    bot_model = SimpleNamespace(name="data-insights-assistant", bot_class=" BasicBot ")

    resolved_class = manager._resolve_database_bot_class(bot_model)

    assert resolved_class is BasicBot
    manager.get_bot_class.assert_called_once_with("BasicBot")
    manager.logger.warning.assert_not_called()
    manager.logger.error.assert_not_called()
