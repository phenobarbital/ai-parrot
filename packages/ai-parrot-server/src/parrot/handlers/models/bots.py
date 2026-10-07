"""Backward-compatible re-export of the bot models.

``BotModel`` and its companions moved to core :mod:`parrot.models.bots` so that
``parrot.bots`` (and everything that imports it, e.g. ``wikitoolkit``) no longer
depends on the ai-parrot-server distribution at import time. Import from
``parrot.models.bots`` in new code.
"""

from parrot.models.bots import (
    BotModel,
    ChatbotFeedback,
    ChatbotUsage,
    FeedbackType,
    PromptCategory,
    PromptLibrary,
    create_bot,
    created_at,
)

__all__ = [
    "BotModel",
    "ChatbotFeedback",
    "ChatbotUsage",
    "FeedbackType",
    "PromptCategory",
    "PromptLibrary",
    "create_bot",
    "created_at",
]
