"""
Integrations package for external service connections.

Provides integration modules for various platforms:
- telegram: Expose agents via Telegram bots
- msteams: Expose agents via MS Teams bots
"""
from .models import (
    IntegrationBotConfig, 
    TelegramAgentConfig, 
    MSTeamsAgentConfig
)
from .manager import IntegrationBotManager

__all__ = [
    "IntegrationBotManager",
    "TelegramAgentConfig",
    "MSTeamsAgentConfig",
    "IntegrationBotConfig",
]
