"""Avatar audio bridge — WebSocket PCM push (FEAT-242 Phase A — Module 2).

Ports the LiveAvatar starter ``avatar_ws.py`` (websockets library) to
``aiohttp`` per project standards.

Responsibilities:
- Wait for ``session.state_updated == "connected"`` before sending any frames.
- Emit ``agent.speak`` / ``agent.speak_end`` / ``agent.interrupt`` protocol frames.
- Send PCM as base64 INSIDE the ``agent.speak`` JSON message (the LITE-mode
  protocol carries audio in-band, not as raw binary WS frames):
    ``{"type": "agent.speak", "audio": "<base64 PCM 16-bit 24 kHz>"}``
  PCM (already 24 kHz mono 16-bit from Supertonic) is sliced into chunks:
    - First chunk: ≈ 400 ms  (~19 200 bytes)
    - Subsequent:  ≈ 1 s     (~48 000 bytes)
    - Hard cap:    1 MB per packet
- Reconnect on WS disconnect.  There is NO in-band auth handshake — the
  ``ws_url`` returned by ``/v1/sessions/start`` is already authenticated.
- Input PCM is already 24 kHz mono 16-bit — no resampling is done.

Protocol reference: https://docs.liveavatar.com/docs/lite-mode/events

PCM size constants (from supertonic_backend.py, verified):
    _SAMPLE_RATE = 24000
    _CHANNELS    = 1      (mono)
    _SAMPLE_WIDTH = 2     (16-bit / 2 bytes per sample)
    => 1 s = 24000 * 1 * 2 = 48 000 bytes
    => 400 ms ≈ 9 600 samples * 2 bytes = 19 200 bytes
"""
from __future__ import annotations

import asyncio
import base64
import contextlib
import inspect
import json
import logging
import os
import uuid
from types import TracebackType
from typing import Any, Awaitable, Callable, Dict, Optional, Type, Union

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

# Max time to wait for the server's ``session.state_updated == "connected"``
# event before giving up (prevents an indefinite hang if the media server
# never signals readiness — e.g. wrong URL or a server-side error).
# Kept short: this gate is awaited once per sentence, so a never-arriving
# "connected" event must fail FAST or it serialises 30 s per sentence into the
# turn. Once it times out the gate is latched failed (see ``_await_connected``)
# so the rest of the turn short-circuits instead of paying the timeout again.
# Override via ``LIVEAVATAR_WS_CONNECT_TIMEOUT`` (seconds).
def _connect_timeout_default() -> float:
    raw = os.environ.get("LIVEAVATAR_WS_CONNECT_TIMEOUT", "")
    if raw:
        try:
            return float(raw)
        except ValueError:
            pass
    return 5.0


_CONNECT_TIMEOUT: float = _connect_timeout_default()  # seconds

#: A callback may be sync or async; both are supported everywhere.
EventCallback = Callable[[Dict[str, Any]], Union[Awaitable[None], None]]
CloseCallback = Callable[[str], Union[Awaitable[None], None]]


class AvatarSendTimeout(RuntimeError):
    """A vendor send exceeded its per-send deadline.

    Distinct from a generic :class:`RuntimeError` so the broadcast session can
    treat "the avatar sink is stalling" as a fallback trigger (spec §2 runtime
    fallback triggers: "send timeout") rather than as an unknown error.
    """


async def _invoke(callback: Optional[Callable[..., Any]], *args: Any) -> None:
    """Call a possibly-async callback, swallowing and logging its failures.

    A misbehaving observer must never take down the reader loop or abort a
    turn — the callback is telemetry/routing, not part of the audio path.

    Args:
        callback: The callback, or ``None``.
        *args: Positional arguments to pass.
    """
    if callback is None:
        return
    try:
        result = callback(*args)
        if inspect.isawaitable(result):
            await result
    except Exception:  # noqa: BLE001 — observers must not break the transport
        logging.getLogger(__name__).exception(
            "AvatarWebSocket: callback %r raised", getattr(callback, "__name__", callback)
        )


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
        assume_connected: When ``True`` the connected gate is opened as soon as
            the WS handshake completes, instead of waiting for a fresh
            ``session.state_updated == "connected"`` event.  Use this when
            attaching to an **already-started, already-connected** session (the
            per-turn :class:`AvatarTurnSpeaker` reuse path): the server only
            emits the ``connected`` state once, at the moment the session first
            becomes connected — a WS that attaches later never sees a re-emitted
            event, so waiting for it would always time out.  The one-shot
            orchestrator, which opens its WS at the exact connect transition,
            leaves this ``False`` and genuinely waits for the event.
        on_event: Called with every parsed server message.  This is the only
            observation point for LITE lifecycle events until the live gate
            (TASK-2950) confirms their names, so messages are forwarded whole
            and unfiltered rather than being mapped to invented constants.
        on_close: Called once with a short reason string when the transport
            closes permanently.  Only meaningful with ``auto_reconnect=False``.
        auto_reconnect: Keep the legacy silent-reconnect behaviour (default).
            A broadcast sets this ``False``: an avatar control socket that
            drops is a *fallback trigger*, and silently reconnecting would
            hide it and strand the audience in a half-dead avatar mode.
        send_timeout_s: Per-send deadline.  Exceeding it raises
            :class:`AvatarSendTimeout` (spec §2 default for broadcast: 2 s).
        aggregate: Buffer PCM **across** ``send_audio_frame`` calls so small
            Nova chunks become ~1 s vendor frames instead of a flood of tiny
            ``agent.speak`` messages.
    """

    def __init__(
        self,
        handle: AvatarSessionHandle,
        *,
        session: Optional[aiohttp.ClientSession] = None,
        assume_connected: bool = False,
        on_event: Optional[EventCallback] = None,
        on_close: Optional[CloseCallback] = None,
        auto_reconnect: bool = True,
        send_timeout_s: Optional[float] = None,
        aggregate: bool = False,
    ) -> None:
        self.handle = handle
        self.logger = logging.getLogger(__name__)
        self._session: Optional[aiohttp.ClientSession] = session
        self._owns_session: bool = session is None
        self._assume_connected: bool = assume_connected
        self._on_event: Optional[EventCallback] = on_event
        self._on_close: Optional[CloseCallback] = on_close
        self._auto_reconnect: bool = auto_reconnect
        self._send_timeout_s: Optional[float] = send_timeout_s
        self._aggregate: bool = aggregate
        #: Verbatim ``type`` of the last speaking-related server event.  The
        #: real LITE names are unconfirmed until the TASK-2950 live gate runs,
        #: so nothing here hard-codes ``agent.speaking_started``.
        self.speaking_state: Optional[str] = None
        #: Set once the transport is permanently closed (``auto_reconnect``
        #: off).  Callers await it instead of polling.
        self.closed: asyncio.Event = asyncio.Event()
        self._close_reason: str = ""
        self._close_notified: bool = False
        self._buffer: bytearray = bytearray()
        self._first_frame_sent: bool = False
        self._ws: Optional[aiohttp.ClientWebSocketResponse] = None
        self._connected: asyncio.Event = asyncio.Event()
        # Latched True once the connected gate times out, so the remaining
        # sends of the turn fail fast instead of each paying _CONNECT_TIMEOUT.
        # Cleared on (re)connect attempts so a later recovery can still speak.
        self._connect_failed: bool = False
        # Tracks the background reader coroutine so it can be cancelled cleanly
        # on close / reconnect (otherwise the task leaks and two readers can
        # race over the same connection).
        self._reader_task: Optional[asyncio.Task[None]] = None

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
        """Block until the avatar media server is ready to receive audio.

        The LITE-mode protocol has no separate "begin speaking" frame — audio
        is carried per-chunk inside ``agent.speak`` (see :meth:`send_audio_frame`).
        This method only awaits the ``session.state_updated == "connected"``
        gate so callers can fail fast if the server never becomes ready.

        Raises:
            RuntimeError: If the connected gate is not opened within
                :data:`_CONNECT_TIMEOUT`.
        """
        await self._await_connected()
        self.logger.debug("AvatarWebSocket: connected — ready to speak")

    async def send_audio_frame(self, pcm: bytes) -> None:
        """Push PCM audio to the avatar as base64 ``agent.speak`` messages.

        Slices ``pcm`` into appropriately-sized chunks and sends each as a
        ``{"type": "agent.speak", "audio": "<base64>"}`` JSON frame (LITE-mode
        carries audio in-band, not as raw binary WS frames):
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

        if self._aggregate:
            self._buffer.extend(pcm)
            await self._drain_buffer()
            return

        offset = 0
        is_first = True
        while offset < len(pcm):
            chunk_size = _FIRST_CHUNK_BYTES if is_first else _NORMAL_CHUNK_BYTES
            # Never exceed the hard cap
            chunk_size = min(chunk_size, _MAX_PACKET_BYTES)
            chunk = pcm[offset: offset + chunk_size]
            await self._emit_chunk(chunk, is_first)
            offset += chunk_size
            is_first = False

    @property
    def pending_bytes(self) -> int:
        """Bytes buffered but not yet submitted to the vendor.

        Only these are safe to re-route on a fallback cutover: anything already
        submitted may or may not have been played, and replaying it would
        duplicate speech (spec §2).
        """
        return len(self._buffer)

    async def _emit_chunk(self, chunk: bytes, is_first: bool) -> None:
        """Base64-encode one slice and send it as a single ``agent.speak``.

        Args:
            chunk: Raw PCM slice, already sized to the vendor's limits.
            is_first: Whether this is the utterance's first (shorter) frame.
        """
        audio_b64 = base64.b64encode(chunk).decode("ascii")
        await self._send_json({"type": "agent.speak", "audio": audio_b64})
        self.logger.debug(
            "AvatarWebSocket: sent %d-byte PCM chunk as agent.speak (first=%s)",
            len(chunk),
            is_first,
        )

    async def _drain_buffer(self, *, flush: bool = False) -> None:
        """Emit whole frames from the aggregation buffer, in order.

        Bytes are never reordered or duplicated: each emitted frame is the
        exact prefix of the buffer, and the buffer is truncated by exactly
        what was sent.

        Args:
            flush: Also emit a final short frame with whatever remains, which
                is what ``finish_speaking`` needs before ``agent.speak_end``.
        """
        while True:
            target = _NORMAL_CHUNK_BYTES if self._first_frame_sent else _FIRST_CHUNK_BYTES
            target = min(target, _MAX_PACKET_BYTES)
            if len(self._buffer) >= target:
                chunk = bytes(self._buffer[:target])
                del self._buffer[:target]
                await self._emit_chunk(chunk, not self._first_frame_sent)
                self._first_frame_sent = True
                continue
            if flush and self._buffer:
                chunk = bytes(self._buffer)
                self._buffer.clear()
                await self._emit_chunk(chunk, not self._first_frame_sent)
                self._first_frame_sent = True
            return

    async def finish_speaking(self) -> None:
        """Send the ``agent.speak_end`` frame to flush the playback buffer.

        Carries a fresh ``event_id`` which the server echoes back in its
        ``agent.speak_ended`` response.

        Raises:
            RuntimeError: If the WebSocket connection is not open.
        """
        await self._await_connected()
        if self._aggregate:
            # The tail must reach the vendor BEFORE speak_end, or the last
            # fraction of a second of the utterance is silently dropped.
            await self._drain_buffer(flush=True)
            self._first_frame_sent = False
        event_id = uuid.uuid4().hex
        await self._send_json({"type": "agent.speak_end", "event_id": event_id})
        self.logger.debug("AvatarWebSocket: agent.speak_end sent (event_id=%s)", event_id)

    async def interrupt(self) -> None:
        """Send the ``agent.interrupt`` frame to clear scheduled audio.

        Raises:
            RuntimeError: If the WebSocket connection is not open.
        """
        await self._await_connected()
        # Drop pending bytes BEFORE the interrupt so a concurrent drain cannot
        # push stale audio in behind it.
        dropped = len(self._buffer)
        self._buffer.clear()
        self._first_frame_sent = False
        await self._send_json({"type": "agent.interrupt"})
        self.logger.debug(
            "AvatarWebSocket: agent.interrupt sent (dropped %d buffered bytes)", dropped
        )

    # ── Connection management ──────────────────────────────────────────

    async def _connect(self) -> None:
        """Open the WebSocket connection and start the message-reader loop.

        The ``ws_url`` (from ``/v1/sessions/start``) is already authenticated,
        so no in-band handshake is sent.  The server emits
        ``session.state_updated == "connected"`` on its own; the background
        reader sets the ``_connected`` gate when it arrives.
        """
        if self._session is None:
            raise RuntimeError("AvatarWebSocket: no aiohttp session available")

        self.logger.debug(
            "AvatarWebSocket: connecting to %s", self.handle.ws_url
        )
        self._ws = await self._session.ws_connect(self.handle.ws_url)
        # Reusing an already-connected session: the server will NOT re-emit the
        # one-time ``connected`` state to this late-attaching WS, so open the
        # gate now (the session is already live) instead of timing out.
        if self._assume_connected:
            self._connected.set()
            self.logger.debug(
                "AvatarWebSocket: assume_connected — gate opened on handshake"
            )
        # Start the reader coroutine in the background; it sets _connected.
        self._reader_task = asyncio.create_task(
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
                    reason = "close" if msg.type == aiohttp.WSMsgType.CLOSE else "error"
                    if not self._auto_reconnect:
                        # A broadcast treats this as a fallback trigger.
                        # Reconnecting silently would hide the failure and
                        # strand the audience in a half-dead avatar mode.
                        await self._notify_closed(reason)
                        return
                    self.logger.warning(
                        "AvatarWebSocket: WS closed/error — attempting reconnect"
                    )
                    await self._reconnect()
                    return
            if not self._auto_reconnect:
                await self._notify_closed("eof")
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001
            self.logger.exception("AvatarWebSocket: reader loop error")
            if not self._auto_reconnect:
                await self._notify_closed("error")

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
        # Log every inbound server event at INFO so the real LITE-mode protocol
        # (esp. under LiveKit BYO transport) can be confirmed from logs — the
        # speaker path was only ever exercised against fakes.
        self.logger.info(
            "AvatarWebSocket: server event type=%r payload=%s", msg_type, raw[:300]
        )
        if msg_type == "session.state_updated":
            state = msg.get("state", "")
            if state == "connected":
                self._connected.set()
                self.logger.info("AvatarWebSocket: session connected — gate open")
        lowered = msg_type.lower()
        if "speak" in lowered or "speaking" in lowered:
            # Recorded verbatim: the real LITE speaking-event names are
            # unconfirmed until the TASK-2950 live gate runs, so this must not
            # normalise them into invented constants.
            self.speaking_state = msg_type
        # Forward EVERY message, including ones handled above — the broadcast
        # session is the component that decides what an event means.
        await _invoke(self._on_event, msg)

    async def _reconnect(self) -> None:
        """Reconnect the WebSocket after a drop.

        Clears the connected gate and re-opens the (pre-authenticated) WS so
        the avatar is ready to receive frames again.  No handshake is replayed
        — the server re-emits ``session.state_updated == "connected"`` itself.
        """
        self._connected.clear()
        self._connect_failed = False
        self.logger.info("AvatarWebSocket: reconnecting…")
        if self._session is None:
            return
        # Cancel the current reader before spawning a new one so two readers
        # never race over the same connection.  This runs from inside the old
        # reader, so cancel-without-await is correct here (the old task is
        # about to ``return`` anyway); we only clear the reference.
        self._reader_task = None
        try:
            self._ws = await self._session.ws_connect(self.handle.ws_url)
            # Same rationale as _connect: a reused session never re-emits the
            # one-time ``connected`` state, so re-open the gate on reconnect.
            if self._assume_connected:
                self._connected.set()
            self._reader_task = asyncio.create_task(
                self._reader_loop(),
                name=f"avatar-ws-reader-{self.handle.liveavatar_session_id}",
            )
            self.logger.info("AvatarWebSocket: reconnected")
        except Exception:  # noqa: BLE001
            self.logger.exception("AvatarWebSocket: reconnect failed")

    async def _notify_closed(self, reason: str) -> None:
        """Latch the permanent-close state and notify the observer exactly once.

        Args:
            reason: Short, non-sensitive reason code (``close``/``error``/``eof``).
        """
        if self._close_notified:
            return
        self._close_notified = True
        self._close_reason = reason
        self.closed.set()
        # Release anyone blocked on the connect gate so they fail fast with the
        # close error rather than waiting out the full connect timeout.
        self._connected.set()
        self.logger.warning(
            "AvatarWebSocket: transport closed permanently (reason=%s)", reason
        )
        await _invoke(self._on_close, reason)

    async def _close(self) -> None:
        """Cancel the reader task and close the underlying WebSocket gracefully."""
        # Cancel + await the reader FIRST so it cannot re-enter ``_reconnect``
        # after we close the socket.
        task = self._reader_task
        self._reader_task = None
        if task is not None and not task.done():
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
        if self._ws is not None and not self._ws.closed:
            await self._ws.close()
            self.logger.debug("AvatarWebSocket: connection closed")
        self._ws = None

    # ── Internal send helpers ──────────────────────────────────────────

    async def _await_connected(self) -> None:
        """Block until the ``session.state_updated == "connected"`` event.

        This is the gate: NO protocol commands may be sent before the avatar
        media server signals it is ready.  Bounded by :data:`_CONNECT_TIMEOUT`
        so a never-arriving "connected" event cannot hang the turn forever.

        Raises:
            RuntimeError: If the connected event does not arrive within
                :data:`_CONNECT_TIMEOUT` seconds.
        """
        if self.closed.is_set():
            raise RuntimeError(
                f"AvatarWebSocket: closed ({self._close_reason})"
            )
        if self._connected.is_set():
            return
        # Already gave up earlier this turn — fail immediately rather than
        # waiting another full _CONNECT_TIMEOUT for every subsequent sentence.
        if self._connect_failed:
            raise RuntimeError(
                "AvatarWebSocket: connected gate previously timed out this turn"
            )
        try:
            await asyncio.wait_for(self._connected.wait(), timeout=_CONNECT_TIMEOUT)
        except asyncio.TimeoutError as exc:
            self._connect_failed = True
            raise RuntimeError(
                "AvatarWebSocket: timed out waiting for "
                f"session.state_updated='connected' after {_CONNECT_TIMEOUT}s"
            ) from exc

    async def _send_json(self, payload: Dict[str, Any]) -> None:
        """Send a JSON control frame.

        Args:
            payload: Dict to serialise as JSON.

        Raises:
            RuntimeError: If the WebSocket is not open or permanently closed.
            AvatarSendTimeout: If the send exceeds ``send_timeout_s``.
        """
        if self.closed.is_set():
            raise RuntimeError(f"AvatarWebSocket: closed ({self._close_reason})")
        if self._ws is None or self._ws.closed:
            raise RuntimeError("AvatarWebSocket: cannot send — WS not connected")
        if self._send_timeout_s is None:
            await self._ws.send_json(payload)
            return
        try:
            await asyncio.wait_for(
                self._ws.send_json(payload), timeout=self._send_timeout_s
            )
        except asyncio.TimeoutError as exc:
            raise AvatarSendTimeout(
                "AvatarWebSocket: vendor send exceeded "
                f"{self._send_timeout_s}s deadline"
            ) from exc
