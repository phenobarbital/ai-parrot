"""Unit tests for `O365OAuthManager.refresh_access_token` (FEAT-266)."""
from unittest.mock import AsyncMock, MagicMock

import pytest

from parrot.auth.o365_oauth import O365OAuthManager
from parrot.auth.oauth2_base import InvalidGrantError, RefreshTransientError


class _FakeResponse:
    """Minimal async-context-manager stand-in for `aiohttp.ClientResponse`."""

    def __init__(self, status: int, json_data=None, text_data: str = ""):
        self.status = status
        self._json = json_data or {}
        self._text = text_data

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc_info):
        return False

    async def json(self, **kwargs):
        # Accept aiohttp kwargs such as ``content_type=None``.
        return self._json

    async def text(self):
        return self._text


class _FakeSession:
    """Minimal stand-in for `aiohttp.ClientSession` — `post()` returns a fixed response."""

    def __init__(self, response: _FakeResponse):
        self._response = response

    def post(self, *args, **kwargs):
        return self._response


@pytest.fixture
def manager() -> O365OAuthManager:
    return O365OAuthManager(
        client_id="client-id",
        client_secret="client-secret",
        redirect_uri="http://localhost/callback",
        redis_client=MagicMock(),
    )


@pytest.mark.asyncio
async def test_refresh_access_token_returns_token(manager, monkeypatch):
    fake_response = _FakeResponse(
        200, json_data={"access_token": "new-tok", "expires_in": 3600}
    )
    monkeypatch.setattr(
        manager, "_get_session", AsyncMock(return_value=_FakeSession(fake_response))
    )

    result = await manager.refresh_access_token("refresh-tok")

    assert result["access_token"] == "new-tok"


@pytest.mark.asyncio
async def test_refresh_access_token_dead_token_raises_permissionerror(manager, monkeypatch):
    """An OAuth ``invalid_grant`` body is the only dead-token signal."""
    fake_response = _FakeResponse(400, json_data={"error": "invalid_grant"})
    monkeypatch.setattr(
        manager, "_get_session", AsyncMock(return_value=_FakeSession(fake_response))
    )

    with pytest.raises(InvalidGrantError) as excinfo:
        await manager.refresh_access_token("dead-token")
    assert isinstance(excinfo.value, PermissionError)
    assert "dead-token" not in str(excinfo.value)


@pytest.mark.asyncio
async def test_refresh_access_token_401_without_invalid_grant_keeps_grant(manager, monkeypatch):
    """A 401 that is not ``invalid_grant`` (e.g. ``invalid_client``) does not revoke the grant."""
    fake_response = _FakeResponse(401, json_data={"error": "invalid_client"})
    monkeypatch.setattr(
        manager, "_get_session", AsyncMock(return_value=_FakeSession(fake_response))
    )

    with pytest.raises(RuntimeError) as excinfo:
        await manager.refresh_access_token("dead-token")
    assert not isinstance(excinfo.value, PermissionError)
    assert "invalid_client" in str(excinfo.value)


@pytest.mark.asyncio
async def test_refresh_access_token_5xx_is_transient(manager, monkeypatch):
    """A 5xx without an ``invalid_grant`` body is transient, never a revocation."""
    fake_response = _FakeResponse(503, text_data="service unavailable")
    monkeypatch.setattr(
        manager, "_get_session", AsyncMock(return_value=_FakeSession(fake_response))
    )

    with pytest.raises(RefreshTransientError):
        await manager.refresh_access_token("refresh-tok")


@pytest.mark.asyncio
async def test_refresh_access_token_delegates_to_refresh_request(manager, monkeypatch):
    """No duplicated HTTP logic — `refresh_access_token` is a thin public wrapper."""
    called = {}

    async def fake_refresh_request(refresh_token: str):
        called["refresh_token"] = refresh_token
        return {"access_token": "delegated-tok"}

    monkeypatch.setattr(manager, "_refresh_request", fake_refresh_request)

    result = await manager.refresh_access_token("abc-123")

    assert called["refresh_token"] == "abc-123"
    assert result == {"access_token": "delegated-tok"}
