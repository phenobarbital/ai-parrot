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
from .models import TelegramAgentConfig, TelegramBotsConfig
from .wrapper import TelegramAgentWrapper
from .manager import TelegramBotManager
from .filters import BotMentionedFilter, CommandInGroupFilter
from .utils import extract_query_from_mention
from .decorators import telegram_command, discover_telegram_commands
from .auth import TelegramUserSession, NavigatorAuthClient

__all__ = [
    "TelegramAgentConfig",
    "TelegramBotsConfig",
    "TelegramAgentWrapper",
    "TelegramBotManager",
    "BotMentionedFilter",
    "CommandInGroupFilter",
    "extract_query_from_mention",
    "telegram_command",
    "discover_telegram_commands",
    "TelegramUserSession",
    "NavigatorAuthClient",
]
