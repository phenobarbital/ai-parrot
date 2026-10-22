"""Bot and Agent implementations.

Only the base hierarchy is imported eagerly — ``AbstractBot``, ``BaseBot``,
``BasicAgent`` and ``Agent`` — so ``import parrot.bots`` stays cheap and never
drags optional satellites (ai-parrot-server, ai-parrot-tools, google-genai…)
into the process. Every concrete bot class is still reachable as
``from parrot.bots import X`` but is resolved lazily on first access.
"""

from .abstract import AbstractBot
from .base import BaseBot
from .agent import Agent, BasicAgent

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


# Lazy imports: concrete / heavy classes resolved on first access only.
# - Chatbot is already loaded by ``.agent`` but exported lazily to keep the
#   eager surface to the base hierarchy.
# - WebAgent / WebSearchAgent pull browser and search toolkits.
# - VoiceBot pulls parrot.clients.google.live -> google.genai (optional google-genai)
# - InfoAgent pulls the heavy a2ui/infographic chain via its mixins
_LAZY_ATTRS = {
    "BasicBot": ".basic",
    "Chatbot": ".chatbot",
    "WebAgent": ".chrome",
    "WebSearchAgent": ".search",
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
