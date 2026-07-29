"""Unit tests for the FULL mode avatar handler (TASK-1594 + TASK-1595).

Tests cover:
- _start_fullmode_session: returns viewer creds, no sensitive fields, opt-in gate,
  tenant_id persisted on handle, HTTPConflict for duplicate session_id
- _stop_fullmode_session: tears down via store, idempotent
- _list_avatars: proxies list_avatars() with config resolver
- _list_voices: proxies list_voices() with config resolver
- _get_session_transcript: happy path and 404 for missing session

All LiveAvatar and liveavatar stack imports are lazy-injected via sys.modules
so the test suite never requires ai-parrot-integrations to be installed.
"""
from __future__ import annotations

import json
import sys
import types
from typing import Any, Dict
from unittest.mock import AsyncMock, MagicMock

import pytest
from aiohttp.web import (
    HTTPBadRequest,
    HTTPConflict,
    HTTPForbidden,
    HTTPInternalServerError,
    HTTPServiceUnavailable,
)

from parrot.handlers.avatar_fullmode import (
    FULLMODE_SESSIONS_KEY,
    _get_session_transcript,
    _list_avatars,
    _list_voices,
    _start_fullmode_session,
    _stop_fullmode_session,
)


# ---------------------------------------------------------------------------
# Helpers: inject fake liveavatar stack
# ---------------------------------------------------------------------------


def _inject_fullmode_stack(
    *,
    fullmode_enabled: bool = True,
    livekit_url: str = "wss://test.livekit.cloud",
    livekit_client_token: str = "eyJ-browser-token",
    session_id_response: str = "la-session-1",
) -> tuple:
    """Inject fake liveavatar modules into sys.modules.

    Returns ``(saved_modules, inject_keys, fake_client, fake_handle)``
    so callers can assert on interactions and restore sys.modules.
    """
    # Fake session handle
    fake_handle = MagicMock()
    fake_handle.session_id = ""
    fake_handle.liveavatar_session_id = session_id_response
    fake_handle.session_token = "server-secret"
    fake_handle.ws_url = ""
    fake_handle.agent_name = "test-agent"
    fake_handle.livekit_url = livekit_url
    fake_handle.livekit_client_token = livekit_client_token

    # Fake client — supports aopen() and the context manager protocol
    fake_client = MagicMock()
    fake_client.aopen = AsyncMock(return_value=fake_client)
    fake_client.aclose = AsyncMock()
    fake_client.create_full_session_token = AsyncMock(return_value=fake_handle)
    fake_client.start_session = AsyncMock(return_value={})
    fake_client.stop_session = AsyncMock()
    fake_client.list_avatars = AsyncMock(return_value=[])
    fake_client.list_voices = AsyncMock(return_value=[])
    fake_client.__aenter__ = AsyncMock(return_value=fake_client)
    fake_client.__aexit__ = AsyncMock(return_value=False)

    # Fake LiveAvatarClient class — returns our fake instance
    fake_client_cls = MagicMock(return_value=fake_client)

    # Fake resolve_fullmode_config (async — must be AsyncMock)
    fake_cfg = MagicMock()
    fake_cfg.api_key = "test-key"
    fake_resolve = AsyncMock(return_value=fake_cfg)

    # Fake is_fullmode_enabled
    fake_is_fullmode = MagicMock(return_value=fullmode_enabled)

    # Build the fake modules
    fake_client_mod = types.ModuleType("parrot.integrations.liveavatar.client")
    fake_client_mod.LiveAvatarClient = fake_client_cls  # type: ignore[attr-defined]

    fake_optin_mod = types.ModuleType("parrot.integrations.liveavatar.optin")
    fake_optin_mod.is_fullmode_enabled = fake_is_fullmode  # type: ignore[attr-defined]

    fake_tenant_mod = types.ModuleType("parrot.integrations.liveavatar.tenant_config")
    fake_tenant_mod.resolve_fullmode_config = fake_resolve  # type: ignore[attr-defined]

    inject_keys = [
        "parrot.integrations.liveavatar.client",
        "parrot.integrations.liveavatar.optin",
        "parrot.integrations.liveavatar.tenant_config",
    ]
    saved_modules = {k: sys.modules.get(k) for k in inject_keys}
    sys.modules["parrot.integrations.liveavatar.client"] = fake_client_mod
    sys.modules["parrot.integrations.liveavatar.optin"] = fake_optin_mod
    sys.modules["parrot.integrations.liveavatar.tenant_config"] = fake_tenant_mod

    return saved_modules, inject_keys, fake_client, fake_handle


def _restore_modules(saved_modules: dict, inject_keys: list) -> None:
    """Restore sys.modules to their pre-injection state."""
    for key in inject_keys:
        if saved_modules[key] is None:
            sys.modules.pop(key, None)
        else:
            sys.modules[key] = saved_modules[key]


def _make_request(
    json_body: Dict[str, Any],
    match_info: Dict[str, str] | None = None,
) -> MagicMock:
    """Build a fake aiohttp.web.Request with a real dict app."""
    req = MagicMock()
    req.json = AsyncMock(return_value=json_body)
    req.match_info = match_info or {"agent_id": "test-agent"}
    req.app = {}

    # Fake rel_url for GET query params
    fake_url = MagicMock()
    fake_url.query = {}
    req.rel_url = fake_url

    return req


# ---------------------------------------------------------------------------
# TASK-1594: _start_fullmode_session
# ---------------------------------------------------------------------------


class TestStartFullmodeSession:
    """Tests for _start_fullmode_session (TASK-1594)."""

    async def test_returns_viewer_creds(self) -> None:
        """Response contains session_id, livekit_url, livekit_client_token."""
        req = _make_request({"session_id": "sess-1", "tenant_id": "acme"})

        saved, keys, fake_client, fake_handle = _inject_fullmode_stack()
        try:
            resp = await _start_fullmode_session(req)
        finally:
            _restore_modules(saved, keys)

        body = json.loads(resp.body)  # type: ignore[attr-defined]
        assert body["session_id"] == "sess-1"
        assert body["livekit_url"] == "wss://test.livekit.cloud"
        assert body["livekit_client_token"] == "eyJ-browser-token"

    async def test_no_sensitive_fields_in_response(self) -> None:
        """Response does NOT contain session_token, agent_token, ws_url."""
        req = _make_request({"session_id": "sess-1", "tenant_id": "acme"})

        saved, keys, _, _ = _inject_fullmode_stack()
        try:
            resp = await _start_fullmode_session(req)
        finally:
            _restore_modules(saved, keys)

        body = json.loads(resp.body)  # type: ignore[attr-defined]
        assert "session_token" not in body, "session_token must never be returned"
        assert "agent_token" not in body, "agent_token must never be returned"
        assert "ws_url" not in body, "ws_url must never be returned"

    async def test_rejects_disabled_tenant(self) -> None:
        """Returns 403 when is_fullmode_enabled returns False."""
        req = _make_request({"session_id": "sess-1", "tenant_id": "blocked"})

        saved, keys, _, _ = _inject_fullmode_stack(fullmode_enabled=False)
        try:
            with pytest.raises(HTTPForbidden):
                await _start_fullmode_session(req)
        finally:
            _restore_modules(saved, keys)

    async def test_requires_session_id(self) -> None:
        """Returns 400 when session_id is missing from request body."""
        req = _make_request({})

        saved, keys, _, _ = _inject_fullmode_stack()
        try:
            with pytest.raises(HTTPBadRequest):
                await _start_fullmode_session(req)
        finally:
            _restore_modules(saved, keys)

    async def test_client_stored_in_session_store(self) -> None:
        """The live client is kept alive and stored in app[FULLMODE_SESSIONS_KEY]."""
        req = _make_request({"session_id": "sess-1", "tenant_id": "acme"})

        saved, keys, fake_client, _ = _inject_fullmode_stack()
        try:
            await _start_fullmode_session(req)
        finally:
            _restore_modules(saved, keys)

        # aclose must NOT have been called (client is kept alive)
        fake_client.aclose.assert_not_called()
        # Client stored in session store
        store = req.app[FULLMODE_SESSIONS_KEY]
        assert "sess-1" in store
        assert store["sess-1"]["client"] is fake_client

    async def test_config_error_returns_503(self) -> None:
        """Returns 503 when resolve_fullmode_config raises RuntimeError."""
        req = _make_request({"session_id": "sess-1", "tenant_id": "acme"})

        saved, keys, _, _ = _inject_fullmode_stack()
        try:
            sys.modules[
                "parrot.integrations.liveavatar.tenant_config"
            ].resolve_fullmode_config = AsyncMock(
                side_effect=RuntimeError("missing env vars")
            )
            with pytest.raises(HTTPServiceUnavailable):
                await _start_fullmode_session(req)
        finally:
            _restore_modules(saved, keys)

    async def test_avatar_id_override_applied(self) -> None:
        """A request-supplied avatar_id overrides the resolved config avatar_id."""
        req = _make_request(
            {"session_id": "sess-1", "tenant_id": "acme", "avatar_id": "custom-av"}
        )

        saved, keys, fake_client, _ = _inject_fullmode_stack()
        try:
            # The resolved config is a MagicMock — capture the overridden copy it
            # produces so we can assert it is the cfg actually used downstream.
            fake_cfg = await sys.modules[
                "parrot.integrations.liveavatar.tenant_config"
            ].resolve_fullmode_config()
            overridden_cfg = fake_cfg.model_copy.return_value

            await _start_fullmode_session(req)

            # cfg.model_copy must be called with the request avatar_id override.
            fake_cfg.model_copy.assert_called_once_with(
                update={"avatar_id": "custom-av"}
            )
            # And the OVERRIDDEN cfg must be the one passed to session creation.
            fake_client.create_full_session_token.assert_awaited_once_with(
                overridden_cfg
            )
        finally:
            _restore_modules(saved, keys)

    async def test_no_avatar_id_uses_config_default(self) -> None:
        """Without avatar_id in the body, model_copy is NOT called (config default)."""
        req = _make_request({"session_id": "sess-1", "tenant_id": "acme"})

        saved, keys, _, _ = _inject_fullmode_stack()
        try:
            fake_cfg = await sys.modules[
                "parrot.integrations.liveavatar.tenant_config"
            ].resolve_fullmode_config()

            await _start_fullmode_session(req)

            fake_cfg.model_copy.assert_not_called()
        finally:
            _restore_modules(saved, keys)


# ---------------------------------------------------------------------------
# TASK-1875 (FEAT-247): custom_llm_url in /full/start response
# ---------------------------------------------------------------------------


class TestStartReturnsCustomLLMURL:
    """Tests for the FEAT-247 `custom_llm_url` field (TASK-1875)."""

    async def test_start_returns_custom_llm_url(self) -> None:
        """Response includes custom_llm_url matching /v1/chat/completions/{session_id}?agent={agent_id}."""
        req = _make_request(
            {"session_id": "sess-1", "tenant_id": "acme"},
            match_info={"agent_id": "pokemon_analyst"},
        )
        req.scheme = "https"
        req.host = "parrot.example.com"

        saved, keys, _, _ = _inject_fullmode_stack()
        try:
            resp = await _start_fullmode_session(req)
        finally:
            _restore_modules(saved, keys)

        body = json.loads(resp.body)  # type: ignore[attr-defined]
        assert (
            body["custom_llm_url"]
            == "https://parrot.example.com/v1/chat/completions/sess-1?agent=pokemon_analyst"
        )

    async def test_existing_fields_unchanged(self) -> None:
        """session_id, livekit_url, livekit_client_token are still present and correct."""
        req = _make_request(
            {"session_id": "sess-1", "tenant_id": "acme"},
            match_info={"agent_id": "pokemon_analyst"},
        )
        req.scheme = "https"
        req.host = "parrot.example.com"

        saved, keys, _, _ = _inject_fullmode_stack()
        try:
            resp = await _start_fullmode_session(req)
        finally:
            _restore_modules(saved, keys)

        body = json.loads(resp.body)  # type: ignore[attr-defined]
        assert body["session_id"] == "sess-1"
        assert body["livekit_url"] == "wss://test.livekit.cloud"
        assert body["livekit_client_token"] == "eyJ-browser-token"

    async def test_custom_llm_url_uses_base_url_override(self, monkeypatch) -> None:
        """OPENAI_COMPAT_BASE_URL, when set, wins over request.scheme/host."""
        monkeypatch.setenv("OPENAI_COMPAT_BASE_URL", "https://public.example.com")

        req = _make_request(
            {"session_id": "sess-2", "tenant_id": "acme"},
            match_info={"agent_id": "weather_bot"},
        )
        req.scheme = "http"
        req.host = "internal-host:8080"

        saved, keys, _, _ = _inject_fullmode_stack()
        try:
            resp = await _start_fullmode_session(req)
        finally:
            _restore_modules(saved, keys)

        body = json.loads(resp.body)  # type: ignore[attr-defined]
        assert (
            body["custom_llm_url"]
            == "https://public.example.com/v1/chat/completions/sess-2?agent=weather_bot"
        )


# ---------------------------------------------------------------------------
# TASK-1594: _stop_fullmode_session
# ---------------------------------------------------------------------------


class TestStopFullmodeSession:
    """Tests for _stop_fullmode_session (TASK-1594)."""

    async def test_stops_existing_session(self) -> None:
        """Stops a tracked session: calls stop_session + aclose, removes from store."""
        fake_client = MagicMock()
        fake_client.stop_session = AsyncMock()
        fake_client.aclose = AsyncMock()
        fake_handle = MagicMock()

        req = _make_request({"session_id": "sess-1"})
        req.app = {
            FULLMODE_SESSIONS_KEY: {
                "sess-1": {"client": fake_client, "handle": fake_handle}
            }
        }

        resp = await _stop_fullmode_session(req)

        assert resp.status == 204
        fake_client.stop_session.assert_awaited_once_with(fake_handle)
        fake_client.aclose.assert_awaited_once()
        assert "sess-1" not in req.app[FULLMODE_SESSIONS_KEY]

    async def test_idempotent_stop_unknown_session(self) -> None:
        """Returns 204 for an unknown/already-stopped session (idempotent)."""
        req = _make_request({"session_id": "ghost"})
        req.app = {}

        resp = await _stop_fullmode_session(req)

        assert resp.status == 204

    async def test_requires_session_id(self) -> None:
        """Returns 400 when session_id is missing."""
        req = _make_request({})

        with pytest.raises(HTTPBadRequest):
            await _stop_fullmode_session(req)

    async def test_aclose_called_even_on_stop_error(self) -> None:
        """aclose() is called in the finally block even when stop_session raises."""
        import aiohttp

        fake_client = MagicMock()
        fake_client.stop_session = AsyncMock(
            side_effect=aiohttp.ClientResponseError(
                request_info=MagicMock(), history=(), status=500
            )
        )
        fake_client.aclose = AsyncMock()
        fake_handle = MagicMock()

        req = _make_request({"session_id": "sess-1"})
        req.app = {
            FULLMODE_SESSIONS_KEY: {
                "sess-1": {"client": fake_client, "handle": fake_handle}
            }
        }

        try:
            await _stop_fullmode_session(req)
        except Exception:
            pass

        fake_client.aclose.assert_awaited_once()


# ---------------------------------------------------------------------------
# TASK-1595: _list_avatars / _list_voices
# ---------------------------------------------------------------------------


class TestListAvatars:
    """Tests for _list_avatars (TASK-1595)."""

    async def test_returns_avatars(self) -> None:
        """Returns a list of avatars from the LiveAvatar API."""
        fake_avatars = [{"id": "av1", "name": "Avatar 1"}]

        req = MagicMock()
        req.rel_url.query = {}

        saved, keys, fake_client, _ = _inject_fullmode_stack()
        fake_client.list_avatars = AsyncMock(return_value=fake_avatars)
        try:
            resp = await _list_avatars(req)
        finally:
            _restore_modules(saved, keys)

        body = json.loads(resp.body)  # type: ignore[attr-defined]
        assert body == {"avatars": fake_avatars}

    async def test_handles_api_error(self) -> None:
        """Returns 500 when LiveAvatar API raises an exception."""
        req = MagicMock()
        req.rel_url.query = {}

        saved, keys, fake_client, _ = _inject_fullmode_stack()
        fake_client.list_avatars = AsyncMock(side_effect=RuntimeError("API down"))
        try:
            with pytest.raises(HTTPInternalServerError):
                await _list_avatars(req)
        finally:
            _restore_modules(saved, keys)

    async def test_config_error_returns_503(self) -> None:
        """Returns 503 when resolve_fullmode_config raises RuntimeError."""
        req = MagicMock()
        req.rel_url.query = {}

        saved, keys, _, _ = _inject_fullmode_stack()
        sys.modules[
            "parrot.integrations.liveavatar.tenant_config"
        ].resolve_fullmode_config = AsyncMock(
            side_effect=RuntimeError("missing vars")
        )
        try:
            with pytest.raises(HTTPServiceUnavailable):
                await _list_avatars(req)
        finally:
            _restore_modules(saved, keys)


class TestListVoices:
    """Tests for _list_voices (TASK-1595)."""

    async def test_returns_voices(self) -> None:
        """Returns a list of voices from the LiveAvatar API."""
        fake_voices = [{"id": "v1", "name": "Voice 1"}]

        req = MagicMock()
        req.rel_url.query = {}

        saved, keys, fake_client, _ = _inject_fullmode_stack()
        fake_client.list_voices = AsyncMock(return_value=fake_voices)
        try:
            resp = await _list_voices(req)
        finally:
            _restore_modules(saved, keys)

        body = json.loads(resp.body)  # type: ignore[attr-defined]
        assert body == {"voices": fake_voices}

    async def test_handles_api_error(self) -> None:
        """Returns 500 when LiveAvatar API raises an exception."""
        req = MagicMock()
        req.rel_url.query = {}

        saved, keys, fake_client, _ = _inject_fullmode_stack()
        fake_client.list_voices = AsyncMock(side_effect=RuntimeError("API down"))
        try:
            with pytest.raises(HTTPInternalServerError):
                await _list_voices(req)
        finally:
            _restore_modules(saved, keys)


# ---------------------------------------------------------------------------
# MAJOR-2: handle.tenant_id persists in session store
# ---------------------------------------------------------------------------


class TestTenantIdPersistedInStore:
    """Verify that handle.tenant_id is correctly set and stored (MAJOR-2)."""

    async def test_tenant_id_persisted_on_handle(self) -> None:
        """After /start, store['sess-1']['handle'].tenant_id == 'acme'."""
        req = _make_request({"session_id": "sess-1", "tenant_id": "acme"})

        saved, keys, fake_client, fake_handle = _inject_fullmode_stack()
        try:
            await _start_fullmode_session(req)
        finally:
            _restore_modules(saved, keys)

        store = req.app[FULLMODE_SESSIONS_KEY]
        assert "sess-1" in store
        assert store["sess-1"]["handle"].tenant_id == "acme"

    async def test_tenant_id_none_when_not_provided(self) -> None:
        """handle.tenant_id is None when tenant_id is absent from the request."""
        req = _make_request({"session_id": "sess-2"})

        saved, keys, fake_client, fake_handle = _inject_fullmode_stack()
        try:
            await _start_fullmode_session(req)
        finally:
            _restore_modules(saved, keys)

        store = req.app[FULLMODE_SESSIONS_KEY]
        assert store["sess-2"]["handle"].tenant_id is None


# ---------------------------------------------------------------------------
# MAJOR-3: duplicate /start raises HTTPConflict (409)
# ---------------------------------------------------------------------------


class TestConcurrentStartConflict:
    """Verify that a second /start for the same session_id raises 409 (MAJOR-3)."""

    async def test_duplicate_session_raises_conflict(self) -> None:
        """Second /start with an already-active session_id raises HTTPConflict."""
        req = _make_request({"session_id": "sess-dup", "tenant_id": "acme"})
        # Pre-populate the store to simulate an already-active session.
        fake_existing_client = MagicMock()
        fake_existing_handle = MagicMock()
        req.app = {
            FULLMODE_SESSIONS_KEY: {
                "sess-dup": {
                    "client": fake_existing_client,
                    "handle": fake_existing_handle,
                }
            }
        }

        saved, keys, fake_client, _ = _inject_fullmode_stack()
        try:
            with pytest.raises(HTTPConflict):
                await _start_fullmode_session(req)
        finally:
            _restore_modules(saved, keys)

        # The existing session must not have been replaced.
        assert req.app[FULLMODE_SESSIONS_KEY]["sess-dup"]["client"] is fake_existing_client
        # The new client must not have been opened.
        fake_client.aopen.assert_not_called()


# ---------------------------------------------------------------------------
# MINOR-5: _get_session_transcript handler tests
# ---------------------------------------------------------------------------


class TestGetSessionTranscript:
    """Tests for _get_session_transcript (MINOR-5)."""

    async def test_returns_transcript(self) -> None:
        """Happy path: returns the transcript dict from the LiveAvatar API."""
        fake_transcript = {"entries": [{"speaker": "user", "text": "Hello"}]}

        req = MagicMock()
        req.match_info = {"session_id": "la-session-1"}

        saved, keys, fake_client, _ = _inject_fullmode_stack()
        fake_client.get_session_transcript = AsyncMock(return_value=fake_transcript)
        try:
            resp = await _get_session_transcript(req)
        finally:
            _restore_modules(saved, keys)

        body = json.loads(resp.body)  # type: ignore[attr-defined]
        assert body == fake_transcript

    async def test_missing_session_id_returns_400(self) -> None:
        """Returns 400 when session_id path parameter is absent."""
        req = MagicMock()
        req.match_info = {}

        saved, keys, _, _ = _inject_fullmode_stack()
        try:
            with pytest.raises(HTTPBadRequest):
                await _get_session_transcript(req)
        finally:
            _restore_modules(saved, keys)

    async def test_api_error_returns_500(self) -> None:
        """Returns 500 when the LiveAvatar API raises an exception."""
        req = MagicMock()
        req.match_info = {"session_id": "la-session-1"}

        saved, keys, fake_client, _ = _inject_fullmode_stack()
        fake_client.get_session_transcript = AsyncMock(
            side_effect=RuntimeError("API down")
        )
        try:
            with pytest.raises(HTTPInternalServerError):
                await _get_session_transcript(req)
        finally:
            _restore_modules(saved, keys)

    async def test_config_error_returns_503(self) -> None:
        """Returns 503 when resolve_fullmode_config raises RuntimeError."""
        req = MagicMock()
        req.match_info = {"session_id": "la-session-1"}

        saved, keys, _, _ = _inject_fullmode_stack()
        sys.modules[
            "parrot.integrations.liveavatar.tenant_config"
        ].resolve_fullmode_config = AsyncMock(
            side_effect=RuntimeError("missing vars")
        )
        try:
            with pytest.raises(HTTPServiceUnavailable):
                await _get_session_transcript(req)
        finally:
            _restore_modules(saved, keys)


# ---------------------------------------------------------------------------
# MAJOR-1: authenticated view classes are BaseView subclasses
# ---------------------------------------------------------------------------


class TestAuthenticatedViews:
    """Verify FULL mode views inherit from navigator BaseView (MAJOR-1)."""

    def test_fullmode_views_are_baseview_subclasses(self) -> None:
        """All FULLMODE view classes are navigator BaseView subclasses."""
        from navigator.views import BaseView

        from parrot.handlers.avatar_fullmode import (
            FullmodeAvatarsView,
            FullmodeStartView,
            FullmodeStopView,
            FullmodeTranscriptView,
            FullmodeVoicesView,
        )

        for view_cls in (
            FullmodeStartView,
            FullmodeStopView,
            FullmodeAvatarsView,
            FullmodeVoicesView,
            FullmodeTranscriptView,
        ):
            assert issubclass(view_cls, BaseView), (
                f"{view_cls.__name__} must be a BaseView subclass"
            )
