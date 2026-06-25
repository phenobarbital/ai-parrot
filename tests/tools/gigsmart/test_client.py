"""Unit tests for GigSmartClient — aiohttp-based GraphQL transport."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch, PropertyMock

import pytest

from parrot_tools.interfaces.gigsmart.client import GigSmartClient
from parrot_tools.interfaces.gigsmart.config import GigSmartConfig
from parrot_tools.interfaces.gigsmart.exceptions import (
    GigSmartAuthError,
    GigSmartConflictError,
    GigSmartGraphQLError,
    GigSmartNotFoundError,
    GigSmartRateLimitError,
    GigSmartTransportError,
    GigSmartValidationError,
)


@pytest.fixture
def config():
    """GigSmartConfig with test credentials."""
    return GigSmartConfig(
        client_id="test",
        client_secret="secret",
        max_concurrent_requests=8,
    )


def _make_response(status: int = 200, body: dict | None = None):
    """Build a mock aiohttp response."""
    mock_resp = AsyncMock()
    mock_resp.status = status
    mock_resp.headers = {}
    body = body or {"data": {}}
    mock_resp.json = AsyncMock(return_value=body)
    mock_resp.text = AsyncMock(return_value=json.dumps(body))
    mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
    mock_resp.__aexit__ = AsyncMock(return_value=False)
    return mock_resp


def _make_session(response):
    """Build a mock aiohttp.ClientSession whose post() returns *response*."""
    session = MagicMock()
    session.closed = False
    session.close = AsyncMock()
    session.post = MagicMock(return_value=response)
    return session


# ---------------------------------------------------------------------------
# Basic execute
# ---------------------------------------------------------------------------

class TestExecute:
    """Tests for GigSmartClient.execute()."""

    @pytest.mark.asyncio
    async def test_execute_returns_data(self, config):
        """execute() returns the data dict from a successful response."""
        client = GigSmartClient(config)
        response_body = {"data": {"viewer": {"id": "org-123"}}}

        with patch.object(client, "_auth") as mock_auth, \
             patch.object(client, "_ensure_session") as mock_session_fn:
            mock_auth.build_headers = AsyncMock(return_value={"Authorization": "Bearer tok"})
            session = _make_session(_make_response(200, response_body))
            mock_session_fn.return_value = session

            result = await client.execute("query { viewer { id } }")
            assert result == {"viewer": {"id": "org-123"}}

    @pytest.mark.asyncio
    async def test_error_classification_unauthenticated(self, config):
        """extensions.code=UNAUTHENTICATED raises GigSmartAuthError."""
        client = GigSmartClient(config)
        error_body = {
            "errors": [{"message": "Not authenticated",
                        "extensions": {"code": "UNAUTHENTICATED"}}],
            "data": None,
        }

        with patch.object(client, "_auth") as mock_auth, \
             patch.object(client, "_ensure_session") as mock_session_fn:
            mock_auth.build_headers = AsyncMock(return_value={"Authorization": "Bearer tok"})
            session = _make_session(_make_response(200, error_body))
            mock_session_fn.return_value = session

            with pytest.raises(GigSmartAuthError):
                await client.execute("query { viewer { id } }")

    @pytest.mark.asyncio
    async def test_error_classification_forbidden(self, config):
        """extensions.code=FORBIDDEN raises GigSmartAuthError."""
        client = GigSmartClient(config)
        error_body = {
            "errors": [{"message": "Forbidden",
                        "extensions": {"code": "FORBIDDEN"}}],
            "data": None,
        }

        with patch.object(client, "_auth") as mock_auth, \
             patch.object(client, "_ensure_session") as mock_session_fn:
            mock_auth.build_headers = AsyncMock(return_value={"Authorization": "Bearer tok"})
            session = _make_session(_make_response(200, error_body))
            mock_session_fn.return_value = session

            with pytest.raises(GigSmartAuthError):
                await client.execute("query { viewer { id } }")

    @pytest.mark.asyncio
    async def test_error_classification_not_found(self, config):
        """extensions.code=NOT_FOUND raises GigSmartNotFoundError."""
        client = GigSmartClient(config)
        error_body = {
            "errors": [{"message": "not found",
                        "extensions": {"code": "NOT_FOUND"}}],
            "data": None,
        }

        with patch.object(client, "_auth") as mock_auth, \
             patch.object(client, "_ensure_session") as mock_session_fn:
            mock_auth.build_headers = AsyncMock(return_value={"Authorization": "Bearer tok"})
            session = _make_session(_make_response(200, error_body))
            mock_session_fn.return_value = session

            with pytest.raises(GigSmartNotFoundError):
                await client.execute("query { node(id: \"x\") { id } }")

    @pytest.mark.asyncio
    async def test_error_classification_bad_user_input(self, config):
        """extensions.code=BAD_USER_INPUT raises GigSmartValidationError."""
        client = GigSmartClient(config)
        error_body = {
            "errors": [{"message": "invalid input",
                        "extensions": {"code": "BAD_USER_INPUT"}}],
            "data": None,
        }

        with patch.object(client, "_auth") as mock_auth, \
             patch.object(client, "_ensure_session") as mock_session_fn:
            mock_auth.build_headers = AsyncMock(return_value={"Authorization": "Bearer tok"})
            session = _make_session(_make_response(200, error_body))
            mock_session_fn.return_value = session

            with pytest.raises(GigSmartValidationError):
                await client.execute("mutation { postShift(input: {}) { shift { id } } }")

    @pytest.mark.asyncio
    async def test_error_classification_conflict(self, config):
        """extensions.code=CONFLICT raises GigSmartConflictError."""
        client = GigSmartClient(config)
        error_body = {
            "errors": [{"message": "conflict",
                        "extensions": {"code": "CONFLICT"}}],
            "data": None,
        }

        with patch.object(client, "_auth") as mock_auth, \
             patch.object(client, "_ensure_session") as mock_session_fn:
            mock_auth.build_headers = AsyncMock(return_value={"Authorization": "Bearer tok"})
            session = _make_session(_make_response(200, error_body))
            mock_session_fn.return_value = session

            with pytest.raises(GigSmartConflictError):
                await client.execute("mutation {}", is_mutation=True)

    @pytest.mark.asyncio
    async def test_unknown_code_raises_graphql_error(self, config):
        """Unknown extension code raises GigSmartGraphQLError."""
        client = GigSmartClient(config)
        error_body = {
            "errors": [{"message": "some error",
                        "extensions": {"code": "SOME_UNKNOWN_CODE"}}],
            "data": None,
        }

        with patch.object(client, "_auth") as mock_auth, \
             patch.object(client, "_ensure_session") as mock_session_fn:
            mock_auth.build_headers = AsyncMock(return_value={"Authorization": "Bearer tok"})
            session = _make_session(_make_response(200, error_body))
            mock_session_fn.return_value = session

            with pytest.raises(GigSmartGraphQLError) as exc_info:
                await client.execute("query { x }")
            assert exc_info.value.errors  # stores raw errors list

    @pytest.mark.asyncio
    async def test_http_429_raises_rate_limit_error(self, config):
        """HTTP 429 raises GigSmartRateLimitError (after all retries)."""
        client = GigSmartClient(config)
        client._MAX_RETRIES = 0  # no retries for speed

        rate_resp = _make_response(429, {})
        rate_resp.headers = {"Retry-After": "30"}

        with patch.object(client, "_auth") as mock_auth, \
             patch.object(client, "_ensure_session") as mock_session_fn:
            mock_auth.build_headers = AsyncMock(return_value={"Authorization": "Bearer tok"})
            session = _make_session(rate_resp)
            mock_session_fn.return_value = session

            with pytest.raises(GigSmartRateLimitError) as exc_info:
                await client.execute("query { x }")
            assert exc_info.value.status_code == 429

    @pytest.mark.asyncio
    async def test_http_500_raises_transport_error(self, config):
        """HTTP 500 raises GigSmartTransportError (after all retries)."""
        client = GigSmartClient(config)
        client._MAX_RETRIES = 0  # no retries for speed

        with patch.object(client, "_auth") as mock_auth, \
             patch.object(client, "_ensure_session") as mock_session_fn:
            mock_auth.build_headers = AsyncMock(return_value={"Authorization": "Bearer tok"})
            session = _make_session(_make_response(500, {}))
            mock_session_fn.return_value = session

            with pytest.raises(GigSmartTransportError):
                await client.execute("query { x }")

    @pytest.mark.asyncio
    async def test_partial_success_query_returns_data(self, config):
        """Query with errors AND data returns data (with warning, no raise)."""
        client = GigSmartClient(config)
        partial_body = {
            "data": {"gigs": {"edges": []}},
            "errors": [{"message": "partial", "extensions": {"code": "PARTIAL"}}],
        }

        with patch.object(client, "_auth") as mock_auth, \
             patch.object(client, "_ensure_session") as mock_session_fn:
            mock_auth.build_headers = AsyncMock(return_value={"Authorization": "Bearer tok"})
            session = _make_session(_make_response(200, partial_body))
            mock_session_fn.return_value = session

            # Should not raise for a non-mutation (is_mutation=False by default)
            result = await client.execute("query { gigs { edges { node { id } } } }")
            assert "gigs" in result

    @pytest.mark.asyncio
    async def test_partial_success_mutation_raises(self, config):
        """Mutation with any errors raises (no partial-success tolerance)."""
        client = GigSmartClient(config)
        partial_body = {
            "data": {"postShift": {"shift": {"id": "gig_1"}}},
            "errors": [{"message": "partial error",
                        "extensions": {"code": "SOME_CODE"}}],
        }

        with patch.object(client, "_auth") as mock_auth, \
             patch.object(client, "_ensure_session") as mock_session_fn:
            mock_auth.build_headers = AsyncMock(return_value={"Authorization": "Bearer tok"})
            session = _make_session(_make_response(200, partial_body))
            mock_session_fn.return_value = session

            with pytest.raises(GigSmartGraphQLError):
                await client.execute("mutation {}", is_mutation=True)


# ---------------------------------------------------------------------------
# Retry behaviour
# ---------------------------------------------------------------------------

class TestRetryBehaviour:
    """Tests for retry and backoff on transient errors."""

    @pytest.mark.asyncio
    async def test_retry_on_transient_error_succeeds(self, config):
        """Client retries on 5xx and returns data on the second attempt."""
        client = GigSmartClient(config)

        call_count = 0

        async def fake_do_request(session, headers, payload, is_mutation):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise GigSmartTransportError("server error", status_code=500)
            return {"viewer": {"id": "org-1"}}

        with patch.object(client, "_auth") as mock_auth, \
             patch.object(client, "_ensure_session") as mock_session_fn, \
             patch.object(client, "_do_request", side_effect=fake_do_request), \
             patch("asyncio.sleep", new=AsyncMock()):
            mock_auth.build_headers = AsyncMock(return_value={"Authorization": "Bearer tok"})
            mock_session_fn.return_value = MagicMock()

            result = await client.execute("query { viewer { id } }")
            assert result == {"viewer": {"id": "org-1"}}
            assert call_count == 2

    @pytest.mark.asyncio
    async def test_no_retry_on_auth_error(self, config):
        """Auth errors are not retried."""
        client = GigSmartClient(config)
        call_count = 0

        async def fake_do_request(session, headers, payload, is_mutation):
            nonlocal call_count
            call_count += 1
            raise GigSmartAuthError("auth failed")

        with patch.object(client, "_auth") as mock_auth, \
             patch.object(client, "_ensure_session") as mock_session_fn, \
             patch.object(client, "_do_request", side_effect=fake_do_request):
            mock_auth.build_headers = AsyncMock(return_value={"Authorization": "Bearer tok"})
            mock_session_fn.return_value = MagicMock()

            with pytest.raises(GigSmartAuthError):
                await client.execute("query { x }")

        assert call_count == 1  # no retry


# ---------------------------------------------------------------------------
# Pagination
# ---------------------------------------------------------------------------

class TestPagination:
    """Tests for Relay auto-pagination."""

    @pytest.mark.asyncio
    async def test_paginate_follows_pages(self, config):
        """paginate() collects nodes from multiple pages."""
        client = GigSmartClient(config)

        page_1 = {
            "organization": {
                "gigs": {
                    "edges": [{"node": {"id": "gig_1"}}, {"node": {"id": "gig_2"}}],
                    "pageInfo": {"hasNextPage": True, "endCursor": "cursor_2"},
                }
            }
        }
        page_2 = {
            "organization": {
                "gigs": {
                    "edges": [{"node": {"id": "gig_3"}}],
                    "pageInfo": {"hasNextPage": False, "endCursor": "cursor_3"},
                }
            }
        }
        call_count = 0

        async def fake_execute(document, variables=None, **kwargs):
            nonlocal call_count
            call_count += 1
            return page_1 if call_count == 1 else page_2

        with patch.object(client, "execute", side_effect=fake_execute):
            nodes = await client.paginate(
                "query ...", {"organizationId": "org_1"}, "organization.gigs"
            )

        assert len(nodes) == 3
        assert nodes[0] == {"id": "gig_1"}
        assert nodes[2] == {"id": "gig_3"}

    @pytest.mark.asyncio
    async def test_paginate_single_page(self, config):
        """paginate() stops after a single page when hasNextPage=False."""
        client = GigSmartClient(config)

        data = {
            "gigs": {
                "edges": [{"node": {"id": "gig_1"}}],
                "pageInfo": {"hasNextPage": False, "endCursor": None},
            }
        }

        with patch.object(client, "execute", new=AsyncMock(return_value=data)):
            nodes = await client.paginate("query ...", {}, "gigs")

        assert nodes == [{"id": "gig_1"}]


# ---------------------------------------------------------------------------
# Context manager
# ---------------------------------------------------------------------------

class TestContextManager:
    """Tests for async context manager support."""

    @pytest.mark.asyncio
    async def test_aenter_aexit(self, config):
        """GigSmartClient supports async with."""
        async with GigSmartClient(config) as client:
            assert client._session is not None

        # After exit, session should be closed or None
        assert client._session is None or client._session.closed
