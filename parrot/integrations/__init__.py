"""
Integrations package for external service connections.

Provides integration modules for various platforms:
- telegram: Expose agents via Telegram bots
- msteams: Expose agents via MS Teams bots
- whatsapp: Expose agents via WhatsApp Business API
- slack: Expose agents via Slack Events API
"""
from .models import (
    IntegrationBotConfig,
    TelegramAgentConfig,
    MSTeamsAgentConfig,
    WhatsAppAgentConfig,
    SlackAgentConfig,
)
from .manager import IntegrationBotManager

__all__ = [
    "IntegrationBotManager",
    "TelegramAgentConfig",
    "MSTeamsAgentConfig",
    "WhatsAppAgentConfig",
    "IntegrationBotConfig",
    "SlackAgentConfig",
]
