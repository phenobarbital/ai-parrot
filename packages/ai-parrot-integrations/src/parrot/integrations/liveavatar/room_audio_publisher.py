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
import base64
import binascii
import inspect
import json
import logging
from typing import Any, Awaitable, Callable, Optional, Union

from parrot.integrations.liveavatar.models import LiveKitRoomTokens

#: Failure callback: receives a short, non-sensitive reason code.
FailureCallback = Callable[[str], Union[Awaitable[None], None]]
PresenceCallback = Callable[[str, bool], Union[Awaitable[None], None]]

#: Reason codes this publisher can report.  Deliberately a closed set — they
#: are surfaced to the broadcast session as fallback/abort triggers.
FAILURE_CAPTURE: str = "capture_failed"
FAILURE_DISCONNECTED: str = "room_disconnected"

# PCM constants — mirror avatar_ws.py / supertonic (no resampling)
_SAMPLE_RATE: int = 24_000  # Hz
_NUM_CHANNELS: int = 1  # mono
_BYTES_PER_SAMPLE: int = 2  # 16-bit

_logger = logging.getLogger(__name__)


def _identity_from_token(token: str) -> Optional[str]:
    """Read the ``sub`` claim out of a JWT without verifying it.

    Used only to label logs and expose :attr:`RoomAudioPublisher.identity`.  No
    security decision depends on this value, and the token itself is never
    logged or stored.

    Args:
        token: A JWT.

    Returns:
        The ``sub`` claim, or ``None`` when the token cannot be parsed.
    """
    try:
        payload_b64 = token.split(".")[1]
        padding = "=" * (-len(payload_b64) % 4)
        payload = json.loads(base64.urlsafe_b64decode(payload_b64 + padding))
    except (IndexError, ValueError, binascii.Error, UnicodeDecodeError):
        return None
    subject = payload.get("sub")
    return subject if isinstance(subject, str) else None


async def _invoke(callback: Optional[FailureCallback], reason: str) -> None:
    """Call a possibly-async failure callback, never letting it raise.

    Args:
        callback: The callback, or ``None``.
        reason: Reason code to report.
    """
    if callback is None:
        return
    try:
        result = callback(reason)
        if inspect.isawaitable(result):
            await result
    except Exception:  # noqa: BLE001 — an observer must not break teardown
        _logger.exception("RoomAudioPublisher: on_failure callback raised")


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
        identity: Optional[str] = None,
        track_sid: Optional[str] = None,
        on_failure: Optional[FailureCallback] = None,
        on_presence: Optional["PresenceCallback"] = None,
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
            identity: This publisher's LiveKit participant identity.
            track_sid: SID of the published track, when the SDK returned one.
            on_failure: Called once with a reason code when publication fails.
            on_presence: Called with ``(identity, present)`` on every remote
                participant join/leave.  This connection is the only real
                LiveKit room handle the producer holds, so it is also the only
                place server-verified presence can be observed — which is what
                a lease's ``confirmed`` flag is required to mean.
        """
        self.room = room
        self.source = source
        self.track = track
        self.identity = identity
        self.track_sid = track_sid
        #: Latched on the first publication failure.  Once set, ``capture_pcm``
        #: is a no-op: a sink that has already failed must not keep half-
        #: succeeding, and the broadcast session has been told to cut over.
        self.failed = False
        self._audio_frame_cls = audio_frame_cls
        self._sample_rate = sample_rate
        self._num_channels = num_channels
        self._on_failure = on_failure
        self._on_presence = on_presence
        self._failure_notified = False
        self._closed = False
        self._flushing = False
        self.logger = logging.getLogger(__name__)

    # ── Factory ────────────────────────────────────────────────────────────

    @classmethod
    async def start(
        cls,
        tokens: Optional[LiveKitRoomTokens] = None,
        *,
        sample_rate: int = _SAMPLE_RATE,
        num_channels: int = _NUM_CHANNELS,
        livekit_url: Optional[str] = None,
        token: Optional[str] = None,
        track_name: str = "agent-voice",
        queue_size_ms: int = 1000,
        on_failure: Optional[FailureCallback] = None,
        on_presence: Optional[PresenceCallback] = None,
    ) -> "RoomAudioPublisher":
        """Connect to the LiveKit room and publish an audio track.

        Two calling conventions:

        * **Legacy** — ``start(tokens)`` joins with ``tokens.agent_token`` and
          publishes ``agent-voice``, exactly as FEAT-256 callers expect.
        * **Broadcast** — ``start(livekit_url=…, token=…,
          track_name="direct-voice")`` joins with a *distinct* direct-publisher
          token (TASK-2954). Sharing the avatar's fixed ``avatar-agent``
          identity would make the two publishers evict each other in the room
          (spec §6).

        Args:
            tokens: Legacy room credentials.  Mutually exclusive with
                ``livekit_url``/``token``.
            sample_rate: PCM sample rate in Hz (default 24 000).
            num_channels: Number of PCM channels (default 1 — mono).
            livekit_url: Room WebSocket URL, for the broadcast convention.
            token: Publish-capable JWT for this publisher's own identity.
            track_name: Published track name.
            queue_size_ms: Native audio-source queue depth.
            on_failure: Called once with a reason code when publication fails
                or the room disconnects.
            on_presence: Called with ``(identity, present)`` as remote
                participants join and leave the room.

        Returns:
            A ready :class:`RoomAudioPublisher` instance.

        Raises:
            ValueError: If neither or both calling conventions are used.
            ImportError: If the ``livekit`` realtime SDK is not installed.
            Exception: If the room connection or track publication fails.
        """
        explicit = livekit_url is not None and token is not None
        if (tokens is None) == (not explicit):
            raise ValueError(
                "RoomAudioPublisher.start requires exactly one of `tokens` or " "(`livekit_url` + `token`)"
            )
        if tokens is not None:
            url, jwt, room_name = tokens.livekit_url, tokens.agent_token, tokens.room
        else:
            url, jwt, room_name = str(livekit_url), str(token), "<explicit>"

        rtc = _require_livekit_rtc()

        room = rtc.Room()
        await room.connect(url, jwt)

        source = rtc.AudioSource(sample_rate, num_channels, queue_size_ms)
        track = rtc.LocalAudioTrack.create_audio_track(track_name, source)

        publish_opts = rtc.TrackPublishOptions(
            source=rtc.TrackSource.SOURCE_MICROPHONE,
        )
        publication = await room.local_participant.publish_track(track, publish_opts)

        identity = _identity_from_token(jwt)
        publisher = cls(
            room,
            source,
            track,
            rtc.AudioFrame,
            sample_rate=sample_rate,
            num_channels=num_channels,
            identity=identity,
            track_sid=getattr(publication, "sid", None),
            on_failure=on_failure,
            on_presence=on_presence,
        )
        publisher._watch_disconnect()
        publisher._watch_presence()
        _logger.info(
            "RoomAudioPublisher: connected to room %s as identity=%s track=%s",
            room_name,
            identity or "<unknown>",
            track_name,
        )
        return publisher

    def _watch_disconnect(self) -> None:
        """Route a LiveKit ``disconnected`` event to :attr:`_on_failure`.

        Registered only when an observer exists, and guarded because the fake
        rooms used in unit tests need not implement ``on``.
        """
        if self._on_failure is None:
            return
        register = getattr(self.room, "on", None)
        if register is None:
            return

        def _on_disconnected(*_args: Any) -> None:
            asyncio.ensure_future(self._report_failure(FAILURE_DISCONNECTED))

        try:
            register("disconnected", _on_disconnected)
        except Exception:  # noqa: BLE001 — event wiring is best-effort
            self.logger.debug(
                "RoomAudioPublisher: could not subscribe to room disconnect",
                exc_info=True,
            )

    def _watch_presence(self) -> None:
        """Route LiveKit participant join/leave events to :attr:`_on_presence`.

        Guarded exactly like :meth:`_watch_disconnect`: the fake rooms used by
        unit tests need not implement ``on``, and a room SDK that does not
        emit these events must not break publication.
        """
        if self._on_presence is None:
            return
        register = getattr(self.room, "on", None)
        if register is None:
            return

        def _emit(identity: Optional[str], present: bool) -> None:
            if not identity:
                return
            asyncio.ensure_future(self._report_presence(identity, present))

        def _on_connected(participant: Any = None, *_args: Any) -> None:
            _emit(getattr(participant, "identity", None), True)

        def _on_disconnected(participant: Any = None, *_args: Any) -> None:
            _emit(getattr(participant, "identity", None), False)

        try:
            register("participant_connected", _on_connected)
            register("participant_disconnected", _on_disconnected)
        except Exception:  # noqa: BLE001 — event wiring is best-effort
            self.logger.debug(
                "RoomAudioPublisher: could not subscribe to participant events",
                exc_info=True,
            )

    async def _report_presence(self, identity: str, present: bool) -> None:
        """Deliver one presence transition, never letting it break the room.

        Args:
            identity: The remote participant's LiveKit identity.
            present: ``True`` on join, ``False`` on leave.
        """
        if self._on_presence is None:
            return
        try:
            await self._on_presence(identity, present)
        except Exception:  # noqa: BLE001 — an observer must not kill the room
            self.logger.exception(
                "RoomAudioPublisher: presence observer raised for %s", identity
            )

    async def _report_failure(self, reason: str) -> None:
        """Latch the failed state and notify the observer exactly once.

        Args:
            reason: One of :data:`FAILURE_CAPTURE` / :data:`FAILURE_DISCONNECTED`.
        """
        self.failed = True
        if self._failure_notified:
            return
        self._failure_notified = True
        self.logger.warning("RoomAudioPublisher: failed (%s)", reason)
        await _invoke(self._on_failure, reason)

    # ── Public API ─────────────────────────────────────────────────────────

    async def capture_pcm(self, pcm: bytes) -> None:
        """Push a block of raw PCM audio into the room audio track.

        Wraps the bytes in a :class:`livekit.rtc.AudioFrame` and calls
        ``AudioSource.capture_frame``.  A no-op when closed or during a flush.

        Args:
            pcm: Raw 16-bit PCM bytes at the sample rate / channel count the
                publisher was created with (default: 24 kHz mono 16-bit).
        """
        if self._closed or self._flushing or self.failed:
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
        except Exception:  # noqa: BLE001 — reported, not swallowed
            self.logger.warning("RoomAudioPublisher: capture_frame failed", exc_info=True)
            # Awaited outside the try so an observer's own failure cannot be
            # mistaken for another capture failure.
            await self._report_failure(FAILURE_CAPTURE)

    async def flush(self) -> None:
        """Barge-in: drop in-flight audio **and purge the native queue**.

        The pre-FEAT-537 implementation only toggled a Python-side flag, which
        left everything already handed to ``AudioSource`` to play out — so a
        "flushed" interrupt still spoke the previous turn (spec §6: "``flush()``
        is not a native queue purge in the verified baseline").  This now calls
        ``AudioSource.clear_queue()`` as well.

        Idempotent and never raises; a no-op once closed.
        """
        if self._closed:
            return
        self._flushing = True
        # Yield to the event loop once so any in-progress capture_frame can
        # complete, then clear the flag.
        await asyncio.sleep(0)
        self._clear_native_queue()
        self._flushing = False
        self.logger.debug("RoomAudioPublisher: flushed (barge-in, native queue cleared)")

    def _clear_native_queue(self) -> None:
        """Purge the SDK's queued audio.  Never raises."""
        clear = getattr(self.source, "clear_queue", None)
        if clear is None:
            self.logger.warning(
                "RoomAudioPublisher: AudioSource has no clear_queue — queued " "audio may still play out"
            )
            return
        try:
            clear()
        except Exception:  # noqa: BLE001 — interrupt must never raise
            self.logger.warning("RoomAudioPublisher: clear_queue failed", exc_info=True)

    async def wait_for_playout(self, timeout_s: Optional[float] = None) -> bool:
        """Await the native queue draining at *normal* turn completion.

        Call this only when a turn finished on its own.  Spec §2: "never wait
        for stale audio during cancellation" — on an interrupt or handoff use
        :meth:`flush`, which discards that audio instead of waiting for it.

        Args:
            timeout_s: Optional deadline in seconds.

        Returns:
            ``True`` when playout completed, ``False`` on timeout or when the
            SDK does not expose ``wait_for_playout``.
        """
        if self._closed:
            return True
        waiter = getattr(self.source, "wait_for_playout", None)
        if waiter is None:
            return False
        try:
            if timeout_s is None:
                await waiter()
            else:
                await asyncio.wait_for(waiter(), timeout=timeout_s)
            return True
        except asyncio.TimeoutError:
            self.logger.warning("RoomAudioPublisher: playout did not drain within %.3fs", timeout_s)
            return False

    async def aclose(self) -> None:
        """Disconnect from the room and release resources (idempotent).

        Safe to call multiple times; subsequent calls are no-ops.  Never
        raises — teardown errors are logged and suppressed.
        """
        if self._closed:
            return
        # Purge before flipping _closed so _clear_native_queue still runs; any
        # audio still queued must not play out after we claim to be gone.
        self._clear_native_queue()
        self._closed = True

        if self.track_sid is not None:
            await self._guarded(
                "unpublish_track",
                getattr(self.room.local_participant, "unpublish_track", None),
                self.track_sid,
            )
        await self._guarded("source.aclose", getattr(self.source, "aclose", None))
        await self._guarded("room.disconnect", getattr(self.room, "disconnect", None))
        self.logger.info("RoomAudioPublisher: disconnected from room")

    async def _guarded(self, label: str, call: Optional[Callable[..., Any]], *args: Any) -> None:
        """Run one teardown step, tolerating absence and failure.

        Args:
            label: Step name for logging.
            call: The callable, or ``None`` when the SDK lacks it.
            *args: Arguments to pass.
        """
        if call is None:
            return
        try:
            result = call(*args)
            if inspect.isawaitable(result):
                await result
        except Exception:  # noqa: BLE001 — teardown must never raise
            self.logger.warning("RoomAudioPublisher: %s failed during teardown", label, exc_info=True)
