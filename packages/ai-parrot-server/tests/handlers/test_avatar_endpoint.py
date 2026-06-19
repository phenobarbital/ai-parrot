"""Unit tests for the avatar session endpoint (TASK-007).

Verifies:
- ``/api/v1/agents/avatar/{agent_id}/start`` returns viewer credentials only
  (livekit_url + client_token + session_id; no agent_token or ws_url).
- Avatar mode flag in AgentVoiceTalk is absent by default.
- Avatar flag is parsed from the request body.
"""
from __future__ import annotations

from unittest.mock import patch


from parrot.handlers.agent_voice import AgentVoiceTalk


# ---------------------------------------------------------------------------
# AgentVoiceTalk avatar-mode flag
# ---------------------------------------------------------------------------

def _make_voice_handler() -> AgentVoiceTalk:
    """Build an AgentVoiceTalk instance without an aiohttp request."""
    handler = AgentVoiceTalk.__new__(AgentVoiceTalk)
    handler.post_init()
    return handler


def test_avatar_mode_flag_off_by_default() -> None:
    """Avatar mode is off unless the request body carries 'avatar=true'."""
    h = _make_voice_handler()
    assert h._avatar_mode is False


def test_avatar_mode_flag_parsed_true() -> None:
    """_read_voice_options sets _avatar_mode when 'avatar': True."""
    h = _make_voice_handler()
    data = {"avatar": True, "query": "Hello"}
    h._read_voice_options(data)
    assert h._avatar_mode is True
    # The flag should be consumed (popped) from data
    assert "avatar" not in data


def test_avatar_mode_flag_parsed_string_true() -> None:
    """_read_voice_options accepts 'avatar': 'true' (string)."""
    h = _make_voice_handler()
    data = {"avatar": "true"}
    h._read_voice_options(data)
    assert h._avatar_mode is True


def test_avatar_mode_flag_stays_off_for_false() -> None:
    """_read_voice_options does not enable avatar mode for 'avatar': False."""
    h = _make_voice_handler()
    data = {"avatar": False}
    h._read_voice_options(data)
    assert h._avatar_mode is False


def test_avatar_tenant_id_parsed() -> None:
    """_read_voice_options extracts tenant_id into _avatar_tenant_id."""
    h = _make_voice_handler()
    data = {"avatar": True, "tenant_id": "acme"}
    h._read_voice_options(data)
    assert h._avatar_tenant_id == "acme"
    assert "tenant_id" not in data


def test_no_breaking_change_to_voice_selectors() -> None:
    """Existing tts_backend / stt_backend / audio_format still parsed correctly."""
    h = _make_voice_handler()
    data = {"tts_backend": "supertonic", "audio_format": "audio/wav", "stt_backend": "local"}
    h._read_voice_options(data)
    assert h._tts_backend == "supertonic"
    assert h._tts_format == "audio/wav"
    assert h._stt_backend == "local"


# ---------------------------------------------------------------------------
# Avatar endpoint response contract (function-level view test)
# ---------------------------------------------------------------------------

async def test_start_endpoint_response_keys() -> None:
    """_start_avatar_session returns livekit_url + client_token + session_id.

    Uses fully-mocked LiveAvatar stack so the test does not require
    ``ai-parrot-integrations`` to be installed in the test environment.

    Because the handler lazily imports from ``parrot.integrations.liveavatar``
    inside the request handler body, we inject fake module objects into
    ``sys.modules`` before the handler runs so all lazy imports resolve without
    requiring the satellite package to be installed.
    """
    import json
    import os
    import sys
    import types
    from unittest.mock import AsyncMock, MagicMock

    from parrot.handlers.avatar import _start_avatar_session

    # Build a fake request with a REAL dict app so the session store behaves
    # like the real aiohttp MutableMapping (setdefault/get/pop).
    fake_request = MagicMock()
    fake_request.match_info = {"agent_id": "test-agent"}
    fake_request.app = {}
    fake_request.json = AsyncMock(return_value={
        "session_id": "sess-1",
        "tenant_id": "t1",
    })

    # Fake token object — attributes accessed by the handler
    fake_tokens = MagicMock()
    fake_tokens.livekit_url = "wss://x.livekit.cloud"
    fake_tokens.room = "sess-1"
    fake_tokens.client_token = "viewer-jwt"
    fake_tokens.agent_token = "agent-jwt"

    fake_handle = MagicMock()
    fake_handle.session_id = "sess-1"

    # Build fake module objects for the liveavatar stack
    fake_liveavatar_mod = types.ModuleType("parrot.integrations.liveavatar")
    fake_liveavatar_mod.LiveAvatarClient = MagicMock()
    fake_liveavatar_mod.LiveAvatarConfig = MagicMock()
    fake_liveavatar_mod.LiveKitRoomManager = MagicMock()

    fake_optin_mod = types.ModuleType("parrot.integrations.liveavatar.optin")
    fake_optin_mod.is_avatar_enabled = MagicMock(return_value=True)  # type: ignore[attr-defined]

    # Wire fake client context manager
    fake_client_ctx = AsyncMock()
    fake_client_ctx.__aenter__ = AsyncMock(return_value=fake_client_ctx)
    fake_client_ctx.__aexit__ = AsyncMock(return_value=False)
    fake_client_ctx.create_session_token = AsyncMock(return_value=fake_handle)
    fake_client_ctx.start_session = AsyncMock(return_value={})
    fake_liveavatar_mod.LiveAvatarClient.return_value = fake_client_ctx

    # Wire room manager
    fake_liveavatar_mod.LiveKitRoomManager.return_value.mint_room_tokens.return_value = fake_tokens

    # Wire config (just needs to be constructible)
    fake_liveavatar_mod.LiveAvatarConfig.return_value = MagicMock()

    saved_modules: dict = {}
    inject_keys = [
        "parrot.integrations.liveavatar",
        "parrot.integrations.liveavatar.optin",
    ]

    with patch.dict(os.environ, {
        "LIVEAVATAR_API_KEY": "key",
        "LIVEAVATAR_AVATAR_ID": "avatar",
        "LIVEKIT_URL": "wss://x.livekit.cloud",
        "LIVEKIT_API_KEY": "lk-key",
        "LIVEKIT_API_SECRET": "lk-secret",
    }):
        # Inject fakes; restore originals (or remove) after the test
        for key in inject_keys:
            saved_modules[key] = sys.modules.get(key)
        sys.modules["parrot.integrations.liveavatar"] = fake_liveavatar_mod
        sys.modules["parrot.integrations.liveavatar.optin"] = fake_optin_mod
        try:
            response = await _start_avatar_session(fake_request)
        finally:
            for key in inject_keys:
                if saved_modules[key] is None:
                    sys.modules.pop(key, None)
                else:
                    sys.modules[key] = saved_modules[key]

    body = response.body  # type: ignore[attr-defined]
    data = json.loads(body)
    assert "livekit_url" in data
    assert "client_token" in data
    assert "session_id" in data
    assert "agent_token" not in data, "agent_token must never be returned to the client"
    assert "ws_url" not in data, "ws_url must never be returned to the client"
    assert "session_token" not in data, "session_token must never be returned to the client"
    assert data["client_token"] == "viewer-jwt"

    # C-1: the client must be kept ALIVE (not closed on the way out) and stored
    # in the session store so /stop can reach it.
    fake_client_ctx.aclose.assert_not_called()
    store = fake_request.app["avatar_sessions"]
    assert "sess-1" in store
    assert store["sess-1"]["client"] is fake_client_ctx


# ---------------------------------------------------------------------------
# Stop endpoint: tears down via the store, no client-supplied session_token
# ---------------------------------------------------------------------------

async def test_stop_endpoint_tears_down_stored_session() -> None:
    """_stop_avatar_session stops + closes the stored client; no token from client."""
    from unittest.mock import AsyncMock, MagicMock

    from parrot.handlers.avatar import AVATAR_SESSIONS_KEY, _stop_avatar_session

    fake_client = MagicMock()
    fake_client.stop_session = AsyncMock()
    fake_client.aclose = AsyncMock()
    fake_handle = MagicMock()

    req = MagicMock()
    req.json = AsyncMock(return_value={"session_id": "sess-1"})  # NO session_token
    req.app = {AVATAR_SESSIONS_KEY: {"sess-1": {"client": fake_client, "handle": fake_handle}}}

    resp = await _stop_avatar_session(req)

    assert resp.status == 204
    fake_client.stop_session.assert_awaited_once_with(fake_handle)
    fake_client.aclose.assert_awaited_once()
    # Session removed from the store
    assert "sess-1" not in req.app[AVATAR_SESSIONS_KEY]


async def test_stop_endpoint_idempotent_for_unknown_session() -> None:
    """Stopping an unknown session returns 204 without error."""
    from unittest.mock import AsyncMock, MagicMock

    from parrot.handlers.avatar import _stop_avatar_session

    req = MagicMock()
    req.json = AsyncMock(return_value={"session_id": "ghost"})
    req.app = {}

    resp = await _stop_avatar_session(req)
    assert resp.status == 204


# ---------------------------------------------------------------------------
# Auth: the avatar view requires authentication (C-3)
# ---------------------------------------------------------------------------

def test_avatar_view_is_baseview_subclass() -> None:
    """AvatarSessionView is a navigator BaseView (carries auth decorators)."""
    from navigator.views import BaseView

    from parrot.handlers.avatar import AvatarSessionView

    assert issubclass(AvatarSessionView, BaseView)
