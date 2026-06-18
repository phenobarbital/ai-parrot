"""FULL Mode Room Observer (FEAT-248 — Module 6).

Joins the LiveAvatar-managed LiveKit room as a passive (non-publishing)
participant to log data-channel events and relay structured outputs to the
AgentChat UI via :class:`OutputBridge`.

**Q-room-token gate (open question)**
--------------------------------------
This module is gated by Q-room-token: the backend needs a LiveKit participant
token to join the LiveAvatar-managed room.  The ``/start`` response currently
returns only ``livekit_client_token`` (intended for the browser).  The backend
would need its own participant token — either from LiveAvatar (undocumented) or
by minting one with our own LiveKit API credentials (requires the same LiveKit
project).

Resolution path:
1. If LiveAvatar exposes a backend participant token in its ``/start`` response
   (or via a separate API), use that.
2. If we can mint a token with our own LiveKit credentials (same project), wire
   ``LiveKitRoomManager`` here.
3. If neither is available, :meth:`connect` falls back to post-session transcript
   retrieval via :meth:`LiveAvatarClient.get_session_transcript`.

Until Q-room-token is resolved, :meth:`connect` logs a warning and returns
without crashing.  The observer is wired into the start handler as an optional
component — sessions work correctly without it.

**Event channel**
-----------------
The LiveAvatar data channel topic is ``"agent-response"``.  Messages are
JSON envelopes with the structure::

    {
        "event_id": "<uuid>",
        "event_type": "<user.transcription|avatar.speak_started|...>",
        "session_id": "<liveavatar-session-id>",
        "text": "<optional text payload>"
    }

Known event types:
- ``user.transcription`` — user speech transcription from LiveAvatar STT.
- ``avatar.speak_started`` — avatar started speaking.
- ``avatar.speak_ended`` — avatar finished speaking.
- ``avatar.transcription`` — avatar's spoken text.
- ``session.stopped`` — LiveAvatar session ended.
"""
from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Any, Dict, Optional

from parrot.integrations.liveavatar.models import FullModeSessionHandle

if TYPE_CHECKING:
    from parrot.integrations.liveavatar.output_bridge import OutputBridge

_logger = logging.getLogger("Parrot.FullModeRoomObserver")

# Data channel topic name used by the LiveAvatar FULL mode managed room.
_AGENT_RESPONSE_TOPIC = "agent-response"


class FullModeRoomObserver:
    """Passive observer for a LiveAvatar FULL mode LiveKit room.

    Joins the room as a non-publishing participant, listens for data
    channel events on the ``"agent-response"`` topic, and relays structured
    outputs via :class:`~parrot.integrations.liveavatar.output_bridge.OutputBridge`.

    The observer is entirely optional — the FULL mode session works without
    it.  When Q-room-token is unresolved, :meth:`connect` logs a warning
    and skips the LiveKit connection.

    Args:
        handle: The active FULL mode session handle containing ``livekit_url``
            and session identifiers.
        output_bridge: Optional :class:`OutputBridge` for forwarding data-channel
            events to the AgentChat UI channel.  When ``None``, events are
            only logged.
    """

    def __init__(
        self,
        handle: FullModeSessionHandle,
        output_bridge: Optional["OutputBridge"] = None,
    ) -> None:
        self._handle = handle
        self._bridge = output_bridge
        self._connected: bool = False
        # Placeholder for the live livekit.Room object once Q-room-token
        # is resolved and the connection is established.
        self._room: Optional[Any] = None

    @property
    def connected(self) -> bool:
        """Return ``True`` if the observer is currently connected to the room."""
        return self._connected

    async def connect(self) -> None:
        """Join the LiveKit room as a passive observer.

        **Q-room-token gate**: If ``livekit_url`` is empty (or the backend
        cannot obtain a participant token), logs a warning and returns without
        raising.  The session continues normally — the observer is optional.

        Once Q-room-token is resolved, replace the TODO block below with::

            from livekit import rtc
            room = rtc.Room()
            await room.connect(self._handle.livekit_url, backend_participant_token)
            room.on("data_received", self._on_data)
            self._room = room
            self._connected = True
        """
        if not self._handle.livekit_url:
            _logger.warning(
                "FullModeRoomObserver: livekit_url is empty on handle %s — "
                "Q-room-token may be unresolved.  Skipping room connection.",
                self._handle.liveavatar_session_id,
            )
            return

        # TODO Q-room-token: obtain a backend participant token and connect.
        # Until the token source is resolved the observer cannot join the room.
        # Implementation sketch (replace this block when token is available):
        #
        #   from livekit import rtc  # requires livekit-rtc extra
        #   backend_token = await _obtain_backend_token(self._handle)
        #   if not backend_token:
        #       _logger.warning("FullModeRoomObserver: could not obtain backend token")
        #       return
        #   self._room = rtc.Room()
        #   await self._room.connect(self._handle.livekit_url, backend_token)
        #   self._room.on("data_received", self._on_data)
        #   self._connected = True
        #   _logger.info(
        #       "FullModeRoomObserver: connected to room %s",
        #       self._handle.liveavatar_session_id,
        #   )

        _logger.debug(
            "FullModeRoomObserver: Q-room-token not yet resolved — "
            "observer is in stub mode for session %s.",
            self._handle.liveavatar_session_id,
        )

    async def disconnect(self) -> None:
        """Leave the LiveKit room gracefully (idempotent).

        Safe to call multiple times.  If the room was never connected (e.g.
        Q-room-token gate) this is a no-op.
        """
        if self._room is not None:
            try:
                # TODO Q-room-token: await self._room.disconnect()
                pass
            except Exception:  # noqa: BLE001
                _logger.warning(
                    "FullModeRoomObserver: error during room disconnect for %s",
                    self._handle.liveavatar_session_id,
                    exc_info=True,
                )
            finally:
                self._room = None

        self._connected = False
        _logger.debug(
            "FullModeRoomObserver: disconnected from session %s",
            self._handle.liveavatar_session_id,
        )

    async def _on_data(self, data: bytes, topic: str) -> None:
        """Handle an incoming data channel message.

        Args:
            data: Raw bytes of the JSON message payload.
            topic: Data channel topic name.  Only ``"agent-response"`` messages
                are processed; all others are silently ignored.
        """
        if topic != _AGENT_RESPONSE_TOPIC:
            return

        try:
            event: Dict[str, Any] = json.loads(data.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            _logger.warning(
                "FullModeRoomObserver: failed to decode data-channel message: %s", exc
            )
            return

        event_type: str = event.get("event_type", "unknown")
        _logger.debug(
            "FullModeRoomObserver: received event_type=%s session=%s",
            event_type,
            event.get("session_id", "?"),
        )

        # Forward to the OutputBridge if available.
        if self._bridge is not None:
            await self._forward_event(event_type, event)

    async def _forward_event(
        self, event_type: str, event: Dict[str, Any]
    ) -> None:
        """Forward a data-channel event to the AgentChat UI via OutputBridge.

        Args:
            event_type: The ``event_type`` field from the data-channel envelope.
            event: The full parsed event dict.
        """
        try:
            from parrot.integrations.liveavatar.livekit_agent.models import (
                StructuredOutputMessage,
            )

            msg = StructuredOutputMessage(
                type=event_type,
                session_id=self._handle.session_id or self._handle.liveavatar_session_id,
                payload=event,
            )
            await self._bridge.publish(msg)  # type: ignore[union-attr]
        except Exception:  # noqa: BLE001
            _logger.warning(
                "FullModeRoomObserver: failed to forward event %s to OutputBridge",
                event_type,
                exc_info=True,
            )
