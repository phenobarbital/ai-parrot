"""Matrix protocol hook for AutonomousOrchestrator.

Concrete implementation of :class:`~navigator_eventbus.hooks.base.BaseHook`
for the Matrix messaging protocol. Listens to Matrix room messages via
mautrix-python and routes them to agents/crews.

This module auto-registers ``MatrixHook`` with
:class:`~navigator_eventbus.hooks.base.HookRegistry` on import::

    import parrot.integrations.matrix.hook   # triggers auto-registration

Features:
- Listens to room messages via /sync loop
- Filters by allowed_users (MXIDs)
- Supports command_prefix (e.g., "!ask")
- Routes to specific agents based on room_routing config
- Auto-reply support via Matrix
"""
from __future__ import annotations

from typing import Any, Dict

from navigator_eventbus.hooks.base import BaseHook, HookRegistry
from navigator_eventbus.hooks.models import HookType, MatrixHookConfig


class MatrixHook(BaseHook):
    """Matrix message listener via mautrix-python.

    Example configuration::

        config = MatrixHookConfig(
            name="matrix_hook",
            enabled=True,
            target_type="agent",
            target_id="AssistantAgent",
            homeserver="http://localhost:8008",
            bot_mxid="@parrot-bot:parrot.local",
            access_token="syt_...",
            command_prefix="!ask",
            allowed_users=["@jesus:parrot.local"],
            room_routing={
                "!sales-room:parrot.local": "SalesAgent",
                "!finance-room:parrot.local": "FinanceCrew",
            },
        )

    Args:
        config: Matrix hook configuration.
        **kwargs: Extra keyword arguments forwarded to :class:`BaseHook`.
    """

    hook_type = HookType.MATRIX

    def __init__(self, config: MatrixHookConfig, **kwargs: Any) -> None:
        super().__init__(
            name=config.name,
            enabled=config.enabled,
            target_type=config.target_type,
            target_id=config.target_id,
            metadata=config.metadata,
            **kwargs,
        )
        self._config = config
        self._wrapper = None  # MatrixClientWrapper
        self._allowed_users = (
            set(config.allowed_users) if config.allowed_users else None
        )
        self._room_routing: Dict[str, str] = config.room_routing or {}

    async def start(self) -> None:
        """Connect to Matrix homeserver and start listening."""
        from parrot.integrations.matrix.client import MatrixClientWrapper

        if not self._config.bot_mxid or not self._config.access_token:
            raise ValueError(
                "MatrixHookConfig requires bot_mxid and access_token"
            )

        self._wrapper = MatrixClientWrapper(
            homeserver=self._config.homeserver,
            mxid=self._config.bot_mxid,
            access_token=self._config.access_token,
            device_id=self._config.device_id,
        )

        await self._wrapper.connect()

        # Register message handler
        self._wrapper.on_message(self._on_room_message)

        # Start sync loop
        await self._wrapper.start_sync()

        self.logger.info(
            "MatrixHook '%s' started as %s on %s",
            self.name, self._config.bot_mxid, self._config.homeserver,
        )

    async def stop(self) -> None:
        """Stop listening and disconnect."""
        if self._wrapper:
            await self._wrapper.disconnect()
            self._wrapper = None
        self.logger.info("MatrixHook '%s' stopped", self.name)

    async def _on_room_message(self, event: Any) -> None:
        """Handle incoming m.room.message events from the sync loop.

        Args:
            event: Raw mautrix event.
        """
        try:
            # Extract fields from mautrix event
            room_id = str(event.room_id)
            sender = str(event.sender)
            body = event.content.body if hasattr(event.content, "body") else ""

            # Ignore our own messages
            if sender == self._config.bot_mxid:
                return

            # Ignore edits (m.replace) — only process original messages
            if hasattr(event.content, "relates_to") and event.content.relates_to:
                if hasattr(event.content.relates_to, "rel_type"):
                    rel_type = str(event.content.relates_to.rel_type)
                    if rel_type == "m.replace":
                        return

            await self._handle_message(room_id, sender, body, event)

        except Exception as exc:
            self.logger.error(
                "Error processing Matrix message: %s",
                exc,
                exc_info=True,
            )

    async def _handle_message(
        self,
        room_id: str,
        sender: str,
        body: str,
        raw_event: Any,
    ) -> None:
        """Process a message and route to the appropriate agent.

        Args:
            room_id: Matrix room ID.
            sender: Sender MXID.
            body: Message body text.
            raw_event: Raw mautrix event object.
        """
        # 1. Filter by allowed users
        if self._allowed_users and sender not in self._allowed_users:
            self.logger.debug("Ignoring message from non-allowed user: %s", sender)
            return

        # 2. Check command prefix
        original_content = body
        if self._config.command_prefix:
            if not body.startswith(self._config.command_prefix):
                return
            body = body[len(self._config.command_prefix):].strip()

        if not body:
            return

        # 3. Routing — room-based, then default
        target_id = self.target_id
        target_type = self.target_type
        matched_route = None

        if room_id in self._room_routing:
            target_id = self._room_routing[room_id]
            matched_route = f"room:{room_id}"

        # 4. Build session_id for conversation continuity
        session_id = f"matrix_{sender}_{room_id}"

        # 5. Emit HookEvent
        event = self._make_event(
            event_type="matrix.message",
            payload={
                # User identification
                "sender": sender,
                "user_id": sender,
                # Message content
                "content": body,
                "original_content": original_content,
                "event_id": str(raw_event.event_id)
                if hasattr(raw_event, "event_id")
                else "",
                # Room info
                "room_id": room_id,
                # Session management
                "session_id": session_id,
                # Routing info
                "matched_route": matched_route,
                # Auto-reply configuration
                "reply_via_matrix": self._config.auto_reply,
                "matrix_config": {
                    "room_id": room_id,
                    "auto_reply": self._config.auto_reply,
                },
                # Raw event type for debugging
                "raw_event_type": str(raw_event.type)
                if hasattr(raw_event, "type")
                else "m.room.message",
            },
            task=body,
        )

        # Override target from routing
        if target_id:
            event.target_id = target_id
        if target_type:
            event.target_type = target_type

        self.logger.info(
            "Matrix from %s in %s: '%s...' -> %s via %s",
            sender,
            room_id,
            body[:50],
            target_id or "default",
            matched_route or "default",
        )

        # Send event to orchestrator
        await self.on_event(event)

    async def send_reply(
        self,
        room_id: str,
        message: str,
    ) -> bool:
        """Send a reply to a Matrix room.

        Called by the orchestrator after processing.

        Args:
            room_id: Target room ID.
            message: Message content.

        Returns:
            True if sent successfully, False otherwise.
        """
        if not self._config.auto_reply:
            self.logger.debug("Auto-reply disabled, skipping send")
            return False

        if not self._wrapper:
            self.logger.error("Cannot send reply: Matrix client not connected")
            return False

        try:
            await self._wrapper.send_text(room_id, message)
            self.logger.info("Reply sent to %s", room_id)
            return True
        except Exception as exc:
            self.logger.error("Failed to send Matrix reply: %s", exc)
            return False


# Auto-register with HookRegistry on import
HookRegistry.register("matrix", MatrixHook)
