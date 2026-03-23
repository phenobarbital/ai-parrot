"""Thread-safe in-memory registry of active agents in a crew.

Provides CRUD operations on AgentCard entries and resolution
by Telegram username or agent name.
"""
import asyncio
import logging
from datetime import datetime, timezone
from typing import Dict, List, Optional

from .agent_card import AgentCard

logger = logging.getLogger(__name__)


class CrewRegistry:
    """Thread-safe in-memory registry tracking active agents in the crew.

    All mutating operations use an asyncio.Lock to ensure consistency
    when called from concurrent coroutines.
    """

    def __init__(self) -> None:
        self._agents: Dict[str, AgentCard] = {}  # keyed by telegram_username
        self._lock = asyncio.Lock()
        self.logger = logging.getLogger(__name__)

    async def register(self, card: AgentCard) -> None:
        """Register an agent in the crew.

        Args:
            card: The AgentCard describing the agent to register.
        """
        async with self._lock:
            self._agents[card.telegram_username] = card
            self.logger.info(
                "Registered agent %s (@%s)",
                card.agent_name,
                card.telegram_username,
            )

    async def unregister(self, username: str) -> Optional[AgentCard]:
        """Remove an agent from the registry.

        Args:
            username: Telegram username (with or without @).

        Returns:
            The removed AgentCard, or None if not found.
        """
        username = username.lstrip("@")
        async with self._lock:
            card = self._agents.pop(username, None)
            if card:
                self.logger.info(
                    "Unregistered agent %s (@%s)",
                    card.agent_name,
                    username,
                )
            else:
                self.logger.warning("Attempted to unregister unknown agent @%s", username)
            return card

    async def update_status(
        self,
        username: str,
        status: str,
        current_task: Optional[str] = None,
    ) -> None:
        """Update an agent's status and optionally its current task.

        Also updates the `last_seen` timestamp.

        Args:
            username: Telegram username (with or without @).
            status: New status (ready, busy, offline).
            current_task: Description of current task (when busy).
        """
        username = username.lstrip("@")
        async with self._lock:
            card = self._agents.get(username)
            if card is None:
                self.logger.warning(
                    "Cannot update status for unknown agent @%s", username
                )
                return
            card.status = status
            card.current_task = current_task
            card.last_seen = datetime.now(timezone.utc)
            self.logger.debug(
                "Agent @%s status -> %s (task: %s)",
                username,
                status,
                current_task,
            )

    def get(self, username: str) -> Optional[AgentCard]:
        """Get an agent card by Telegram username.

        Args:
            username: Telegram username (with or without @).

        Returns:
            The AgentCard if found, None otherwise.
        """
        username = username.lstrip("@")
        return self._agents.get(username)

    def list_active(self) -> List[AgentCard]:
        """Return all agents that are not offline.

        Returns:
            List of AgentCard instances with status != 'offline'.
        """
        return [
            card for card in self._agents.values()
            if card.status != "offline"
        ]

    def resolve(self, name_or_username: str) -> Optional[AgentCard]:
        """Resolve an agent by username or agent name.

        Supports both `@username` and `agent_name` (case-insensitive for names).

        Args:
            name_or_username: A Telegram @username or agent name.

        Returns:
            The matching AgentCard, or None if not found.
        """
        # Try username lookup first (strip @ if present)
        cleaned = name_or_username.lstrip("@")
        card = self._agents.get(cleaned)
        if card is not None:
            return card

        # Fall back to case-insensitive agent_name search
        name_lower = name_or_username.lower()
        for card in self._agents.values():
            if card.agent_name.lower() == name_lower:
                return card

        return None
