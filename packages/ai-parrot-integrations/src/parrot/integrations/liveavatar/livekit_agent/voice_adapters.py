"""LiveKit voice adapters — AI-Parrot's own STT/TTS for Phase C (FEAT-246).

Exposes adapter classes that wrap AI-Parrot's existing voice infra behind the
LiveKit Agents component interfaces, plus env-driven provider factories used
by the Phase C pipeline instead of the hardcoded Deepgram/Cartesia defaults.

**TTS** — :class:`SupertonicTTS` wraps
:class:`~parrot.voice.tts.supertonic_inference.SupertonicPipeline` behind
``tts.TTS``.  Synthesis runs in a worker thread (``asyncio.to_thread``) so
the event loop is never blocked.  Native sample rate (typically 44 100 Hz) is
declared honestly; LiveKit handles resampling.

**STT** — :class:`_TranscriberSTT` is a shared base that materialises an
``AudioBuffer`` to a temp WAV, calls
:meth:`~parrot.voice.transcriber.backend.AbstractTranscriberBackend.transcribe`,
and maps the result to a ``stt.SpeechEvent``.  :class:`WhisperSTT`
(faster-whisper) and :class:`MoonshineSTT` are concrete subclasses.  Temp
files are *always* unlinked.  Backend failures degrade to an empty transcript
rather than crashing the session.

**Factories** — :func:`resolve_stt` and :func:`resolve_tts` read
``LIVEAVATAR_STT_PROVIDER`` / ``LIVEAVATAR_TTS_PROVIDER`` from the environment
(default ``"whisper"`` / ``"supertonic"``) and return the matching component.
Non-streaming STT adapters are wrapped in ``stt.StreamAdapter`` + the
prewarmed Silero VAD so Phase C's ``AgentSession`` treats them as streaming.

All ``livekit.plugins.*`` imports (deepgram, cartesia, openai) are lazy inside
factory branches so those optional extras are not required at import time.
``livekit-agents`` itself is a hard dependency of the ``liveavatar-voice``
extra and is expected to be installed when this module is used.

Added by FEAT-246 (LiveKit Native Voice Adapters).
"""
from __future__ import annotations

import asyncio
import logging
import os
import tempfile
import uuid
import wave
from pathlib import Path
from typing import TYPE_CHECKING, Any, Optional

if TYPE_CHECKING:
    from livekit.agents import tts

__all__ = [
    "SupertonicTTS",
    "_TranscriberSTT",
    "WhisperSTT",
    "MoonshineSTT",
    "resolve_stt",
    "resolve_tts",
]

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# TTS adapter
# ---------------------------------------------------------------------------


def _make_supertonic_chunked_stream_cls() -> type:
    """Build and return a ``tts.ChunkedStream`` subclass for SupertonicTTS.

    Deferred to avoid importing ``livekit.agents.tts`` at module level.
    """
    from livekit.agents import tts

    class _SupertonicChunkedStream(tts.ChunkedStream):
        """``ChunkedStream`` backed by ``SupertonicPipeline.synthesize_pcm``."""

        def __init__(
            self,
            *,
            tts_instance: "SupertonicTTS",
            pipeline: Any,
            text: str,
            conn_options: Any,
        ) -> None:
            super().__init__(tts=tts_instance, input_text=text, conn_options=conn_options)
            self._pipeline = pipeline
            self._text = text
            self._stream_logger = logging.getLogger(__name__)

        async def _run(self, output_emitter: tts.AudioEmitter) -> None:  # type: ignore[override]
            """Synthesize *text* off the event loop and push PCM to *output_emitter*."""
            if not self._text or not self._text.strip():
                # Blank / whitespace — initialise emitter and return without pushing.
                output_emitter.initialize(
                    request_id=str(uuid.uuid4()),
                    sample_rate=self._pipeline.sample_rate,
                    num_channels=1,
                    mime_type="audio/pcm",
                )
                return

            try:
                pcm: bytes = await asyncio.to_thread(
                    self._pipeline.synthesize_pcm,
                    self._text,
                    voice=None,
                    language=None,
                )
            except Exception:
                self._stream_logger.exception(
                    "SupertonicTTS: synthesis failed for text %r; emitting silence",
                    self._text[:80],
                )
                pcm = b""

            output_emitter.initialize(
                request_id=str(uuid.uuid4()),
                sample_rate=self._pipeline.sample_rate,
                num_channels=1,
                mime_type="audio/pcm",
            )
            if pcm:
                output_emitter.push(pcm)
            output_emitter.flush()

    return _SupertonicChunkedStream


# Cache the dynamically-built class so it is only constructed once.
_SupertonicChunkedStreamCls: Optional[type] = None


def _get_chunked_stream_cls() -> type:
    global _SupertonicChunkedStreamCls
    if _SupertonicChunkedStreamCls is None:
        _SupertonicChunkedStreamCls = _make_supertonic_chunked_stream_cls()
    return _SupertonicChunkedStreamCls


def _make_supertonic_tts_cls() -> type:
    """Build and return a ``tts.TTS`` subclass for :class:`SupertonicTTS`."""
    from livekit.agents import tts

    class _SupertonicTTSImpl(tts.TTS):
        """``tts.TTS`` backed by ``SupertonicPipeline``."""

        def __init__(
            self,
            *,
            pipeline: Any,
            voice: Optional[str] = None,
            language: Optional[str] = None,
        ) -> None:
            super().__init__(
                capabilities=tts.TTSCapabilities(streaming=False, aligned_transcript=False),
                sample_rate=pipeline.sample_rate,
                num_channels=1,
            )
            self._supertonic_pipeline = pipeline
            self._voice = voice
            self._language = language
            self.logger = logging.getLogger(__name__)

        @property
        def model(self) -> str:
            return "supertonic"

        @property
        def provider(self) -> str:
            return "ai-parrot"

        def synthesize(self, text: str, *, conn_options: Any = None) -> Any:
            """Return a :class:`~_SupertonicChunkedStream` for *text*.

            Args:
                text: Text to synthesize.
                conn_options: LiveKit ``APIConnectOptions``; uses default when ``None``.

            Returns:
                A ``tts.ChunkedStream`` that produces 16-bit PCM audio frames.
            """
            from livekit.agents.tts.tts import DEFAULT_API_CONNECT_OPTIONS

            if conn_options is None:
                conn_options = DEFAULT_API_CONNECT_OPTIONS

            stream_cls = _get_chunked_stream_cls()
            return stream_cls(
                tts_instance=self,
                pipeline=self._supertonic_pipeline,
                text=text,
                conn_options=conn_options,
            )

    return _SupertonicTTSImpl


# Cache
_SupertonicTTSCls: Optional[type] = None


class SupertonicTTS:
    """``tts.TTS`` adapter over :class:`~parrot.voice.tts.supertonic_inference.SupertonicPipeline`.

    Wraps AI-Parrot's Supertonic-3 ONNX TTS behind the LiveKit Agents
    ``tts.TTS`` interface so Phase C's ``AgentSession`` can use it without
    the Cartesia plugin.

    Synthesis always runs off the event loop (``asyncio.to_thread``).  The
    native sample rate (typically 44 100 Hz) is declared honestly; LiveKit
    handles resampling to the room/avatar rate.

    Args:
        pipeline: A :class:`~parrot.voice.tts.supertonic_inference.SupertonicPipeline`
            instance.  Must be provided by the caller — no auto-build here, to
            avoid triggering ONNX model load at import time.
        voice: Optional voice id (e.g. ``"M1"``).  Passed through to the
            pipeline; reserved for future use.
        language: Optional BCP-47 language tag.  Passed through; reserved for
            future use.

    Example::

        pipeline = SupertonicPipeline(model_dir="/models/supertonic")
        tts_adapter = SupertonicTTS(pipeline=pipeline)
        stream = tts_adapter.synthesize("Hello, world!")
        async for audio in stream:
            ...  # process audio frames
    """

    def __new__(
        cls,
        *,
        pipeline: Any,
        voice: Optional[str] = None,
        language: Optional[str] = None,
    ) -> "SupertonicTTS":
        """Instantiate the concrete ``tts.TTS`` subclass (lazy livekit import)."""
        global _SupertonicTTSCls
        if _SupertonicTTSCls is None:
            _SupertonicTTSCls = _make_supertonic_tts_cls()
        # Bypass our own __new__ for the concrete class.
        instance = _SupertonicTTSCls.__new__(_SupertonicTTSCls)
        _SupertonicTTSCls.__init__(instance, pipeline=pipeline, voice=voice, language=language)
        return instance  # type: ignore[return-value]


# ---------------------------------------------------------------------------
# STT adapters
# ---------------------------------------------------------------------------


def _make_transcriber_stt_cls() -> type:
    """Build and return a ``stt.STT`` subclass for :class:`_TranscriberSTT`."""
    from livekit.agents import stt

    class _TranscriberSTTImpl(stt.STT):
        """Non-streaming ``stt.STT`` backed by an ``AbstractTranscriberBackend``."""

        def __init__(
            self,
            backend: Any,
            *,
            language: Optional[str] = None,
        ) -> None:
            super().__init__(
                capabilities=stt.STTCapabilities(
                    streaming=False,
                    interim_results=False,
                )
            )
            self._backend = backend
            self._language = language
            self.logger = logging.getLogger(__name__)

        async def _recognize_impl(
            self,
            buffer: Any,
            *,
            language: Any = None,
            conn_options: Any = None,
        ) -> Any:
            """Transcribe *buffer* via the backend.

            Materialises the ``AudioBuffer`` to a temp 16-bit mono WAV, calls
            the backend, and maps the result to a final ``stt.SpeechEvent``.
            The temp file is always unlinked.  Backend errors degrade to an
            empty transcript (logged, not propagated).

            Args:
                buffer: ``AudioBuffer`` (``AudioFrame | list[AudioFrame]``).
                language: Language hint; overrides ``self._language`` when set.
                conn_options: LiveKit connection options (unused by local
                    backends).

            Returns:
                A final ``stt.SpeechEvent`` with the transcript text.
            """
            from livekit.agents import utils as lk_utils

            lang: Optional[str] = language if language else self._language

            # Merge frames into a single AudioFrame.
            if isinstance(buffer, list):
                frame = lk_utils.combine_frames(buffer)
            else:
                frame = buffer

            sample_rate: int = frame.sample_rate
            num_channels: int = frame.num_channels
            raw_data: bytes = bytes(frame.data)

            tmp_path: Optional[Path] = None
            transcript_text = ""
            detected_language = lang or "en"

            try:
                with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as fh:
                    tmp_path = Path(fh.name)

                with wave.open(str(tmp_path), "wb") as wf:
                    wf.setnchannels(num_channels)
                    wf.setsampwidth(2)  # 16-bit signed integer
                    wf.setframerate(sample_rate)
                    wf.writeframes(raw_data)

                result = await self._backend.transcribe(tmp_path, lang)
                transcript_text = result.text or ""
                detected_language = result.language or detected_language

            except Exception:
                self.logger.exception(
                    "_TranscriberSTT: backend transcription failed; returning empty transcript"
                )
                transcript_text = ""

            finally:
                if tmp_path is not None and tmp_path.exists():
                    try:
                        tmp_path.unlink()
                    except OSError:
                        self.logger.warning(
                            "_TranscriberSTT: could not unlink temp file %s", tmp_path
                        )

            return stt.SpeechEvent(
                type=stt.SpeechEventType.FINAL_TRANSCRIPT,
                request_id=str(uuid.uuid4()),
                alternatives=[
                    stt.SpeechData(
                        language=detected_language,
                        text=transcript_text,
                        confidence=1.0,
                    )
                ],
            )

    return _TranscriberSTTImpl


# Cache
_TranscriberSTTCls: Optional[type] = None


class _TranscriberSTT:
    """Non-streaming ``stt.STT`` base backed by an ``AbstractTranscriberBackend``.

    Materialises the ``AudioBuffer`` to a temp 16-bit mono WAV, calls
    :meth:`~parrot.voice.transcriber.backend.AbstractTranscriberBackend.transcribe`,
    and maps the result to a final ``stt.SpeechEvent``.

    Temp files are *always* unlinked — even when the backend raises.  Backend
    errors degrade gracefully: an empty transcript event is returned and the
    error is logged (never propagated to crash the session).

    Use concrete subclasses :class:`WhisperSTT` or :class:`MoonshineSTT`.

    Args:
        backend: A concrete
            :class:`~parrot.voice.transcriber.backend.AbstractTranscriberBackend`
            instance.
        language: Optional ISO-639-1 language hint forwarded to the backend.
    """

    def __new__(
        cls,
        backend: Any,
        *,
        language: Optional[str] = None,
    ) -> "_TranscriberSTT":
        global _TranscriberSTTCls
        if _TranscriberSTTCls is None:
            _TranscriberSTTCls = _make_transcriber_stt_cls()
        instance = _TranscriberSTTCls.__new__(_TranscriberSTTCls)
        _TranscriberSTTCls.__init__(instance, backend, language=language)
        return instance  # type: ignore[return-value]


class WhisperSTT(_TranscriberSTT):
    """Non-streaming ``stt.STT`` backed by ``FasterWhisperBackend``.

    Wraps AI-Parrot's faster-whisper STT backend behind the LiveKit Agents
    ``stt.STT`` interface.  Designed to be wrapped in ``stt.StreamAdapter``
    with the prewarmed Silero VAD — see :func:`resolve_stt`.

    Args:
        model_size: faster-whisper model size.  Defaults to ``"small"``
            (good balance of latency and accuracy for avatar STT).
        language: Optional language hint forwarded to the backend.
        **kwargs: Extra keyword arguments forwarded to
            :class:`~parrot.voice.transcriber.faster_whisper_backend.FasterWhisperBackend`.

    Example::

        stt_adapter = WhisperSTT(model_size="small")
        wrapped = stt.StreamAdapter(stt=stt_adapter, vad=vad)
    """

    def __new__(  # type: ignore[override]
        cls,
        *,
        model_size: str = "small",
        language: Optional[str] = None,
        **kwargs: Any,
    ) -> "WhisperSTT":
        from parrot.voice.transcriber import FasterWhisperBackend

        backend = FasterWhisperBackend(model_size=model_size, **kwargs)
        return _TranscriberSTT.__new__(cls, backend, language=language)  # type: ignore[return-value]


class MoonshineSTT(_TranscriberSTT):
    """Non-streaming ``stt.STT`` backed by ``MoonshineSTTBackend``.

    Wraps AI-Parrot's Moonshine ONNX STT backend behind the LiveKit Agents
    ``stt.STT`` interface.  English-only; sub-second latency on CPU.

    Args:
        model_name: Moonshine model identifier.  Defaults to
            ``"moonshine/base"``.
        language: Optional language hint (Moonshine is English-only; this is
            passed through but effectively ignored).

    Example::

        stt_adapter = MoonshineSTT(model_name="moonshine/base")
        wrapped = stt.StreamAdapter(stt=stt_adapter, vad=vad)
    """

    def __new__(  # type: ignore[override]
        cls,
        *,
        model_name: str = "moonshine/base",
        language: Optional[str] = None,
    ) -> "MoonshineSTT":
        from parrot.voice.transcriber.moonshine_backend import MoonshineSTTBackend

        backend = MoonshineSTTBackend(model_name=model_name)
        return _TranscriberSTT.__new__(cls, backend, language=language)  # type: ignore[return-value]


# ---------------------------------------------------------------------------
# Provider factories
# ---------------------------------------------------------------------------

#: Default STT provider (env: ``LIVEAVATAR_STT_PROVIDER``).
_DEFAULT_STT_PROVIDER = "whisper"

#: Default TTS provider (env: ``LIVEAVATAR_TTS_PROVIDER``).
_DEFAULT_TTS_PROVIDER = "supertonic"


def resolve_stt(vad: Any) -> Any:
    """Build the STT component selected by ``LIVEAVATAR_STT_PROVIDER``.

    Non-streaming backends (:class:`WhisperSTT`, :class:`MoonshineSTT`) are
    wrapped in ``stt.StreamAdapter`` + *vad* so the ``AgentSession`` receives
    a streaming-capable STT component.

    Provider options (set via ``LIVEAVATAR_STT_PROVIDER``):

    - ``"whisper"`` *(default)* — :class:`WhisperSTT` + ``StreamAdapter``
    - ``"moonshine"`` — :class:`MoonshineSTT` + ``StreamAdapter``
    - ``"deepgram"`` — ``livekit.plugins.deepgram.STT`` (requires the extra)
    - ``"openai"`` — ``livekit.plugins.openai.STT`` (requires the extra)

    Args:
        vad: Prewarmed VAD instance (e.g. Silero) forwarded to
            ``stt.StreamAdapter``.

    Returns:
        A ``stt.STT``-compatible instance ready for ``AgentSession``.

    Raises:
        ImportError: If the requested provider's optional plugin is not
            installed.
    """
    from livekit.agents import stt

    provider = os.environ.get("LIVEAVATAR_STT_PROVIDER", _DEFAULT_STT_PROVIDER).lower()
    logger.debug("resolve_stt: provider=%r", provider)

    if provider == "whisper":
        model_size = os.environ.get("LIVEAVATAR_WHISPER_MODEL_SIZE", "small")
        stt_impl = WhisperSTT(model_size=model_size)
        return stt.StreamAdapter(stt=stt_impl, vad=vad)

    if provider == "moonshine":
        model_name = os.environ.get("LIVEAVATAR_MOONSHINE_MODEL", "moonshine/base")
        stt_impl = MoonshineSTT(model_name=model_name)
        return stt.StreamAdapter(stt=stt_impl, vad=vad)

    if provider == "deepgram":
        try:
            from livekit.plugins import deepgram
        except ImportError as exc:
            raise ImportError(
                "livekit-plugins-deepgram is required for STT provider 'deepgram'. "
                "Install the 'liveavatar-voice' extra."
            ) from exc
        model = os.environ.get("LIVEAVATAR_STT_MODEL", "nova-3")
        return deepgram.STT(model=model)

    if provider == "openai":
        try:
            from livekit.plugins import openai as lk_openai
        except ImportError as exc:
            raise ImportError(
                "livekit-plugins-openai is required for STT provider 'openai'. "
                "Install the 'liveavatar-voice' extra."
            ) from exc
        return lk_openai.STT()

    logger.warning(
        "resolve_stt: unknown provider %r; falling back to 'whisper'", provider
    )
    model_size = os.environ.get("LIVEAVATAR_WHISPER_MODEL_SIZE", "small")
    stt_impl = WhisperSTT(model_size=model_size)
    return stt.StreamAdapter(stt=stt_impl, vad=vad)


def resolve_tts() -> Any:
    """Build the TTS component selected by ``LIVEAVATAR_TTS_PROVIDER``.

    Provider options (set via ``LIVEAVATAR_TTS_PROVIDER``):

    - ``"supertonic"`` *(default)* — :class:`SupertonicTTS` (requires
      ``SUPERTONIC_MODEL_DIR`` env var)
    - ``"cartesia"`` — ``livekit.plugins.cartesia.TTS`` (requires the extra)
    - ``"inference"`` — ``livekit.plugins.openai.TTS`` via LiveKit inference
      (requires the extra)

    Returns:
        A ``tts.TTS``-compatible instance ready for ``AgentSession``.

    Raises:
        ValueError: If provider is ``"supertonic"`` and ``SUPERTONIC_MODEL_DIR``
            is not set.
        ImportError: If the requested provider's optional plugin is not
            installed.
    """
    provider = os.environ.get("LIVEAVATAR_TTS_PROVIDER", _DEFAULT_TTS_PROVIDER).lower()
    logger.debug("resolve_tts: provider=%r", provider)

    if provider == "supertonic":
        return _build_supertonic_tts()

    if provider == "cartesia":
        try:
            from livekit.plugins import cartesia
        except ImportError as exc:
            raise ImportError(
                "livekit-plugins-cartesia is required for TTS provider 'cartesia'. "
                "Install the 'liveavatar-voice' extra."
            ) from exc
        return cartesia.TTS()

    if provider == "inference":
        try:
            from livekit.plugins import openai as lk_openai
        except ImportError as exc:
            raise ImportError(
                "livekit-plugins-openai is required for TTS provider 'inference'. "
                "Install the 'liveavatar-voice' extra."
            ) from exc
        return lk_openai.TTS()

    logger.warning(
        "resolve_tts: unknown provider %r; falling back to 'supertonic'", provider
    )
    return _build_supertonic_tts()


def _build_supertonic_tts() -> Any:
    """Build a :class:`SupertonicTTS` from env configuration.

    Raises:
        ValueError: If ``SUPERTONIC_MODEL_DIR`` is not set.
    """
    model_dir = os.environ.get("SUPERTONIC_MODEL_DIR")
    if not model_dir:
        raise ValueError(
            "SUPERTONIC_MODEL_DIR env var is required for TTS provider 'supertonic'. "
            "Set it to the directory containing the Supertonic-3 ONNX model files."
        )
    from parrot.voice.tts.supertonic_inference import SupertonicPipeline

    pipeline = SupertonicPipeline(model_dir=model_dir)
    return SupertonicTTS(pipeline=pipeline)
