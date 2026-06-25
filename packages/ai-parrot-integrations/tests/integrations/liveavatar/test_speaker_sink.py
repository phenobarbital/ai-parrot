"""Unit tests for mode-aware AvatarTurnSpeaker sink (FEAT-256 TASK-1628).

Verifies that PCM is routed to the correct sink:
- avatar-OFF: RoomAudioPublisher.capture_pcm (NOT the LiveAvatar WS)
- avatar-ON:  AvatarWebSocket.send_audio_frame (unchanged path)
"""
from __future__ import annotations

from typing import List

import pytest

from parrot.integrations.liveavatar.models import AvatarSessionHandle
from parrot.integrations.liveavatar.speaker import AvatarTurnSpeaker


# ---------------------------------------------------------------------------
# Shared helpers / fake objects
# ---------------------------------------------------------------------------


def _make_handle() -> AvatarSessionHandle:
    return AvatarSessionHandle(
        session_id="sess-sink-test",
        liveavatar_session_id="la-sink-1",
        session_token="tok",
        ws_url="wss://example/ws",
        agent_name="test_agent",
    )


async def _fake_synth(text: str) -> bytes:
    """Deterministic 4-byte PCM per call."""
    return b"\x10\x00\x20\x00"


class _FakeWS:
    """Records calls made to the LiveAvatar WebSocket."""

    def __init__(self, *args, **kwargs) -> None:
        self.frames: List[bytes] = []
        self.finished = False
        self.interrupted = False
        self.closed = False

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        self.closed = True

    async def send_audio_frame(self, pcm: bytes) -> None:
        self.frames.append(pcm)

    async def finish_speaking(self) -> None:
        self.finished = True

    async def interrupt(self) -> None:
        self.interrupted = True


class _FakePublisher:
    """Records calls made to RoomAudioPublisher."""

    def __init__(self) -> None:
        self.captured: List[bytes] = []
        self.flush_count = int(0)
        self._closed = False

    async def capture_pcm(self, pcm: bytes) -> None:
        self.captured.append(pcm)

    async def flush(self) -> None:
        self.flush_count += 1

    async def aclose(self) -> None:
        self._closed = True


# ---------------------------------------------------------------------------
# Tests: avatar-OFF (room publisher) sink
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_routes_to_room_when_avatar_off(monkeypatch) -> None:
    """With room_publisher set, PCM goes to publisher.capture_pcm — not the WS."""
    import parrot.integrations.liveavatar.speaker as speaker_mod

    fake_ws = _FakeWS()
    monkeypatch.setattr(
        speaker_mod,
        "AvatarWebSocket",
        lambda handle, session=None, assume_connected=False: fake_ws,
    )

    publisher = _FakePublisher()

    async with AvatarTurnSpeaker(
        _make_handle(), _fake_synth, room_publisher=publisher
    ) as speaker:
        speaker.feed("Hello world. How are you?")
        await speaker.finish()

    # PCM must have gone to the publisher
    assert len(publisher.captured) >= 1
    assert all(f == b"\x10\x00\x20\x00" for f in publisher.captured)
    # The LiveAvatar WS must NOT have been called
    assert fake_ws.frames == []
    # WS must not have been opened (no __aenter__ called)
    assert not fake_ws.closed  # never entered → never exited


@pytest.mark.asyncio
async def test_routes_to_liveavatar_when_avatar_on(monkeypatch) -> None:
    """Without room_publisher, PCM still goes to the LiveAvatar WS (unchanged path)."""
    import parrot.integrations.liveavatar.speaker as speaker_mod

    fake_ws = _FakeWS()
    monkeypatch.setattr(
        speaker_mod,
        "AvatarWebSocket",
        lambda handle, session=None, assume_connected=False: fake_ws,
    )

    publisher = _FakePublisher()

    # no room_publisher → avatar-ON path
    async with AvatarTurnSpeaker(_make_handle(), _fake_synth) as speaker:
        speaker.feed("Hello world. How are you?")
        await speaker.finish()

    # PCM must have gone to the WS
    assert len(fake_ws.frames) >= 1
    assert all(f == b"\x10\x00\x20\x00" for f in fake_ws.frames)
    # Publisher must not have been called
    assert publisher.captured == []


@pytest.mark.asyncio
async def test_interrupt_flushes_publisher_when_avatar_off(monkeypatch) -> None:
    """interrupt() calls publisher.flush() in avatar-OFF mode."""
    import parrot.integrations.liveavatar.speaker as speaker_mod

    monkeypatch.setattr(
        speaker_mod,
        "AvatarWebSocket",
        lambda *a, **kw: _FakeWS(),
    )

    publisher = _FakePublisher()
    speaker = AvatarTurnSpeaker(
        _make_handle(), _fake_synth, room_publisher=publisher
    )
    await speaker.__aenter__()
    await speaker.interrupt()

    assert publisher.flush_count >= 1
    await speaker.aclose()


@pytest.mark.asyncio
async def test_interrupt_calls_ws_interrupt_when_avatar_on(monkeypatch) -> None:
    """interrupt() calls ws.interrupt() in avatar-ON mode."""
    import parrot.integrations.liveavatar.speaker as speaker_mod

    fake_ws = _FakeWS()
    monkeypatch.setattr(
        speaker_mod,
        "AvatarWebSocket",
        lambda *a, **kw: fake_ws,
    )

    # no room_publisher → avatar-ON
    speaker = AvatarTurnSpeaker(_make_handle(), _fake_synth)
    await speaker.__aenter__()
    await speaker.interrupt()

    assert fake_ws.interrupted is True
    await speaker.aclose()


@pytest.mark.asyncio
async def test_finish_calls_publisher_flush_not_finish_speaking(monkeypatch) -> None:
    """finish() calls publisher.flush (not WS.finish_speaking) in avatar-OFF mode."""
    import parrot.integrations.liveavatar.speaker as speaker_mod

    fake_ws = _FakeWS()
    monkeypatch.setattr(
        speaker_mod,
        "AvatarWebSocket",
        lambda *a, **kw: fake_ws,
    )

    publisher = _FakePublisher()
    async with AvatarTurnSpeaker(
        _make_handle(), _fake_synth, room_publisher=publisher
    ) as speaker:
        await speaker.finish()

    assert publisher.flush_count >= 1
    # WS.finish_speaking must NOT have been called
    assert fake_ws.finished is False


@pytest.mark.asyncio
async def test_graceful_degradation_publisher_error(monkeypatch) -> None:
    """A publisher.capture_pcm error is logged and skipped — turn continues."""
    import parrot.integrations.liveavatar.speaker as speaker_mod

    monkeypatch.setattr(
        speaker_mod, "AvatarWebSocket", lambda *a, **kw: _FakeWS()
    )

    class _BrokenPublisher(_FakePublisher):
        async def capture_pcm(self, pcm: bytes) -> None:
            raise RuntimeError("network error")

    broken = _BrokenPublisher()
    async with AvatarTurnSpeaker(
        _make_handle(), _fake_synth, room_publisher=broken
    ) as speaker:
        # Should not raise even though capture_pcm always fails
        speaker.feed("First sentence. Second sentence.")
        await speaker.finish()
    # If we get here without exception the degradation works correctly.
