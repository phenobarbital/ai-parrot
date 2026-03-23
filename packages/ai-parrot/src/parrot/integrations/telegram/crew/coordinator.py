"""CoordinatorBot — manages the pinned registry message in a crew supergroup.

The CoordinatorBot is a non-agent bot that maintains a pinned message
showing which agents are online, busy, or offline. It provides real-time
visibility of the crew's collective state.
"""
import asyncio
import logging
from typing import Optional

from aiogram import Bot

from .agent_card import AgentCard
from .registry import CrewRegistry

logger = logging.getLogger(__name__)

# Rate limit delay between consecutive Telegram API edits (seconds)
_EDIT_DELAY = 0.3


class CoordinatorBot:
    """Non-agent bot that manages the pinned registry message.

    Args:
        token: Telegram Bot API token for the coordinator bot.
        group_id: Telegram supergroup chat ID.
        registry: The CrewRegistry tracking active agents.
        username: Telegram username of the coordinator bot.
    """

    def __init__(
        self,
        token: str,
        group_id: int,
        registry: CrewRegistry,
        username: str = "",
        bot: Optional[Bot] = None,
    ) -> None:
        self.bot = bot if bot is not None else Bot(token=token)
        self.group_id = group_id
        self.registry = registry
        self.username = username
        self._pinned_message_id: Optional[int] = None
        self._lock = asyncio.Lock()
        self.logger = logging.getLogger(__name__)

    async def start(self) -> None:
        """Initialize the coordinator bot and send the initial pinned registry message."""
        self.logger.info("Starting CoordinatorBot in group %d", self.group_id)
        text = self._render_registry()
        msg = await self.bot.send_message(
            chat_id=self.group_id,
            text=text,
        )
        self._pinned_message_id = msg.message_id
        try:
            await self.bot.pin_chat_message(
                chat_id=self.group_id,
                message_id=self._pinned_message_id,
                disable_notification=True,
            )
        except Exception as e:
            self.logger.warning("Failed to pin registry message: %s", e)
        self.logger.info(
            "Pinned registry message (id=%d) in group %d",
            self._pinned_message_id,
            self.group_id,
        )

    async def stop(self) -> None:
        """Gracefully shut down the coordinator bot."""
        self.logger.info("Stopping CoordinatorBot")
        try:
            await self.bot.session.close()
        except Exception as e:
            self.logger.warning("Error closing bot session: %s", e)

    async def on_agent_join(self, card: AgentCard) -> None:
        """Handle an agent joining the crew.

        Registers the agent in the registry and updates the pinned message.

        Args:
            card: The AgentCard of the joining agent.
        """
        await self.registry.register(card)
        self.logger.info("Agent @%s joined the crew", card.telegram_username)
        await self.update_registry()

    async def on_agent_leave(self, username: str) -> None:
        """Handle an agent leaving the crew.

        Unregisters the agent and updates the pinned message.

        Args:
            username: Telegram username of the leaving agent.
        """
        removed = await self.registry.unregister(username)
        if removed:
            self.logger.info("Agent @%s left the crew", username)
        await self.update_registry()

    async def on_agent_status_change(
        self,
        username: str,
        status: str,
        task: Optional[str] = None,
    ) -> None:
        """Handle an agent status change.

        Updates the agent's status in the registry and edits the pinned message.

        Args:
            username: Telegram username of the agent.
            status: New status (ready, busy, offline).
            task: Description of current task (when busy).
        """
        await self.registry.update_status(username, status, task)
        self.logger.debug("Agent @%s status -> %s", username, status)
        await self.update_registry()

    async def update_registry(self) -> None:
        """Render and edit the pinned registry message.

        Serializes concurrent edit attempts with an asyncio.Lock.
        Silently ignores Telegram "message not modified" errors.
        """
        async with self._lock:
            if self._pinned_message_id is None:
                self.logger.debug("No pinned message to update")
                return

            text = self._render_registry()
            try:
                await self.bot.edit_message_text(
                    text=text,
                    chat_id=self.group_id,
                    message_id=self._pinned_message_id,
                )
            except Exception as e:
                # Silently ignore "message is not modified" errors
                error_msg = str(e).lower()
                if "not modified" not in error_msg:
                    self.logger.warning("Failed to edit registry message: %s", e)

            # Rate limit between edits
            await asyncio.sleep(_EDIT_DELAY)

    def _render_registry(self) -> str:
        """Build the pinned registry message text from registry entries.

        Returns:
            Formatted text showing all registered agents and their status.
        """
        agents = self.registry.list_active()
        # Also include offline agents for completeness in the pinned message
        all_agents = list(self.registry._agents.values())

        if not all_agents:
            return "Crew Registry\n\nNo agents registered."

        lines = ["Crew Registry", ""]
        for card in all_agents:
            lines.append(card.to_registry_line())

        lines.append("")
        active_count = len(agents)
        total_count = len(all_agents)
        lines.append(f"Active: {active_count}/{total_count}")

        return "\n".join(lines)
