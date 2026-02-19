"""Async Matrix client wrapper for AI-Parrot.

Thin abstraction over mautrix.client.Client that exposes only
the operations needed by MatrixHook, MatrixStreamHandler, and
MatrixA2ATransport.
"""
from __future__ import annotations
from collections.abc import Callable, Coroutine
from typing import Any, Dict, Optional
import asyncio
from navconfig.logging import logging

try:
    from mautrix.client import Client as MautrixClient
    from mautrix.types import (
        EventType,
        Format,
        MessageType,
        RoomID,
        EventID,
        TextMessageEventContent,
        RelatesTo,
        RelationType,
        StateEvent,
    )

    HAS_MAUTRIX = True
except ImportError:
    HAS_MAUTRIX = False


class MatrixClientWrapper:
    """Async wrapper around mautrix Client for AI-Parrot operations.

    Handles connection lifecycle, message sending, message editing
    (for streaming), room state management, and event listening.
    """
    def __init__(
        self,
        homeserver: str,
        mxid: str,
        access_token: str,
        *,
        device_id: str = "PARROT",
    ) -> None:
        if not HAS_MAUTRIX:
            raise ImportError(
                "mautrix is required for Matrix integration. "
                "Install with: uv pip install 'ai-parrot[matrix]'"
            )
        self._homeserver = homeserver
        self._mxid = mxid
        self._access_token = access_token
        self._device_id = device_id
        self._client: Optional[MautrixClient] = None
        self._sync_task: Optional[asyncio.Task] = None
        self.logger = logging.getLogger("parrot.matrix.client")

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def connect(self) -> None:
        """Connect to the homeserver and start syncing."""
        from mautrix.types import UserID

        self._client = MautrixClient(
            base_url=self._homeserver,
            mxid=UserID(self._mxid),
            device_id=self._device_id,
        )
        self._client.access_token = self._access_token

        # Verify credentials
        whoami = await self._client.whoami()
        self.logger.info(
            f"Matrix client connected as {whoami.user_id} "
            f"on {self._homeserver}"
        )

    async def start_sync(self) -> None:
        """Start the /sync loop in background."""
        if self._client is None:
            raise RuntimeError("Client not connected. Call connect() first.")
        self._sync_task = asyncio.create_task(
            self._client.start(None)
        )
        self.logger.info("Matrix sync loop started")

    async def disconnect(self) -> None:
        """Stop syncing and close the client."""
        if self._sync_task:
            self._sync_task.cancel()
            try:
                await self._sync_task
            except asyncio.CancelledError:
                pass
            self._sync_task = None
        if self._client:
            self._client.stop()
            self._client = None
        self.logger.info("Matrix client disconnected")

    @property
    def client(self) -> MautrixClient:
        """Access the underlying mautrix Client (for event handler registration)."""
        if self._client is None:
            raise RuntimeError("Client not connected.")
        return self._client

    @property
    def mxid(self) -> str:
        """Return the bot's Matrix ID."""
        return self._mxid

    # ------------------------------------------------------------------
    # Message sending
    # ------------------------------------------------------------------

    async def send_text(
        self,
        room_id: str,
        text: str,
        *,
        html: Optional[str] = None,
        msg_type: str = "m.text",
    ) -> str:
        """Send a text message to a room.

        Args:
            room_id: Target room.
            text: Plain-text body.
            html: Optional HTML formatted body.
            msg_type: Message type (m.text, m.notice, etc.).

        Returns:
            The event_id of the sent message.
        """
        content = TextMessageEventContent(
            msgtype=MessageType(msg_type),
            body=text,
        )
        if html:
            content.format = Format.HTML
            content.formatted_body = html

        event_id = await self._client.send_message(
            RoomID(room_id), content
        )
        return str(event_id)

    async def edit_message(
        self,
        room_id: str,
        original_event_id: str,
        new_text: str,
        *,
        new_html: Optional[str] = None,
    ) -> str:
        """Edit a previously sent message (used for streaming).

        Uses the m.replace relation type per MSC2676.

        Args:
            room_id: Room containing the original message.
            original_event_id: Event ID to edit.
            new_text: New plain-text body.
            new_html: Optional new HTML body.

        Returns:
            The event_id of the edit event.
        """
        content = TextMessageEventContent(
            msgtype=MessageType.TEXT,
            body=f"* {new_text}",
        )
        if new_html:
            content.format = Format.HTML
            content.formatted_body = f"* {new_html}"

        content.set_edit(EventID(original_event_id))
        # m.new_content is set automatically by mautrix's set_edit()

        event_id = await self._client.send_message(
            RoomID(room_id), content
        )
        return str(event_id)

    # ------------------------------------------------------------------
    # Custom events
    # ------------------------------------------------------------------

    async def send_event(
        self,
        room_id: str,
        event_type: str,
        content: Dict[str, Any],
    ) -> str:
        """Send a custom message event to a room.

        Args:
            room_id: Target room.
            event_type: Event type string (e.g., m.parrot.task).
            content: Event content dict.

        Returns:
            The event_id.
        """
        evt_type = EventType.find(event_type, t_class=EventType.Class.MESSAGE)
        event_id = await self._client.send_message_event(
            RoomID(room_id),
            evt_type,
            content,
        )
        return str(event_id)

    async def set_room_state(
        self,
        room_id: str,
        event_type: str,
        content: Dict[str, Any],
        state_key: str = "",
    ) -> str:
        """Set a state event in a room.

        Args:
            room_id: Target room.
            event_type: State event type (e.g., m.parrot.agent_card).
            content: State content dict.
            state_key: State key (default: empty).

        Returns:
            The event_id.
        """
        evt_type = EventType.find(event_type, t_class=EventType.Class.STATE)
        event_id = await self._client.send_state_event(
            RoomID(room_id),
            evt_type,
            content,
            state_key=state_key,
        )
        return str(event_id)

    async def get_room_state_event(
        self,
        room_id: str,
        event_type: str,
        state_key: str = "",
    ) -> Optional[Dict[str, Any]]:
        """Read a state event from a room.

        Args:
            room_id: Room to query.
            event_type: State event type.
            state_key: State key.

        Returns:
            The event content dict, or None if not found.
        """
        try:
            evt_type = EventType.find(
                event_type, t_class=EventType.Class.STATE
            )
            event = await self._client.get_state_event(
                RoomID(room_id), evt_type, state_key=state_key
            )
            if hasattr(event, "serialize"):
                return event.serialize()
            return dict(event) if event else None
        except Exception:
            return None

    # ------------------------------------------------------------------
    # Event handlers
    # ------------------------------------------------------------------

    def on_message(
        self,
        callback: Callable[..., Coroutine[Any, Any, None]],
    ) -> None:
        """Register a handler for m.room.message events.

        The callback receives (room_id: RoomID, event: MessageEvent).
        """
        from mautrix.types import EventType as ET

        self._client.add_event_handler(ET.ROOM_MESSAGE, callback)

    def on_custom_event(
        self,
        event_type: str,
        callback: Callable[..., Coroutine[Any, Any, None]],
    ) -> None:
        """Register a handler for a custom event type.

        Args:
            event_type: The m.parrot.* event type string.
            callback: Async callback receiving the event.
        """
        evt_type = EventType.find(
            event_type, t_class=EventType.Class.MESSAGE
        )
        self._client.add_event_handler(evt_type, callback)
