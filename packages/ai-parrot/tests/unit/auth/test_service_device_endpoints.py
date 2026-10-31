"""Server device-code endpoints (FEAT-774 M3/M8)."""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from parrot.auth.oauth2.service import IntegrationsService
from parrot.auth.principal import Principal
from parrot.handlers.connections import ConnectionsHandler


def _provider() -> MagicMock:
    """Build a provider double with a device-grant manager."""
    provider = MagicMock()
    provider.default_scopes = ["read:jira-work"]
    provider.manager.redis.get = AsyncMock()
    provider.manager._device_key.return_value = "oauth2:jira:device:handle"
    provider.manager.start_device_authorization = AsyncMock()
    provider.manager.complete_device_authorization = AsyncMock()
    return provider


@pytest.mark.asyncio
async def test_device_start_never_returns_device_code(monkeypatch: pytest.MonkeyPatch) -> None:
    """The server returns an opaque handle and public authorization fields only."""
    provider = _provider()
    authorization = SimpleNamespace(
        device_code="provider-secret-device-code",
        user_code="ABCD-EFGH",
        verification_uri="https://idp.example.test/device",
        verification_uri_complete="https://idp.example.test/device?user_code=ABCD-EFGH",
        expires_in=900,
        interval=5,
    )
    provider.manager.start_device_authorization.return_value = ("opaque-handle", authorization)
    monkeypatch.setattr("parrot.auth.oauth2.service.OAuth2ProviderRegistry.get", lambda _self, _provider_id: provider)
    service = IntegrationsService()
    service._check_pbac = AsyncMock(return_value=True)
    principal = Principal(user_id="user-1", channel="cli", channel_user_id="user-1")

    result = await service.device_start("user-1", "jira", principal=principal, request=MagicMock())

    assert result == {
        "handle": "opaque-handle",
        "user_code": "ABCD-EFGH",
        "verification_uri": "https://idp.example.test/device",
        "verification_uri_complete": "https://idp.example.test/device?user_code=ABCD-EFGH",
        "expires_in": 900,
        "interval": 5,
    }
    assert "device_code" not in result
    provider.manager.start_device_authorization.assert_awaited_once_with(principal, scopes=None)


@pytest.mark.asyncio
async def test_device_poll_owner_check(monkeypatch: pytest.MonkeyPatch) -> None:
    """A device handle can only be polled by the principal that started it."""
    provider = _provider()
    provider.manager.redis.get.return_value = b'{"principal": {"user_id": "user-2"}}'
    monkeypatch.setattr("parrot.auth.oauth2.service.OAuth2ProviderRegistry.get", lambda _self, _provider_id: provider)

    with pytest.raises(PermissionError, match="does not belong"):
        await IntegrationsService().device_poll("user-1", "jira", handle="opaque-handle")

    provider.manager.complete_device_authorization.assert_not_awaited()


@pytest.mark.asyncio
async def test_device_poll_completed_persists_without_token(monkeypatch: pytest.MonkeyPatch) -> None:
    """Completed grants persist through the CLI channel without exposing the token set."""
    provider = _provider()
    provider.manager.redis.get.return_value = '{"principal": {"user_id": "user-1"}}'
    token_set = SimpleNamespace(access_token="secret")
    provider.manager.complete_device_authorization.return_value = {
        "status": "completed",
        "token_set": token_set,
        "account_id": "account-1",
    }
    monkeypatch.setattr("parrot.auth.oauth2.service.OAuth2ProviderRegistry.get", lambda _self, _provider_id: provider)
    service = IntegrationsService()
    service.persist_credential = AsyncMock()

    result = await service.device_poll("user-1", "jira", handle="opaque-handle")

    assert result == {"status": "completed", "account_id": "account-1"}
    assert "token_set" not in result
    service.persist_credential.assert_awaited_once_with("user-1", "jira", token_set, channel="cli")


class _Request:
    """Minimal authenticated request for the device route handler tests."""

    def __init__(self, body: dict, path: str) -> None:
        self._body = body
        self.match_info = {"provider": "jira"}
        self.path = path
        self.session = {"user_id": "session-user"}

    def get(self, key: str, default: object = None) -> object:
        """Return no direct identity so the session identity path is exercised."""
        return default

    async def json(self) -> dict:
        """Return the configured request body."""
        return self._body


def _handler(request: _Request) -> ConnectionsHandler:
    """Build a handler without aiohttp routing setup."""
    handler = ConnectionsHandler.__new__(ConnectionsHandler)
    handler._request = request
    return handler


def _unwrap(method):
    """Remove authentication decorators for isolated handler tests."""
    while hasattr(method, "__wrapped__"):
        method = method.__wrapped__
    return method


@pytest.mark.asyncio
async def test_device_start_handler_builds_cli_principal(monkeypatch: pytest.MonkeyPatch) -> None:
    """The start route binds the authenticated session user to a CLI principal."""
    service = MagicMock()
    service.device_start = AsyncMock(return_value={"handle": "opaque-handle"})
    monkeypatch.setattr("parrot.handlers.connections.IntegrationsService", lambda: service)

    response = await _unwrap(ConnectionsHandler.post)(
        _handler(_Request({"scopes": ["read:jira-work"]}, "/api/v1/connections/jira/device/start"))
    )

    assert response.status == 200
    assert json.loads(response.body) == {"handle": "opaque-handle"}
    call = service.device_start.await_args
    assert call.args == ("session-user", "jira")
    assert call.kwargs["principal"] == Principal(user_id="session-user", channel="cli", channel_user_id="session-user")
    assert call.kwargs["scopes"] == ["read:jira-work"]


@pytest.mark.asyncio
async def test_device_poll_handler_requires_handle(monkeypatch: pytest.MonkeyPatch) -> None:
    """The poll route rejects missing or empty handles before calling the service."""
    service = MagicMock()
    service.device_poll = AsyncMock()
    monkeypatch.setattr("parrot.handlers.connections.IntegrationsService", lambda: service)

    response = await _unwrap(ConnectionsHandler.post)(_handler(_Request({}, "/api/v1/connections/jira/device/poll")))

    assert response.status == 400
    assert json.loads(response.body) == {"error": "handle is required"}
    service.device_poll.assert_not_awaited()
