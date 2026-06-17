"""Avatar session orchestrator (FEAT-242 Phase A — Module 5).

Phase A glue that opens a LiveAvatar LITE session (with ``livekit_config`` so
the avatar joins our LiveKit Cloud room), consumes ``bot.ask_stream()``, runs
the ``SpeakableFlattener`` + sentence segmenter, synthesizes each sentence to
raw PCM via Supertonic (``synthesize_pcm``), and pushes the PCM frames to the
``AvatarWebSocket``.

Ownership:
- Opens the LiveAvatar session (TASK-002).
- Awaits the WS ``connected`` gate (TASK-003).
- Mints room tokens (TASK-004).
- Flattens + segments streamed text (TASK-005).
- Guarantees ``stop_session`` + WS close + keep-alive cancellation in ``finally``.

``synthesize_pcm_fn`` is an injectable callable that converts text → raw PCM
bytes (int16 LE mono 24 kHz).  This decouples the orchestrator from the ONNX
runtime for testing and allows plugging in Kokoro later without touching this
module.

Open questions deferred to owners:
- P6: per-sentence latency / 400 ms first-chunk feasibility on target hardware
  is unconfirmed.  # TODO P6 — tune chunk timing if needed after profiling.

Design note — ``synthesize_pcm_fn`` vs ``VoiceSynthesizer``:
``VoiceSynthesizer.synthesize()`` wraps the PCM in a WAV container, which is
NOT the format required by the AvatarWebSocket (raw PCM int16 LE 24 kHz).  The
raw PCM path is ``SupertonicPipeline.synthesize_pcm()`` (``supertonic_inference.py:528``).
Callers should inject this callable directly; see the module-level helper
``make_supertonic_pcm_fn()`` for a ready-to-use factory.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Callable, Dict, Optional

from parrot.integrations.liveavatar.avatar_ws import AvatarWebSocket
from parrot.integrations.liveavatar.client import LiveAvatarClient
from parrot.integrations.liveavatar.models import AvatarSessionHandle, LiveAvatarConfig
from parrot.integrations.liveavatar.room_manager import LiveKitRoomManager
from parrot.integrations.liveavatar.speakable import SpeakableFlattener


def make_supertonic_pcm_fn(
    *,
    voice: Optional[str] = None,
    language: Optional[str] = None,
) -> Callable[[str], bytes]:
    """Factory for a ``synthesize_pcm`` callable backed by Supertonic.

    Lazily imports ``SupertonicONNXBackend`` so the orchestrator does not
    hard-depend on the ONNX runtime at module-load time.

    Args:
        voice: Optional Supertonic voice identifier.
        language: Optional BCP-47 language tag.

    Returns:
        A synchronous callable ``(text: str) -> bytes`` that returns raw PCM
        int16 LE mono 24 kHz bytes.

    Raises:
        ImportError: If ``ai-parrot-integrations[voice-supertonic]`` is not
            installed.
    """
    try:
        from parrot.voice.tts.supertonic_inference import SupertonicPipeline  # type: ignore[import-untyped]
    except ImportError as exc:
        raise ImportError(
            "Supertonic is not installed.  "
            "Install ai-parrot-integrations[voice-supertonic]."
        ) from exc

    _pipeline = SupertonicPipeline()

    def _synthesize_pcm(text: str) -> bytes:
        return _pipeline.synthesize_pcm(text, voice=voice, language=language)

    return _synthesize_pcm


class AvatarSessionOrchestrator:
    """Phase A avatar session orchestrator — connects all M1–M4 components.

    Opens a LiveAvatar LITE session (with ``livekit_config`` so the avatar
    joins our LiveKit Cloud room), consumes ``bot.ask_stream()``, feeds the
    ``SpeakableFlattener``, synthesizes each complete sentence to PCM, and
    pushes the PCM frames via ``AvatarWebSocket``.

    ``stop_session``, WS close and keep-alive cancellation are guaranteed in
    ``finally`` blocks on every exit path.

    Args:
        cfg: LiveAvatar configuration (API key, avatar ID, …).
        bot: Any object with an ``ask_stream(question)`` async-generator method
            that yields ``str`` chunks followed by a non-str sentinel.
        client: The ``LiveAvatarClient`` instance (owns the HTTP session lifecycle).
        room_manager: The ``LiveKitRoomManager`` instance for minting tokens.
        synthesize_pcm_fn: Synchronous callable ``(text: str) -> bytes`` that
            returns raw PCM int16 LE mono 24 kHz.  Inject the Supertonic
            pipeline's ``synthesize_pcm`` method or a test stub here.
        ws_session: Optional ``aiohttp.ClientSession`` to inject into the WS
            (defaults to None — the WS creates its own).
    """

    def __init__(
        self,
        cfg: LiveAvatarConfig,
        bot: Any,
        *,
        client: LiveAvatarClient,
        room_manager: LiveKitRoomManager,
        synthesize_pcm_fn: Callable[[str], bytes],
        ws_session: Any = None,
    ) -> None:
        self.cfg = cfg
        self.bot = bot
        self._client = client
        self._room_manager = room_manager
        self._synthesize_pcm_fn = synthesize_pcm_fn
        self._ws_session = ws_session
        self.logger = logging.getLogger(__name__)

    async def run(
        self,
        question: str,
        *,
        agent_name: str,
        session_id: str,
        tenant_id: Optional[str] = None,
    ) -> AvatarSessionHandle:
        """Run the full Phase A avatar turn.

        Mints LiveKit room tokens, creates and starts the LiveAvatar session,
        opens the AvatarWebSocket, then iterates ``ask_stream`` to produce
        and speak each sentence as PCM.  Guaranteed cleanup on every exit path.

        Args:
            question: The user's question / query text.
            agent_name: Logical agent name (used as LiveKit room identity).
            session_id: ai-parrot session ID shared with AgentChat.
            tenant_id: Optional tenant identifier for opt-in gating.

        Returns:
            The completed :class:`AvatarSessionHandle` (session already stopped).

        # TODO P6 — per-sentence latency / 400 ms first-chunk feasibility on
        #   target hardware is unconfirmed; tune chunk timing after profiling.
        """
        # 1. Mint LiveKit room tokens
        tokens = self._room_manager.mint_room_tokens(room=session_id, identity=agent_name)
        livekit_config: Dict[str, Any] = {
            "url": tokens.livekit_url,
            "room": tokens.room,
            "agentToken": tokens.agent_token,
        }

        # 2. Create LiveAvatar session (with livekit_config for BYO transport)
        handle = await self._client.create_session_token(
            self.cfg, livekit_config=livekit_config
        )
        handle = AvatarSessionHandle(
            session_id=session_id,
            liveavatar_session_id=handle.liveavatar_session_id,
            session_token=handle.session_token,
            ws_url=handle.ws_url,
            tenant_id=tenant_id,
            agent_name=agent_name,
        )

        try:
            # 3. Start the session
            await self._client.start_session(handle)

            # 4. Open the Avatar WebSocket and await the connected gate
            async with AvatarWebSocket(handle, session=self._ws_session) as ws:
                await ws.start_speaking()

                flattener = SpeakableFlattener()

                async for item in self.bot.ask_stream(question):
                    if isinstance(item, str):
                        # Accumulate and emit complete sentences for TTS
                        for sentence in flattener.feed(item):
                            await self._speak(ws, sentence)
                    else:
                        # Final AIMessage sentinel — flush remaining buffer
                        for sentence in flattener.flush():
                            await self._speak(ws, sentence)

                await ws.finish_speaking()

        finally:
            # Guaranteed teardown: stop_session on every exit path
            try:
                await self._client.stop_session(handle)
            except Exception:  # noqa: BLE001
                self.logger.exception(
                    "AvatarSessionOrchestrator: stop_session failed for %s",
                    handle.liveavatar_session_id,
                )

        # Also return the room tokens for TASK-007 to forward to the client
        handle = AvatarSessionHandle(
            session_id=handle.session_id,
            liveavatar_session_id=handle.liveavatar_session_id,
            session_token=handle.session_token,
            ws_url=handle.ws_url,
            tenant_id=handle.tenant_id,
            agent_name=handle.agent_name,
        )
        # Attach room tokens as attributes for the endpoint (TASK-007)
        object.__setattr__(handle, "_livekit_tokens", tokens)
        return handle

    async def _speak(self, ws: AvatarWebSocket, sentence: str) -> None:
        """Synthesize a sentence to PCM and push it to the AvatarWebSocket.

        On TTS failure the sentence is logged and skipped — the turn continues
        in text-only mode (graceful degradation per spec §7).

        Args:
            ws: The connected ``AvatarWebSocket``.
            sentence: The speakable sentence to synthesize.
        """
        if not sentence.strip():
            return
        try:
            # Run synchronous synthesize_pcm off the event loop
            # TODO P6 — per-sentence ONNX latency; profile on target hw
            pcm_bytes: bytes = await asyncio.to_thread(self._synthesize_pcm_fn, sentence)
            if pcm_bytes:
                await ws.send_audio_frame(pcm_bytes)
        except Exception:  # noqa: BLE001
            self.logger.warning(
                "AvatarSessionOrchestrator: TTS failed for sentence %r — skipping",
                sentence[:80],
                exc_info=True,
            )
            # Graceful degradation: continue; text already rendered in the UI
