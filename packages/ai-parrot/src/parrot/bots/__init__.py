

from .abstract import AbstractBot
from .agent import Agent, BasicAgent
from .base import BaseBot
from .basic import BasicBot
from .chatbot import Chatbot
from .chrome import WebAgent
from .search import WebSearchAgent
# FEAT-416 (TASK-2151): export VoiceBot — previously importable only via
# the private `parrot.bots.voice` module path.
from .voice import VoiceBot

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


def __getattr__(name: str):
    # Lazy import: InfoAgent pulls the heavy a2ui/infographic chain via its
    # mixins — only pay the cost when actually requested.
    if name == "InfoAgent":
        from .info import InfoAgent  # noqa: PLC0415

        globals()["InfoAgent"] = InfoAgent
        return InfoAgent
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
