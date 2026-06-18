"""Tests for the chat→avatar bridge (FEAT-242 Phase A).

Covers :class:`AvatarVoiceProvider` PCM resampling and the per-turn
:class:`AvatarTurnSpeaker` (feed → background synth → WS push → finish).
"""
from __future__ import annotations

import asyncio
from typing import List

import numpy as np
import pytest

from parrot.integrations.liveavatar.models import AvatarSessionHandle
from parrot.integrations.liveavatar.speaker import AvatarTurnSpeaker
from parrot.integrations.liveavatar.voice_provider import (
    AVATAR_PCM_SAMPLE_RATE,
    AvatarVoiceProvider,
    _resample_pcm_int16,
)


def _make_handle() -> AvatarSessionHandle:
    return AvatarSessionHandle(
        session_id="sess-1",
        liveavatar_session_id="la-1",
        session_token="tok",
        ws_url="wss://example/ws",
        agent_name="pokemon_analyst",
    )


# ── Resampling ─────────────────────────────────────────────────────────


def test_resample_changes_length_by_rate_ratio() -> None:
    samples = (np.sin(np.linspace(0, 50, 44100)) * 10000).astype("<i2").tobytes()
    out = _resample_pcm_int16(samples, 44100, 24000)
    in_n = len(samples) // 2
    out_n = len(out) // 2
    assert out_n == pytest.approx(in_n * 24000 / 44100, rel=0.001)


def test_resample_noop_when_rates_equal() -> None:
    pcm = b"\x01\x00\x02\x00"
    assert _resample_pcm_int16(pcm, 24000, 24000) is pcm


def test_resample_empty_returns_empty() -> None:
    assert _resample_pcm_int16(b"", 44100, 24000) == b""


# ── Provider (with a fake pipeline — no ONNX) ──────────────────────────


class _FakePipeline:
    """Stand-in for SupertonicPipeline emitting deterministic 44.1 kHz PCM."""

    sample_rate = 44100

    def synthesize_pcm(self, text, *, voice=None, language=None):  # noqa: D401
        # 100 ms of non-silence per call, native rate.
        n = int(self.sample_rate * 0.1)
        return (np.ones(n) * 1000).astype("<i2").tobytes()


@pytest.mark.asyncio
async def test_provider_synthesizes_and_resamples_to_avatar_rate() -> None:
    provider = AvatarVoiceProvider()
    provider._pipeline = _FakePipeline()  # inject — skip the ONNX load

    pcm = await provider.synthesize_pcm("Hello world.")
    # 100 ms at 24 kHz mono 16-bit = 0.1 * 24000 * 2 bytes
    expected_samples = int(AVATAR_PCM_SAMPLE_RATE * 0.1)
    assert len(pcm) // 2 == pytest.approx(expected_samples, abs=2)


@pytest.mark.asyncio
async def test_provider_blank_text_returns_empty() -> None:
    provider = AvatarVoiceProvider()
    provider._pipeline = _FakePipeline()
    assert await provider.synthesize_pcm("   ") == b""


# ── Speaker (with a fake WebSocket — no network) ───────────────────────


class _FakeWS:
    """Records the audio frames + lifecycle calls an AvatarTurnSpeaker makes."""

    def __init__(self, handle, *, session=None) -> None:
        self.handle = handle
        self.frames: List[bytes] = []
        self.finished = False
        self.closed = False

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        self.closed = True

    async def send_audio_frame(self, pcm: bytes) -> None:
        self.frames.append(pcm)

    async def finish_speaking(self) -> None:
        self.finished = True


async def _fake_synth(text: str) -> bytes:
    # Deterministic: 4 bytes (2 samples) per sentence, non-empty.
    return b"\x10\x00\x20\x00"


@pytest.mark.asyncio
async def test_speaker_feeds_sentences_and_pushes_pcm(monkeypatch) -> None:
    import parrot.integrations.liveavatar.speaker as speaker_mod

    fake_ws = _FakeWS(_make_handle())
    monkeypatch.setattr(
        speaker_mod, "AvatarWebSocket", lambda handle, session=None, assume_connected=False: fake_ws
    )

    async with AvatarTurnSpeaker(_make_handle(), _fake_synth) as speaker:
        # Two complete sentences + one trailing partial flushed on finish.
        speaker.feed("Hello world. How are ")
        speaker.feed("you? Trailing tail")
        await speaker.finish()

    # 3 sentences synthesized → 3 frames pushed.
    assert len(fake_ws.frames) == 3
    assert all(f == b"\x10\x00\x20\x00" for f in fake_ws.frames)
    assert fake_ws.finished is True
    assert fake_ws.closed is True


@pytest.mark.asyncio
async def test_speaker_tts_failure_is_skipped_not_fatal(monkeypatch) -> None:
    import parrot.integrations.liveavatar.speaker as speaker_mod

    fake_ws = _FakeWS(_make_handle())
    monkeypatch.setattr(
        speaker_mod, "AvatarWebSocket", lambda handle, session=None, assume_connected=False: fake_ws
    )

    calls = {"n": 0}

    async def _flaky_synth(text: str) -> bytes:
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("boom")
        return b"\x01\x00"

    async with AvatarTurnSpeaker(_make_handle(), _flaky_synth) as speaker:
        speaker.feed("First sentence. Second sentence.")
        await speaker.finish()

    # First sentence failed (skipped), second succeeded → exactly one frame.
    assert fake_ws.frames == [b"\x01\x00"]
    assert fake_ws.finished is True


@pytest.mark.asyncio
async def test_speaker_aclose_is_idempotent(monkeypatch) -> None:
    import parrot.integrations.liveavatar.speaker as speaker_mod

    fake_ws = _FakeWS(_make_handle())
    monkeypatch.setattr(
        speaker_mod, "AvatarWebSocket", lambda handle, session=None, assume_connected=False: fake_ws
    )

    speaker = AvatarTurnSpeaker(_make_handle(), _fake_synth)
    await speaker.__aenter__()
    await speaker.aclose()
    await speaker.aclose()  # second call must be a no-op
    assert fake_ws.closed is True
    # feed after close is ignored (no exception)
    speaker.feed("ignored.")
