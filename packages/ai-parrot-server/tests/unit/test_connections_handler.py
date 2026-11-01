"""Behavioral tests for the principal-level connections handler."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from parrot.handlers.connections import ConnectionsHandler


class _Request:
    """Minimal request carrying session identity and a JSON request body."""

    def __init__(self, body: dict, provider: str = "jira", path: str = "/api/v1/connections/jira") -> None:
        self._body = body
        self.match_info = {"provider": provider}
        self.session = {"user_id": "session-user"}
        self.path = path

    def get(self, key: str, default: object = None) -> object:
        """Return no direct request identity so the session lookup is exercised."""
        return default

    async def json(self) -> dict:
        """Return the configured request JSON body."""
        return self._body


def _handler(request: _Request) -> ConnectionsHandler:
    """Build a handler without aiohttp's routing setup."""
    handler = ConnectionsHandler.__new__(ConnectionsHandler)
    handler._request = request
    return handler


def _unwrap(method):
    """Remove authentication decorators for isolated handler tests."""
    while hasattr(method, "__wrapped__"):
        method = method.__wrapped__
    return method


@pytest.mark.asyncio
async def test_connections_handler_principal_from_session(monkeypatch: pytest.MonkeyPatch) -> None:
    """A body user ID cannot replace the authenticated session principal."""
    response_payload = {"auth_url": "https://auth.example.test", "state": "nonce", "scopes": [], "expires_in": 600}
    service = MagicMock()
    service.start_connect = AsyncMock(return_value=MagicMock(model_dump=MagicMock(return_value=response_payload)))
    monkeypatch.setattr("parrot.handlers.connections.IntegrationsService", lambda: service)

    response = await _unwrap(ConnectionsHandler.post)(
        _handler(_Request({"user_id": "999", "return_origin": "https://app.example.test", "scopes": ["read"]}))
    )

    assert response.status == 200
    assert json.loads(response.body) == response_payload
    service.start_connect.assert_awaited_once()
    assert service.start_connect.await_args.args[:3] == ("session-user", "jira", "https://app.example.test")
    assert service.start_connect.await_args.kwargs["scopes"] == ["read"]


@pytest.mark.asyncio
@pytest.mark.parametrize("method_name", ["get", "delete"])
async def test_start_route_is_post_only(method_name: str, monkeypatch: pytest.MonkeyPatch) -> None:
    """GET/DELETE on /connections/{provider}/start must not read status or disconnect."""
    service = MagicMock()
    service.status = AsyncMock()
    service.disconnect = AsyncMock()
    monkeypatch.setattr("parrot.handlers.connections.IntegrationsService", lambda: service)

    request = _Request({}, path="/api/v1/connections/jira/start")
    response = await _unwrap(getattr(ConnectionsHandler, method_name))(_handler(request))

    assert response.status == 405
    service.status.assert_not_awaited()
    service.disconnect.assert_not_awaited()


@pytest.mark.asyncio
async def test_provider_named_start_is_not_mistaken_for_start_route(monkeypatch: pytest.MonkeyPatch) -> None:
    """A provider literally called 'start' on /connections/start still disconnects normally."""
    service = MagicMock()
    service.disconnect = AsyncMock(return_value=MagicMock(model_dump=MagicMock(return_value={"ok": True})))
    monkeypatch.setattr("parrot.handlers.connections.IntegrationsService", lambda: service)

    request = _Request({}, provider="start", path="/api/v1/connections/start")
    response = await _unwrap(ConnectionsHandler.delete)(_handler(request))

    assert response.status == 200
    service.disconnect.assert_awaited_once()


@pytest.mark.asyncio
async def test_username_is_never_a_principal_id() -> None:
    """A session carrying only a username (no Navigator user id) is unauthenticated (401)."""
    request = _Request({})
    request.session = {"username": "someone@example.test"}

    response = await _unwrap(ConnectionsHandler.get)(_handler(request))

    assert response.status == 401


@pytest.mark.asyncio
async def test_internal_errors_do_not_leak_details(monkeypatch: pytest.MonkeyPatch) -> None:
    """500 responses carry a generic message, not the exception text."""
    service = MagicMock()
    service.disconnect = AsyncMock(side_effect=RuntimeError("secret dsn postgres://u:p@h/db"))
    monkeypatch.setattr("parrot.handlers.connections.IntegrationsService", lambda: service)

    response = await _unwrap(ConnectionsHandler.delete)(_handler(_Request({})))

    assert response.status == 500
    assert json.loads(response.body) == {"error": "internal_error"}
