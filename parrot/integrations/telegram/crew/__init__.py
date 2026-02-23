"""Telegram Crew Transport — multi-agent crew in a Telegram supergroup.

Provides all public types for configuring and running a crew of AI agents
that communicate via @mentions in a shared Telegram supergroup, managed
by a coordinator bot with a pinned registry message.

Usage::

    from parrot.integrations.telegram.crew import (
        TelegramCrewTransport,
        TelegramCrewConfig,
    )

    config = TelegramCrewConfig.from_yaml("crew.yaml")
    async with TelegramCrewTransport(config) as transport:
        await asyncio.Event().wait()
"""
from .agent_card import AgentCard, AgentSkill
from .config import CrewAgentEntry, TelegramCrewConfig
from .coordinator import CoordinatorBot
from .crew_wrapper import CrewAgentWrapper
from .mention import format_reply, mention_from_card, mention_from_username
from .payload import DataPayload
from .registry import CrewRegistry
from .transport import TelegramCrewTransport

__all__ = [
    "TelegramCrewTransport",
    "TelegramCrewConfig",
    "CrewAgentEntry",
    "AgentCard",
    "AgentSkill",
    "CrewRegistry",
    "CoordinatorBot",
    "CrewAgentWrapper",
    "DataPayload",
    "mention_from_username",
    "mention_from_card",
    "format_reply",
]
