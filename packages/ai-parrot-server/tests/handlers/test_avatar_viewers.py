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
