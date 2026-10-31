"""Tests for ChannelLinksHandler (FEAT-777 M2)."""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from parrot.auth.channel_link import ChannelLinkClaim
from parrot.handlers.channel_links import ChannelLinksHandler


class _Request:
    """Minimal request carrying session identity, route data, and a JSON body."""

    def __init__(
        self,
        body: object,
        *,
        nonce: str = "nonce",
        path: str = "/api/v1/channel-links/nonce/confirm",
        user_id: str = "1042",
        issuer: object | None = None,
        authdb: object | None = object(),
        content_type: str = "application/json",
    ) -> None:
        self._body = body
        self.content_type = content_type
        self.match_info = {"nonce": nonce}
        self.path = path
        self.session = {"user_id": user_id}
        self.app = {"channel_link_issuer": issuer, "authdb": authdb}

    def get(self, key: str, default: object = None) -> object:
        """Return no direct request identity so session lookup is exercised."""
        return default

    async def json(self) -> object:
        """Return the configured request body."""
        return self._body


def _handler(request: _Request) -> ChannelLinksHandler:
    """Build a handler without aiohttp routing setup."""
    handler = ChannelLinksHandler.__new__(ChannelLinksHandler)
    handler._request = request
    return handler


def _unwrap(method):
    """Remove authentication decorators for isolated handler tests."""
    while hasattr(method, "__wrapped__"):
        method = method.__wrapped__
    return method


def _claim(channel_user_id: str = "T01:U02", **extra: str) -> ChannelLinkClaim:
    """Build a valid Slack channel-link claim."""
    return ChannelLinkClaim(
        channel="slack",
        channel_user_id=channel_user_id,
        extra={"team_id": "T01", "slack_user_id": "U02", **extra},
        issued_at=0,
    )


@pytest.mark.asyncio
async def test_channel_link_preview_read_only() -> None:
    """Preview shows both identities, never consumes, and never writes identity."""
    issuer = MagicMock()
    issuer.peek = AsyncMock(return_value=_claim())
    issuer.consume = AsyncMock()
    request = _Request({}, path="/api/v1/channel-links/nonce", issuer=issuer)

    response_one = await _unwrap(ChannelLinksHandler.get)(_handler(request))
    response_two = await _unwrap(ChannelLinksHandler.get)(_handler(request))

    assert response_one.status == 200
    assert json.loads(response_one.body) == {
        "channel": "slack",
        "channel_user_id": "T01:U02",
        "team_id": "T01",
        "nav_user_id": "1042",
    }
    assert response_one.headers["Cache-Control"] == "no-store"
    assert response_two.status == 200
    assert issuer.peek.await_count == 2
    issuer.consume.assert_not_awaited()


@pytest.mark.asyncio
async def test_channel_link_confirm_uses_session_principal(monkeypatch: pytest.MonkeyPatch) -> None:
    """Confirm validates the body before consuming and claims only the numeric session principal."""
    issuer = MagicMock()
    issuer.consume = AsyncMock(side_effect=[_claim(), None])
    claim_service = MagicMock()
    claim_service.claim_channel_identity = AsyncMock(return_value=SimpleNamespace(status="claimed"))
    monkeypatch.setattr("parrot.handlers.channel_links.IdentityMappingService", lambda _: claim_service)

    override_request = _Request({"confirm": True, "nav_user_id": "999"}, issuer=issuer)
    response = await _unwrap(ChannelLinksHandler.post)(_handler(override_request))
    assert response.status == 400
    issuer.consume.assert_not_awaited()

    response = await _unwrap(ChannelLinksHandler.post)(_handler(_Request({"confirm": True}, issuer=issuer)))
    assert response.status == 200
    assert json.loads(response.body) == {"channel": "slack", "linked": True}
    claim_service.claim_channel_identity.assert_awaited_once_with(
        nav_user_id="1042",
        auth_provider="slack",
        provider_user_id="T01:U02",
        auth_data={"team_id": "T01", "slack_user_id": "U02"},
    )

    spent = await _unwrap(ChannelLinksHandler.post)(_handler(_Request({"confirm": True}, issuer=issuer)))
    assert spent.status == 410
    non_numeric = _Request({"confirm": True}, issuer=issuer, user_id="not-numeric")
    forbidden = await _unwrap(ChannelLinksHandler.post)(_handler(non_numeric))
    assert forbidden.status == 403
    assert issuer.consume.await_count == 2


@pytest.mark.asyncio
async def test_channel_link_confirm_conflict_and_db_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    """Conflicts hide owner details and database failures never report success."""
    issuer = MagicMock()
    issuer.consume = AsyncMock(side_effect=[_claim(), _claim()])
    claim_service = MagicMock()
    claim_service.claim_channel_identity = AsyncMock(
        side_effect=[SimpleNamespace(status="conflict"), RuntimeError("db")]
    )
    monkeypatch.setattr("parrot.handlers.channel_links.IdentityMappingService", lambda _: claim_service)

    conflict = await _unwrap(ChannelLinksHandler.post)(_handler(_Request({"confirm": True}, issuer=issuer)))
    assert conflict.status == 409
    assert json.loads(conflict.body) == {"error": "already_linked"}
    assert "owner" not in conflict.text

    failure = await _unwrap(ChannelLinksHandler.post)(_handler(_Request({"confirm": True}, issuer=issuer)))
    assert failure.status == 500
    assert json.loads(failure.body) == {"error": "internal_error"}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "claim",
    [
        ChannelLinkClaim(
            channel="telegram", channel_user_id="T01:U02", extra={"team_id": "T01", "slack_user_id": "U02"}, issued_at=0
        ),
        ChannelLinkClaim(
            channel="slack",
            channel_user_id="T01:U02:extra",
            extra={"team_id": "T01", "slack_user_id": "U02"},
            issued_at=0,
        ),
    ],
)
async def test_channel_link_rejects_non_slack_claim(claim: ChannelLinkClaim) -> None:
    """Malformed or non-Slack claims are rejected after consumption and never claimed."""
    issuer = MagicMock()
    issuer.consume = AsyncMock(return_value=claim)
    request = _Request({"confirm": True}, issuer=issuer)
    response = await _unwrap(ChannelLinksHandler.post)(_handler(request))

    assert response.status == 400
    issuer.consume.assert_awaited_once()


@pytest.mark.asyncio
async def test_channel_link_confirm_rejects_non_json_content_type() -> None:
    """A CORS-simple (text/plain) POST is refused before the nonce is touched (CSRF defence)."""
    issuer = SimpleNamespace(consume=AsyncMock())
    request = _Request({"confirm": True}, issuer=issuer, content_type="text/plain")
    response = await _unwrap(ChannelLinksHandler.post)(_handler(request))
    assert response.status == 415
    issuer.consume.assert_not_awaited()
