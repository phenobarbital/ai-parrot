"""
Telegram Integration for AI-Parrot Agents.

Provides Telegram bot functionality using aiogram v3 to expose
agents, crews, and flows via Telegram messaging.

Example YAML configuration (env/telegram_bots.yaml):

    agents:
      HRAgent:
        agent_class: parrot.agents.hr.HRAgent
        welcome_message: "Hello! I'm your HR Assistant."
        allowed_chat_ids: [12345678]
        # bot_token: optional - defaults to HRAGENT_TELEGRAM_TOKEN env var
"""
from .models import TelegramAgentConfig, TelegramBotsConfig
from .wrapper import TelegramAgentWrapper
from .manager import TelegramBotManager

__all__ = [
    "TelegramAgentConfig",
    "TelegramBotsConfig",
    "TelegramAgentWrapper",
    "TelegramBotManager",
]
