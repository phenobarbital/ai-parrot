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
from collections.abc import AsyncIterator, Awaitable, Callable

from ..clients.protocols import VoiceCapable
from ..models.voice import LiveVoiceResponse, VoiceConfig, VoiceStreamOptions

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
        stt_only: Request speech-to-text-only behavior on every turn
            (FEAT-418, TASK-2172). Forwarded into the projected
            ``VoiceStreamOptions`` on every ``stream_voice()`` call. If
            ``client.voice_capabilities.native_stt_only`` is ``False``
            (e.g. Nova, which always generates a spoken response), this
            never raises — it emits one ``capability_notice`` frame per
            session instead (spec §7: never filter, never fail).

    Raises:
        ValueError: At construction, if ``voice_config``'s audio formats
            or sample rates are not declared as supported by
            ``client.voice_capabilities`` (FEAT-418, TASK-2172 preflight).
    """

    def __init__(
        self,
        client: VoiceCapable,
        send_fn: Callable[[dict], Awaitable[None]],
        system_prompt: str,
        voice_config: VoiceConfig | None = None,
        session_id: str | None = None,
        stt_only: bool = False,
    ) -> None:
        self.client = client
        self.send_fn = send_fn
        self.system_prompt = system_prompt
        self.voice_config = voice_config or VoiceConfig()
        self.session_id = session_id or str(uuid.uuid4())
        self.stt_only = stt_only
        self.logger = logger.getChild("session")

        self._queue: asyncio.Queue | None = None
        self._task: asyncio.Task | None = None
        self._turn_no = 0
        # FEAT-416 (TASK-2150): lifetime reconnection counter — resets
        # only on __init__, not per-turn (spec §3 Module 6 Key Constraints).
        self._reconnect_count = 0
        # FEAT-418 (TASK-2172): capability names already notified this
        # session — a notice fires at most once per session, not per turn.
        self._notified_capabilities: set = set()

        # FEAT-418 (TASK-2172): audio-format preflight. Raises at
        # construction (fail fast) rather than mid-stream; the knob-level
        # check (stt_only, etc.) is intentionally NOT here — it must never
        # raise (spec §7) and happens per-turn in _run_turn() instead.
        self._preflight_audio_formats()

    # -- capability checks (FEAT-418, TASK-2172) -----------------------

    def _preflight_audio_formats(self) -> None:
        """Validate ``voice_config``'s audio formats/sample rates against
        ``client.voice_capabilities`` at construction time.

        Raises:
            ValueError: Naming both the requested and the supported side,
                so the mismatch is immediately actionable. Both current
                providers (Gemini, Nova) declare identical formats
                (PCM 16k in / 24k out) — this is descriptive today, but
                becomes load-bearing the moment a non-PCM provider lands.
        """
        caps = self.client.voice_capabilities
        checks = (
            ("input_format", self.voice_config.input_format, caps.input_formats),
            ("output_format", self.voice_config.output_format, caps.output_formats),
            ("input_sample_rate", self.voice_config.input_sample_rate, caps.input_sample_rates),
            ("output_sample_rate", self.voice_config.output_sample_rate, caps.output_sample_rates),
        )
        for name, requested, supported in checks:
            if requested not in supported:
                raise ValueError(
                    f"VoiceConfig.{name}={requested!r} is not supported by "
                    f"{caps.provider.value} (supports: {sorted(map(str, supported))})"
                )

    def _check_capability_notices(self, options: VoiceStreamOptions) -> list[dict]:
        """Compare the projected *options* against the client's declared
        capabilities, returning any new ``capability_notice`` frames.

        Never raises — an unsupported-but-requested knob is reported, not
        rejected (spec §7: e.g. ``stt_only=True`` on Nova must still
        proceed and still generate a spoken response). Each capability
        name notifies at most once per session (tracked in
        ``self._notified_capabilities``), not per turn and not per frame.

        Args:
            options: The per-call options projected for this turn.

        Returns:
            A list of ``capability_notice`` frame dicts (usually 0 or 1).
        """
        notices: list[dict] = []
        caps = self.client.voice_capabilities

        if (
            options.stt_only
            and not caps.native_stt_only
            and "stt_only" not in self._notified_capabilities
        ):
            self._notified_capabilities.add("stt_only")
            message = (
                f"{caps.provider.value} does not natively support "
                f"stt_only — the model response is still generated."
            )
            self.logger.warning("VoiceSession: %s", message)
            notices.append({
                "type": "capability_notice",
                "session_id": self.session_id,
                "capability": "stt_only",
                "provider": caps.provider.value,
                "message": message,
            })

        return notices

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
    ) -> AsyncIterator[bytes | None]:
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
            # FEAT-416 (TASK-2150): outer loop enables transparent
            # reconnection — reconnect_required=True + reconnect_on_limit
            # closes the exhausted stream_voice() generator and opens a
            # fresh one with the same system_prompt/session_id, resuming
            # from the same (still-live) audio queue (spec §3 Module 6).
            while True:
                reconnecting = False
                # FEAT-418 (TASK-2171): project VoiceConfig into per-call
                # options on EVERY iteration of this loop — including
                # reconnects — so a reconnect that silently drops the
                # caller's temperature/max_tokens/voice/etc. (the bug this
                # task fixes) cannot happen. Recomputed each iteration
                # rather than hoisted above the loop, in case a subclass
                # mutates ``self.voice_config`` between reconnects.
                # FEAT-418 (TASK-2172): self.stt_only is folded in as an
                # explicit override, since VoiceConfig itself carries no
                # stt_only field.
                options = self.voice_config.to_stream_options(stt_only=self.stt_only)
                for notice in self._check_capability_notices(options):
                    await self._send(notice)
                stream = self.client.stream_voice(
                    self._audio_iterator(queue),
                    system_prompt=self.system_prompt,
                    session_id=self.session_id,
                    stt_only=self.stt_only,
                    options=options,
                )
                try:
                    async for resp in stream:
                        # Relaying the frame first — including any
                        # tool_calls it carries — before evaluating
                        # reconnect_required ensures pending tool
                        # execution for this response is already
                        # complete (spec §7 8-minute reconnection race).
                        await self._relay(resp, turn_no)

                        if not (
                            resp.metadata.get("reconnect_required")
                            and self.voice_config.reconnect_on_limit
                        ):
                            continue

                        if self._reconnect_count >= self.voice_config.max_reconnects:
                            await self._send({
                                "type": "error",
                                "message": "max reconnections reached",
                                "session_id": self.session_id,
                            })
                            # Tear down directly rather than via close()/
                            # _cancel_turn() — this coroutine IS self._task,
                            # so awaiting self._task here would deadlock
                            # (a task cannot await itself). The task is
                            # ending on its own; just clear the references
                            # (guarded, mirroring the outer finally below,
                            # in case a newer start_turn() already replaced
                            # them).
                            if self._task is asyncio.current_task():
                                self._queue = None
                                self._task = None
                            return

                        self._reconnect_count += 1
                        await self._send({
                            "type": "reconnect",
                            "session_id": self.session_id,
                            "reconnect_count": self._reconnect_count,
                        })
                        reconnecting = True
                        break
                finally:
                    # Close the exhausted (or abandoned) generator before
                    # opening a new one or exiting — mirrors "close the
                    # old stream_voice() async generator" (spec §3
                    # Module 6, step 3).
                    with contextlib.suppress(Exception):
                        await stream.aclose()

                if not reconnecting:
                    break
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

    def build_frames(self, resp: LiveVoiceResponse, turn_no: int) -> list[dict]:
        """Translate one :class:`LiveVoiceResponse` into transport frames.

        Relay extension hook (FEAT-418, spec §3 Module 6, G5). Subclasses
        override THIS method to emit a richer/different frame protocol —
        e.g. ``_HandlerVoiceSession`` in ai-parrot-integrations — without
        re-implementing the turn loop or reconnection logic in
        ``_run_turn()``. ``_relay()`` calls this and sends whatever it
        returns, in order; it never needs to know about ``_send()``.

        The default implementation reproduces the frame construction that
        previously lived directly in ``_relay()``, byte-for-byte, so
        existing frontends and tests see no change.

        Args:
            resp: The provider response to translate.
            turn_no: The current turn number.

        Returns:
            A list of JSON-serializable frame dicts, in send order.
        """
        frames: list[dict] = []

        # Membership, not truthiness: a modelled provider error can carry an
        # empty message, and treating that as "no error" silently reports
        # the turn as complete.
        if "error" in resp.metadata:
            frames.append({
                "type": "error",
                "turn": turn_no,
                "message": resp.metadata["error"] or "Unknown voice provider error",
            })
            return frames

        if resp.text:
            frames.append({
                "type": "text",
                "turn": turn_no,
                "text": resp.text,
                "role": resp.role,
            })

        if resp.audio_data:
            frames.append({
                "type": "audio",
                "turn": turn_no,
                "audio_base64": base64.b64encode(resp.audio_data).decode("ascii"),
                "audio_format": resp.audio_format,
                "sample_rate": self.voice_config.output_sample_rate,
            })

        for call in resp.tool_calls:
            frames.append({
                "type": "tool_call",
                "turn": turn_no,
                "name": call.name,
                "arguments": call.arguments,
                "result": str(call.result) if call.result is not None else None,
                "error": call.error,
            })

        if resp.is_interrupted:
            frames.append({"type": "interrupted", "turn": turn_no})

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
            frames.append({
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

        return frames

    async def _relay(self, resp: LiveVoiceResponse, turn_no: int) -> None:
        """Send every frame :meth:`build_frames` produces for *resp*."""
        for frame in self.build_frames(resp, turn_no):
            await self._send(frame)

    async def _send(self, payload: dict) -> None:
        """Relay one frame via the injected ``send_fn``.

        ``ConnectionResetError`` is suppressed (mirrors
        ``NovaVoiceSession._send``'s handling of a transport that dropped
        mid-turn); any other exception from ``send_fn`` propagates.
        """
        with contextlib.suppress(ConnectionResetError):
            await self.send_fn(payload)
