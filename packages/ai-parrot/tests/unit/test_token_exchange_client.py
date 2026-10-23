"""Tests for the Navigator token-exchange client."""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional
from unittest.mock import patch

import aiohttp
import pytest

from parrot.auth.token_exchange import (
    REASON_BACKEND_NOT_LOADED,
    REASON_EXPIRED,
    REASON_INVALID_TOKEN,
    REASON_TRANSPORT,
    REASON_USER_NOT_FOUND,
    ExchangeResult,
    TokenExchangeClient,
)


class FakeResponse:
    """Minimal aiohttp response context manager for client tests."""

    def __init__(self, status: int, *, body: Optional[Dict[str, Any]] = None, text: str = "") -> None:
        self.status = status
        self._body = body or {}
        self._text = text

    async def __aenter__(self) -> "FakeResponse":
        """Enter the fake response context."""
        return self

    async def __aexit__(self, *args: object) -> None:
        """Exit the fake response context."""

    async def json(self) -> Dict[str, Any]:
        """Return the configured JSON body."""
        return self._body

    async def text(self) -> str:
        """Return the configured text body."""
        return self._text


class FakeSession:
    """Capture one aiohttp POST and return a configured response."""

    def __init__(self, response: FakeResponse) -> None:
        self.response = response
        self.post_kwargs: Dict[str, Any] = {}
        self.post_url: Optional[str] = None

    async def __aenter__(self) -> "FakeSession":
        """Enter the fake session context."""
        return self

    async def __aexit__(self, *args: object) -> None:
        """Exit the fake session context."""

    def post(self, url: str, **kwargs: Any) -> FakeResponse:
        """Capture POST arguments and return the fake response."""
        self.post_url = url
        self.post_kwargs = kwargs
        return self.response


def patch_client_session(fake_session: FakeSession):
    """Patch aiohttp to return a test session.

    Args:
        fake_session: Session to return from ``aiohttp.ClientSession``.

    Returns:
        A mock patch context manager.
    """
    return patch("parrot.auth.token_exchange.aiohttp.ClientSession", return_value=fake_session)


class TestExchangeRequest:
    """Request-shape tests."""

    async def test_sends_token_exchange_header_and_maps_success(self) -> None:
        """The POST carries the exchange contract and maps the real body shape."""
        response_body = {
            "token": "navigator-session",
            "session": {
                "user_id": 35,
                "email": "user@example.com",
                "first_name": "Example",
                "last_name": "User",
                "provider_user_id": "entra-oid",
                "external_expires_at": "2026-10-22T17:42:01+00:00",
            },
            "user_id": 35,
            "name": "Example User",
            "email": "user@example.com",
            "provider_user_id": "entra-oid",
            "external_expires_at": "2026-10-22T17:42:01+00:00",
        }
        session = FakeSession(FakeResponse(200, body=response_body))

        with patch_client_session(session):
            result = await TokenExchangeClient("https://navigator.example/api/v1/login/").exchange("provider-token")

        assert session.post_url == "https://navigator.example/api/v1/login"
        assert session.post_kwargs["headers"]["X-Auth-Method"] == "TokenExchangeAuth"
        assert session.post_kwargs["json"] == {
            "provider": "azure",
            "token": "provider-token",
            "token_type": "Bearer",
        }
        assert result == ExchangeResult(
            ok=True,
            nav_user_id="35",
            session_token="navigator-session",
            email="user@example.com",
            display_name="Example User",
            provider_user_id="entra-oid",
            expires_at="2026-10-22T17:42:01+00:00",
            raw=response_body,
        )

    @pytest.mark.parametrize("prefer_id_token", [True, False])
    async def test_omits_id_token_when_absent(self, prefer_id_token: bool) -> None:
        """id_token is absent from the body, not null."""
        session = FakeSession(FakeResponse(200, body={}))

        with patch_client_session(session):
            await TokenExchangeClient("https://navigator.example/login", prefer_id_token=prefer_id_token).exchange(
                "provider-token"
            )

        assert "id_token" not in session.post_kwargs["json"]

    @pytest.mark.parametrize(
        ("prefer_id_token", "expected_present"),
        [(True, True), (False, False)],
    )
    async def test_prefer_id_token_controls_payload(self, prefer_id_token: bool, expected_present: bool) -> None:
        """An available ID token is sent only when the preference is enabled."""
        session = FakeSession(FakeResponse(200, body={}))

        with patch_client_session(session):
            await TokenExchangeClient("https://navigator.example/login", prefer_id_token=prefer_id_token).exchange(
                "provider-token", id_token="provider-id-token"
            )

        assert (session.post_kwargs["json"].get("id_token") == "provider-id-token") is expected_present


class TestFailureClassification:
    """Stable failure-reason tests."""

    def test_unacceptable_auth_method_maps_to_backend_not_loaded(self) -> None:
        """The live-deployment failure is an operator error, not a bad token."""
        result = TokenExchangeClient._classify_failure(
            401,
            '{"reason": "Unacceptable Auth Method: TokenExchangeAuth"}',
        )

        assert result == ExchangeResult(ok=False, reason=REASON_BACKEND_NOT_LOADED)

    @pytest.mark.parametrize("body", ['{"reason": "user_not_found"}', "Navigator user not found"])
    def test_missing_user_maps_to_user_not_found(self, body: str) -> None:
        """The exchange never provisions, so this is its own reason."""
        result = TokenExchangeClient._classify_failure(401, body)

        assert result == ExchangeResult(ok=False, reason=REASON_USER_NOT_FOUND)

    @pytest.mark.parametrize(
        ("body", "reason"),
        [("External token expired", REASON_EXPIRED), ("Graph rejected token", REASON_INVALID_TOKEN)],
    )
    def test_other_token_failures_are_distinguished(self, body: str, reason: str) -> None:
        """Expired tokens remain distinct and unknown failures are invalid tokens."""
        assert TokenExchangeClient._classify_failure(401, body).reason == reason

    async def test_client_error_maps_to_transport_error(self, caplog: pytest.LogCaptureFixture) -> None:
        """aiohttp transport failures neither escape nor leak exception text."""
        token = "secret-token-in-error"
        with caplog.at_level(logging.ERROR):
            with patch(
                "parrot.auth.token_exchange.aiohttp.ClientSession",
                side_effect=aiohttp.ClientConnectionError(token),
            ):
                result = await TokenExchangeClient("https://navigator.example/login").exchange(token)

        assert result == ExchangeResult(ok=False, reason=REASON_TRANSPORT)
        assert token not in caplog.text

    async def test_never_logs_the_token(self, caplog: pytest.LogCaptureFixture) -> None:
        """No log record contains either provider token value."""
        access_token = "secret-access-token"
        id_token = "secret-id-token"
        session = FakeSession(FakeResponse(401, text='{"reason": "invalid_token"}'))

        with caplog.at_level(logging.DEBUG), patch_client_session(session):
            await TokenExchangeClient("https://navigator.example/login").exchange(
                access_token,
                id_token=id_token,
            )

        assert access_token not in caplog.text
        assert id_token not in caplog.text
