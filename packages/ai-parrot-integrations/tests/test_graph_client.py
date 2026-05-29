"""
Unit tests for the Teams HITL Graph client (TASK-002 / FEAT-205).

All tests use a stubbed aiohttp session (via unittest.mock) to avoid
making real HTTP calls.  Three scenarios are covered:
  - Resolve by UPN (direct hit)
  - Mail-filter fallback on 404
  - Generic failure returns None
  - get_user_manager happy path
"""
from __future__ import annotations

import json
from typing import Any, Dict
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from parrot.integrations.msteams.graph import GraphClient, ResolvedTeamsUser


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def graph_client() -> GraphClient:
    """Return a GraphClient with dummy credentials."""
    return GraphClient(
        client_id="test-client-id",
        client_secret="test-secret",
        tenant_id="test-tenant-id",
    )


def _make_response(status: int, body: Any) -> MagicMock:
    """Build a mock aiohttp response.

    Args:
        status: HTTP status code.
        body: JSON body (dict) or text body (str).

    Returns:
        An async-context-manager mock for use with ClientSession.
    """
    resp = MagicMock()
    resp.status = status
    if isinstance(body, (dict, list)):
        resp.json = AsyncMock(return_value=body)
        resp.text = AsyncMock(return_value=json.dumps(body))
    else:
        resp.json = AsyncMock(return_value={})
        resp.text = AsyncMock(return_value=str(body))

    # Support async context manager (__aenter__ / __aexit__)
    resp.__aenter__ = AsyncMock(return_value=resp)
    resp.__aexit__ = AsyncMock(return_value=False)
    return resp


def _make_session(*responses: MagicMock) -> MagicMock:
    """Build a mock aiohttp.ClientSession returning responses in order.

    Args:
        *responses: Responses to return from get/post, in call order.

    Returns:
        A mock session that can be used as an async context manager.
    """
    session = MagicMock()
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=False)

    # Each get/post call returns successive responses
    session.post = MagicMock(side_effect=list(responses))
    session.get = MagicMock(side_effect=list(responses))
    return session


# ── Token acquisition helper ──────────────────────────────────────────────────

def _patch_token(client: GraphClient, token: str = "fake-token") -> None:
    """Inject a pre-cached token so tests skip real token acquisition."""
    import time
    client._token = token
    client._token_expiry = time.monotonic() + 3600


# ── Tests ─────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_resolve_by_upn(graph_client: GraphClient) -> None:
    """email == UPN → /users/{upn} returns ResolvedTeamsUser directly."""
    _patch_token(graph_client)

    user_payload = {
        "id": "aad-object-id-001",
        "userPrincipalName": "manager@contoso.com",
        "mail": "manager@contoso.com",
    }
    direct_resp = _make_response(200, user_payload)
    session = _make_session(direct_resp)

    with patch("aiohttp.ClientSession", return_value=session):
        result = await graph_client.get_user_by_email("manager@contoso.com")

    assert result is not None
    assert isinstance(result, ResolvedTeamsUser)
    assert result.aad_object_id == "aad-object-id-001"
    assert result.upn == "manager@contoso.com"
    assert result.email == "manager@contoso.com"
    assert result.service_url is None


@pytest.mark.asyncio
async def test_resolve_mail_filter_fallback_on_404(graph_client: GraphClient) -> None:
    """email != UPN → /users/{upn} returns 404 → mail-filter fallback resolves."""
    _patch_token(graph_client)

    # First call (direct): 404
    not_found = _make_response(404, {"error": {"code": "Request_ResourceNotFound"}})

    # Second call (mail filter): 200 with value list
    user_payload = {
        "id": "aad-object-id-002",
        "userPrincipalName": "mgr-internal@contoso.onmicrosoft.com",
        "mail": "manager@external.com",
    }
    filter_resp = _make_response(200, {"value": [user_payload]})

    # Mock two separate ClientSession usages
    sessions = [
        _make_session(not_found),
        _make_session(filter_resp),
    ]

    call_count = 0

    class _FakeSession:
        def __init__(self):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        def get(self, url, **kwargs):
            nonlocal call_count
            idx = call_count
            call_count += 1
            if idx == 0:
                return not_found
            return filter_resp

    with patch("aiohttp.ClientSession", return_value=_FakeSession()):
        result = await graph_client.get_user_by_email("manager@external.com")

    assert result is not None
    assert result.aad_object_id == "aad-object-id-002"
    assert result.email == "manager@external.com"


@pytest.mark.asyncio
async def test_resolve_failure_returns_none(graph_client: GraphClient) -> None:
    """Any Graph error → resolution returns None (never raises)."""
    _patch_token(graph_client)

    error_resp = _make_response(500, "Internal Server Error")
    filter_error_resp = _make_response(500, "Internal Server Error")

    call_count = 0

    class _FakeSession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        def get(self, url, **kwargs):
            nonlocal call_count
            idx = call_count
            call_count += 1
            return error_resp if idx == 0 else filter_error_resp

    with patch("aiohttp.ClientSession", return_value=_FakeSession()):
        result = await graph_client.get_user_by_email("nobody@contoso.com")

    assert result is None


@pytest.mark.asyncio
async def test_resolve_failure_on_empty_filter_returns_none(graph_client: GraphClient) -> None:
    """UPN 404 + empty mail-filter result → None."""
    _patch_token(graph_client)

    not_found = _make_response(404, {})
    empty_filter = _make_response(200, {"value": []})

    call_count = 0

    class _FakeSession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        def get(self, url, **kwargs):
            nonlocal call_count
            idx = call_count
            call_count += 1
            return not_found if idx == 0 else empty_filter

    with patch("aiohttp.ClientSession", return_value=_FakeSession()):
        result = await graph_client.get_user_by_email("ghost@contoso.com")

    assert result is None


@pytest.mark.asyncio
async def test_get_user_manager(graph_client: GraphClient) -> None:
    """get_user_manager returns the raw Graph dict on success."""
    _patch_token(graph_client)

    manager_payload = {
        "id": "mgr-aad-id",
        "userPrincipalName": "boss@contoso.com",
        "mail": "boss@contoso.com",
    }
    mgr_resp = _make_response(200, manager_payload)

    class _FakeSession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        def get(self, url, **kwargs):
            return mgr_resp

    with patch("aiohttp.ClientSession", return_value=_FakeSession()):
        result = await graph_client.get_user_manager("employee@contoso.com")

    assert result is not None
    assert result["id"] == "mgr-aad-id"


@pytest.mark.asyncio
async def test_get_user_manager_not_found_returns_none(graph_client: GraphClient) -> None:
    """get_user_manager on a user with no manager returns None."""
    _patch_token(graph_client)

    not_found = _make_response(404, {"error": {"code": "Request_ResourceNotFound"}})

    class _FakeSession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        def get(self, url, **kwargs):
            return not_found

    with patch("aiohttp.ClientSession", return_value=_FakeSession()):
        result = await graph_client.get_user_manager("toplevel@contoso.com")

    assert result is None


@pytest.mark.asyncio
async def test_token_acquisition_failure_returns_none(graph_client: GraphClient) -> None:
    """If the token call fails, get_user_by_email returns None."""
    token_resp = _make_response(401, "Unauthorized")

    class _FakeSession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        def post(self, url, **kwargs):
            return token_resp

    with patch("aiohttp.ClientSession", return_value=_FakeSession()):
        result = await graph_client.get_user_by_email("someone@contoso.com")

    assert result is None
