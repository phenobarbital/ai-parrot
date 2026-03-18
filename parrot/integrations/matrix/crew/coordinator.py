"""Matrix crew coordinator bot — manages pinned status board.

Maintains a pinned message in the general room that shows the live status
of all agents in the crew (ready / busy / offline).  The board is updated
on every agent join, leave, or status-change event, subject to a
configurable rate limit.
"""
import logging
import time
from datetime import datetime, timezone
from typing import Optional

from .registry import MatrixAgentCard, MatrixCrewRegistry


class MatrixCoordinator:
    """Manages the pinned status board in the general room.

    Creates (or updates) a single pinned message in the general room that
    reflects the current state of all registered agents.  Updates are
    rate-limited to ``_rate_limit_interval`` seconds to avoid excessive edits.

    Args:
        client: A ``MatrixClientWrapper`` (or any object exposing
            ``send_text``, ``edit_message``, and ``client.send_state_event``).
        registry: The shared ``MatrixCrewRegistry``.
        general_room_id: Room ID of the shared general room.
        rate_limit_interval: Minimum seconds between status-board edits.
    """

    def __init__(
        self,
        client,  # MatrixClientWrapper — avoid circular import at module level
        registry: MatrixCrewRegistry,
        general_room_id: str,
        rate_limit_interval: float = 0.5,
    ) -> None:
        self._client = client
        self._registry = registry
        self._room_id = general_room_id
        self._status_event_id: Optional[str] = None
        self._rate_limit_interval: float = rate_limit_interval
        self._last_update: float = 0.0
        self.logger = logging.getLogger(__name__)

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Create the initial status board message and pin it.

        Sends the rendered status board to the general room, stores the
        returned event ID, and pins the message via ``m.room.pinned_events``.
        """
        board = await self._render_board()
        try:
            event_id = await self._client.send_text(self._room_id, board)
            self._status_event_id = event_id
            self._last_update = time.monotonic()
            self.logger.info(
                "Status board posted in %s (event: %s)",
                self._room_id,
                event_id,
            )

            # Pin the message
            await self._pin_message(event_id)
        except Exception as exc:
            self.logger.error("Failed to post status board: %s", exc, exc_info=True)

    async def stop(self) -> None:
        """Post a shutdown notice to the general room."""
        shutdown_text = (
            "AI-Parrot Crew shutting down...\n"
            "All agents are going offline. Goodbye!"
        )
        try:
            await self._client.send_text(self._room_id, shutdown_text)
            self.logger.info("Shutdown notice sent to %s", self._room_id)
        except Exception as exc:
            self.logger.error(
                "Failed to send shutdown notice: %s", exc, exc_info=True
            )

    # ------------------------------------------------------------------
    # Event hooks
    # ------------------------------------------------------------------

    async def on_agent_join(self, card: MatrixAgentCard) -> None:
        """Called when an agent joins the crew.

        Args:
            card: The ``MatrixAgentCard`` of the joining agent.
        """
        self.logger.info("Agent '%s' joined the crew", card.agent_name)
        await self.refresh_status_board()

    async def on_agent_leave(self, agent_name: str) -> None:
        """Called when an agent leaves the crew.

        Args:
            agent_name: Name of the departing agent.
        """
        self.logger.info("Agent '%s' left the crew", agent_name)
        await self.refresh_status_board()

    async def on_status_change(self, agent_name: str) -> None:
        """Called when an agent's status changes.

        Args:
            agent_name: Name of the agent whose status changed.
        """
        await self.refresh_status_board()

    # ------------------------------------------------------------------
    # Status board
    # ------------------------------------------------------------------

    async def refresh_status_board(self) -> None:
        """Re-render and edit the pinned status board message.

        Rate-limited: if called within ``_rate_limit_interval`` seconds of
        the previous update it is silently skipped.
        """
        if self._status_event_id is None:
            self.logger.debug(
                "Status board not yet created; skipping refresh"
            )
            return

        now = time.monotonic()
        if now - self._last_update < self._rate_limit_interval:
            return

        board = await self._render_board()
        try:
            await self._client.edit_message(
                self._room_id,
                self._status_event_id,
                board,
            )
            self._last_update = now
            self.logger.debug("Status board refreshed")
        except Exception as exc:
            self.logger.error(
                "Failed to refresh status board: %s", exc, exc_info=True
            )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _render_board(self) -> str:
        """Render the status board text from the current registry state.

        Returns:
            Multi-line string representing all agent statuses.
        """
        agents = await self._registry.all_agents()
        now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

        lines = [
            "AI-Parrot Crew -- Agent Status",
            "",
        ]

        if agents:
            for card in agents:
                lines.append(card.to_status_line())
        else:
            lines.append("(no agents registered)")

        lines.extend(["", f"Last updated: {now_str}"])
        return "\n".join(lines)

    async def _pin_message(self, event_id: str) -> None:
        """Pin a message in the general room via ``m.room.pinned_events``.

        Args:
            event_id: Event ID of the message to pin.
        """
        try:
            # Use the underlying mautrix client to set pinned events state
            if hasattr(self._client, "set_room_state"):
                await self._client.set_room_state(
                    self._room_id,
                    "m.room.pinned_events",
                    {"pinned": [event_id]},
                )
            elif hasattr(self._client, "client"):
                # Direct mautrix client access
                from mautrix.types import EventType, RoomID, EventID
                await self._client.client.send_state_event(
                    RoomID(self._room_id),
                    EventType.find(
                        "m.room.pinned_events",
                        t_class=EventType.Class.STATE,
                    ),
                    {"pinned": [event_id]},
                )
            self.logger.info("Pinned status board message %s", event_id)
        except Exception as exc:
            self.logger.warning(
                "Could not pin status board: %s", exc
            )
