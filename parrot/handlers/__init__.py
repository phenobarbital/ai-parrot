"""
Parrot basic Handlers.
"""
from .bots import ChatbotHandler
from .dashboard_handler import DashboardHandler, DashboardTabHandler
from .llm import LLMClient


def __getattr__(name: str):
    """Lazy import for BotConfigHandler to avoid circular import with parrot.registry."""
    if name == "BotConfigHandler":
        from .config_handler import BotConfigHandler
        return BotConfigHandler
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
