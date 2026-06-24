"""Headless LiveKit room audio publisher (FEAT-256 Module 1).

Joins the ai-parrot-owned LiveKit room as a headless participant (using the
publish-capable ``agent_token`` from :func:`~room_manager.LiveKitRoomManager.mint_room_tokens`)
and publishes a direct audio track fed with Supertonic PCM frames.

This is the core of the avatar-OFF path: when the avatar is disabled (or
LiveAvatar has no credits), ai-parrot itself pushes audio directly into the
room so the browser still hears the bot.

Audio format: 24 kHz mono 16-bit PCM (matches Supertonic output — no
resampling).

Design constraints:
- Keep-alive: the publisher is long-lived; do NOT use it as a one-shot
  context manager per turn (mirrors the keep-alive caveat in
  ``handlers/avatar.py``).
- Idempotent ``aclose``: teardown never raises; safe to call multiple times.
- No double audio: only ONE sink (publisher OR LiveAvatar WS) is ever active
  per session.

Usage::

    publisher = await RoomAudioPublisher.start(tokens)
    # ... per turn ...
    await publisher.capture_pcm(pcm_bytes)
    # ... on interrupt ...
    await publisher.flush()
    # ... on session end ...
    await publisher.aclose()
"""
from __future__ import annotations

import asyncio
import logging

from parrot.integrations.liveavatar.models import LiveKitRoomTokens

# PCM constants — mirror avatar_ws.py / supertonic (no resampling)
_SAMPLE_RATE: int = 24_000   # Hz
_NUM_CHANNELS: int = 1        # mono
_BYTES_PER_SAMPLE: int = 2    # 16-bit

_logger = logging.getLogger(__name__)


def _require_livekit_rtc() -> object:
    """Lazily import ``livekit.rtc`` and raise a clear error when missing.

    Returns:
        The ``livekit.rtc`` module.

    Raises:
        ImportError: If ``livekit`` realtime SDK is not installed.
    """
    try:
        from livekit import rtc  # type: ignore[import-untyped]

        return rtc
    except ImportError as exc:
        raise ImportError(
            "livekit realtime SDK is not installed.  "
            "Install the liveavatar extra: "
            "pip install ai-parrot-integrations[liveavatar]"
        ) from exc


class RoomAudioPublisher:
    """Headless LiveKit participant that publishes a Supertonic audio track.

    Created via :meth:`start` (class-method factory) which performs the async
    room connection and track publication.  After creation the publisher is
    ready to receive PCM via :meth:`capture_pcm`.

    Attributes:
        room: The connected ``livekit.rtc.Room`` instance.
        source: The ``livekit.rtc.AudioSource`` that frames are pushed into.
        track: The published ``livekit.rtc.LocalAudioTrack``.
    """

    def __init__(
        self,
        room: object,
        source: object,
        track: object,
        audio_frame_cls: type,
        *,
        sample_rate: int = _SAMPLE_RATE,
        num_channels: int = _NUM_CHANNELS,
    ) -> None:
        """Initialise the publisher (internal — use :meth:`start`).

        Args:
            room: Connected ``livekit.rtc.Room``.
            source: ``livekit.rtc.AudioSource`` for pushing frames.
            track: Published ``livekit.rtc.LocalAudioTrack``.
            audio_frame_cls: ``livekit.rtc.AudioFrame`` class (cached to avoid
                repeated lazy imports in the hot-path :meth:`capture_pcm`).
            sample_rate: PCM sample rate in Hz (default 24 000).
            num_channels: Number of PCM channels (default 1 — mono).
        """
        self.room = room
        self.source = source
        self.track = track
        self._audio_frame_cls = audio_frame_cls
        self._sample_rate = sample_rate
        self._num_channels = num_channels
        self._closed = False
        self._flushing = False
        self.logger = logging.getLogger(__name__)

    # ── Factory ────────────────────────────────────────────────────────────

    @classmethod
    async def start(
        cls,
        tokens: LiveKitRoomTokens,
        *,
        sample_rate: int = _SAMPLE_RATE,
        num_channels: int = _NUM_CHANNELS,
    ) -> "RoomAudioPublisher":
        """Connect to the LiveKit room and publish an audio track.

        Joins the room using the publish-capable ``agent_token``, creates an
        :class:`livekit.rtc.AudioSource` + :class:`livekit.rtc.LocalAudioTrack`,
        and calls ``local_participant.publish_track``.

        Args:
            tokens: Room credentials from
                :func:`~room_manager.LiveKitRoomManager.mint_room_tokens`.
                The ``agent_token`` (publish grants) is used to connect.
            sample_rate: PCM sample rate in Hz (default 24 000 — Supertonic).
            num_channels: Number of PCM channels (default 1 — mono).

        Returns:
            A ready :class:`RoomAudioPublisher` instance.

        Raises:
            ImportError: If ``livekit`` realtime SDK is not installed.
            Exception: If the room connection or track publication fails.
        """
        rtc = _require_livekit_rtc()

        room = rtc.Room()
        await room.connect(tokens.livekit_url, tokens.agent_token)

        source = rtc.AudioSource(sample_rate, num_channels)
        track = rtc.LocalAudioTrack.create_audio_track("agent-voice", source)

        publish_opts = rtc.TrackPublishOptions(
            source=rtc.TrackSource.SOURCE_MICROPHONE,
        )
        await room.local_participant.publish_track(track, publish_opts)

        _logger.info(
            "RoomAudioPublisher: connected to room %s as headless audio participant",
            tokens.room,
        )
        return cls(
            room,
            source,
            track,
            rtc.AudioFrame,
            sample_rate=sample_rate,
            num_channels=num_channels,
        )

    # ── Public API ─────────────────────────────────────────────────────────

    async def capture_pcm(self, pcm: bytes) -> None:
        """Push a block of raw PCM audio into the room audio track.

        Wraps the bytes in a :class:`livekit.rtc.AudioFrame` and calls
        ``AudioSource.capture_frame``.  A no-op when closed or during a flush.

        Args:
            pcm: Raw 16-bit PCM bytes at the sample rate / channel count the
                publisher was created with (default: 24 kHz mono 16-bit).
        """
        if self._closed or self._flushing:
            return
        if not pcm:
            return

        # samples_per_channel = total_bytes / (bytes_per_sample * num_channels)
        samples_per_channel = len(pcm) // (_BYTES_PER_SAMPLE * self._num_channels)
        if samples_per_channel <= 0:
            return

        # Use the cached AudioFrame class (set at start() time) to avoid a
        # repeated lazy import in this hot-path method.
        frame = self._audio_frame_cls(
            data=pcm,
            sample_rate=self._sample_rate,
            num_channels=self._num_channels,
            samples_per_channel=samples_per_channel,
        )
        try:
            await self.source.capture_frame(frame)
        except Exception:  # noqa: BLE001 — graceful degradation
            self.logger.warning(
                "RoomAudioPublisher: capture_frame failed", exc_info=True
            )

    async def flush(self) -> None:
        """Signal a barge-in / interrupt: drop in-flight audio.

        Sets an internal flag so any concurrent :meth:`capture_pcm` calls are
        dropped until the flag is cleared.  The flag is cleared immediately
        after setting so a brief pause is all that is needed.  Idempotent.
        """
        if self._closed:
            return
        self._flushing = True
        # Yield to the event loop once so any in-progress capture_frame can
        # complete, then clear the flag.
        await asyncio.sleep(0)
        self._flushing = False
        self.logger.debug("RoomAudioPublisher: flushed (barge-in)")

    async def aclose(self) -> None:
        """Disconnect from the room and release resources (idempotent).

        Safe to call multiple times; subsequent calls are no-ops.  Never
        raises — teardown errors are logged and suppressed.
        """
        if self._closed:
            return
        self._closed = True
        try:
            await self.room.disconnect()
        except Exception:  # noqa: BLE001 — teardown must never raise
            self.logger.warning(
                "RoomAudioPublisher: room.disconnect() failed", exc_info=True
            )
        self.logger.info("RoomAudioPublisher: disconnected from room")
