"""MentionBuilder — utilities for constructing @mention strings.

Provides helper functions for building Telegram @mentions from
usernames, user IDs, and AgentCard instances. Used throughout
the crew transport for message addressing.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .agent_card import AgentCard


def mention_from_username(username: str) -> str:
    """Build an @mention string from a Telegram username.

    Idempotent: strips leading @ if already present.

    Args:
        username: Telegram username, with or without leading @.

    Returns:
        String in the format ``@username``.
    """
    return f"@{username.lstrip('@')}"


def mention_from_user_id(user_id: int, display_name: str) -> str:
    """Build a Telegram HTML deep-link mention from a user ID.

    Args:
        user_id: Telegram user ID.
        display_name: Display name shown in the mention link.

    Returns:
        HTML anchor tag linking to the user via ``tg://user?id=``.
    """
    return f'<a href="tg://user?id={user_id}">{display_name}</a>'


def mention_from_card(card: AgentCard) -> str:
    """Build an @mention string from an AgentCard.

    Args:
        card: The AgentCard to extract the username from.

    Returns:
        String in the format ``@username``.
    """
    return f"@{card.telegram_username}"


def format_reply(mention: str, text: str) -> str:
    """Format a response by prepending a mention to the text.

    Args:
        mention: The @mention string to prepend.
        text: The response text body.

    Returns:
        Combined string with mention on the first line,
        followed by the text on a new line.
    """
    return f"{mention}\n{text}"
