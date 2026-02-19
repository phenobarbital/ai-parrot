"""Matrix Application Service for AI-Parrot.

Wraps mautrix.appservice.AppService to provide:
- Virtual MXIDs for each registered agent
- Event routing from homeserver push to agents
- HookEvent emission compatible with AutonomousOrchestrator
- Lifecycle management (start/stop)
"""
from __future__ import annotations
from typing import Any, Callable, Coroutine, Dict, Optional, Set
import asyncio

from navconfig.logging import logging

try:
    from mautrix.appservice import AppService as MautrixAppService
    from mautrix.appservice import IntentAPI
    from mautrix.types import (
        Event,
        EventType,
        RoomID,
        UserID,
        StateEvent,
    )
    HAS_MAUTRIX = True
except ImportError:
    HAS_MAUTRIX = False

from .models import MatrixAppServiceConfig
from .events import ParrotEventType


# Type alias for event handler callbacks
EventCallback = Callable[[str, str, str, Any], Coroutine[Any, Any, None]]


class MatrixAppService:
    """Matrix Application Service for AI-Parrot.

    Provides each registered agent with a virtual MXID and receives
    events from the homeserver via HTTP push (no polling).

    Usage::

        config = MatrixAppServiceConfig(
            as_token="...",
            hs_token="...",
            homeserver="http://localhost:8008",
            server_name="parrot.local",
            agent_mxid_map={"FinanceAgent": "parrot-finance"},
        )
        appservice = MatrixAppService(config)
        appservice.set_event_callback(my_handler)
        await appservice.start()

        # Each agent gets its own Matrix presence
        await appservice.register_agent("FinanceAgent", "Finance Agent")

        # Send a message as a specific agent
        await appservice.send_as_agent(
            "FinanceAgent", "!room:server", "Revenue is $1M"
        )
    """

    def __init__(self, config: MatrixAppServiceConfig) -> None:
        if not HAS_MAUTRIX:
            raise ImportError(
                "mautrix is required for Matrix integration. "
                "Install with: uv pip install 'ai-parrot[matrix]'"
            )
        self._config = config
        self._appservice: Optional[MautrixAppService] = None
        self._registered_agents: Dict[str, str] = {}  # name → mxid
        self._agent_rooms: Dict[str, Set[str]] = {}  # mxid → room_ids
        self._event_callback: Optional[EventCallback] = None
        self.logger = logging.getLogger("parrot.matrix.appservice")

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Start the Application Service HTTP server."""
        self._appservice = MautrixAppService(
            server=self._config.homeserver,
            domain=self._config.server_name,
            as_token=self._config.as_token,
            hs_token=self._config.hs_token,
            bot_localpart=self._config.bot_localpart,
            id=self._config.as_id,
            log=self.logger,
            query_user=self._query_user,
            query_alias=self._query_alias,
        )

        # Register event handler for all room events
        self._appservice.matrix_event_handler(self._handle_event)

        await self._appservice.start(
            host=self._config.listen_host,
            port=self._config.listen_port,
        )

        self._appservice.ready = True
        self.logger.info(
            f"Matrix AppService started on "
            f"{self._config.listen_host}:{self._config.listen_port} "
            f"(bot: {self._config.bot_mxid})"
        )

        # Auto-join configured rooms
        for room_id in self._config.auto_join_rooms:
            try:
                await self.bot_intent.ensure_joined(RoomID(room_id))
                self.logger.info(f"Bot joined room {room_id}")
            except Exception as exc:
                self.logger.warning(
                    f"Failed to join room {room_id}: {exc}"
                )

    async def stop(self) -> None:
        """Stop the Application Service HTTP server."""
        if self._appservice:
            await self._appservice.stop()
            self._appservice = None
        self._registered_agents.clear()
        self._agent_rooms.clear()
        self.logger.info("Matrix AppService stopped")

    @property
    def running(self) -> bool:
        """Whether the AS is currently running."""
        return self._appservice is not None

    @property
    def bot_intent(self) -> IntentAPI:
        """Get the IntentAPI for the bot user."""
        if not self._appservice:
            raise RuntimeError("AppService not started")
        return self._appservice.intent

    # ------------------------------------------------------------------
    # Agent Management
    # ------------------------------------------------------------------

    async def register_agent(
        self,
        agent_name: str,
        displayname: Optional[str] = None,
    ) -> str:
        """Register an agent as a virtual Matrix user.

        Args:
            agent_name: Agent name (used for MXID generation).
            displayname: Display name for the virtual user.

        Returns:
            The full MXID of the virtual user.
        """
        mxid = self._config.agent_mxid(agent_name)
        intent = self._get_intent(mxid)

        # Ensure the user exists (created on first use by AS)
        await intent.ensure_registered()

        # Set display name
        display = displayname or agent_name
        await intent.set_displayname(display)

        self._registered_agents[agent_name] = mxid
        self._agent_rooms.setdefault(mxid, set())

        self.logger.info(
            f"Registered agent '{agent_name}' as {mxid} "
            f"(displayname: {display})"
        )
        return mxid

    async def unregister_agent(self, agent_name: str) -> None:
        """Remove a virtual agent (leaves rooms, clears state)."""
        mxid = self._registered_agents.pop(agent_name, None)
        if not mxid:
            return

        # Leave all rooms
        rooms = self._agent_rooms.pop(mxid, set())
        intent = self._get_intent(mxid)
        for room_id in rooms:
            try:
                await intent.leave_room(RoomID(room_id))
            except Exception:
                pass

        self.logger.info(f"Unregistered agent '{agent_name}' ({mxid})")

    async def ensure_agent_in_room(
        self,
        agent_name: str,
        room_id: str,
    ) -> None:
        """Join a virtual agent to a room.

        Args:
            agent_name: Name of a registered agent.
            room_id: Room to join.
        """
        mxid = self._registered_agents.get(agent_name)
        if not mxid:
            raise ValueError(
                f"Agent '{agent_name}' not registered. "
                f"Call register_agent() first."
            )

        intent = self._get_intent(mxid)

        # Bot invites, then agent joins
        try:
            await self.bot_intent.invite_user(
                RoomID(room_id), UserID(mxid)
            )
        except Exception:
            pass  # Already invited or member

        await intent.ensure_joined(RoomID(room_id))
        self._agent_rooms.setdefault(mxid, set()).add(room_id)

        self.logger.info(
            f"Agent '{agent_name}' joined room {room_id}"
        )

    def list_agents(self) -> Dict[str, str]:
        """Return mapping of registered agent_name → mxid."""
        return dict(self._registered_agents)

    # ------------------------------------------------------------------
    # Messaging
    # ------------------------------------------------------------------

    async def send_as_agent(
        self,
        agent_name: str,
        room_id: str,
        message: str,
    ) -> str:
        """Send a message to a room as a specific agent.

        Args:
            agent_name: Name of the registered agent.
            room_id: Target room.
            message: Message text.

        Returns:
            Event ID of the sent message.
        """
        mxid = self._registered_agents.get(agent_name)
        if not mxid:
            raise ValueError(f"Agent '{agent_name}' not registered")

        intent = self._get_intent(mxid)
        event_id = await intent.send_text(RoomID(room_id), message)
        return str(event_id)

    async def send_as_bot(self, room_id: str, message: str) -> str:
        """Send a message as the bot user."""
        event_id = await self.bot_intent.send_text(
            RoomID(room_id), message
        )
        return str(event_id)

    # ------------------------------------------------------------------
    # Event handling
    # ------------------------------------------------------------------

    def set_event_callback(self, callback: EventCallback) -> None:
        """Set the callback for incoming room messages.

        The callback signature:
            async def handler(
                room_id: str,
                sender: str,
                message: str,
                raw_event: Any,
            ) -> None
        """
        self._event_callback = callback

    async def _handle_event(self, event: Event) -> None:
        """Process events pushed by the homeserver."""
        try:
            # Only handle room messages
            if event.type != EventType.ROOM_MESSAGE:
                return

            room_id = str(event.room_id)
            sender = str(event.sender)
            body = ""

            if hasattr(event, "content") and hasattr(event.content, "body"):
                body = event.content.body or ""

            # Ignore messages from our own virtual users
            if sender in self._registered_agents.values():
                return
            if sender == self._config.bot_mxid:
                return

            # Ignore edits
            if hasattr(event.content, "relates_to") and event.content.relates_to:
                if hasattr(event.content.relates_to, "rel_type"):
                    if str(event.content.relates_to.rel_type) == "m.replace":
                        return

            if not body:
                return

            if self._event_callback:
                await self._event_callback(room_id, sender, body, event)

        except Exception as exc:
            self.logger.error(
                f"Error handling event: {exc}", exc_info=True
            )

    async def _query_user(self, user_id: str) -> Optional[dict]:
        """Respond to homeserver user existence queries."""
        # Accept any user in our namespace
        user = UserID(user_id) if isinstance(user_id, str) else user_id
        localpart = str(user).split(":")[0].lstrip("@")

        import re
        if re.match(self._config.namespace_regex, localpart):
            return {}
        return None

    async def _query_alias(self, alias: str) -> Optional[dict]:
        """Respond to room alias queries (not used yet)."""
        return None

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_intent(self, mxid: str) -> IntentAPI:
        """Get IntentAPI for a virtual user."""
        if not self._appservice:
            raise RuntimeError("AppService not started")
        return self._appservice.intent.user(UserID(mxid))

    # ------------------------------------------------------------------
    # Context manager
    # ------------------------------------------------------------------

    async def __aenter__(self) -> "MatrixAppService":
        await self.start()
        return self

    async def __aexit__(self, *args) -> None:
        await self.stop()
