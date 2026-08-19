

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
    "VoiceBot",
    "WebAgent",
    "WebSearchAgent",
)


# FEAT-416 (TASK-2151) exported VoiceBot eagerly, which pulled
# `parrot.bots.voice` -> `parrot.clients.live` -> `from google import genai`
# into EVERY importer of `parrot.bots` — making the optional `google-genai`
# dependency a hard requirement of the agent REPL, agentd and every bot.
# Kept in `__all__` (the public name is unchanged) but resolved lazily via
# PEP 562 so only actual voice users pay for it.
_LAZY_ATTRS = {"VoiceBot": ".voice"}


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

    return getattr(import_module(module_name, __name__), name)


def __dir__() -> list[str]:
    """Return the public attribute names, including lazy exports."""
    return sorted(set(globals()) | set(__all__))
