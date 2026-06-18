"""Unit tests for the request-agnostic voice-native helpers (FEAT-244 TASK-1584).

Tests cover:
- start_voice_native: dispatches worker, records in AVATAR_VOICE_SESSIONS_KEY,
  returns the expected dict.
- stop_voice_native: pops the dispatch record and calls delete_dispatch; idempotent
  on unknown session_id.
- REST view (_start_voice_native_session) returns the same JSON as before the refactor.
"""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from aiohttp import web

from parrot.handlers import avatar
from parrot.handlers.avatar import (
    AVATAR_VOICE_SESSIONS_KEY,
    start_voice_native,
    stop_voice_native,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def fake_room_manager():
    """A mock LiveKitRoomManager with the minimal interface used by the helpers."""
    rm = MagicMock()
    rm.url = "wss://test.livekit.cloud"
    rm.mint_browser_token.return_value = "browser-jwt"
    rm.dispatch_worker = AsyncMock(return_value="dispatch-123")
    rm.delete_dispatch = AsyncMock()
    return rm


def _make_job_metadata(ws_url, session_id, agent_name, tenant_id, **kwargs):
    """Lightweight stand-in for AvatarJobMetadata (only needs model_dump_json)."""
    meta = MagicMock()
    meta.model_dump_json.return_value = json.dumps({
        "ws_url": ws_url,
        "session_id": session_id,
    })
    return meta


# Patch targets: the names are imported LAZILY inside start_voice_native's body,
# so we must patch them at their canonical source locations.
_PATCH_ROOM_MANAGER = "parrot.integrations.liveavatar.LiveKitRoomManager"
_PATCH_JOB_METADATA = "parrot.integrations.liveavatar.livekit_agent.models.AvatarJobMetadata"
_PATCH_IS_ENABLED = "parrot.integrations.liveavatar.optin.is_avatar_enabled"


# ---------------------------------------------------------------------------
# Tests for start_voice_native
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_start_voice_native_dispatches_and_records(fake_room_manager):
    """start_voice_native mints a token, dispatches the worker, records the dispatch."""
    app = web.Application()

    with (
        patch(_PATCH_ROOM_MANAGER, return_value=fake_room_manager),
        patch(_PATCH_JOB_METADATA, side_effect=_make_job_metadata),
        patch(_PATCH_IS_ENABLED, return_value=True),
    ):
        out = await start_voice_native(app, "my-agent", "sess-1", None)

    assert out == {
        "livekit_url": "wss://test.livekit.cloud",
        "token": "browser-jwt",
        "session_id": "sess-1",
    }
    fake_room_manager.dispatch_worker.assert_awaited_once()
    assert app[AVATAR_VOICE_SESSIONS_KEY]["sess-1"]["dispatch_id"] == "dispatch-123"
    assert app[AVATAR_VOICE_SESSIONS_KEY]["sess-1"]["room"] == "sess-1"


@pytest.mark.asyncio
async def test_start_voice_native_returns_correct_fields(fake_room_manager):
    """Return value matches the {livekit_url, token, session_id} contract."""
    app = web.Application()

    with (
        patch(_PATCH_ROOM_MANAGER, return_value=fake_room_manager),
        patch(_PATCH_JOB_METADATA, side_effect=_make_job_metadata),
        patch(_PATCH_IS_ENABLED, return_value=True),
    ):
        result = await start_voice_native(app, "agent-x", "room-42", "tenant-abc")

    assert set(result.keys()) == {"livekit_url", "token", "session_id"}
    assert result["session_id"] == "room-42"


@pytest.mark.asyncio
async def test_start_voice_native_forbidden_when_not_enabled(fake_room_manager):
    """Raises HTTPForbidden when is_avatar_enabled returns False."""
    app = web.Application()
    with patch(_PATCH_IS_ENABLED, return_value=False):
        with pytest.raises(web.HTTPForbidden):
            await start_voice_native(app, "my-agent", "sess-1", None)


@pytest.mark.asyncio
async def test_start_voice_native_503_on_missing_livekit_env(fake_room_manager):
    """Raises HTTPServiceUnavailable when LiveKitRoomManager raises KeyError."""
    app = web.Application()
    bad_rm_class = MagicMock(side_effect=KeyError("LIVEKIT_URL"))
    with (
        patch(_PATCH_IS_ENABLED, return_value=True),
        patch(_PATCH_ROOM_MANAGER, bad_rm_class),
    ):
        with pytest.raises(web.HTTPServiceUnavailable):
            await start_voice_native(app, "my-agent", "sess-1", None)


@pytest.mark.asyncio
async def test_start_voice_native_503_on_dispatch_failure(fake_room_manager):
    """Raises HTTPServiceUnavailable when dispatch_worker raises."""
    app = web.Application()
    fake_room_manager.dispatch_worker = AsyncMock(side_effect=RuntimeError("timeout"))
    with (
        patch(_PATCH_ROOM_MANAGER, return_value=fake_room_manager),
        patch(_PATCH_JOB_METADATA, side_effect=_make_job_metadata),
        patch(_PATCH_IS_ENABLED, return_value=True),
    ):
        with pytest.raises(web.HTTPServiceUnavailable):
            await start_voice_native(app, "my-agent", "sess-1", None)


# ---------------------------------------------------------------------------
# Tests for stop_voice_native
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_stop_voice_native_deletes_dispatch(fake_room_manager):
    """stop_voice_native pops the session record and calls delete_dispatch."""
    app = web.Application()

    with (
        patch(_PATCH_ROOM_MANAGER, return_value=fake_room_manager),
        patch(_PATCH_JOB_METADATA, side_effect=_make_job_metadata),
        patch(_PATCH_IS_ENABLED, return_value=True),
    ):
        await start_voice_native(app, "my-agent", "sess-1", None)

    assert "sess-1" in app[AVATAR_VOICE_SESSIONS_KEY]

    # stop_voice_native calls _delete_voice_dispatch which imports LiveKitRoomManager lazily
    with patch(_PATCH_ROOM_MANAGER, return_value=fake_room_manager):
        await stop_voice_native(app, "sess-1")

    fake_room_manager.delete_dispatch.assert_awaited_once()
    assert "sess-1" not in app[AVATAR_VOICE_SESSIONS_KEY]


@pytest.mark.asyncio
async def test_stop_voice_native_unknown_is_idempotent():
    """stop_voice_native does not raise when session_id is unknown."""
    app = web.Application()
    # Must not raise even if AVATAR_VOICE_SESSIONS_KEY doesn't exist on app
    await stop_voice_native(app, "does-not-exist")


@pytest.mark.asyncio
async def test_stop_voice_native_idempotent_twice(fake_room_manager):
    """Calling stop_voice_native twice on the same session doesn't raise."""
    app = web.Application()

    with (
        patch(_PATCH_ROOM_MANAGER, return_value=fake_room_manager),
        patch(_PATCH_JOB_METADATA, side_effect=_make_job_metadata),
        patch(_PATCH_IS_ENABLED, return_value=True),
    ):
        await start_voice_native(app, "my-agent", "sess-1", None)

    with patch(_PATCH_ROOM_MANAGER, return_value=fake_room_manager):
        await stop_voice_native(app, "sess-1")
        await stop_voice_native(app, "sess-1")  # second call — must not raise

    assert fake_room_manager.delete_dispatch.await_count == 1  # only called once


# ---------------------------------------------------------------------------
# Tests for REST view (_start_voice_native_session) — regression
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_rest_view_delegates_to_helper(fake_room_manager):
    """_start_voice_native_session returns the same JSON as before the refactor."""
    app = web.Application()

    # Build a minimal fake request
    request = MagicMock()
    request.app = app
    request.match_info = {"agent_id": "test-agent"}
    request.json = AsyncMock(return_value={"session_id": "sess-rest"})

    with (
        patch(_PATCH_ROOM_MANAGER, return_value=fake_room_manager),
        patch(_PATCH_JOB_METADATA, side_effect=_make_job_metadata),
        patch(_PATCH_IS_ENABLED, return_value=True),
    ):
        response = await avatar._start_voice_native_session(request)

    assert response.status == 200
    body = json.loads(response.body)
    assert body["livekit_url"] == "wss://test.livekit.cloud"
    assert body["token"] == "browser-jwt"
    assert body["session_id"] == "sess-rest"
