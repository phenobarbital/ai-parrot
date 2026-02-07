"""
Custom aiogram filters for Telegram bot message handling.

Provides filters for detecting bot mentions in group messages.
"""
from aiogram import Bot
from aiogram.types import Message
from aiogram.filters.base import Filter


class BotMentionedFilter(Filter):
    """
    Filter that matches messages where the bot is @mentioned.

    Works by checking:
    1. Message entities for 'mention' type matching the bot username
    2. Message text containing @bot_username (fallback)

    Usage:
        @router.message(BotMentionedFilter())
        async def handle_mention(message: Message, bot: Bot):
            ...
    """

    async def __call__(self, message: Message, bot: Bot) -> bool:
        """Check if message contains a mention of this bot."""
        if not message.text:
            return False

        bot_info = await bot.me()
        bot_username = bot_info.username

        if not bot_username:
            return False

        # Check via message entities (more reliable)
        if message.entities:
            for entity in message.entities:
                if entity.type == "mention":
                    mentioned = message.text[
                        entity.offset : entity.offset + entity.length
                    ]
                    if mentioned.lower() == f"@{bot_username.lower()}":
                        return True

        # Fallback: simple text check (case-insensitive)
        if f"@{bot_username.lower()}" in message.text.lower():
            return True

        return False


class CommandInGroupFilter(Filter):
    """
    Filter that matches commands directed at this bot in groups.

    Handles both:
    - /command (standard command)
    - /command@bot_username (command explicitly for this bot)

    Usage:
        @router.message(CommandInGroupFilter("ask"))
        async def handle_ask(message: Message, bot: Bot):
            ...
    """

    def __init__(self, command: str):
        """Initialize with command name (without leading slash)."""
        self.command = command.lower()

    async def __call__(self, message: Message, bot: Bot) -> bool:
        """Check if message is this command for this bot."""
        if not message.text:
            return False

        text = message.text.strip()
        if not text.startswith("/"):
            return False

        bot_info = await bot.me()
        bot_username = bot_info.username or ""

        # Extract command part (before space or end of string)
        command_part = text.split()[0].lower()

        # Check for /command or /command@bot_username
        expected_simple = f"/{self.command}"
        expected_targeted = f"/{self.command}@{bot_username.lower()}"

        return command_part in (expected_simple, expected_targeted)
