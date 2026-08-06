"""VoiceSession — provider-agnostic voice turn lifecycle manager (FEAT-416).

Promotes ``NovaVoiceSession`` (``examples/clients/nova/audio.py:116-338``)
from a `NovaClient`/``aiohttp.web.WebSocketResponse``-coupled example into a
reusable core class:

- ``NovaClient`` -> any :class:`~parrot.clients.protocols.VoiceCapable`
  client (structural Protocol — see spec §3 Module 1).
- ``self.ws.send_json(payload)`` -> an injected
  ``send_fn: Callable[[dict], Awaitable[None]]``, so ``VoiceSession`` works
  with any transport (aiohttp WS, FastAPI WS, raw TCP, a test double).

One session serves many sequential turns over one transport connection;
only one turn is ever in flight (:meth:`start_turn` cancels any turn still
running). ``VoiceSession`` is stateless with respect to conversation
history (spec §8 Q2, resolved) — it forwards ``system_prompt`` and
``session_id`` on every turn (and on reconnect, TASK-2150); the caller
(``VoiceBot``, ``VoiceChatHandler``) owns memory persistence.
"""
from __future__ import annotations

import asyncio
import base64
import contextlib
import logging
import uuid
from typing import AsyncIterator, Awaitable, Callable, Optional

from ..clients.live import LiveVoiceResponse
from ..clients.protocols import VoiceCapable
from ..models.voice import VoiceConfig

logger = logging.getLogger(__name__)


class VoiceSession:
    """Provider-agnostic voice turn lifecycle manager.

    One session serves many sequential turns over one transport connection.

    Args:
        client: A :class:`~parrot.clients.protocols.VoiceCapable` client
            (e.g. ``GeminiLiveClient``, ``NovaClient``).
        send_fn: Async callable used to relay a JSON-serializable frame to
            the transport — typically a WebSocket's ``.send_json()``,
            wrapped in a small adapter.
        system_prompt: System instructions sent at the start of every turn.
        voice_config: Voice configuration; defaults to ``VoiceConfig()``.
        session_id: Stable identifier reported back to the caller and
            passed to ``stream_voice()`` for tracking.
    """

    def __init__(
        self,
        client: VoiceCapable,
        send_fn: Callable[[dict], Awaitable[None]],
        system_prompt: str,
        voice_config: Optional[VoiceConfig] = None,
        session_id: Optional[str] = None,
    ) -> None:
        self.client = client
        self.send_fn = send_fn
        self.system_prompt = system_prompt
        self.voice_config = voice_config or VoiceConfig()
        self.session_id = session_id or str(uuid.uuid4())
        self.logger = logger.getChild("session")

        self._queue: Optional[asyncio.Queue] = None
        self._task: Optional[asyncio.Task] = None
        self._turn_no = 0

    # -- turn lifecycle -----------------------------------------------------

    async def start_turn(self) -> None:
        """Open a new voice turn, cancelling any turn still running."""
        await self._cancel_turn()

        self._turn_no += 1
        self._queue = asyncio.Queue()
        self._task = asyncio.create_task(self._run_turn(self._turn_no))

        await self._send({
            "type": "turn_started",
            "turn": self._turn_no,
            "session_id": self.session_id,
        })

    async def push_audio(self, pcm: bytes) -> None:
        """Forward one PCM chunk (per ``voice_config.input_format``) to the
        current turn."""
        if self._queue is None:
            self.logger.debug("Dropping %d audio bytes — no turn open", len(pcm))
            return
        await self._queue.put(pcm)

    async def end_turn(self) -> None:
        """Signal end-of-turn so the model starts responding.

        Server-side VAD ends the user turn on detected end-of-speech —
        audio that stops abruptly after the last spoken word gives a
        speech-start event but the model never replies. Inject ~1.5 s of
        trailing silence so VAD detects end-of-speech before we push the
        ``None`` sentinel that marks end-of-turn. The turn task keeps
        running until the model finishes its reply.
        """
        if self._queue is not None:
            # ~1.5 s of silence at input_sample_rate, 16-bit mono, sent as
            # 1024-sample frames (~64 ms each at 16 kHz) to match the
            # working demo's frame size.
            #
            # CRITICAL: pace the silence so the provider's VAD has time to
            # detect end-of-speech. Dumping all frames in a burst causes
            # the VAD to miss end-of-speech entirely — see
            # NovaVoiceSession.end_turn() (the source this was promoted
            # from) for the full incident writeup. The working
            # sonic_e2e_demo.py paces every frame at 20 ms; preserved here
            # exactly. Total wall-clock cost: ~460 ms.
            silence_frame = b"\x00\x00" * 1024
            num_frames = int(self.voice_config.input_sample_rate * 1.5 / 1024)
            qsize_before = self._queue.qsize()
            for _ in range(num_frames):
                await self._queue.put(silence_frame)
                await asyncio.sleep(0.02)
            await self._queue.put(None)
            self.logger.info(
                "end_turn: pushed %d silence frames + None "
                "(queue was %d, now %d)",
                num_frames, qsize_before, self._queue.qsize(),
            )
        else:
            self.logger.warning("end_turn: _queue is None — nothing pushed")

    async def close(self) -> None:
        """Tear down any in-flight turn (caller disconnected)."""
        await self._cancel_turn()

    async def _cancel_turn(self) -> None:
        if self._task is not None and not self._task.done():
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
        self._task = None
        self._queue = None

    # -- provider plumbing ----------------------------------------------

    async def _audio_iterator(
        self,
        queue: asyncio.Queue,
    ) -> AsyncIterator[Optional[bytes]]:
        """Yield queued PCM chunks forever, until the turn task is cancelled.

        Deliberately does **not** stop on the ``None`` sentinel: ``None``
        marks end-of-*turn*, not end-of-stream, and the sender must stay
        alive while the model streams its reply back. The client's
        ``stream_voice()`` is responsible for stopping the sender in its
        own cleanup.
        """
        while True:
            yield await queue.get()

    async def _run_turn(self, turn_no: int) -> None:
        """Consume ``stream_voice()`` for one turn and relay it to the
        transport."""
        queue = self._queue
        assert queue is not None  # set by start_turn() before the task starts

        self.logger.info(
            "Turn %d starting (session=%s)", turn_no, self.session_id,
        )
        try:
            async for resp in self.client.stream_voice(
                self._audio_iterator(queue),
                system_prompt=self.system_prompt,
                session_id=self.session_id,
            ):
                await self._relay(resp, turn_no)
        except asyncio.CancelledError:
            self.logger.info("Turn %d cancelled", turn_no)
            raise
        except Exception as exc:  # surface any failure to the caller
            self.logger.exception("Turn %d failed", turn_no)
            await self._send({
                "type": "error",
                "turn": turn_no,
                "message": f"{type(exc).__name__}: {exc}",
            })
        finally:
            if self._task is asyncio.current_task():
                self._queue = None

    async def _relay(self, resp: LiveVoiceResponse, turn_no: int) -> None:
        """Translate one :class:`LiveVoiceResponse` into transport frames."""
        # Membership, not truthiness: a modelled provider error can carry an
        # empty message, and treating that as "no error" silently reports
        # the turn as complete.
        if "error" in resp.metadata:
            await self._send({
                "type": "error",
                "turn": turn_no,
                "message": resp.metadata["error"] or "Unknown voice provider error",
            })
            return

        if resp.text:
            await self._send({
                "type": "text",
                "turn": turn_no,
                "text": resp.text,
                "role": resp.role,
            })

        if resp.audio_data:
            await self._send({
                "type": "audio",
                "turn": turn_no,
                "audio_base64": base64.b64encode(resp.audio_data).decode("ascii"),
                "audio_format": resp.audio_format,
                "sample_rate": self.voice_config.output_sample_rate,
            })

        for call in resp.tool_calls:
            await self._send({
                "type": "tool_call",
                "turn": turn_no,
                "name": call.name,
                "arguments": call.arguments,
                "result": str(call.result) if call.result is not None else None,
                "error": call.error,
            })

        if resp.is_interrupted:
            await self._send({"type": "interrupted", "turn": turn_no})

        if resp.is_complete:
            usage = resp.usage
            if usage:
                self.logger.info(
                    "Turn %d usage: %d input / %d output / %d total tokens%s",
                    turn_no, usage.prompt_tokens, usage.completion_tokens,
                    usage.total_tokens,
                    f" ({usage.tool_calls_executed} tool call(s))"
                    if usage.tool_calls_executed else "",
                )
            await self._send({
                "type": "turn_complete",
                "turn": turn_no,
                "reconnect_required": bool(resp.metadata.get("reconnect_required")),
                "usage": {
                    "prompt_tokens": usage.prompt_tokens,
                    "completion_tokens": usage.completion_tokens,
                    "total_tokens": usage.total_tokens,
                    "tool_calls_executed": usage.tool_calls_executed,
                } if usage else None,
            })

    async def _send(self, payload: dict) -> None:
        """Relay one frame via the injected ``send_fn``.

        ``ConnectionResetError`` is suppressed (mirrors
        ``NovaVoiceSession._send``'s handling of a transport that dropped
        mid-turn); any other exception from ``send_fn`` propagates.
        """
        with contextlib.suppress(ConnectionResetError):
            await self.send_fn(payload)
