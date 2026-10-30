"""Regression tests for typed Office 365 refresh failures."""
from unittest.mock import AsyncMock, MagicMock

import aiohttp
import pytest

from parrot.auth.o365_oauth import O365OAuthManager
from parrot.auth.oauth2_base import InvalidGrantError, RefreshTransientError


class _FakeResponse:
    """Minimal aiohttp response substitute for token endpoint responses."""

    def __init__(self, status: int, body: object) -> None:
        self.status = status
        self._body = body

    async def __aenter__(self) -> "_FakeResponse":
        return self

    async def __aexit__(self, *exc_info: object) -> bool:
        return False

    async def json(self, *, content_type: object = None) -> object:
        del content_type
        if isinstance(self._body, str):
            raise ValueError("not JSON")
        return self._body


class _FakeSession:
    """Session substitute which returns a fixed response from ``post``."""

    def __init__(self, response: _FakeResponse) -> None:
        self._response = response

    def post(self, *args: object, **kwargs: object) -> _FakeResponse:
        return self._response


class _FailingSession:
    """Session substitute which fails while initiating a network request."""

    def post(self, *args: object, **kwargs: object) -> _FakeResponse:
        raise aiohttp.ClientConnectionError("connection unavailable")


@pytest.fixture
def manager() -> O365OAuthManager:
    """Build an O365 manager with inert persistence for request-only tests."""
    return O365OAuthManager(
        client_id="client-id",
        client_secret="client-secret",
        redirect_uri="http://localhost/callback",
        redis_client=MagicMock(),
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status", "body", "exc"),
    [
        (400, {"error": "invalid_grant"}, InvalidGrantError),
        (429, {}, RefreshTransientError),
        (503, "<html>", RefreshTransientError),
        (401, {"error": "invalid_client"}, RuntimeError),
        (400, "not-json", RuntimeError),
    ],
)
async def test_o365_refresh_error_classification(
    manager: O365OAuthManager,
    monkeypatch: pytest.MonkeyPatch,
    status: int,
    body: object,
    exc: type[Exception],
) -> None:
    """Map OAuth status and error codes to their required typed outcomes."""
    monkeypatch.setattr(manager, "_get_session", AsyncMock(return_value=_FakeSession(_FakeResponse(status, body))))

    with pytest.raises(exc) as error:
        await manager.refresh_access_token("REFRESH-SECRET")

    assert type(error.value) is exc
    assert "REFRESH-SECRET" not in str(error.value)


@pytest.mark.asyncio
async def test_o365_refresh_network_error_is_transient(
    manager: O365OAuthManager,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Treat request initiation failures as transient without exposing a token."""
    monkeypatch.setattr(manager, "_get_session", AsyncMock(return_value=_FailingSession()))

    with pytest.raises(RefreshTransientError) as error:
        await manager.refresh_access_token("REFRESH-SECRET")

    assert type(error.value) is RefreshTransientError
    assert "REFRESH-SECRET" not in str(error.value)
