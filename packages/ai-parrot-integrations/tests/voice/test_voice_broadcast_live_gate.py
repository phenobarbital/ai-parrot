"""FEAT-537 TASK-2950 — live vendor contract probe (Nova PCM → LITE → LiveKit).

Spec: ``sdd/specs/voicebot-multiroom-heygen-avatar.spec.md`` §2 "Vendor contract
and implementation gate", §3 Module 1; gates AC10/AC15.

This module is an **opt-in, env-gated live probe**.  It is skipped unless BOTH
of the following hold:

* ``PARROT_LIVE_BROADCAST_GATE=1``
* every credential in :data:`_REQUIRED_ENV` is present.

Nothing in this module reads a credential at import time — the module-level
``os.environ.get`` calls only decide whether to skip.  All real reads happen
inside fixtures.

What the probe demonstrates (and *only* what it demonstrates):

1. A real LiveAvatar LITE session accepts our ``livekit_config`` payload with
   the OpenAPI-verified keys ``livekit_url`` / ``livekit_room`` /
   ``livekit_client_token`` and publishes into **our** LiveKit room.
2. Deterministic 24 kHz mono PCM16 sent through ``agent.speak`` reaches
   **two distinct** headless LiveKit subscribers as non-zero audio, with a
   companion video track.
3. ``agent.interrupt`` stops scheduled avatar speech, and the session survives
   the interruption well enough to speak a second utterance (the
   speaker-handoff analogue).
4. ``livekit.rtc.AudioSource.clear_queue()`` on the *direct* publisher actually
   purges queued audio.

Everything else the probe collects (track identities/kinds, codec and
sample-rate observations, first-frame latency, server event-type manifest,
SDK versions) is **measured and reported**, not asserted — vendor latency is
not a contract we control.

Evidence is written, sanitized, to ``artifacts/logs/feat-537-live-gate-*``.
No token, ``ws_url`` or API secret is ever printed, logged or persisted here.
"""

from __future__ import annotations

import asyncio
import json
import logging
import math
import os
import re
import struct
import sys
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pytest

# Load the project's configuration layer BEFORE reading os.environ below.
#
# The gate's enablement is decided at import time, but credentials live in
# `env/.env`, which only reaches os.environ when navconfig is imported. Nothing
# in this module's own import graph pulls navconfig in, so running
# `PARROT_LIVE_BROADCAST_GATE=1 pytest <this file>` on a machine that HAS
# credentials still skipped — and the skip text blames "credentials missing",
# which makes the wrong diagnosis look confirmed. Requiring the caller to
# hand-export the five variables was a workaround for this, not a fix.
try:  # pragma: no cover — configuration bootstrap, not logic under test
    import navconfig  # noqa: F401
except ImportError:  # navconfig absent: fall back to a bare os.environ read
    pass

# Every test in this module is a live-vendor probe.
pytestmark = pytest.mark.live_vendor

# ── Gate ───────────────────────────────────────────────────────────────────

_REQUIRED_ENV: Tuple[str, ...] = (
    "LIVEAVATAR_API_KEY",
    "LIVEAVATAR_AVATAR_ID",
    "LIVEKIT_URL",
    "LIVEKIT_API_KEY",
    "LIVEKIT_API_SECRET",
)

_GATE_ENABLED: bool = os.environ.get("PARROT_LIVE_BROADCAST_GATE") == "1" and all(
    os.environ.get(name) for name in _REQUIRED_ENV
)


def _skip_reason() -> str:
    """Say which precondition is actually unmet.

    A single "not enabled / credentials missing" string cannot distinguish the
    switch being off from a credential being absent, and reading as though it
    were the latter sent this feature's own acceptance report down the wrong
    path for days. Name the specific missing pieces instead.

    Returns:
        A precise, actionable skip reason.
    """
    missing = [name for name in _REQUIRED_ENV if not os.environ.get(name)]
    if os.environ.get("PARROT_LIVE_BROADCAST_GATE") != "1":
        return "live vendor gate is OFF — NOT VERIFIED. Set " "PARROT_LIVE_BROADCAST_GATE=1 to run it" + (
            f" (also missing: {', '.join(missing)})" if missing else " (all five credentials were found)"
        )
    return (
        "live vendor gate is ON but credentials are missing — NOT VERIFIED. "
        f"Absent from the environment: {', '.join(missing)}"
    )


_SKIP_REASON: str = _skip_reason()

# ── Probe constants ────────────────────────────────────────────────────────

_SAMPLE_RATE: int = 24_000  # Hz — LITE agent.speak contract
_NUM_CHANNELS: int = 1  # mono
_BYTES_PER_SAMPLE: int = 2  # PCM16
_TONE_HZ: float = 440.0
_TONE_AMPLITUDE: int = 12_000  # well below int16 clipping

#: Seconds of tone pushed per utterance (kept short — total vendor time must
#: stay far below ``max_session_duration``).
_UTTERANCE_SECONDS: float = 3.0

#: How long to observe subscriber media after the utterance is sent.
_OBSERVE_SECONDS: float = 8.0

#: Budget for "avatar audio stops after agent.interrupt" (spec §2).
_INTERRUPT_BUDGET_SECONDS: float = 1.0

#: Vendor session cap (spec §7 — must be ≤ 600 s / 10 min).
#:
#: Overridable because the ceiling is an *account* property, not a protocol
#: constant: a sandbox key rejects anything above 60 s outright
#: (``400 max_session_duration (600s) exceeds the maximum allowed (60s)``), so
#: a hard-coded 600 made the probe unrunnable on exactly the tier most people
#: have. Defaults to the sandbox-safe value; raise it via
#: ``PARROT_LIVE_MAX_SESSION_DURATION`` on a production key.
_MAX_SESSION_DURATION: int = int(os.environ.get("PARROT_LIVE_MAX_SESSION_DURATION", "60"))

#: A frame is considered audible when its peak sample exceeds this.
_SILENCE_PEAK_THRESHOLD: int = 300

_ARTIFACTS_DIR: Path = Path(__file__).resolve().parents[4] / "artifacts" / "logs"

_logger = logging.getLogger(__name__)

# Patterns whose *values* must never leave this process.
_SECRET_ENV_NAMES: Tuple[str, ...] = _REQUIRED_ENV + ("LIVEAVATAR_BASE_URL",)
_JWT_RE = re.compile(r"\beyJ[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+")
_WSS_RE = re.compile(r"wss?://[^\s\"']+")


# ── Sanitization ───────────────────────────────────────────────────────────


def _sanitize(value: Any) -> Any:
    """Recursively redact secrets from an evidence payload.

    Removes JWTs, ``ws(s)://`` URLs and any literal value taken from a
    credential environment variable.  Applied to *everything* written to
    ``artifacts/`` or ``docs/``.

    Args:
        value: Arbitrary JSON-serialisable structure.

    Returns:
        The same structure with secret-looking substrings replaced by
        ``"<redacted>"``.
    """
    if isinstance(value, dict):
        return {key: _sanitize(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_sanitize(item) for item in value]
    if not isinstance(value, str):
        return value

    text = value
    for name in _SECRET_ENV_NAMES:
        secret = os.environ.get(name)
        if secret and len(secret) >= 8 and secret in text:
            text = text.replace(secret, "<redacted>")
    text = _JWT_RE.sub("<redacted-jwt>", text)
    text = _WSS_RE.sub("<redacted-url>", text)
    return text


# ── PCM helpers ────────────────────────────────────────────────────────────


def _tone_pcm(seconds: float, *, start_sample: int = 0) -> bytes:
    """Generate a deterministic mono PCM16 sine tone at 24 kHz.

    Deterministic (phase derived from the absolute sample index) so successive
    calls concatenate without a discontinuity, which keeps correlation-based
    inspection of the recorded audio meaningful.

    Args:
        seconds: Duration of the generated tone.
        start_sample: Absolute sample index the block starts at.

    Returns:
        Raw little-endian int16 mono PCM bytes at 24 kHz.
    """
    total = int(seconds * _SAMPLE_RATE)
    step = 2.0 * math.pi * _TONE_HZ / _SAMPLE_RATE
    samples = [int(_TONE_AMPLITUDE * math.sin(step * (start_sample + index))) for index in range(total)]
    return struct.pack(f"<{total}h", *samples)


def _frame_peak(frame: Any) -> int:
    """Return the peak absolute int16 sample of a ``livekit.rtc.AudioFrame``.

    Args:
        frame: An ``rtc.AudioFrame`` (``.data`` is a buffer of int16 samples).

    Returns:
        Peak absolute amplitude, or ``0`` for an empty/unreadable frame.
    """
    raw = bytes(frame.data)
    count = len(raw) // _BYTES_PER_SAMPLE
    if count <= 0:
        return 0
    return max(abs(sample) for sample in struct.unpack(f"<{count}h", raw[: count * 2]))


# ── Evidence collection ────────────────────────────────────────────────────


@dataclass
class _Evidence:
    """Accumulates sanitized probe observations for the run report."""

    started_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    versions: Dict[str, str] = field(default_factory=dict)
    scenarios: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    events: List[str] = field(default_factory=list)

    def record(self, scenario: str, **payload: Any) -> None:
        """Merge sanitized observations into one scenario's record.

        Args:
            scenario: Scenario key (matches a row in the report table).
            **payload: Arbitrary JSON-serialisable observations.
        """
        bucket = self.scenarios.setdefault(scenario, {})
        bucket.update(_sanitize(payload))

    def to_dict(self) -> Dict[str, Any]:
        """Return the whole sanitized evidence payload."""
        return _sanitize(
            {
                "feature": "FEAT-537",
                "task": "TASK-2950",
                "started_at": self.started_at,
                "finished_at": datetime.now(timezone.utc).isoformat(),
                "versions": self.versions,
                "scenarios": self.scenarios,
                "server_event_types": sorted(set(self.events)),
            }
        )


def _collect_versions() -> Dict[str, str]:
    """Return installed versions of every dependency the gate depends on."""
    import importlib.metadata as metadata

    names = (
        "livekit",
        "livekit-api",
        "ai-parrot-integrations",
        "aiohttp",
        "aws_sdk_bedrock_runtime",
    )
    versions: Dict[str, str] = {}
    for name in names:
        try:
            versions[name] = metadata.version(name)
        except metadata.PackageNotFoundError:
            versions[name] = "not installed"
    versions["python"] = sys.version.split()[0]
    return versions


# ── Fixtures ───────────────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def evidence() -> Any:
    """Module-scoped evidence collector; writes the JSON manifest on teardown.

    Yields:
        The :class:`_Evidence` accumulator.
    """
    collector = _Evidence(versions=_collect_versions())
    yield collector
    _ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    target = _ARTIFACTS_DIR / f"feat-537-live-gate-{stamp}.json"
    target.write_text(json.dumps(collector.to_dict(), indent=2), encoding="utf-8")
    _logger.info("FEAT-537 live gate: evidence manifest written to %s", target)


@pytest.fixture
def avatar_config() -> Any:
    """Build a :class:`LiveAvatarConfig` from env with the 10-minute cap."""
    from parrot.integrations.liveavatar.models import LiveAvatarConfig

    return LiveAvatarConfig(
        api_key=os.environ["LIVEAVATAR_API_KEY"],
        avatar_id=os.environ["LIVEAVATAR_AVATAR_ID"],
        base_url=os.environ.get("LIVEAVATAR_BASE_URL", "https://api.liveavatar.com"),
        is_sandbox=os.environ.get("LIVEAVATAR_SANDBOX", "true").lower() != "false",
        max_session_duration=_MAX_SESSION_DURATION,
    )


@pytest.fixture
def room_tokens() -> Any:
    """Mint a fresh LiveKit room plus the server-side publisher token."""
    from parrot.integrations.liveavatar.room_manager import LiveKitRoomManager

    manager = LiveKitRoomManager()
    room = f"feat537-probe-{uuid.uuid4().hex[:12]}"
    return manager.mint_room_tokens(room, "feat537-probe-publisher")


# ── Subscriber harness ─────────────────────────────────────────────────────


def _kind_name(kind: Any) -> str:
    """Readable track-kind label for the evidence artifact.

    The raw enum serialises as a bare "1"/"2", which is what disguised the
    pump-selection bug in the first place.

    Args:
        kind: A ``livekit.rtc.TrackKind`` value.

    Returns:
        ``"audio"``, ``"video"``, or the raw value as a string.
    """
    from livekit import rtc

    if kind == rtc.TrackKind.KIND_AUDIO:
        return "audio"
    if kind == rtc.TrackKind.KIND_VIDEO:
        return "video"
    return str(kind)


class _Subscriber:
    """A headless ``livekit.rtc.Room`` that measures received audio and video.

    Attributes:
        identity: The LiveKit participant identity used to join.
        audio_frames: Number of audio frames received.
        audible_frames: Number of audio frames above the silence threshold.
        video_frames: Number of decoded video frames received.
        tracks: Track manifest (identity, kind, name, sid, source).
    """

    def __init__(self, identity: str) -> None:
        self.identity = identity
        self.audio_frames = 0
        self.audible_frames = 0
        self.video_frames = 0
        self.peak = 0
        self.first_audio_at: Optional[float] = None
        self.first_audible_at: Optional[float] = None
        self.last_audible_at: Optional[float] = None
        self.tracks: List[Dict[str, Any]] = []
        self._room: Any = None
        self._pumps: List[asyncio.Task[None]] = []
        self.logger = logging.getLogger(f"{__name__}.subscriber.{identity}")

    async def connect(self, url: str, token: str) -> None:
        """Join the room and start pumping every subscribed track.

        Args:
            url: LiveKit WebSocket URL.
            token: Subscribe-only JWT for :attr:`identity`.
        """
        from livekit import rtc

        self._room = rtc.Room()

        def _on_track_subscribed(track: Any, publication: Any, participant: Any) -> None:
            self.tracks.append(
                {
                    "publisher_identity": participant.identity,
                    "kind": _kind_name(getattr(track, "kind", None)),
                    "name": getattr(publication, "name", ""),
                    "sid": getattr(publication, "sid", ""),
                    "source": str(getattr(publication, "source", "")),
                    "mime_type": getattr(publication, "mime_type", ""),
                    "subscribed_at": time.monotonic(),
                }
            )
            # Compare against the enum, not its string form: livekit's
            # TrackKind is an int-backed protobuf enum, so str() yields "1" /
            # "2" and a `.endswith("AUDIO")` test silently never matches —
            # every track subscribed, no pump was ever started, and the probe
            # reported zero audio AND zero video while the vendor was in fact
            # publishing both.
            kind = getattr(track, "kind", None)
            if kind == rtc.TrackKind.KIND_AUDIO:
                self._pumps.append(asyncio.create_task(self._pump_audio(rtc.AudioStream(track))))
            elif kind == rtc.TrackKind.KIND_VIDEO:
                self._pumps.append(asyncio.create_task(self._pump_video(rtc.VideoStream(track))))

        self._room.on("track_subscribed", _on_track_subscribed)
        await self._room.connect(url, token)
        self.logger.info("subscriber %s connected", self.identity)

    async def _pump_audio(self, stream: Any) -> None:
        """Consume an ``rtc.AudioStream`` and accumulate audio statistics."""
        try:
            async for event in stream:
                self.audio_frames += 1
                peak = _frame_peak(event.frame)
                self.peak = max(self.peak, peak)
                now = time.monotonic()
                if self.first_audio_at is None:
                    self.first_audio_at = now
                if peak >= _SILENCE_PEAK_THRESHOLD:
                    self.audible_frames += 1
                    if self.first_audible_at is None:
                        self.first_audible_at = now
                    self.last_audible_at = now
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 — probe must never mask its own report
            self.logger.exception("audio pump failed")

    async def _pump_video(self, stream: Any) -> None:
        """Consume an ``rtc.VideoStream`` and count decoded frames."""
        try:
            async for _event in stream:
                self.video_frames += 1
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001
            self.logger.exception("video pump failed")

    def reset_audio_counters(self) -> None:
        """Zero the audio counters so a later phase can be measured alone."""
        self.audio_frames = 0
        self.audible_frames = 0
        self.peak = 0
        self.first_audio_at = None
        self.first_audible_at = None
        self.last_audible_at = None

    def manifest(self) -> Dict[str, Any]:
        """Return this subscriber's sanitized observation summary."""
        return {
            "identity": self.identity,
            "audio_frames": self.audio_frames,
            "audible_frames": self.audible_frames,
            "video_frames": self.video_frames,
            "peak_amplitude": self.peak,
            "tracks": [{key: value for key, value in track.items() if key != "subscribed_at"} for track in self.tracks],
        }

    async def aclose(self) -> None:
        """Cancel pumps and disconnect.  Never raises."""
        for pump in self._pumps:
            pump.cancel()
        for pump in self._pumps:
            try:
                await pump
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
        self._pumps.clear()
        if self._room is not None:
            try:
                await self._room.disconnect()
            except Exception:  # noqa: BLE001 — teardown must not raise
                self.logger.warning("subscriber disconnect failed", exc_info=True)
            self._room = None


async def _spawn_subscribers(tokens: Any, count: int) -> List[_Subscriber]:
    """Connect ``count`` subscribe-only browsers-equivalents to the room.

    Each subscriber gets a **distinct** identity and its own freshly minted
    subscribe-only JWT (identity reuse would evict the previous participant —
    see spec §2 "Ownership, admission and cleanup").

    Args:
        tokens: The publisher's :class:`LiveKitRoomTokens` (room + URL source).
        count: Number of subscribers to connect.

    Returns:
        The connected subscribers.
    """
    from parrot.integrations.liveavatar.room_manager import LiveKitRoomManager

    manager = LiveKitRoomManager()
    subscribers: List[_Subscriber] = []
    for index in range(1, count + 1):
        identity = f"probe-viewer-{index}"
        viewer_tokens = manager.mint_room_tokens(tokens.room, identity)
        subscriber = _Subscriber(identity)
        await subscriber.connect(viewer_tokens.livekit_url, viewer_tokens.client_token)
        subscribers.append(subscriber)
    return subscribers


class _AvatarProbeSession:
    """Owns one live LITE session for the duration of a probe scenario."""

    def __init__(self, config: Any, tokens: Any) -> None:
        self.config = config
        self.tokens = tokens
        self.client: Any = None
        self.handle: Any = None
        self.ws: Any = None
        self.max_duration_accepted: bool = False
        self.max_duration_error: Optional[str] = None

    async def __aenter__(self) -> "_AvatarProbeSession":
        from parrot.integrations.liveavatar.avatar_ws import AvatarWebSocket
        from parrot.integrations.liveavatar.client import LiveAvatarClient

        # Verified LiveKitConfigSchema keys (OpenAPI SHA 8f589bc4…): the avatar
        # publishes into OUR room, so it receives the publish-capable token.
        livekit_config = {
            "livekit_url": self.tokens.livekit_url,
            "livekit_room": self.tokens.room,
            "livekit_client_token": self.tokens.agent_token,
        }
        self.client = LiveAvatarClient(self.config)
        await self.client.aopen()
        try:
            self.handle = await self.client.create_session_token(self.config, livekit_config=livekit_config)
            self.max_duration_accepted = True
        except Exception as exc:  # noqa: BLE001 — recorded, then re-raised
            self.max_duration_error = f"{type(exc).__name__}: {exc}"
            await self.client.aclose()
            raise
        try:
            await self.client.start_session(self.handle)
            self.ws = AvatarWebSocket(self.handle)
            await self.ws.__aenter__()
            await self.ws.start_speaking()
        except Exception:
            await self.aclose()
            raise
        return self

    async def __aexit__(self, *_exc: Any) -> None:
        await self.aclose()

    async def speak_tone(self, seconds: float, *, start_sample: int = 0) -> int:
        """Send ``seconds`` of deterministic tone, then ``agent.speak_end``.

        Args:
            seconds: Tone duration.
            start_sample: Absolute sample offset for phase continuity.

        Returns:
            The next absolute sample index (for a following utterance).
        """
        pcm = _tone_pcm(seconds, start_sample=start_sample)
        await self.ws.send_audio_frame(pcm)
        await self.ws.finish_speaking()
        return start_sample + len(pcm) // _BYTES_PER_SAMPLE

    async def aclose(self) -> None:
        """Tear down WS, vendor session and HTTP client.  Never raises."""
        if self.ws is not None:
            try:
                await self.ws.__aexit__(None, None, None)
            except Exception:  # noqa: BLE001
                _logger.warning("probe: avatar ws close failed", exc_info=True)
            self.ws = None
        if self.client is not None and self.handle is not None:
            try:
                await self.client.stop_session(self.handle)
            except Exception:  # noqa: BLE001
                _logger.warning("probe: stop_session failed", exc_info=True)
            self.handle = None
        if self.client is not None:
            try:
                await self.client.aclose()
            except Exception:  # noqa: BLE001
                _logger.warning("probe: client aclose failed", exc_info=True)
            self.client = None


def _harvest_event_types(caplog: Any) -> List[str]:
    """Extract LITE server event type names from ``AvatarWebSocket`` INFO logs.

    ``AvatarWebSocket._handle_server_message`` logs every inbound event at INFO
    as ``server event type=%r payload=%s``; that is the only observation point
    available before TASK-2955 adds real callbacks.

    Args:
        caplog: pytest ``caplog`` fixture.

    Returns:
        Sorted unique event-type names.
    """
    found: List[str] = []
    for record in caplog.records:
        message = record.getMessage()
        match = re.search(r"server event type='([^']*)'", message)
        if match:
            found.append(match.group(1))
    return sorted(set(found))


# ── Scenarios ──────────────────────────────────────────────────────────────


@pytest.mark.skipif(not _GATE_ENABLED, reason=_SKIP_REASON)
async def test_nova_pcm_reaches_two_subscribers(
    avatar_config: Any,
    room_tokens: Any,
    evidence: Any,
    caplog: Any,
) -> None:
    """LITE accepts 24 kHz PCM and publishes A/V to two distinct subscribers.

    Spec §2 vendor gate / AC10.  Asserts only what is a contract: both
    subscribers receive non-zero audio from the avatar participant.  Track
    identities, codecs, video-frame progress and first-frame latency are
    measured and reported.
    """
    caplog.set_level(logging.INFO, logger="parrot.integrations.liveavatar.avatar_ws")
    subscribers: List[_Subscriber] = []
    try:
        subscribers = await _spawn_subscribers(room_tokens, 2)
        async with _AvatarProbeSession(avatar_config, room_tokens) as session:
            started = time.monotonic()
            await session.speak_tone(_UTTERANCE_SECONDS)
            await asyncio.sleep(_OBSERVE_SECONDS)
            # Measured to the first *audible* frame, not the first frame of
            # any kind: the avatar publishes silent comfort audio from the
            # moment it joins, and the subscribers connect before the speak
            # request, so timing to `first_audio_at` reported a NEGATIVE
            # latency (-0.54 s) — an obviously meaningless figure to carry
            # into an acceptance record.
            latencies = {
                sub.identity: (round(sub.first_audible_at - started, 3) if sub.first_audible_at is not None else None)
                for sub in subscribers
            }
            evidence.events.extend(_harvest_event_types(caplog))
            evidence.record(
                "two_subscribers",
                room="<probe-room>",
                max_session_duration_requested=_MAX_SESSION_DURATION,
                max_session_duration_accepted=session.max_duration_accepted,
                first_audio_latency_seconds=latencies,
                subscribers=[sub.manifest() for sub in subscribers],
            )
    finally:
        for subscriber in subscribers:
            await subscriber.aclose()

    for subscriber in subscribers:
        assert subscriber.audible_frames > 0, (
            f"{subscriber.identity} received no audible audio from the avatar "
            f"({subscriber.audio_frames} frames, peak {subscriber.peak})"
        )


@pytest.mark.skipif(not _GATE_ENABLED, reason=_SKIP_REASON)
async def test_interrupt_stops_avatar_audio_within_budget(
    avatar_config: Any,
    room_tokens: Any,
    evidence: Any,
    caplog: Any,
) -> None:
    """``agent.interrupt`` stops speech, and the session survives for a re-speak.

    Spec §2 "Audio routing, failure and interruption" / AC6.  The
    speak → interrupt → speak-again sequence is the vendor-side analogue of a
    speaker handoff (spec §2 moderation barrier).
    """
    caplog.set_level(logging.INFO, logger="parrot.integrations.liveavatar.avatar_ws")
    subscribers: List[_Subscriber] = []
    time_to_silence: Optional[float] = None
    try:
        subscribers = await _spawn_subscribers(room_tokens, 1)
        listener = subscribers[0]
        async with _AvatarProbeSession(avatar_config, room_tokens) as session:
            next_sample = await session.speak_tone(_UTTERANCE_SECONDS)
            # Let playback actually begin before interrupting.
            deadline = time.monotonic() + _OBSERVE_SECONDS
            while listener.audible_frames == 0 and time.monotonic() < deadline:
                await asyncio.sleep(0.05)

            interrupted_at = time.monotonic()
            await session.ws.interrupt()
            # Poll until audio stops arriving (audible_frames stops growing).
            silence_deadline = interrupted_at + 5.0
            while time.monotonic() < silence_deadline:
                last = listener.last_audible_at
                if last is not None and (time.monotonic() - last) > 0.35:
                    time_to_silence = round(last - interrupted_at, 3)
                    break
                await asyncio.sleep(0.05)

            # Second utterance — proves the session survived the interrupt.
            listener.reset_audio_counters()
            await session.speak_tone(_UTTERANCE_SECONDS, start_sample=next_sample)
            await asyncio.sleep(_OBSERVE_SECONDS)
            second_audible = listener.audible_frames

            evidence.events.extend(_harvest_event_types(caplog))
            evidence.record(
                "interrupt",
                time_to_silence_seconds=time_to_silence,
                budget_seconds=_INTERRUPT_BUDGET_SECONDS,
                within_budget=(time_to_silence is not None and time_to_silence <= _INTERRUPT_BUDGET_SECONDS),
                second_utterance_audible_frames=second_audible,
                subscriber=listener.manifest(),
            )
    finally:
        for subscriber in subscribers:
            await subscriber.aclose()

    assert time_to_silence is not None, "avatar audio never went silent after agent.interrupt within 5 s"
    assert second_audible > 0, "session did not survive agent.interrupt — second utterance was inaudible"


@pytest.mark.skipif(not _GATE_ENABLED, reason=_SKIP_REASON)
async def test_direct_publisher_clear_queue_stops_audio(
    room_tokens: Any,
    evidence: Any,
) -> None:
    """``AudioSource.clear_queue()`` purges queued direct-publisher audio.

    Spec §2: ``RoomAudioPublisher.flush()`` is *not* a native queue purge in the
    baseline (fixed by TASK-2956).  This probe establishes the real SDK
    behaviour the fix must rely on: after ``clear_queue()`` the queued tail
    must stop within :data:`_INTERRUPT_BUDGET_SECONDS`.
    """
    from parrot.integrations.liveavatar.room_audio_publisher import RoomAudioPublisher

    subscribers: List[_Subscriber] = []
    publisher: Any = None
    time_to_silence: Optional[float] = None
    heard_before_clear = 0
    try:
        subscribers = await _spawn_subscribers(room_tokens, 1)
        listener = subscribers[0]
        publisher = await RoomAudioPublisher.start(room_tokens)

        # Queue several seconds of tone, far more than real-time playout.
        await publisher.capture_pcm(_tone_pcm(_UTTERANCE_SECONDS))

        deadline = time.monotonic() + _OBSERVE_SECONDS
        while listener.audible_frames == 0 and time.monotonic() < deadline:
            await asyncio.sleep(0.05)
        heard_before_clear = listener.audible_frames

        cleared_at = time.monotonic()
        publisher.source.clear_queue()
        silence_deadline = cleared_at + 5.0
        while time.monotonic() < silence_deadline:
            last = listener.last_audible_at
            if last is not None and (time.monotonic() - last) > 0.35:
                time_to_silence = round(last - cleared_at, 3)
                break
            await asyncio.sleep(0.05)

        evidence.record(
            "clear_queue",
            audible_frames_before_clear=heard_before_clear,
            time_to_silence_seconds=time_to_silence,
            budget_seconds=_INTERRUPT_BUDGET_SECONDS,
            within_budget=(time_to_silence is not None and time_to_silence <= _INTERRUPT_BUDGET_SECONDS),
            subscriber=listener.manifest(),
        )
    finally:
        if publisher is not None:
            await publisher.aclose()
        for subscriber in subscribers:
            await subscriber.aclose()

    assert heard_before_clear > 0, "direct publisher produced no audible audio at all"
    assert time_to_silence is not None, "direct-publisher audio never went silent after AudioSource.clear_queue()"
