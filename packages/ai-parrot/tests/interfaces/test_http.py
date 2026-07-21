"""Unit tests for parrot.interfaces.http.HTTPService.session().

Regression coverage for a bug where call-time ``headers=`` passed to
``session()`` were silently discarded before being merged into the
outgoing request (FEAT-304 code review). These tests intentionally patch
``httpx.AsyncClient`` itself — NOT ``HTTPService.session`` — so they
exercise the real header-merge logic inside ``session()`` rather than
bypassing it.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from parrot.interfaces.http import HTTPService


class _FakeResponse:
    """Minimal stand-in for an httpx.Response, enough for process_response
    to be bypassed entirely in these tests (we patch process_response)."""

    status_code = 200
    headers: dict = {"Content-Type": "application/json"}
    text = "{}"


class _FakeAsyncClient:
    """Captures the headers httpx.AsyncClient(...) was constructed with."""

    captured: dict = {}

    def __init__(self, **kwargs):
        _FakeAsyncClient.captured["init_kwargs"] = kwargs

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def request(self, **kwargs):
        _FakeAsyncClient.captured["request_kwargs"] = kwargs
        return _FakeResponse()


@pytest.fixture
def http_service():
    return HTTPService(accept="application/json")


@pytest.mark.asyncio
async def test_session_forwards_call_time_headers_to_the_request(http_service):
    """Regression test: headers passed to session() must reach httpx.

    Before the fix, `session()` did `headers = self.headers` before ever
    reading the `headers` parameter, silently discarding whatever the
    caller passed in (e.g. an Authorization header built per-call) and
    merging `self.headers` with itself as a no-op. That broke any
    composed-HTTPService caller (e.g. LeadIQToolkit) that relies on
    passing auth headers at call time rather than mutating `self.headers`
    up front.
    """
    _FakeAsyncClient.captured.clear()
    call_headers = {
        "Authorization": "Basic Zm9vOg==",
        "apollo-require-preflight": "true",
    }

    with patch("httpx.AsyncClient", _FakeAsyncClient):
        with patch.object(
            HTTPService, "process_response", AsyncMock(return_value=({}, None))
        ):
            await http_service.session(
                url="https://api.example.com/graphql",
                method="post",
                data="{}",
                headers=call_headers,
            )

    sent_headers = _FakeAsyncClient.captured["init_kwargs"]["headers"]
    assert sent_headers["Authorization"] == "Basic Zm9vOg=="
    assert sent_headers["apollo-require-preflight"] == "true"
    # Instance defaults (e.g. Accept, User-Agent) must still be present —
    # call-time headers are merged on top, not a full replacement.
    assert "User-Agent" in sent_headers


@pytest.mark.asyncio
async def test_session_call_time_headers_override_instance_defaults(http_service):
    """Call-time headers win over instance defaults on key collisions."""
    _FakeAsyncClient.captured.clear()
    http_service.headers["X-Custom"] = "instance-value"

    with patch("httpx.AsyncClient", _FakeAsyncClient):
        with patch.object(
            HTTPService, "process_response", AsyncMock(return_value=({}, None))
        ):
            await http_service.session(
                url="https://api.example.com/graphql",
                method="post",
                headers={"X-Custom": "call-time-value"},
            )

    sent_headers = _FakeAsyncClient.captured["init_kwargs"]["headers"]
    assert sent_headers["X-Custom"] == "call-time-value"


@pytest.mark.asyncio
async def test_session_falls_back_to_instance_headers_when_none_passed(
    http_service,
):
    """No call-time headers -> instance defaults are used unchanged."""
    _FakeAsyncClient.captured.clear()

    with patch("httpx.AsyncClient", _FakeAsyncClient):
        with patch.object(
            HTTPService, "process_response", AsyncMock(return_value=({}, None))
        ):
            await http_service.session(
                url="https://api.example.com/graphql", method="get"
            )

    sent_headers = _FakeAsyncClient.captured["init_kwargs"]["headers"]
    assert sent_headers == http_service.headers
