"""Shared avatar voice provider (FEAT-242 Phase A — chat→avatar wiring).

Bridges the agent's text replies to the LiveAvatar "mouth" by synthesizing
speakable sentences to **raw PCM at the rate the avatar expects** (24 kHz mono
16-bit, see :mod:`parrot.integrations.liveavatar.avatar_ws`).

Two concerns are solved here so the request handlers stay thin:

1. **Lazy, shared Supertonic pipeline.** Building a :class:`SupertonicPipeline`
   loads four ONNX graphs and costs seconds, so the pipeline is created ONCE on
   first use (under an async lock) and reused across every avatar turn.  The
   provider object itself is cheap to construct, so it can be stored on the
   aiohttp ``app`` at startup without paying the model-load cost up front.

2. **Sample-rate reconciliation.** Supertonic-3 emits PCM at its *native* rate
   (``pipeline.sample_rate`` — 44.1 kHz for the shipped weights), but the
   LiveAvatar LITE media server assumes 24 kHz mono 16-bit (the chunk sizing in
   ``avatar_ws.py`` is built around that).  Feeding 44.1 kHz PCM unchanged makes
   the avatar play audio at the wrong pitch/speed, so the provider resamples to
   :data:`AVATAR_PCM_SAMPLE_RATE` before returning.

The public surface is a single async callable :meth:`synthesize_pcm` with the
shape ``(text: str) -> bytes`` — exactly what :class:`AvatarTurnSpeaker`
consumes.  Synthesis runs in a worker thread so the event loop is never blocked.
"""
from __future__ import annotations

import asyncio
import logging
import os
from typing import Any, Optional

# The sample rate the LiveAvatar LITE media server expects (mirrors the
# constant baked into avatar_ws.py).  All PCM handed to the avatar MUST be at
# this rate, mono, 16-bit little-endian.
AVATAR_PCM_SAMPLE_RATE: int = 24_000


def _resample_pcm_int16(pcm: bytes, src_rate: int, dst_rate: int) -> bytes:
    """Resample 16-bit LE mono PCM from ``src_rate`` to ``dst_rate``.

    Uses linear interpolation (``numpy.interp``), which is more than adequate
    for speech and avoids a heavyweight DSP dependency.  A no-op when the rates
    already match or ``pcm`` is empty.

    Args:
        pcm: Raw PCM bytes (int16 little-endian, mono) at ``src_rate``.
        src_rate: Source sample rate in Hz.
        dst_rate: Target sample rate in Hz.

    Returns:
        Resampled raw PCM bytes (int16 little-endian, mono) at ``dst_rate``.
    """
    if not pcm or src_rate == dst_rate:
        return pcm

    import numpy as np  # lazy: numpy is heavy and only needed for resampling

    samples = np.frombuffer(pcm, dtype="<i2").astype(np.float32)
    n_src = samples.shape[0]
    if n_src == 0:
        return b""

    n_dst = int(round(n_src * dst_rate / src_rate))
    if n_dst <= 0:
        return b""

    # Map each target sample position back onto the source index grid.
    src_index = np.linspace(0.0, n_src - 1, num=n_dst, dtype=np.float64)
    resampled = np.interp(src_index, np.arange(n_src, dtype=np.float64), samples)
    return np.clip(resampled, -32768.0, 32767.0).astype("<i2").tobytes()


class AvatarVoiceProvider:
    """Lazily-built, shared Supertonic→PCM provider for avatar speech.

    Construct once (cheap) and store on the aiohttp ``app``.  The first call to
    :meth:`synthesize_pcm` builds the ONNX pipeline; subsequent calls reuse it.

    Args:
        model_dir: Supertonic model directory.  When ``None`` the standard
            resolution order is used: ``SUPERTONIC_MODEL_PATH`` env var, then
            ``<BASE_DIR>/models/supertonic-3``.
        voice: Default Supertonic voice id (``M1``..``F5``).
        language: Default BCP-47 language tag.
        target_sample_rate: Output PCM sample rate handed to the avatar.
            Defaults to :data:`AVATAR_PCM_SAMPLE_RATE` (24 kHz).
    """

    def __init__(
        self,
        *,
        model_dir: Optional[str] = None,
        voice: Optional[str] = None,
        language: Optional[str] = None,
        target_sample_rate: int = AVATAR_PCM_SAMPLE_RATE,
    ) -> None:
        self._model_dir = model_dir
        self._voice = voice
        self._language = language
        self._target_sample_rate = target_sample_rate
        self._pipeline: Optional[Any] = None
        self._lock = asyncio.Lock()
        self.logger = logging.getLogger(__name__)

    def _resolve_model_dir(self) -> str:
        """Resolve the Supertonic model directory (env / BASE_DIR fallback)."""
        if self._model_dir:
            return os.path.expanduser(self._model_dir)
        env = os.environ.get("SUPERTONIC_MODEL_PATH")
        if env:
            return os.path.expanduser(env)
        try:
            from navconfig import BASE_DIR  # type: ignore[import-untyped]

            return str(BASE_DIR / "models" / "supertonic-3")
        except Exception:  # noqa: BLE001 - fall back to a CWD-relative default
            return os.path.join(os.getcwd(), "models", "supertonic-3")

    async def _ensure_pipeline(self) -> Any:
        """Build the Supertonic pipeline once, under a lock, and cache it.

        Returns:
            The shared :class:`SupertonicPipeline` instance.

        Raises:
            ImportError: If ``ai-parrot-integrations[voice-supertonic]`` is not
                installed.
            ValueError: If the model directory cannot be resolved.
        """
        if self._pipeline is not None:
            return self._pipeline
        async with self._lock:
            if self._pipeline is not None:  # double-checked under the lock
                return self._pipeline
            model_dir = self._resolve_model_dir()
            self.logger.info(
                "AvatarVoiceProvider: loading Supertonic pipeline from %s "
                "(first avatar turn — this is a one-time cost)",
                model_dir,
            )

            def _build() -> Any:
                from parrot.voice.tts.supertonic_inference import (  # noqa: PLC0415
                    SupertonicPipeline,
                )

                return SupertonicPipeline(model_dir)

            self._pipeline = await asyncio.to_thread(_build)
            self.logger.info(
                "AvatarVoiceProvider: Supertonic ready (native_rate=%d → "
                "avatar_rate=%d)",
                getattr(self._pipeline, "sample_rate", -1),
                self._target_sample_rate,
            )
            return self._pipeline

    async def synthesize_pcm(self, text: str) -> bytes:
        """Synthesize ``text`` to avatar-ready PCM (24 kHz mono 16-bit LE).

        Builds the pipeline on first use, runs synthesis in a worker thread,
        and resamples the native-rate output down to the avatar's expected
        rate.  Returns ``b""`` for blank input.

        Args:
            text: A speakable sentence (already markdown-flattened).

        Returns:
            Raw PCM bytes at :attr:`_target_sample_rate`, or ``b""`` if there is
            nothing to speak.
        """
        if not text or not text.strip():
            return b""
        pipeline = await self._ensure_pipeline()

        def _synth() -> bytes:
            native = pipeline.synthesize_pcm(
                text, voice=self._voice, language=self._language
            )
            return _resample_pcm_int16(
                native, int(pipeline.sample_rate), self._target_sample_rate
            )

        return await asyncio.to_thread(_synth)
