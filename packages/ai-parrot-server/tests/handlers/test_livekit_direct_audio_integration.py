"""Integration tests for the LiveKit direct-audio path (FEAT-256 TASK-1630).

End-to-end (mocked-room) coverage that verifies:
1. ``test_livekit_direct_audio_end_to_end_mock``
   /start (avatar off) → one simulated turn → assert PCM frames captured to
   room track → /stop tears down (no orphaned participant).

2. ``test_autofallback_end_to_end_mock``
   /start (avatar on) where LiveAvatar start raises the no-credits
   ClientResponseError → assert fallback to publisher → turn audio still flows
   → /stop clean.

All network-facing components (LiveKit room, LiveAvatar API) are mocked — no
real connections are made.

Note on the publisher import: ``room_audio_publisher.py`` lives in the
``ai-parrot-integrations`` package whose editable-install path points to the
*main* repo directory, not the worktree.  These tests therefore work with a
fully inlined fake publisher (``_FakeRoomAudioPublisher``) and inject it via
``sys.modules``, exactly like the handler's lazy import resolves it at runtime.
This is consistent with the pattern used by the other avatar endpoint tests in
this directory.
"""
from __future__ import annotations

import json
import os
import sys
import types
from typing import Any, List
from unittest.mock import AsyncMock, MagicMock

import pytest
from aiohttp import ClientResponseError


# ---------------------------------------------------------------------------
# Shared fake objects
# ---------------------------------------------------------------------------


class _FakeAudioSource:
    """Records PCM frames pushed to the room audio track."""

    def __init__(self, sample_rate: int = 24000, num_channels: int = 1) -> None:
        self.sample_rate = sample_rate
        self.num_channels = num_channels
        self.captured_frames: List[Any] = []

    async def capture_frame(self, frame: Any) -> None:
        self.captured_frames.append(frame)


class _FakeAudioFrame:
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


class _FakeRoom:
    """Tracks connect/disconnect lifecycle calls."""

    def __init__(self) -> None:
        self.connected_url = ""
        self.connected_token = ""
        self.disconnected = False

        # Simulate a local_participant that records published tracks
        self.local_participant = MagicMock()
        self.local_participant.published_tracks: List[Any] = []
        self.local_participant.publish_track = AsyncMock(
            side_effect=lambda t, o: self.local_participant.published_tracks.append((t, o))
        )

    async def connect(self, url: str, token: str) -> None:
        self.connected_url = url
        self.connected_token = token

    async def disconnect(self) -> None:
        self.disconnected = True


class _FakeRoomAudioPublisher:
    """Inline fake that mirrors the ``RoomAudioPublisher`` interface.

    Backed by a ``_FakeAudioSource`` for verifiable PCM capture, and a
    ``_FakeRoom`` to verify room connect/disconnect lifecycle.

    Created via :meth:`start` (class-method factory), like the real publisher.
    """

    _BYTES_PER_SAMPLE: int = 2
    _NUM_CHANNELS: int = 1

    def __init__(self, room: _FakeRoom, source: _FakeAudioSource) -> None:
        self.room = room
        self.source = source
        self._closed = False
        self._flushing = False

    @classmethod
    async def start(cls, tokens: Any, **kwargs: Any) -> "_FakeRoomAudioPublisher":
        room = _FakeRoom()
        await room.connect(tokens.livekit_url, tokens.agent_token)
        source = _FakeAudioSource()
        return cls(room, source)

    async def capture_pcm(self, pcm: bytes) -> None:
        if self._closed or self._flushing or not pcm:
            return
        samples_per_channel = len(pcm) // (self._BYTES_PER_SAMPLE * self._NUM_CHANNELS)
        if samples_per_channel <= 0:
            return
        frame = _FakeAudioFrame(
            data=pcm,
            sample_rate=24000,
            num_channels=self._NUM_CHANNELS,
            samples_per_channel=samples_per_channel,
        )
        await self.source.capture_frame(frame)

    async def flush(self) -> None:
        self._flushing = True
        self._flushing = False

    async def aclose(self) -> None:
        if self._closed:
            return
        self._closed = True
        await self.room.disconnect()


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _make_no_credits_error() -> ClientResponseError:
    return ClientResponseError(
        request_info=MagicMock(),
        history=(),
        status=403,
        message="Error code 4033: No credits available",
    )


def _fake_tokens() -> MagicMock:
    t = MagicMock()
    t.livekit_url = "wss://integration-test.livekit.cloud"
    t.room = "integration-test-room"
    t.client_token = "viewer-jwt-integration"
    t.agent_token = "agent-jwt-integration"
    return t


def _fake_request(session_id: str, extra_body: dict | None = None):
    body: dict = {"session_id": session_id}
    if extra_body:
        body.update(extra_body)
    req = MagicMock()
    req.match_info = {"agent_id": "integration-agent"}
    req.app = {}
    req.json = AsyncMock(return_value=body)
    return req


_ENV = {
    "LIVEAVATAR_API_KEY": "test-key",
    "LIVEAVATAR_AVATAR_ID": "test-avatar",
    "LIVEKIT_URL": "wss://integration-test.livekit.cloud",
    "LIVEKIT_API_KEY": "lk-key",
    "LIVEKIT_API_SECRET": "lk-secret",
}

_INJECT_KEYS = [
    "parrot.integrations.liveavatar",
    "parrot.integrations.liveavatar.optin",
    "parrot.integrations.liveavatar.room_audio_publisher",
]


def _inject(modules: dict) -> dict:
    saved = {k: sys.modules.get(k) for k in _INJECT_KEYS}
    for k, v in modules.items():
        if v is not None:
            sys.modules[k] = v
    return saved


def _restore(saved: dict) -> None:
    for k, v in saved.items():
        if v is None:
            sys.modules.pop(k, None)
        else:
            sys.modules[k] = v


def _build_liveavatar_modules(tokens, *, start_session_raises=None):
    fake_handle = MagicMock()
    fake_handle.session_id = "integration-test"

    fake_client = AsyncMock()
    fake_client.aopen = AsyncMock()
    fake_client.create_session_token = AsyncMock(return_value=fake_handle)
    if start_session_raises is not None:
        fake_client.start_session = AsyncMock(side_effect=start_session_raises)
    else:
        fake_client.start_session = AsyncMock()
    fake_client.stop_session = AsyncMock()
    fake_client.aclose = AsyncMock()

    mod = types.ModuleType("parrot.integrations.liveavatar")
    mod.LiveAvatarClient = MagicMock(return_value=fake_client)
    mod.LiveAvatarConfig = MagicMock()
    mod.LiveKitRoomManager = MagicMock()
    mod.LiveKitRoomManager.return_value.mint_room_tokens.return_value = tokens

    optin = types.ModuleType("parrot.integrations.liveavatar.optin")
    optin.is_avatar_enabled = MagicMock(return_value=True)  # type: ignore[attr-defined]

    return mod, optin, fake_client


def _build_publisher_module() -> types.ModuleType:
    """Return a fake room_audio_publisher module backed by _FakeRoomAudioPublisher."""
    pub_mod = types.ModuleType("parrot.integrations.liveavatar.room_audio_publisher")
    pub_mod.RoomAudioPublisher = _FakeRoomAudioPublisher  # type: ignore[attr-defined]
    return pub_mod


# ---------------------------------------------------------------------------
# Integration test 1: avatar-OFF end-to-end
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_livekit_direct_audio_end_to_end_mock() -> None:
    """/start (avatar=false) → turn PCM → frames captured → /stop tears down."""
    from parrot.handlers.avatar import _start_avatar_session, _stop_avatar_session

    tokens = _fake_tokens()
    la_mod, optin_mod, fake_la_client = _build_liveavatar_modules(tokens)
    pub_mod = _build_publisher_module()

    # ── /start (avatar=false) ──────────────────────────────────────────────
    req_start = _fake_request("integration-test", extra_body={"avatar": False})

    saved = _inject({
        "parrot.integrations.liveavatar": la_mod,
        "parrot.integrations.liveavatar.optin": optin_mod,
        "parrot.integrations.liveavatar.room_audio_publisher": pub_mod,
    })
    try:
        with patch_env(_ENV):
            start_response = await _start_avatar_session(req_start)
    finally:
        _restore(saved)

    # Verify 200 + correct keys
    assert start_response.status == 200
    start_data = json.loads(start_response.body)  # type: ignore[attr-defined]
    assert start_data["session_id"] == "integration-test"
    assert start_data["client_token"] == "viewer-jwt-integration"
    assert "agent_token" not in start_data  # never expose agent_token

    # LiveAvatar must NOT have been used
    fake_la_client.start_session.assert_not_called()

    # Publisher must be in the session store
    store = req_start.app["avatar_sessions"]
    assert "integration-test" in store
    publisher: _FakeRoomAudioPublisher = store["integration-test"]["publisher"]
    assert isinstance(publisher, _FakeRoomAudioPublisher)

    # Room must have connected with agent_token (not client_token)
    assert publisher.room.connected_token == "agent-jwt-integration"

    # ── Simulate a turn: push PCM through the publisher ────────────────────
    # 10 ms of 24 kHz mono 16-bit = 240 samples * 2 bytes = 480 bytes
    pcm = b"\x01\x00" * 240
    await publisher.capture_pcm(pcm)

    # Verify frames were captured to the AudioSource
    source = publisher.source
    assert len(source.captured_frames) == 1
    frame = source.captured_frames[0]
    assert frame.data == pcm
    assert frame.samples_per_channel == 240  # len(480) // (2 * 1)
    assert frame.sample_rate == 24_000

    # ── /stop ──────────────────────────────────────────────────────────────
    req_stop = MagicMock()
    req_stop.app = req_start.app
    req_stop.json = AsyncMock(return_value={"session_id": "integration-test"})

    stop_response = await _stop_avatar_session(req_stop)

    assert stop_response.status == 204
    # Publisher must have disconnected from the room (no orphaned participant)
    assert publisher.room.disconnected
    # Session must be gone from the store
    assert "integration-test" not in req_start.app["avatar_sessions"]


# ---------------------------------------------------------------------------
# Integration test 2: auto-fallback end-to-end
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_autofallback_end_to_end_mock() -> None:
    """/start (avatar=true) + LiveAvatar 402 → fallback → turn audio flows → /stop clean."""
    from parrot.handlers.avatar import _start_avatar_session, _stop_avatar_session

    tokens = _fake_tokens()
    no_credits = _make_no_credits_error()
    la_mod, optin_mod, fake_la_client = _build_liveavatar_modules(
        tokens, start_session_raises=no_credits
    )
    pub_mod = _build_publisher_module()

    # ── /start (avatar=true, but 402 from LiveAvatar) ──────────────────────
    req_start = _fake_request("fallback-test", extra_body={"avatar": True})

    saved = _inject({
        "parrot.integrations.liveavatar": la_mod,
        "parrot.integrations.liveavatar.optin": optin_mod,
        "parrot.integrations.liveavatar.room_audio_publisher": pub_mod,
    })
    try:
        with patch_env(_ENV):
            start_response = await _start_avatar_session(req_start)
    finally:
        _restore(saved)

    # Must be 200 (NOT 402) — the auto-fallback succeeded
    assert start_response.status == 200
    start_data = json.loads(start_response.body)  # type: ignore[attr-defined]
    assert start_data["session_id"] == "fallback-test"
    assert "agent_token" not in start_data

    # LiveAvatar client must have been closed (cleanup after 402)
    fake_la_client.aclose.assert_called_once()

    # Publisher must be in the store (fallback succeeded)
    store = req_start.app["avatar_sessions"]
    publisher: _FakeRoomAudioPublisher = store["fallback-test"]["publisher"]
    assert isinstance(publisher, _FakeRoomAudioPublisher)

    # ── Simulate a turn: audio still flows via the fallback publisher ───────
    pcm = b"\x02\x00" * 480  # 20 ms of 24 kHz mono 16-bit
    await publisher.capture_pcm(pcm)

    source = publisher.source
    assert len(source.captured_frames) == 1
    assert source.captured_frames[0].data == pcm
    assert source.captured_frames[0].samples_per_channel == 480

    # ── /stop ──────────────────────────────────────────────────────────────
    req_stop = MagicMock()
    req_stop.app = req_start.app
    req_stop.json = AsyncMock(return_value={"session_id": "fallback-test"})

    stop_response = await _stop_avatar_session(req_stop)

    assert stop_response.status == 204
    # Publisher disconnected — no orphaned room participant
    assert publisher.room.disconnected
    assert "fallback-test" not in req_start.app["avatar_sessions"]


# ---------------------------------------------------------------------------
# Env patch helper (avoids importing unittest.mock.patch at module level)
# ---------------------------------------------------------------------------


def patch_env(env: dict):
    """Context manager: temporarily set environment variables."""
    from unittest.mock import patch as _patch
    return _patch.dict(os.environ, env)
