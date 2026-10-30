"""Behavioral tests for the principal-level connections handler."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from parrot.handlers.connections import ConnectionsHandler


class _Request:
    """Minimal request carrying session identity and a JSON request body."""

    def __init__(self, body: dict, provider: str = "jira") -> None:
        self._body = body
        self.match_info = {"provider": provider}
        self.session = {"user_id": "session-user"}

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
