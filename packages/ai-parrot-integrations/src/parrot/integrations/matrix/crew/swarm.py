"""Concurrent swarm session manager for the Matrix agent swarm (FEAT-463).

``SwarmSessionManager`` enforces ``CollaborativeConfig.max_concurrent_sessions``
per room and ``cooldown_seconds`` between trigger events, and starts
``MatrixCollaborativeSession`` instances as background tasks — replacing the
single-session-per-room limit with a concurrent, per-session-id map.
"""
import asyncio
import logging
import time
import uuid
from typing import TYPE_CHECKING, List, Optional

from .config import CollaborativeConfig

if TYPE_CHECKING:
    from .session import MatrixCollaborativeSession
    from .transport import MatrixCrewTransport


class SwarmSessionManager:
    """Starts and bounds concurrent collaborative sessions per room.

    Attributes:
        config: Collaborative session configuration (concurrency cap, cooldown).
    """

    def __init__(self, config: CollaborativeConfig, transport: "MatrixCrewTransport") -> None:
        """Initialize the swarm session manager.

        Args:
            config: Collaborative session configuration.
            transport: The owning ``MatrixCrewTransport`` (used for
                ``_active_sessions``, ``_build_session``, ``_run_session``,
                and ``_appservice``).
        """
        self._cfg = config
        self._t = transport
        self._last_start: dict = {}
        self.logger = logging.getLogger("parrot.matrix.swarm")

    def active(self, room_id: str) -> List["MatrixCollaborativeSession"]:
        """List active sessions in a room.

        Args:
            room_id: The Matrix room id.

        Returns:
            The active (not completed/failed) sessions currently running in
            that room.
        """
        return [s for s in self._t._active_sessions.get(room_id, {}).values() if s.is_active]

    async def maybe_start(
        self,
        room_id: str,
        sender: str,
        body: str,
        event_id: str,
        *,
        explicit: bool = False,
    ) -> Optional[str]:
        """Start a new collaborative session, subject to cap and cooldown.

        Args:
            room_id: Matrix room id the trigger occurred in.
            sender: MXID of the human who triggered the session.
            body: The question / trigger text.
            event_id: Event id of the triggering message.
            explicit: When ``True`` (e.g. ``!investigate``), the cooldown
                check is skipped — only the concurrency cap still applies.

        Returns:
            The new session's id, or ``None`` when the room is at capacity
            or the request was suppressed by the cooldown.
        """
        now = time.monotonic()

        if len(self.active(room_id)) >= self._cfg.max_concurrent_sessions:
            await self._t._appservice.send_reply_as_bot(
                room_id, "🐦 Swarm is busy — try again shortly.", event_id
            )
            return None

        if not explicit and now - self._last_start.get(room_id, 0.0) < self._cfg.cooldown_seconds:
            self.logger.debug("cooldown active in %s", room_id)
            return None

        session_id = uuid.uuid4().hex[:8]
        session = self._t._build_session(session_id, room_id, body, trigger_event_id=event_id)
        self._t._active_sessions.setdefault(room_id, {})[session_id] = session
        self._last_start[room_id] = now

        asyncio.create_task(
            self._t._run_session(room_id, session),
            name=f"swarm-{room_id}-{session_id}",
        )
        return session_id
