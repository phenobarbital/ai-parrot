"""Per-turn avatar speaker (FEAT-242 Phase A — chat→avatar wiring).

The missing bridge between the chat handler and the avatar's "mouth".

Unlike :class:`AvatarSessionOrchestrator` — which owns the whole session
lifecycle (create → start → speak → stop) for a single one-shot turn — this
class **reuses an already-started session** (the one created by
``POST /api/v1/agents/avatar/{agent}/start`` and stored in
``app['avatar_sessions']``).  That matches the real lifecycle:

    /start  → session created once, persists
    /chat   → AvatarTurnSpeaker opens a WS, speaks this turn, closes the WS
    /chat   → …another turn, same session…
    /stop   → session torn down

Design goals:

- **Never block the text stream.**  Synthesis is CPU-heavy ONNX work.  If the
  chat handler awaited synthesis inside its per-chunk loop, the browser's text
  stream would stall.  So sentences are pushed onto an :class:`asyncio.Queue`
  (a cheap, non-blocking op) and a background consumer task synthesizes + sends
  the PCM concurrently.  The avatar audio lags the text slightly — which is the
  desired behaviour.
- **Graceful degradation.**  Any TTS or WS error is logged and skipped; the
  chat turn continues in text-only mode (spec §7).
- **Mode-aware sink (FEAT-256).**  When a :class:`~room_audio_publisher.RoomAudioPublisher`
  is injected (avatar-OFF path), the speaker routes PCM to the room audio source
  instead of the LiveAvatar WebSocket.  Exactly one sink is active per session
  (avatar-ON XOR avatar-OFF) — no double audio.

Usage (avatar-ON)::

    async with AvatarTurnSpeaker(handle, synth_pcm_fn) as speaker:
        async for chunk in bot.ask_stream(...):
            if isinstance(chunk, str):
                speaker.feed(chunk)        # cheap, non-blocking
        await speaker.finish()             # flush + flush WS buffer

Usage (avatar-OFF / FEAT-256)::

    async with AvatarTurnSpeaker(
        handle, synth_pcm_fn, room_publisher=publisher
    ) as speaker:
        ...
"""
from __future__ import annotations

import asyncio
import logging
from types import TracebackType
from typing import TYPE_CHECKING, Awaitable, Callable, Optional, Type

import aiohttp

from parrot.integrations.liveavatar.avatar_ws import AvatarWebSocket
from parrot.integrations.liveavatar.models import AvatarSessionHandle
from parrot.integrations.liveavatar.speakable import SpeakableFlattener

if TYPE_CHECKING:
    from parrot.integrations.liveavatar.room_audio_publisher import RoomAudioPublisher

# Sentinel pushed onto the queue to signal the consumer to drain and exit.
_DONE = object()

# Bounded queue so a runaway agent can't grow memory without limit; sentences
# are small and the consumer keeps up, so this is a generous safety cap.
_MAX_QUEUED_SENTENCES = 256


class AvatarTurnSpeaker:
    """Speak one chat turn through an already-started LiveAvatar session.

    Supports two audio sinks (FEAT-256):
    - **avatar-ON** (default): PCM is pushed to the LiveAvatar ``agent.speak``
      WebSocket via :class:`~avatar_ws.AvatarWebSocket`.
    - **avatar-OFF**: PCM is pushed to a
      :class:`~room_audio_publisher.RoomAudioPublisher` (direct LiveKit track).
      Pass the publisher as ``room_publisher`` to activate this mode.

    Args:
        handle: The active :class:`AvatarSessionHandle` (from ``/start``), which
            carries the avatar media-server ``ws_url`` and ``session_token``.
            Required for avatar-ON mode; ignored (but still required for the
            constructor signature) in avatar-OFF mode.
        synthesize_pcm_fn: Async callable ``(text: str) -> bytes`` returning raw
            PCM at the rate the avatar expects (24 kHz mono 16-bit LE).  In
            production this is :meth:`AvatarVoiceProvider.synthesize_pcm`.
        ws_session: Optional shared ``aiohttp.ClientSession`` for the WS
            (avatar-ON only; ignored when ``room_publisher`` is set).
        room_publisher: Optional :class:`~room_audio_publisher.RoomAudioPublisher`
            for the avatar-OFF path (FEAT-256).  When set the LiveAvatar WS is
            never opened; PCM goes to the room audio track instead.
    """

    def __init__(
        self,
        handle: Optional[AvatarSessionHandle],
        synthesize_pcm_fn: Callable[[str], Awaitable[bytes]],
        *,
        ws_session: Optional[aiohttp.ClientSession] = None,
        room_publisher: Optional["RoomAudioPublisher"] = None,
    ) -> None:
        self._handle = handle
        self._synthesize_pcm_fn = synthesize_pcm_fn
        self._ws_session = ws_session
        self._room_publisher = room_publisher
        self._ws: Optional[AvatarWebSocket] = None
        # Accumulate the synthesized PCM so the caller can offer a replay
        # (play button) of the exact audio we already generated for the room.
        self._pcm_chunks: list[bytes] = []
        self._flattener = SpeakableFlattener()
        self._queue: asyncio.Queue = asyncio.Queue(maxsize=_MAX_QUEUED_SENTENCES)
        self._consumer: Optional[asyncio.Task] = None
        self._closed = False
        self.logger = logging.getLogger(__name__)

    # ── Context manager ────────────────────────────────────────────────

    async def __aenter__(self) -> "AvatarTurnSpeaker":
        if self._room_publisher is None:
            # avatar-ON path: open the LiveAvatar WebSocket.
            # assume_connected=True: this attaches to an already-started,
            # already-connected session (created at /start), so the server will
            # NOT re-emit the one-time ``session.state_updated == "connected"``
            # event to this late-attaching WS.  Waiting for it would always
            # time out and latch the whole turn into failure — open the gate on
            # handshake instead.
            self._ws = AvatarWebSocket(
                self._handle, session=self._ws_session, assume_connected=True
            )
            await self._ws.__aenter__()
        # avatar-OFF path: no WS needed — the room_publisher is already running.
        self._consumer = asyncio.create_task(
            self._consume(),
            name=(
                "avatar-speaker-"
                + (self._handle.liveavatar_session_id if self._handle else "room")
            ),
        )
        return self

    async def __aexit__(
        self,
        exc_type: Optional[Type[BaseException]],
        exc: Optional[BaseException],
        tb: Optional[TracebackType],
    ) -> None:
        await self.aclose()

    # ── Public API ─────────────────────────────────────────────────────

    def feed(self, chunk: str) -> None:
        """Feed a streamed text chunk; queue any newly completed sentences.

        Cheap and non-blocking — markdown flattening + sentence segmentation is
        pure-Python, and queueing is O(1).  The actual synthesis happens in the
        background consumer.  Sentences are dropped (with a warning) only if the
        queue is full, which should not happen under normal load.

        Args:
            chunk: Next partial text chunk from ``ask_stream()``.
        """
        if self._closed:
            return
        for sentence in self._flattener.feed(chunk):
            self._enqueue(sentence)

    def collected_pcm(self) -> bytes:
        """Return all PCM synthesized this turn (for a replay/play button).

        Concatenation of every sentence's PCM (24 kHz mono 16-bit) — the exact
        audio sent to the room/avatar. Empty until the turn has been spoken
        (call after ``finish()``).
        """
        return b"".join(self._pcm_chunks)

    async def finish(self) -> None:
        """Flush the remaining buffer, wait for playback, and flush the avatar.

        Queues any trailing partial sentence, signals the consumer to drain,
        waits for it to finish synthesizing/sending every queued sentence, then
        sends ``agent.speak_end`` so the media server flushes its playback
        buffer.
        """
        if self._closed:
            return
        for sentence in self._flattener.flush():
            self._enqueue(sentence)
        # Signal end-of-stream and wait for the consumer to drain the queue.
        await self._queue.put(_DONE)
        if self._consumer is not None:
            await self._consumer
            self._consumer = None
        # All audio sent — flush the active sink's playback buffer.
        if self._room_publisher is not None:
            # avatar-OFF: room audio source has no "flush playback" concept;
            # the audio is already in-flight in the LiveKit track.  Call flush()
            # to ensure any barge-in flag is cleared.
            try:
                await self._room_publisher.flush()
            except Exception:  # noqa: BLE001 - graceful degradation
                self.logger.warning(
                    "AvatarTurnSpeaker: publisher flush failed", exc_info=True
                )
        elif self._ws is not None:
            # avatar-ON: tell the avatar to flush its playback buffer.
            try:
                await self._ws.finish_speaking()
            except Exception:  # noqa: BLE001 - graceful degradation
                self.logger.warning(
                    "AvatarTurnSpeaker: finish_speaking failed", exc_info=True
                )

    async def interrupt(self) -> None:
        """Cancel in-flight audio (barge-in / interrupt).

        Cancels the background consumer and signals the active sink to flush
        any buffered/in-flight audio:
        - avatar-OFF: calls :meth:`~room_audio_publisher.RoomAudioPublisher.flush`.
        - avatar-ON: calls :meth:`~avatar_ws.AvatarWebSocket.interrupt` (sends
          ``agent.interrupt`` to the LiveAvatar media server).

        Idempotent — safe to call when already closed.
        """
        if self._closed:
            return
        if self._consumer is not None and not self._consumer.done():
            self._consumer.cancel()
            try:
                await self._consumer
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
            self._consumer = None
        # Flush the active sink.
        if self._room_publisher is not None:
            try:
                await self._room_publisher.flush()
            except Exception:  # noqa: BLE001
                self.logger.warning(
                    "AvatarTurnSpeaker: publisher flush on interrupt failed",
                    exc_info=True,
                )
        elif self._ws is not None:
            try:
                await self._ws.interrupt()
            except Exception:  # noqa: BLE001
                self.logger.warning(
                    "AvatarTurnSpeaker: WS interrupt failed", exc_info=True
                )

    async def aclose(self) -> None:
        """Tear down the consumer task and close the WebSocket (idempotent)."""
        if self._closed:
            return
        self._closed = True
        if self._consumer is not None and not self._consumer.done():
            self._consumer.cancel()
            try:
                await self._consumer
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
            self._consumer = None
        if self._ws is not None:
            try:
                await self._ws.__aexit__(None, None, None)
            except Exception:  # noqa: BLE001
                self.logger.warning(
                    "AvatarTurnSpeaker: WS close failed", exc_info=True
                )
            self._ws = None

    # ── Internals ──────────────────────────────────────────────────────

    def _enqueue(self, sentence: str) -> None:
        """Queue a sentence for the consumer; warn (don't block) if full."""
        if not sentence.strip():
            return
        try:
            self._queue.put_nowait(sentence)
        except asyncio.QueueFull:
            self.logger.warning(
                "AvatarTurnSpeaker: sentence queue full — dropping %r",
                sentence[:60],
            )

    async def _consume(self) -> None:
        """Background loop: synthesize each queued sentence and send its PCM."""
        while True:
            item = await self._queue.get()
            if item is _DONE:
                return
            await self._speak(item)

    async def _speak(self, sentence: str) -> None:
        """Synthesize one sentence to PCM and push it to the active sink.

        Routes to the :class:`~room_audio_publisher.RoomAudioPublisher`
        (avatar-OFF) or the LiveAvatar WebSocket (avatar-ON).  On any TTS/sink
        failure the sentence is logged and skipped — the turn continues (the
        text is already rendered in the UI).

        Args:
            sentence: The speakable sentence to synthesize and send.
        """
        if self._room_publisher is None and self._ws is None:
            return
        try:
            pcm = await self._synthesize_pcm_fn(sentence)
            if pcm:
                # Keep a copy for replay (same audio we send to the room/avatar).
                self._pcm_chunks.append(pcm)
                if self._room_publisher is not None:
                    # avatar-OFF: push PCM directly into the LiveKit room track.
                    await self._room_publisher.capture_pcm(pcm)
                elif self._ws is not None:
                    # avatar-ON: push PCM to the LiveAvatar WS (unchanged path).
                    await self._ws.send_audio_frame(pcm)
        except Exception:  # noqa: BLE001 - graceful degradation per spec §7
            self.logger.warning(
                "AvatarTurnSpeaker: failed speaking sentence %r — skipping",
                sentence[:80],
                exc_info=True,
            )
