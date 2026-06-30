"""Unit tests for `O365OAuthManager.refresh_access_token` (FEAT-266)."""
from unittest.mock import AsyncMock, MagicMock

import pytest

from parrot.auth.o365_oauth import O365OAuthManager


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

    async def json(self):
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
    fake_response = _FakeResponse(400, text_data="invalid_grant")
    monkeypatch.setattr(
        manager, "_get_session", AsyncMock(return_value=_FakeSession(fake_response))
    )

    with pytest.raises(PermissionError):
        await manager.refresh_access_token("dead-token")


@pytest.mark.asyncio
async def test_refresh_access_token_401_raises_permissionerror(manager, monkeypatch):
    fake_response = _FakeResponse(401, text_data="unauthorized")
    monkeypatch.setattr(
        manager, "_get_session", AsyncMock(return_value=_FakeSession(fake_response))
    )

    with pytest.raises(PermissionError):
        await manager.refresh_access_token("dead-token")


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
