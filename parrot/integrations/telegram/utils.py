"""
Utility functions for Telegram bot message processing.

Provides helpers for extracting user queries from group messages.
"""
import re
from typing import Optional

from aiogram import Bot
from aiogram.types import Message


async def extract_query_from_mention(message: Message, bot: Bot) -> str:
    """
    Extract the actual query from a mention or command message.

    Strips the @bot_username and any leading /command from the message
    to get the user's actual query text.

    Args:
        message: The Telegram message
        bot: The aiogram Bot instance

    Returns:
        Cleaned query string with @mention and /command removed

    Examples:
        "@mybot what is Python?" -> "what is Python?"
        "Hey @mybot tell me about AI" -> "Hey tell me about AI"
        "/ask@mybot what is RAG?" -> "what is RAG?"
        "/ask what is machine learning?" -> "what is machine learning?"
    """
    bot_info = await bot.me()
    bot_username = bot_info.username or ""

    text = message.text or ""

    # Remove @username (case-insensitive)
    cleaned = re.sub(
        rf"@{re.escape(bot_username)}\b",
        "",
        text,
        flags=re.IGNORECASE,
    ).strip()

    # Remove leading command if present (e.g., "/ask" or "/ask@botname")
    cleaned = re.sub(
        rf"^/\w+(@{re.escape(bot_username)})?\s*",
        "",
        cleaned,
        flags=re.IGNORECASE,
    ).strip()

    return cleaned


def get_user_display_name(message: Message) -> str:
    """Get a display name for the message sender."""
    if not message.from_user:
        return "Unknown User"

    user = message.from_user
    if user.full_name:
        return user.full_name
    if user.username:
        return f"@{user.username}"
    return f"User {user.id}"
