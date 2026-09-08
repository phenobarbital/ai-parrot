"""Unit tests for RoomAudioPublisher (FEAT-256 TASK-1627).

The livekit realtime SDK is mocked — no real network connections are made.
"""

from __future__ import annotations

import asyncio
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
    """Stand-in for ``livekit.rtc.AudioSource``.

    FEAT-537 (TASK-2956) adds ``queue_size_ms`` plus ``clear_queue`` /
    ``wait_for_playout`` / ``aclose`` counters, mirroring the real
    ``livekit.rtc.AudioSource`` on livekit 1.1.14.
    """

    def __init__(self, sample_rate: int, num_channels: int, queue_size_ms: int = 1000) -> None:
        self.sample_rate = sample_rate
        self.num_channels = num_channels
        self.queue_size_ms = queue_size_ms
        self.captured_frames: List[Any] = []
        self.clear_queue_calls = 0
        self.aclose_calls = 0
        self.capture_error: Exception | None = None
        #: When set, ``wait_for_playout`` blocks until it is resolved.
        self.playout_gate: asyncio.Event | None = None

    async def capture_frame(self, frame: Any) -> None:
        if self.capture_error is not None:
            raise self.capture_error
        self.captured_frames.append(frame)

    def clear_queue(self) -> None:
        self.clear_queue_calls += 1

    async def wait_for_playout(self) -> None:
        if self.playout_gate is not None:
            await self.playout_gate.wait()

    async def aclose(self) -> None:
        self.aclose_calls += 1


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


class _FakePublication:
    """Stand-in for ``livekit.rtc.LocalTrackPublication``."""

    def __init__(self, sid: str = "TR_fake") -> None:
        self.sid = sid


class _FakeLocalParticipant:
    """Stand-in for ``livekit.rtc.Room.local_participant``."""

    def __init__(self) -> None:
        self.published_tracks: List[Any] = []
        self.unpublished: List[str] = []

    async def publish_track(self, track: Any, options: Any) -> "_FakePublication":
        self.published_tracks.append((track, options))
        return _FakePublication()

    async def unpublish_track(self, track_sid: str) -> None:
        self.unpublished.append(track_sid)


class _FakeRoom:
    """Stand-in for ``livekit.rtc.Room``."""

    def __init__(self) -> None:
        self.connected_url: str = ""
        self.connected_token: str = ""
        self.local_participant = _FakeLocalParticipant()
        self.disconnected = False
        self.handlers: dict[str, Any] = {}

    async def connect(self, url: str, token: str) -> None:
        self.connected_url = url
        self.connected_token = token

    async def disconnect(self) -> None:
        self.disconnected = True

    def on(self, event: str, handler: Any) -> None:
        """Record an event subscription (mirrors ``rtc.Room.on``)."""
        self.handlers[event] = handler


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


# ---------------------------------------------------------------------------
# FEAT-537 (TASK-2956): explicit identity, real flush, failure propagation
# ---------------------------------------------------------------------------

# A JWT-shaped token whose payload decodes to {"sub": "direct-abcd1234"};
# signature is meaningless (the publisher never verifies it).
_DIRECT_TOKEN = "eyJhbGciOiJIUzI1NiJ9." "eyJzdWIiOiAiZGlyZWN0LWFiY2QxMjM0In0." "not-a-real-signature"


async def _start_publisher(**kwargs: Any) -> RoomAudioPublisher:
    """Start a publisher against the fake SDK with sane broadcast defaults."""
    defaults: dict[str, Any] = {
        "livekit_url": "wss://test.livekit.cloud",
        "token": _DIRECT_TOKEN,
        "track_name": "direct-voice",
    }
    defaults.update(kwargs)
    with _patch_rtc():
        return await RoomAudioPublisher.start(**defaults)


# ── Calling conventions ────────────────────────────────────────────────────


async def test_start_with_explicit_token_and_track_name() -> None:
    """The broadcast direct publisher joins under its own identity."""
    publisher = await _start_publisher()
    assert publisher.room.connected_url == "wss://test.livekit.cloud"
    assert publisher.room.connected_token == _DIRECT_TOKEN
    track, _options = publisher.room.local_participant.published_tracks[0]
    assert track.name == "direct-voice"
    # Identity is read from the token's `sub`, never from the avatar constant.
    assert publisher.identity == "direct-abcd1234"
    assert publisher.identity != "avatar-agent"
    assert publisher.track_sid == "TR_fake"


async def test_legacy_start_still_uses_agent_token_and_track(
    fake_room_tokens: LiveKitRoomTokens,
) -> None:
    """FEAT-256 callers are unaffected."""
    with _patch_rtc():
        publisher = await RoomAudioPublisher.start(fake_room_tokens)
    assert publisher.room.connected_token == "agent-tok"
    track, _options = publisher.room.local_participant.published_tracks[0]
    assert track.name == "agent-voice"


async def test_start_requires_exactly_one_calling_convention(
    fake_room_tokens: LiveKitRoomTokens,
) -> None:
    with _patch_rtc():
        with pytest.raises(ValueError, match="exactly one"):
            await RoomAudioPublisher.start()
        with pytest.raises(ValueError, match="exactly one"):
            await RoomAudioPublisher.start(fake_room_tokens, livekit_url="wss://x", token="t")


async def test_queue_size_is_passed_to_the_audio_source() -> None:
    publisher = await _start_publisher(queue_size_ms=250)
    assert publisher.source.queue_size_ms == 250


async def test_identity_is_none_for_an_undecodable_token() -> None:
    publisher = await _start_publisher(token="not-a-jwt")
    assert publisher.identity is None


# ── Native queue purge ─────────────────────────────────────────────────────


async def test_flush_clears_native_queue() -> None:
    """The whole point of TASK-2956: flush is a real purge, not a flag."""
    publisher = await _start_publisher()
    await publisher.flush()
    assert publisher.source.clear_queue_calls == 1
    await publisher.flush()
    assert publisher.source.clear_queue_calls == 2


async def test_flush_after_close_is_a_noop() -> None:
    publisher = await _start_publisher()
    await publisher.aclose()
    before = publisher.source.clear_queue_calls
    await publisher.flush()
    assert publisher.source.clear_queue_calls == before


async def test_flush_survives_a_failing_clear_queue() -> None:
    """An interrupt must never raise, even if the SDK misbehaves."""
    publisher = await _start_publisher()

    def _boom() -> None:
        raise RuntimeError("sdk exploded")

    publisher.source.clear_queue = _boom  # type: ignore[method-assign]
    await publisher.flush()  # must not raise


# ── Playout ────────────────────────────────────────────────────────────────


async def test_wait_for_playout_timeout_returns_false() -> None:
    publisher = await _start_publisher()
    publisher.source.playout_gate = asyncio.Event()  # never set
    assert await publisher.wait_for_playout(timeout_s=0.01) is False


async def test_wait_for_playout_returns_true_when_drained() -> None:
    publisher = await _start_publisher()
    assert await publisher.wait_for_playout(timeout_s=1.0) is True
    assert await publisher.wait_for_playout() is True


# ── Failure propagation ────────────────────────────────────────────────────


async def test_capture_failure_invokes_on_failure_once() -> None:
    reasons: List[str] = []
    publisher = await _start_publisher(on_failure=reasons.append)
    publisher.source.capture_error = RuntimeError("track gone")

    await publisher.capture_pcm(b"\x00\x00" * 480)
    assert reasons == ["capture_failed"]
    assert publisher.failed is True

    # A failed sink stops accepting audio and does not re-notify.
    await publisher.capture_pcm(b"\x00\x00" * 480)
    assert reasons == ["capture_failed"]
    assert publisher.source.captured_frames == []


async def test_capture_failure_without_observer_still_latches() -> None:
    publisher = await _start_publisher()
    publisher.source.capture_error = RuntimeError("track gone")
    await publisher.capture_pcm(b"\x00\x00" * 480)
    assert publisher.failed is True


async def test_room_disconnect_reports_a_failure() -> None:
    reasons: List[str] = []
    publisher = await _start_publisher(on_failure=reasons.append)
    handler = publisher.room.handlers.get("disconnected")
    assert handler is not None, "publisher must subscribe to room disconnect"
    handler()
    await asyncio.sleep(0)
    assert reasons == ["room_disconnected"]
    assert publisher.failed is True


async def test_no_disconnect_subscription_without_an_observer() -> None:
    publisher = await _start_publisher()
    assert "disconnected" not in publisher.room.handlers


async def test_an_exploding_failure_callback_is_contained() -> None:
    def _boom(_reason: str) -> None:
        raise ValueError("observer bug")

    publisher = await _start_publisher(on_failure=_boom)
    publisher.source.capture_error = RuntimeError("track gone")
    await publisher.capture_pcm(b"\x00\x00" * 480)  # must not raise
    assert publisher.failed is True


# ── Teardown ───────────────────────────────────────────────────────────────


async def test_aclose_clears_queue_unpublishes_then_disconnects() -> None:
    publisher = await _start_publisher()
    await publisher.aclose()
    assert publisher.source.clear_queue_calls == 1
    assert publisher.room.local_participant.unpublished == ["TR_fake"]
    assert publisher.source.aclose_calls == 1
    assert publisher.room.disconnected is True


async def test_aclose_is_idempotent_and_never_raises() -> None:
    publisher = await _start_publisher()
    await publisher.aclose()
    await publisher.aclose()
    assert publisher.source.clear_queue_calls == 1
    assert publisher.source.aclose_calls == 1


async def test_aclose_continues_past_a_failing_step() -> None:
    publisher = await _start_publisher()

    async def _boom(_sid: str) -> None:
        raise RuntimeError("unpublish failed")

    publisher.room.local_participant.unpublish_track = _boom  # type: ignore[method-assign]
    await publisher.aclose()
    # The later steps still ran.
    assert publisher.source.aclose_calls == 1
    assert publisher.room.disconnected is True
