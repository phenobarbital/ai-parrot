"""Unit tests for RoomAudioPublisher (FEAT-256 TASK-1627).

The livekit realtime SDK is mocked — no real network connections are made.
"""
from __future__ import annotations

from typing import Any, List
from unittest.mock import patch

import pytest

from parrot.integrations.liveavatar.models import LiveKitRoomTokens
from parrot.integrations.liveavatar.room_audio_publisher import RoomAudioPublisher


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def fake_room_tokens() -> LiveKitRoomTokens:
    """Minimal LiveKitRoomTokens for tests (no real JWT signing)."""
    return LiveKitRoomTokens(
        livekit_url="wss://test.livekit.cloud",
        room="test-room",
        client_token="client-tok",
        agent_token="agent-tok",
    )


class _FakeAudioSource:
    """Stand-in for ``livekit.rtc.AudioSource``."""

    def __init__(self, sample_rate: int, num_channels: int) -> None:
        self.sample_rate = sample_rate
        self.num_channels = num_channels
        self.captured_frames: List[Any] = []

    async def capture_frame(self, frame: Any) -> None:
        self.captured_frames.append(frame)


class _FakeAudioFrame:
    """Stand-in for ``livekit.rtc.AudioFrame``."""

    def __init__(
        self,
        *,
        data: bytes,
        sample_rate: int,
        num_channels: int,
        samples_per_channel: int,
    ) -> None:
        self.data = data
        self.sample_rate = sample_rate
        self.num_channels = num_channels
        self.samples_per_channel = samples_per_channel


class _FakeLocalParticipant:
    """Stand-in for ``livekit.rtc.Room.local_participant``."""

    def __init__(self) -> None:
        self.published_tracks: List[Any] = []

    async def publish_track(self, track: Any, options: Any) -> None:
        self.published_tracks.append((track, options))


class _FakeRoom:
    """Stand-in for ``livekit.rtc.Room``."""

    def __init__(self) -> None:
        self.connected_url: str = ""
        self.connected_token: str = ""
        self.local_participant = _FakeLocalParticipant()
        self.disconnected = False

    async def connect(self, url: str, token: str) -> None:
        self.connected_url = url
        self.connected_token = token

    async def disconnect(self) -> None:
        self.disconnected = True


class _FakeLocalAudioTrack:
    """Stand-in for ``livekit.rtc.LocalAudioTrack``."""

    def __init__(self, name: str, source: Any) -> None:
        self.name = name
        self.source = source

    @classmethod
    def create_audio_track(cls, name: str, source: Any) -> "_FakeLocalAudioTrack":
        return cls(name, source)


class _FakeTrackPublishOptions:
    """Stand-in for ``livekit.rtc.TrackPublishOptions``."""

    def __init__(self, *, source: Any = None) -> None:
        self.source = source


class _FakeTrackSource:
    SOURCE_MICROPHONE = "microphone"


class _FakeRtc:
    """Stand-in for the entire ``livekit.rtc`` module."""

    Room = _FakeRoom
    AudioSource = _FakeAudioSource
    AudioFrame = _FakeAudioFrame
    LocalAudioTrack = _FakeLocalAudioTrack
    TrackPublishOptions = _FakeTrackPublishOptions
    TrackSource = _FakeTrackSource


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _patch_rtc():
    """Return a patch context for ``livekit.rtc`` (module-level)."""
    return patch(
        "parrot.integrations.liveavatar.room_audio_publisher._require_livekit_rtc",
        return_value=_FakeRtc,
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_start_connects_with_agent_token_and_publishes_track(
    fake_room_tokens: LiveKitRoomTokens,
) -> None:
    """RoomAudioPublisher.start joins with agent_token and publishes an audio track."""
    with _patch_rtc():
        publisher = await RoomAudioPublisher.start(fake_room_tokens)

    assert isinstance(publisher.room, _FakeRoom)
    assert publisher.room.connected_url == "wss://test.livekit.cloud"
    assert publisher.room.connected_token == "agent-tok"  # agent_token used, not client_token

    # An audio track must have been published
    assert len(publisher.room.local_participant.published_tracks) == 1
    track, opts = publisher.room.local_participant.published_tracks[0]
    assert isinstance(track, _FakeLocalAudioTrack)
    assert track.name == "agent-voice"
    assert opts.source == _FakeTrackSource.SOURCE_MICROPHONE

    await publisher.aclose()


@pytest.mark.asyncio
async def test_capture_pcm_forwards_frames_to_audio_source(
    fake_room_tokens: LiveKitRoomTokens,
) -> None:
    """capture_pcm wraps bytes in AudioFrame and calls source.capture_frame."""
    with _patch_rtc():
        publisher = await RoomAudioPublisher.start(fake_room_tokens)

    # 10 ms of 24 kHz mono 16-bit = 240 samples * 2 bytes = 480 bytes
    pcm = b"\x01\x00" * 240
    await publisher.capture_pcm(pcm)

    source: _FakeAudioSource = publisher.source
    assert len(source.captured_frames) == 1
    frame: _FakeAudioFrame = source.captured_frames[0]
    assert frame.data == pcm
    assert frame.sample_rate == 24_000
    assert frame.num_channels == 1
    assert frame.samples_per_channel == 240  # len(480) // (2 * 1)

    await publisher.aclose()


@pytest.mark.asyncio
async def test_capture_pcm_empty_bytes_is_noop(
    fake_room_tokens: LiveKitRoomTokens,
) -> None:
    """capture_pcm with empty bytes does not call capture_frame."""
    with _patch_rtc():
        publisher = await RoomAudioPublisher.start(fake_room_tokens)

    await publisher.capture_pcm(b"")
    assert publisher.source.captured_frames == []

    await publisher.aclose()


@pytest.mark.asyncio
async def test_aclose_disconnects_room(
    fake_room_tokens: LiveKitRoomTokens,
) -> None:
    """aclose disconnects the room."""
    with _patch_rtc():
        publisher = await RoomAudioPublisher.start(fake_room_tokens)

    assert not publisher.room.disconnected
    await publisher.aclose()
    assert publisher.room.disconnected


@pytest.mark.asyncio
async def test_aclose_is_idempotent(
    fake_room_tokens: LiveKitRoomTokens,
) -> None:
    """Calling aclose twice never raises and disconnects only once."""
    with _patch_rtc():
        publisher = await RoomAudioPublisher.start(fake_room_tokens)

    await publisher.aclose()
    # Wrap in a fake that raises on second disconnect call to confirm idempotency
    original_room = publisher.room

    async def _raise_on_second() -> None:
        raise RuntimeError("should not be called again")

    original_room.disconnect = _raise_on_second  # type: ignore[method-assign]
    # Second aclose must be a no-op (publisher._closed is True)
    await publisher.aclose()  # should not raise


@pytest.mark.asyncio
async def test_capture_pcm_after_close_is_noop(
    fake_room_tokens: LiveKitRoomTokens,
) -> None:
    """capture_pcm after aclose is silently ignored."""
    with _patch_rtc():
        publisher = await RoomAudioPublisher.start(fake_room_tokens)

    await publisher.aclose()
    # Should not raise even though the publisher is closed
    await publisher.capture_pcm(b"\x01\x00" * 100)
    # No frames were pushed (closed flag short-circuits)
    assert publisher.source.captured_frames == []


@pytest.mark.asyncio
async def test_flush_clears_flushing_flag(
    fake_room_tokens: LiveKitRoomTokens,
) -> None:
    """flush sets and then clears _flushing so subsequent captures proceed."""
    with _patch_rtc():
        publisher = await RoomAudioPublisher.start(fake_room_tokens)

    assert not publisher._flushing
    await publisher.flush()
    # After flush completes the flag is cleared (ready for next turn)
    assert not publisher._flushing

    await publisher.aclose()


@pytest.mark.asyncio
async def test_aclose_on_room_disconnect_failure_does_not_raise(
    fake_room_tokens: LiveKitRoomTokens,
) -> None:
    """aclose swallows room.disconnect() exceptions (idempotent teardown)."""
    with _patch_rtc():
        publisher = await RoomAudioPublisher.start(fake_room_tokens)

    async def _failing_disconnect() -> None:
        raise RuntimeError("network gone")

    publisher.room.disconnect = _failing_disconnect  # type: ignore[method-assign]
    # Must not propagate
    await publisher.aclose()
    assert publisher._closed
