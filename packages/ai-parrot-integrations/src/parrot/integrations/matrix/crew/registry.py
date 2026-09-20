"""Thread-safe in-memory agent registry for Matrix multi-agent crew.

Provides CRUD operations on ``MatrixAgentCard`` entries and resolution
by agent name or full MXID.
"""

import asyncio
import logging
import re
from datetime import datetime, timezone
from typing import Dict, List, Optional

from pydantic import BaseModel, Field


class MatrixAgentCard(BaseModel):
    """Agent identity and runtime status for a Matrix crew.

    Attributes:
        agent_name: Internal agent name (key in the crew config).
        display_name: Human-readable display name shown in Matrix.
        mxid: Full ``@user:server`` Matrix ID.
        status: Current status — one of ``ready``, ``busy``, ``offline``.
        current_task: Short description of the current task (when busy).
        skills: Skill descriptions shown on the status board.
        joined_at: Timestamp when the agent joined the crew.
        last_seen: Timestamp of the last status update.
    """

    agent_name: str
    display_name: str
    mxid: str = Field(..., description="Full @user:server MXID")
    status: str = Field(default="offline", description="ready | busy | offline")
    current_task: Optional[str] = None
    skills: List[str] = Field(default_factory=list)
    joined_at: Optional[datetime] = None
    last_seen: Optional[datetime] = None

    model_config = {"arbitrary_types_allowed": True}

    def to_status_line(self) -> str:
        """Render a status line for the pinned status board.

        Returns:
            A formatted single-line status string, e.g.::

                [ready] @analyst -- Financial Analyst | Skills: Stock analysis
                [busy: analyzing AAPL] @researcher -- Research Assistant
                [offline] @assistant -- General Assistant
        """
        localpart = self.mxid.split(":")[0].lstrip("@")

        if self.status == "busy" and self.current_task:
            status_str = f"[busy: {self.current_task}]"
        else:
            status_str = f"[{self.status}]"

        line = f"{status_str} @{localpart} -- {self.display_name}"

        if self.skills:
            skills_str = ", ".join(self.skills)
            line += f" | Skills: {skills_str}"

        return line


class MatrixCrewRegistry:
    """Thread-safe in-memory registry tracking agent status in a Matrix crew.

    All mutating operations use an ``asyncio.Lock`` to ensure consistency
    when called from concurrent coroutines.

    Usage::

        registry = MatrixCrewRegistry()
        card = MatrixAgentCard(
            agent_name="analyst",
            display_name="Financial Analyst",
            mxid="@analyst:example.com",
        )
        await registry.register(card)
        await registry.update_status("analyst", "busy", "Analyzing AAPL")
        agent = await registry.get("analyst")
    """

    def __init__(self) -> None:
        self._agents: Dict[str, MatrixAgentCard] = {}  # keyed by agent_name
        self._lock = asyncio.Lock()
        self._bot_mxid: Optional[str] = None
        self._human_patterns: List["re.Pattern"] = []
        self.logger = logging.getLogger(__name__)

    async def register(self, card: MatrixAgentCard) -> None:
        """Register an agent in the crew.

        Sets ``joined_at``, ``last_seen`` to now, and ``status`` to ``"ready"``.

        Args:
            card: The ``MatrixAgentCard`` describing the agent to register.
        """
        async with self._lock:
            now = datetime.now(timezone.utc)
            card.joined_at = now
            card.last_seen = now
            card.status = "ready"
            self._agents[card.agent_name] = card
            self.logger.info(
                "Registered agent '%s' as %s",
                card.agent_name,
                card.mxid,
            )

    async def unregister(self, agent_name: str) -> None:
        """Remove an agent from the registry.

        Args:
            agent_name: The agent's name key in the registry.
        """
        async with self._lock:
            card = self._agents.pop(agent_name, None)
            if card:
                self.logger.info(
                    "Unregistered agent '%s' (%s)",
                    agent_name,
                    card.mxid,
                )
            else:
                self.logger.warning(
                    "Attempted to unregister unknown agent '%s'",
                    agent_name,
                )

    async def update_status(
        self,
        agent_name: str,
        status: str,
        current_task: Optional[str] = None,
    ) -> None:
        """Update an agent's status and optionally its current task.

        Also updates the ``last_seen`` timestamp.

        Args:
            agent_name: The agent's name key.
            status: New status (``ready``, ``busy``, or ``offline``).
            current_task: Short description of the current task (when busy).
        """
        async with self._lock:
            card = self._agents.get(agent_name)
            if card is None:
                self.logger.warning(
                    "Cannot update status for unknown agent '%s'",
                    agent_name,
                )
                return
            card.status = status
            card.current_task = current_task
            card.last_seen = datetime.now(timezone.utc)
            self.logger.debug(
                "Agent '%s' status → %s (task: %s)",
                agent_name,
                status,
                current_task,
            )

    async def get(self, agent_name: str) -> Optional[MatrixAgentCard]:
        """Get an agent card by agent name.

        Args:
            agent_name: The agent's name key.

        Returns:
            The ``MatrixAgentCard`` if found, ``None`` otherwise.
        """
        async with self._lock:
            return self._agents.get(agent_name)

    async def get_by_mxid(self, mxid: str) -> Optional[MatrixAgentCard]:
        """Find an agent card by its full MXID.

        Iterates the registry — O(n), acceptable for small crews.

        Args:
            mxid: Full ``@user:server`` Matrix ID.

        Returns:
            The matching ``MatrixAgentCard``, or ``None`` if not found.
        """
        async with self._lock:
            for card in self._agents.values():
                if card.mxid == mxid:
                    return card
            return None

    async def all_agents(self) -> List[MatrixAgentCard]:
        """Return all registered agents.

        Returns:
            List of all ``MatrixAgentCard`` instances in registration order.
        """
        async with self._lock:
            return list(self._agents.values())

    # ------------------------------------------------------------------
    # Human classification (FEAT-463)
    # ------------------------------------------------------------------

    def set_bot_mxid(self, mxid: str) -> None:
        """Set the coordinator bot's MXID for human classification.

        Args:
            mxid: The coordinator bot's full MXID.
        """
        self._bot_mxid = mxid

    def set_human_patterns(self, patterns: List[str]) -> None:
        """Set the bridge-puppet regex patterns used to *confirm* humans.

        These patterns identify MXIDs known to be bridged human puppets
        (e.g. Slack/Signal/Discord). They are informational — ``is_human``
        already treats any MXID that isn't a registered agent or the bot
        as human; matching one of these patterns simply confirms it.

        Args:
            patterns: List of regex pattern strings.
        """
        self._human_patterns = [re.compile(p) for p in patterns]

    def is_human(self, mxid: str) -> bool:
        """Classify an MXID as human (not an agent, not the coordinator bot).

        Any MXID matching a registered agent's ``mxid`` or the coordinator
        bot's MXID is NOT human. Every other MXID — including bridged
        puppets matching ``human_namespace_patterns`` and plain native
        Matrix users — is human.

        Args:
            mxid: Full ``@user:server`` Matrix ID to classify.

        Returns:
            ``True`` if ``mxid`` is not a known agent or the bot.
        """
        if mxid == self._bot_mxid:
            return False
        for card in self._agents.values():
            if card.mxid == mxid:
                return False
        return True
