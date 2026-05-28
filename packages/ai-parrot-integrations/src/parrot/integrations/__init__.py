"""
Integrations package for external service connections.

Provides integration modules for various platforms:
- telegram: Expose agents via Telegram bots
- msteams: Expose agents via MS Teams bots
- whatsapp: Expose agents via WhatsApp Business API
- slack: Expose agents via Slack Events API
"""
# Lazy re-exports (PEP 562). `IntegrationBotManager` pulls aiogram (~1.5s),
# so we defer it until the caller actually touches the symbol. Importing a
# submodule path (e.g. parrot.integrations.oauth2.registry) no longer drags
# aiogram in.
import importlib
from typing import TYPE_CHECKING

_LAZY_EXPORTS = {
    "IntegrationBotConfig": ".models",
    "TelegramAgentConfig": ".models",
    "MSTeamsAgentConfig": ".models",
    "WhatsAppAgentConfig": ".models",
    "SlackAgentConfig": ".models",
    "IntegrationBotManager": ".manager",
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
    from .models import (
        IntegrationBotConfig,
        TelegramAgentConfig,
        MSTeamsAgentConfig,
        WhatsAppAgentConfig,
        SlackAgentConfig,
    )
    from .manager import IntegrationBotManager
