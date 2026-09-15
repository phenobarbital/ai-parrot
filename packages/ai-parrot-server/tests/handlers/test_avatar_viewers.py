"""Tests for the multi-viewer token endpoint (TASK-1606 — FEAT-249 Mode C).

Verifies:
- POST /api/v1/avatar/{agent_id}/viewers returns `count` distinct subscribe-only tokens.
- 404 for unknown session.
- 400 for `count` out of bounds or missing session_id.
- agent_token is never in the response.
"""

from __future__ import annotations

import asyncio
import sys
import types
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from aiohttp import web

from parrot.handlers.avatar import AVATAR_SESSIONS_KEY, _mint_viewer_tokens

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_request(body: dict, *, app_store: dict | None = None, agent_id: str = "bot") -> MagicMock:
    """Build a minimal fake aiohttp request."""
    req = MagicMock()
    req.match_info = {"agent_id": agent_id}
    req.json = AsyncMock(return_value=body)
    req.app = {AVATAR_SESSIONS_KEY: app_store or {}}
    return req


def _make_fake_liveavatar_mod():
    """Inject a fake parrot.integrations.liveavatar with a mock LiveKitRoomManager."""
    mod = types.ModuleType("parrot.integrations.liveavatar")

    class _FakeTokens:
        livekit_url = "wss://test.livekit.cloud"
        room = "sess-1"
        client_token = "viewer-jwt"
        agent_token = "agent-jwt"  # NEVER in response

    class _FakeRoomManager:
        def mint_room_tokens(self, room: str, identity: str) -> _FakeTokens:
            t = _FakeTokens()
            t.room = room
            return t

    mod.LiveKitRoomManager = _FakeRoomManager  # type: ignore[attr-defined]
    return mod


# ---------------------------------------------------------------------------
# Test: returns N distinct tokens
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_mint_viewer_tokens_returns_n_tokens():
    """_mint_viewer_tokens returns `count` distinct viewer tokens."""
    store = {"sess-1": {"client": MagicMock(), "handle": MagicMock()}}
    req = _make_request({"session_id": "sess-1", "count": 3}, app_store=store)

    fake_mod = _make_fake_liveavatar_mod()
    saved = sys.modules.get("parrot.integrations.liveavatar")
    sys.modules["parrot.integrations.liveavatar"] = fake_mod
    try:
        resp = await _mint_viewer_tokens(req)
    finally:
        if saved is None:
            sys.modules.pop("parrot.integrations.liveavatar", None)
        else:
            sys.modules["parrot.integrations.liveavatar"] = saved

    import json

    data = json.loads(resp.body)
    viewers = data["viewers"]
    assert len(viewers) == 3

    # All tokens have required keys; no agent_token
    for v in viewers:
        assert "identity" in v
        assert "livekit_url" in v
        assert "client_token" in v
        assert "agent_token" not in v

    # Identities must be distinct
    identities = [v["identity"] for v in viewers]
    assert len(set(identities)) == 3


# ---------------------------------------------------------------------------
# Test: 404 for unknown session
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_mint_viewer_tokens_404_for_unknown_session():
    """_mint_viewer_tokens raises 404 when session_id is not in the store."""
    from aiohttp import web

    req = _make_request({"session_id": "ghost-session", "count": 1}, app_store={})

    fake_mod = _make_fake_liveavatar_mod()
    saved = sys.modules.get("parrot.integrations.liveavatar")
    sys.modules["parrot.integrations.liveavatar"] = fake_mod
    try:
        with pytest.raises(web.HTTPNotFound):
            await _mint_viewer_tokens(req)
    finally:
        if saved is None:
            sys.modules.pop("parrot.integrations.liveavatar", None)
        else:
            sys.modules["parrot.integrations.liveavatar"] = saved


# ---------------------------------------------------------------------------
# Test: 400 for count out of bounds
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("bad_count", [0, 51, -1, 100])
async def test_mint_viewer_tokens_400_for_bad_count(bad_count):
    """_mint_viewer_tokens raises 400 for count outside [1, 50]."""
    from aiohttp import web

    store = {"sess-1": {"client": MagicMock(), "handle": MagicMock()}}
    req = _make_request({"session_id": "sess-1", "count": bad_count}, app_store=store)

    fake_mod = _make_fake_liveavatar_mod()
    saved = sys.modules.get("parrot.integrations.liveavatar")
    sys.modules["parrot.integrations.liveavatar"] = fake_mod
    try:
        with pytest.raises(web.HTTPBadRequest):
            await _mint_viewer_tokens(req)
    finally:
        if saved is None:
            sys.modules.pop("parrot.integrations.liveavatar", None)
        else:
            sys.modules["parrot.integrations.liveavatar"] = saved


# ---------------------------------------------------------------------------
# Test: 400 for missing session_id
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_mint_viewer_tokens_400_for_missing_session_id():
    """_mint_viewer_tokens raises 400 when session_id is absent."""
    from aiohttp import web

    req = _make_request({"count": 1}, app_store={})

    fake_mod = _make_fake_liveavatar_mod()
    saved = sys.modules.get("parrot.integrations.liveavatar")
    sys.modules["parrot.integrations.liveavatar"] = fake_mod
    try:
        with pytest.raises(web.HTTPBadRequest):
            await _mint_viewer_tokens(req)
    finally:
        if saved is None:
            sys.modules.pop("parrot.integrations.liveavatar", None)
        else:
            sys.modules["parrot.integrations.liveavatar"] = saved


# ---------------------------------------------------------------------------
# Test: two tokens can connect to the same room (structural check)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_two_viewer_tokens_same_room():
    """Two viewer tokens share the same livekit_url / room but have distinct identities."""
    store = {"sess-room-42": {"client": MagicMock(), "handle": MagicMock()}}
    req = _make_request({"session_id": "sess-room-42", "count": 2}, app_store=store)

    fake_mod = _make_fake_liveavatar_mod()
    saved = sys.modules.get("parrot.integrations.liveavatar")
    sys.modules["parrot.integrations.liveavatar"] = fake_mod
    try:
        resp = await _mint_viewer_tokens(req)
    finally:
        if saved is None:
            sys.modules.pop("parrot.integrations.liveavatar", None)
        else:
            sys.modules["parrot.integrations.liveavatar"] = saved

    import json

    data = json.loads(resp.body)
    viewers = data["viewers"]
    assert len(viewers) == 2
    # Both tokens point to the same LiveKit URL (same room)
    assert viewers[0]["livekit_url"] == viewers[1]["livekit_url"]
    # But identities differ
    assert viewers[0]["identity"] != viewers[1]["identity"]


# ---------------------------------------------------------------------------
# FEAT-537 (TASK-2962): the legacy viewer helper must not admit broadcast rooms
# ---------------------------------------------------------------------------


async def test_legacy_viewer_helper_rejects_broadcast_room() -> None:
    """A broadcast room name is not mintable through the legacy bypass.

    ``_mint_viewer_tokens`` will mint up to 50 subscribe tokens for *any*
    ``session_id`` present in ``app[AVATAR_SESSIONS_KEY]``, with no seat
    accounting, no lease and no moderator concept. FEAT-537's ten-seat rule
    lives entirely in the broadcast registry, so a broadcast room reachable
    through this helper would be an unbounded admission bypass (spec §2
    "Viewer admission compatibility").

    The guarantee is structural: ``BroadcastService`` never writes to that
    store, so a broadcast id can never be found there. This test pins that —
    if a future change starts registering broadcasts in the avatar store, it
    fails here rather than silently reopening the bypass.
    """
    broadcast_room = "bcast-bc-0123456789abcdef"
    # An avatar store populated by the legacy path only.
    store = {"legacy-avatar-session": {"room": "legacy-avatar-session"}}
    req = _make_request({"session_id": broadcast_room, "count": 3}, app_store=store)

    # The helper signals a missing session by raising HTTPNotFound.
    with pytest.raises(web.HTTPNotFound):
        await _mint_viewer_tokens(req)


def test_broadcast_service_never_writes_to_the_avatar_session_store() -> None:
    """No code path in the broadcast package touches AVATAR_SESSIONS_KEY."""
    import pathlib

    import parrot.integrations.liveavatar.broadcast as broadcast_pkg

    package = pathlib.Path(broadcast_pkg.__file__).parent
    assert package.is_dir(), f"broadcast package not found at {package}"
    offenders = [
        path.name
        for path in package.glob("*.py")
        if "AVATAR_SESSIONS_KEY" in path.read_text() or "avatar_sessions" in path.read_text()
    ]
    assert offenders == [], (
        f"{offenders} reference the legacy avatar session store; a broadcast "
        "registered there would be admissible through _mint_viewer_tokens "
        "without any seat accounting"
    )
