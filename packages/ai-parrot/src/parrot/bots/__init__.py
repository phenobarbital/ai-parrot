

from .abstract import AbstractBot
from .agent import Agent, BasicAgent
from .base import BaseBot
from .basic import BasicBot
from .chatbot import Chatbot
from .chrome import WebAgent
from .search import WebSearchAgent

__all__ = (
    "AbstractBot",
    "Agent",
    "BaseBot",
    "BasicAgent",
    "BasicBot",
    "Chatbot",
    "InfoAgent",
    "VoiceBot",
    "WebAgent",
    "WebSearchAgent",
)


# Lazy imports: heavy optional classes resolved on first access only.
# - VoiceBot pulls parrot.clients.live -> google.genai (optional google-genai)
# - InfoAgent pulls the heavy a2ui/infographic chain via its mixins
_LAZY_ATTRS = {
    "VoiceBot": ".voice",
    "InfoAgent": ".info",
}


def __getattr__(name: str):
    """Resolve lazily-exported bot classes on first attribute access.

    Args:
        name: Attribute being looked up on the ``parrot.bots`` package.

    Returns:
        The resolved attribute.

    Raises:
        AttributeError: If ``name`` is not a lazy export of this package.
    """
    module_name = _LAZY_ATTRS.get(name)
    if module_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    from importlib import import_module

    attr = getattr(import_module(module_name, __name__), name)
    globals()[name] = attr  # cache to avoid repeated import
    return attr


def __dir__() -> list[str]:
    """Return the public attribute names, including lazy exports."""
    return sorted(set(globals()) | set(__all__))
