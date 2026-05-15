"""
Telegram Integration for AI-Parrot Agents.

Provides Telegram bot functionality using aiogram v3 to expose
agents, crews, and flows via Telegram messaging.

Supports:
- Direct messages (private chats)
- Group messages with @mentions
- Group commands (/ask)
- Channel posts (optional)

Example YAML configuration (env/telegram_bots.yaml):

    agents:
      HRAgent:
        chatbot_id: hr_agent
        welcome_message: "Hello! I'm your HR Assistant."
        enable_group_mentions: true
        enable_group_commands: true
        reply_in_thread: true
        # bot_token: optional - defaults to HRAGENT_TELEGRAM_TOKEN env var
"""
# Lazy re-exports (PEP 562). aiogram is heavy (~1.6s import), so we defer
# loading any submodule that pulls it in until the caller actually touches
# one of the names below. Importing a specific submodule path
# (e.g. parrot.integrations.telegram.combined_callback) no longer triggers
# the full aiogram-dependent surface.
import importlib
from typing import TYPE_CHECKING

_LAZY_EXPORTS = {
    "TelegramAgentConfig": ".models",
    "TelegramBotsConfig": ".models",
    "TelegramAgentWrapper": ".wrapper",
    "TelegramBotManager": ".manager",
    "BotMentionedFilter": ".filters",
    "CommandInGroupFilter": ".filters",
    "extract_query_from_mention": ".utils",
    "telegram_command": ".decorators",
    "discover_telegram_commands": ".decorators",
    "TelegramUserSession": ".auth",
    "NavigatorAuthClient": ".auth",
    "telegram_chat_scope": ".context",
    "get_current_telegram_chat_id": ".context",
    "current_telegram_chat_id": ".context",
    "TelegramHumanTool": ".human_tool",
}

__all__ = list(_LAZY_EXPORTS.keys())


def __getattr__(name: str):
    module_path = _LAZY_EXPORTS.get(name)
    if module_path is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module = importlib.import_module(module_path, package=__name__)
    value = getattr(module, name)
    globals()[name] = value
    return value


def __dir__():
    return sorted(list(globals().keys()) + __all__)


if TYPE_CHECKING:
    from .models import TelegramAgentConfig, TelegramBotsConfig
    from .wrapper import TelegramAgentWrapper
    from .manager import TelegramBotManager
    from .filters import BotMentionedFilter, CommandInGroupFilter
    from .utils import extract_query_from_mention
    from .decorators import telegram_command, discover_telegram_commands
    from .auth import TelegramUserSession, NavigatorAuthClient
    from .context import (
        telegram_chat_scope,
        get_current_telegram_chat_id,
        current_telegram_chat_id,
    )
    from .human_tool import TelegramHumanTool
