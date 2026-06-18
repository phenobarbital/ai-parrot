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

Usage::

    async with AvatarTurnSpeaker(handle, synth_pcm_fn) as speaker:
        async for chunk in bot.ask_stream(...):
            if isinstance(chunk, str):
                speaker.feed(chunk)        # cheap, non-blocking
        await speaker.finish()             # flush + flush WS buffer
"""
from __future__ import annotations

import asyncio
import logging
from types import TracebackType
from typing import Awaitable, Callable, Optional, Type

import aiohttp

from parrot.integrations.liveavatar.avatar_ws import AvatarWebSocket
from parrot.integrations.liveavatar.models import AvatarSessionHandle
from parrot.integrations.liveavatar.speakable import SpeakableFlattener

# Sentinel pushed onto the queue to signal the consumer to drain and exit.
_DONE = object()

# Bounded queue so a runaway agent can't grow memory without limit; sentences
# are small and the consumer keeps up, so this is a generous safety cap.
_MAX_QUEUED_SENTENCES = 256


class AvatarTurnSpeaker:
    """Speak one chat turn through an already-started LiveAvatar session.

    Args:
        handle: The active :class:`AvatarSessionHandle` (from ``/start``), which
            carries the avatar media-server ``ws_url`` and ``session_token``.
        synthesize_pcm_fn: Async callable ``(text: str) -> bytes`` returning raw
            PCM at the rate the avatar expects (24 kHz mono 16-bit LE).  In
            production this is :meth:`AvatarVoiceProvider.synthesize_pcm`.
        ws_session: Optional shared ``aiohttp.ClientSession`` for the WS.
    """

    def __init__(
        self,
        handle: AvatarSessionHandle,
        synthesize_pcm_fn: Callable[[str], Awaitable[bytes]],
        *,
        ws_session: Optional[aiohttp.ClientSession] = None,
    ) -> None:
        self._handle = handle
        self._synthesize_pcm_fn = synthesize_pcm_fn
        self._ws_session = ws_session
        self._ws: Optional[AvatarWebSocket] = None
        self._flattener = SpeakableFlattener()
        self._queue: asyncio.Queue = asyncio.Queue(maxsize=_MAX_QUEUED_SENTENCES)
        self._consumer: Optional[asyncio.Task] = None
        self._closed = False
        self.logger = logging.getLogger(__name__)

    # ── Context manager ────────────────────────────────────────────────

    async def __aenter__(self) -> "AvatarTurnSpeaker":
        # Open the WS (fast — does NOT await the connected gate here; the first
        # send_audio_frame awaits it, so entering never blocks the text stream).
        self._ws = AvatarWebSocket(self._handle, session=self._ws_session)
        await self._ws.__aenter__()
        self._consumer = asyncio.create_task(
            self._consume(),
            name=f"avatar-speaker-{self._handle.liveavatar_session_id}",
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
        # All audio sent — tell the avatar to flush its playback buffer.
        if self._ws is not None:
            try:
                await self._ws.finish_speaking()
            except Exception:  # noqa: BLE001 - graceful degradation
                self.logger.warning(
                    "AvatarTurnSpeaker: finish_speaking failed", exc_info=True
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
        """Synthesize one sentence to PCM and push it to the avatar WS.

        On any TTS/WS failure the sentence is logged and skipped — the turn
        continues (the text is already rendered in the UI).

        Args:
            sentence: The speakable sentence to synthesize and send.
        """
        if self._ws is None:
            return
        try:
            pcm = await self._synthesize_pcm_fn(sentence)
            if pcm:
                await self._ws.send_audio_frame(pcm)
        except Exception:  # noqa: BLE001 - graceful degradation per spec §7
            self.logger.warning(
                "AvatarTurnSpeaker: failed speaking sentence %r — skipping",
                sentence[:80],
                exc_info=True,
            )
