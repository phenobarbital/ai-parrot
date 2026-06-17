"""Avatar audio bridge — WebSocket PCM push (FEAT-242 Phase A — Module 2).

Ports the LiveAvatar starter ``avatar_ws.py`` (websockets library) to
``aiohttp`` per project standards.

Responsibilities:
- Wait for ``session.state_updated == "connected"`` before sending any frames.
- Emit ``agent.speak`` / ``agent.speak_end`` / ``agent.interrupt`` protocol frames.
- Send PCM frames (already 24 kHz mono 16-bit from Supertonic) in chunks:
    - First chunk: ≈ 400 ms  (~19 200 bytes)
    - Subsequent:  ≈ 1 s     (~48 000 bytes)
    - Hard cap:    1 MB per packet
- Reconnect + replay ``start`` handshake on WS disconnect.
- Input PCM is already 24 kHz mono 16-bit — no resampling is done.

PCM size constants (from supertonic_backend.py, verified):
    _SAMPLE_RATE = 24000
    _CHANNELS    = 1      (mono)
    _SAMPLE_WIDTH = 2     (16-bit / 2 bytes per sample)
    => 1 s = 24000 * 1 * 2 = 48 000 bytes
    => 400 ms ≈ 9 600 samples * 2 bytes = 19 200 bytes
"""
from __future__ import annotations

import asyncio
import json
import logging
from types import TracebackType
from typing import Any, Dict, Optional, Type

import aiohttp

from parrot.integrations.liveavatar.models import AvatarSessionHandle

# PCM size constants (mirror supertonic_backend.py — no resampling)
_SAMPLE_RATE: int = 24_000   # Hz
_BYTES_PER_SAMPLE: int = 2   # 16-bit mono
_BYTES_PER_SECOND: int = _SAMPLE_RATE * _BYTES_PER_SAMPLE  # 48 000

# Chunk sizes
_FIRST_CHUNK_BYTES: int = int(_BYTES_PER_SECOND * 0.4)   # ≈ 400 ms — 19 200 bytes
_NORMAL_CHUNK_BYTES: int = _BYTES_PER_SECOND              # ≈ 1 s   — 48 000 bytes
_MAX_PACKET_BYTES: int = 1_024 * 1_024                    # 1 MB hard cap


class AvatarWebSocket:
    """WebSocket bridge that pushes PCM audio frames to the LiveAvatar media server.

    Emits the ``agent.speak``, ``agent.speak_end``, and ``agent.interrupt``
    protocol frames required by the LiveAvatar LITE mode.

    No resampling is applied: input PCM is assumed to be 24 kHz mono 16-bit,
    which is exactly what Supertonic produces.

    Usage::

        async with AvatarWebSocket(handle) as ws:
            await ws.start_speaking()
            await ws.send_audio_frame(pcm_bytes)
            await ws.finish_speaking()

    Args:
        handle: The active :class:`AvatarSessionHandle` providing the WS URL
            and session token.
        session: Optional external ``aiohttp.ClientSession``.  When ``None``
            the class creates and owns one.
    """

    def __init__(
        self,
        handle: AvatarSessionHandle,
        *,
        session: Optional[aiohttp.ClientSession] = None,
    ) -> None:
        self.handle = handle
        self.logger = logging.getLogger(__name__)
        self._session: Optional[aiohttp.ClientSession] = session
        self._owns_session: bool = session is None
        self._ws: Optional[aiohttp.ClientWebSocketResponse] = None
        self._connected: asyncio.Event = asyncio.Event()

    # ── Context manager ────────────────────────────────────────────────

    async def __aenter__(self) -> "AvatarWebSocket":
        if self._owns_session:
            self._session = aiohttp.ClientSession()
        await self._connect()
        return self

    async def __aexit__(
        self,
        exc_type: Optional[Type[BaseException]],
        exc: Optional[BaseException],
        tb: Optional[TracebackType],
    ) -> None:
        await self._close()
        if self._owns_session and self._session is not None:
            await self._session.close()
            self._session = None

    # ── Public API ─────────────────────────────────────────────────────

    async def start_speaking(self) -> None:
        """Send the ``agent.speak`` frame, waiting for the connected gate first.

        Blocks until the ``session.state_updated == "connected"`` event is
        received from the server.

        Raises:
            RuntimeError: If the WebSocket connection is not open.
        """
        await self._await_connected()
        await self._send_json({"type": "agent.speak"})
        self.logger.debug("AvatarWebSocket: agent.speak sent")

    async def send_audio_frame(self, pcm: bytes) -> None:
        """Push PCM audio bytes to the avatar, respecting the chunking contract.

        Slices ``pcm`` into appropriately-sized chunks:
        - First slice: ≈ 400 ms (~19 200 bytes).
        - Subsequent slices: ≈ 1 s (~48 000 bytes).
        - Hard cap: 1 MB per packet.

        No resampling — input must be 24 kHz mono 16-bit.

        Args:
            pcm: Raw PCM bytes (int16 LE mono 24 kHz).

        Raises:
            RuntimeError: If the WebSocket is not open.
        """
        await self._await_connected()
        if not pcm:
            return

        offset = 0
        is_first = True
        while offset < len(pcm):
            chunk_size = _FIRST_CHUNK_BYTES if is_first else _NORMAL_CHUNK_BYTES
            # Never exceed the hard cap
            chunk_size = min(chunk_size, _MAX_PACKET_BYTES)
            chunk = pcm[offset: offset + chunk_size]
            await self._send_binary(chunk)
            self.logger.debug(
                "AvatarWebSocket: sent %d-byte PCM chunk (first=%s)", len(chunk), is_first
            )
            offset += chunk_size
            is_first = False

    async def finish_speaking(self) -> None:
        """Send the ``agent.speak_end`` frame.

        Raises:
            RuntimeError: If the WebSocket connection is not open.
        """
        await self._await_connected()
        await self._send_json({"type": "agent.speak_end"})
        self.logger.debug("AvatarWebSocket: agent.speak_end sent")

    async def interrupt(self) -> None:
        """Send the ``agent.interrupt`` frame to clear scheduled audio.

        Raises:
            RuntimeError: If the WebSocket connection is not open.
        """
        await self._await_connected()
        await self._send_json({"type": "agent.interrupt"})
        self.logger.debug("AvatarWebSocket: agent.interrupt sent")

    # ── Connection management ──────────────────────────────────────────

    async def _connect(self) -> None:
        """Open the WebSocket connection and start the message-reader loop.

        After connecting, the method awaits the ``session.state_updated ==
        "connected"`` server event before signalling the ``_connected`` event.
        """
        if self._session is None:
            raise RuntimeError("AvatarWebSocket: no aiohttp session available")

        self.logger.debug(
            "AvatarWebSocket: connecting to %s", self.handle.ws_url
        )
        self._ws = await self._session.ws_connect(self.handle.ws_url)
        # Start the reader coroutine in the background; it sets _connected
        asyncio.create_task(
            self._reader_loop(),
            name=f"avatar-ws-reader-{self.handle.liveavatar_session_id}",
        )

    async def _reader_loop(self) -> None:
        """Receive server messages and set the connected gate.

        Handles ``session.state_updated`` messages and manages reconnects on
        ``WSMsgType.CLOSE`` / ``WSMsgType.ERROR``.
        """
        if self._ws is None:
            return
        try:
            async for msg in self._ws:
                if msg.type == aiohttp.WSMsgType.TEXT:
                    await self._handle_server_message(msg.data)
                elif msg.type in (aiohttp.WSMsgType.CLOSE, aiohttp.WSMsgType.ERROR):
                    self.logger.warning(
                        "AvatarWebSocket: WS closed/error — attempting reconnect"
                    )
                    await self._reconnect()
                    return
        except Exception:  # noqa: BLE001
            self.logger.exception("AvatarWebSocket: reader loop error")

    async def _handle_server_message(self, raw: str) -> None:
        """Process an incoming server text frame.

        Args:
            raw: Raw JSON string from the server.
        """
        try:
            msg: Dict[str, Any] = json.loads(raw)
        except (ValueError, TypeError):
            self.logger.debug("AvatarWebSocket: non-JSON server message: %r", raw)
            return

        msg_type = msg.get("type", "")
        if msg_type == "session.state_updated":
            state = msg.get("state", "")
            if state == "connected":
                self._connected.set()
                self.logger.info("AvatarWebSocket: session connected — gate open")
        else:
            self.logger.debug("AvatarWebSocket: server event %r", msg_type)

    async def _reconnect(self) -> None:
        """Reconnect the WebSocket and replay the ``start`` handshake.

        Clears the connected gate, re-opens the WS, and re-sends the initial
        session negotiation so the avatar is ready to receive frames again.
        """
        self._connected.clear()
        self.logger.info("AvatarWebSocket: reconnecting…")
        if self._session is None:
            return
        try:
            self._ws = await self._session.ws_connect(self.handle.ws_url)
            # Replay the start handshake (per starter avatar_ws.py pattern)
            await self._send_json({
                "type": "session.start",
                "sessionId": self.handle.liveavatar_session_id,
                "sessionToken": self.handle.session_token,
            })
            asyncio.create_task(
                self._reader_loop(),
                name=f"avatar-ws-reader-{self.handle.liveavatar_session_id}",
            )
            self.logger.info("AvatarWebSocket: reconnected and start replayed")
        except Exception:  # noqa: BLE001
            self.logger.exception("AvatarWebSocket: reconnect failed")

    async def _close(self) -> None:
        """Close the underlying WebSocket gracefully."""
        if self._ws is not None and not self._ws.closed:
            await self._ws.close()
            self.logger.debug("AvatarWebSocket: connection closed")
        self._ws = None

    # ── Internal send helpers ──────────────────────────────────────────

    async def _await_connected(self) -> None:
        """Block until the ``session.state_updated == "connected"`` event.

        This is the gate: NO protocol commands may be sent before the avatar
        media server signals it is ready.
        """
        await self._connected.wait()

    async def _send_json(self, payload: Dict[str, Any]) -> None:
        """Send a JSON control frame.

        Args:
            payload: Dict to serialise as JSON.

        Raises:
            RuntimeError: If the WebSocket is not open.
        """
        if self._ws is None or self._ws.closed:
            raise RuntimeError("AvatarWebSocket: cannot send — WS not connected")
        await self._ws.send_json(payload)

    async def _send_binary(self, data: bytes) -> None:
        """Send a binary frame (PCM chunk).

        Args:
            data: PCM bytes to send.

        Raises:
            RuntimeError: If the WebSocket is not open.
        """
        if self._ws is None or self._ws.closed:
            raise RuntimeError("AvatarWebSocket: cannot send — WS not connected")
        await self._ws.send_bytes(data)
