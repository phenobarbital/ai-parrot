"""CLI routes on ConnectionsHandler (FEAT-774 M3)."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from aiohttp import web

from parrot.auth.oauth2.models import NotConnected
from parrot.auth.principal import Principal
from parrot.handlers.connections import ConnectionsHandler


class _Request:
    """Minimal request carrying session identity and a JSON request body."""

    def __init__(
        self,
        body: dict,
        provider: str = "jira",
        path: str = "/api/v1/connections/jira",
        match_provider: bool = True,
    ) -> None:
        self._body = body
        self.match_info = {"provider": provider} if match_provider else {}
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


def test_whoami_route_ordering() -> None:
    """The literal /me route is registered before the provider wildcard."""
    repo_root = Path(__file__).resolve().parents[4]
    source = (repo_root / "packages/ai-parrot-server/src/parrot/manager/manager.py").read_text()
    me_index = source.index('"/api/v1/connections/me"')
    provider_index = source.index('"/api/v1/connections/{provider}"')
    assert me_index < provider_index

    app = web.Application()
    app.router.add_view("/api/v1/connections/me", ConnectionsHandler)
    app.router.add_view("/api/v1/connections/{provider}", ConnectionsHandler)
    resource = next(resource for resource in app.router.resources() if resource.canonical == "/api/v1/connections/me")
    assert resource.canonical == "/api/v1/connections/me"


@pytest.mark.asyncio
async def test_token_route_success_and_not_connected_409(monkeypatch: pytest.MonkeyPatch) -> None:
    """Token pulls return only the service payload and map missing connections to 409."""
    token_payload = {"provider": "jira", "access_token": "secret", "expires_at": 123.0, "scopes": [], "account_id": ""}
    service = MagicMock()
    service.pull_access_token = AsyncMock(return_value=MagicMock(model_dump=MagicMock(return_value=token_payload)))
    monkeypatch.setattr("parrot.handlers.connections.IntegrationsService", lambda: service)

    request = _Request({}, path="/api/v1/connections/jira/token")
    response = await _unwrap(ConnectionsHandler.post)(_handler(request))

    assert response.status == 200
    assert json.loads(response.body) == token_payload
    service.pull_access_token.assert_awaited_once_with("session-user", "jira", request=request)

    required = MagicMock(model_dump=MagicMock(return_value={"provider": "jira", "message": "not_connected"}))
    service.pull_access_token = AsyncMock(side_effect=NotConnected(required))
    response = await _unwrap(ConnectionsHandler.post)(_handler(_Request({}, path="/api/v1/connections/jira/token")))

    assert response.status == 409
    assert json.loads(response.body) == {"provider": "jira", "message": "not_connected"}


@pytest.mark.asyncio
async def test_token_route_pbac_denied_403(monkeypatch: pytest.MonkeyPatch) -> None:
    """PBAC denial is exposed as a generic forbidden response."""
    service = MagicMock()
    service.pull_access_token = AsyncMock(side_effect=PermissionError("denied"))
    monkeypatch.setattr("parrot.handlers.connections.IntegrationsService", lambda: service)

    response = await _unwrap(ConnectionsHandler.post)(_handler(_Request({}, path="/api/v1/connections/jira/token")))

    assert response.status == 403
    assert json.loads(response.body) == {"error": "forbidden"}


@pytest.mark.asyncio
async def test_complete_route_and_cli_start(monkeypatch: pytest.MonkeyPatch) -> None:
    """Complete validates its payload and CLI starts carry a CLI principal."""
    service = MagicMock()
    service.complete_connect = AsyncMock(
        return_value=MagicMock(model_dump=MagicMock(return_value={"status": "active"}))
    )
    service.start_connect = AsyncMock(return_value=MagicMock(model_dump=MagicMock(return_value={"state": "nonce"})))
    monkeypatch.setattr("parrot.handlers.connections.IntegrationsService", lambda: service)

    response = await _unwrap(ConnectionsHandler.post)(
        _handler(_Request({"state": "nonce"}, path="/api/v1/connections/jira/complete"))
    )
    assert response.status == 400

    request = _Request({"code": "code", "state": "nonce"}, path="/api/v1/connections/jira/complete")
    response = await _unwrap(ConnectionsHandler.post)(_handler(request))
    assert response.status == 200
    service.complete_connect.assert_awaited_once_with(
        "session-user", "jira", code="code", state="nonce", channel="cli", request=request
    )

    response = await _unwrap(ConnectionsHandler.post)(_handler(_Request({"channel": "cli"})))
    assert response.status == 200
    principal = service.start_connect.await_args.kwargs["principal"]
    assert isinstance(principal, Principal)
    assert principal.user_id == "session-user"
    assert service.start_connect.await_args.kwargs["channel"] == "cli"

    response = await _unwrap(ConnectionsHandler.post)(_handler(_Request({"channel": "telegram"})))
    assert response.status == 400
