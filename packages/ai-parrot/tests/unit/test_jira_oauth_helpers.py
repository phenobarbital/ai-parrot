"""Tests for module-level 3LO helpers (FEAT-696 M2)."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest

from parrot.auth.jira_oauth import (
    ACCESSIBLE_RESOURCES_URL,
    TOKEN_URL,
    build_authorization_url,
    exchange_code,
    fetch_accessible_resources,
    fetch_myself,
    refresh_access_token,
)


class _Resp:
    def __init__(self, status: int, payload: Any = None, text: str = "") -> None:
        self.status = status
        self._payload = payload
        self._text = text

    async def json(self) -> Any:
        return self._payload

    async def text(self) -> str:
        return self._text

    async def __aenter__(self) -> "_Resp":
        return self

    async def __aexit__(self, *exc: Any) -> None:
        return None


def _session(resp: _Resp) -> MagicMock:
    session = MagicMock()
    session.post = MagicMock(return_value=resp)
    session.get = MagicMock(return_value=resp)
    return session


class TestBuildAuthorizationUrl:
    def test_contains_required_params(self):
        url = build_authorization_url("cid", "http://localhost/cb", "state123")
        assert "client_id=cid" in url
        assert "state=state123" in url
        assert "prompt=consent" in url
        assert "response_type=code" in url

    def test_custom_scopes(self):
        url = build_authorization_url("cid", "http://x", "s", scopes=["read:jira-work"])
        assert "read%3Ajira-work" in url


class TestExchangeCode:
    async def test_posts_payload(self):
        session = _session(_Resp(200, {"access_token": "a"}))
        out = await exchange_code(session, client_id="c", client_secret="s", code="k", redirect_uri="http://r")
        assert out == {"access_token": "a"}
        args, kwargs = session.post.call_args
        assert args[0] == TOKEN_URL
        assert kwargs["data"]["grant_type"] == "authorization_code"
        assert kwargs["data"]["code"] == "k"

    async def test_error_raises(self):
        session = _session(_Resp(400, text="bad"))
        with pytest.raises(ValueError, match="Token exchange failed with status 400"):
            await exchange_code(session, client_id="c", client_secret="s", code="k", redirect_uri="r")


class TestRefreshAccessToken:
    async def test_posts_payload(self):
        session = _session(_Resp(200, {"access_token": "n"}))
        out = await refresh_access_token(session, client_id="c", client_secret="s", refresh_token="rt")
        assert out["access_token"] == "n"
        _, kwargs = session.post.call_args
        assert kwargs["data"]["grant_type"] == "refresh_token"
        assert kwargs["data"]["refresh_token"] == "rt"

    async def test_error_raises(self):
        session = _session(_Resp(401, text="no"))
        with pytest.raises(ValueError, match="Token refresh failed with status 401"):
            await refresh_access_token(session, client_id="c", client_secret="s", refresh_token="rt")


class TestFetchAccessibleResources:
    async def test_returns_list(self):
        session = _session(_Resp(200, [{"id": "cloud"}]))
        out = await fetch_accessible_resources(session, "tok")
        assert out == [{"id": "cloud"}]
        args, kwargs = session.get.call_args
        assert args[0] == ACCESSIBLE_RESOURCES_URL
        assert kwargs["headers"]["Authorization"] == "Bearer tok"

    async def test_non_list_raises(self):
        session = _session(_Resp(200, {"x": 1}))
        with pytest.raises(ValueError, match="non-list"):
            await fetch_accessible_resources(session, "tok")

    async def test_error_raises(self):
        session = _session(_Resp(500, text="boom"))
        with pytest.raises(ValueError, match="status 500"):
            await fetch_accessible_resources(session, "tok")


class TestFetchMyself:
    async def test_returns_profile(self):
        session = _session(_Resp(200, {"accountId": "a"}))
        out = await fetch_myself(session, "tok", "cloud1")
        assert out == {"accountId": "a"}
        assert "cloud1/rest/api/3/myself" in session.get.call_args[0][0]

    async def test_error_raises(self):
        session = _session(_Resp(403, text="nope"))
        with pytest.raises(ValueError, match="/myself failed with status 403"):
            await fetch_myself(session, "tok", "cloud1")
