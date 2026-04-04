"""Tests for FormDesigner authentication integration.

Covers:
- FormAPIHandler._get_org_id() — extracts org_id from request.user
- FormAPIHandler._get_programs() — extracts programs from session dict
- load_from_db org_id resolution (body vs session precedence)
- Route auth integration (API and page routes require auth, Telegram does not)
- Backward compatibility when navigator_auth is not installed
"""

from __future__ import annotations

from functools import wraps
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from aiohttp import web

from parrot.formdesigner.handlers.api import FormAPIHandler
from parrot.formdesigner.handlers.routes import setup_form_routes
from parrot.formdesigner.services.registry import FormRegistry


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def registry() -> FormRegistry:
    """Return a fresh FormRegistry."""
    return FormRegistry()


@pytest.fixture
def handler(registry: FormRegistry) -> FormAPIHandler:
    """Return a FormAPIHandler with a fresh registry and no LLM client."""
    return FormAPIHandler(registry=registry)


@pytest.fixture
def mock_org():
    """Return a mock Organization with org_id='42'."""
    org = MagicMock()
    org.org_id = "42"
    org.organization = "Test Org"
    org.slug = "test-org"
    return org


@pytest.fixture
def mock_auth_user(mock_org):
    """Return a mock AuthUser with one organization."""
    user = MagicMock()
    user.organizations = [mock_org]
    user.username = "testuser"
    user.email = "test@example.com"
    return user


@pytest.fixture
def mock_session() -> dict:
    """Return a mock session dict with programs."""
    return {
        "session": {
            "programs": ["program-a", "program-b"],
            "username": "testuser",
            "email": "test@example.com",
        }
    }


def _make_mock_request(
    *,
    user=None,
    session: dict | None = None,
    authenticated: bool = False,
    json_body: dict | None = None,
    match_info: dict | None = None,
) -> MagicMock:
    """Build a minimal mock web.Request for handler unit tests."""
    req = MagicMock(spec=web.Request)
    req.user = user
    req.session = session
    req.method = "GET"
    req.match_info = match_info or {}

    # request.get("authenticated") / request.get("session")
    def _req_get(key, default=None):
        if key == "authenticated":
            return authenticated
        if key == "session":
            return session
        return default

    req.get = MagicMock(side_effect=_req_get)

    if json_body is not None:
        req.json = AsyncMock(return_value=json_body)

    return req


# ---------------------------------------------------------------------------
# Helpers for route-level auth tests
# ---------------------------------------------------------------------------

def _make_simple_is_authenticated():
    """Return a simple is_authenticated factory for testing.

    The returned factory produces a decorator that checks
    ``request.get("authenticated", False)`` and raises 401 if not set.
    """
    def _factory(content_type: str = "application/json"):
        def _decorator(handler):
            @wraps(handler)
            async def _wrapper(*args, **kwargs):
                # request is the last positional arg in our wrapped handlers
                request = args[-1] if args else None
                if request is None or not isinstance(request, web.Request):
                    raise ValueError("web.Request not found")
                if not request.get("authenticated", False):
                    raise web.HTTPUnauthorized(reason="Access Denied")
                return await handler(*args, **kwargs)
            return _wrapper
        return _decorator
    return _factory


def _make_simple_user_session():
    """Return a simple user_session factory for testing (identity pass-through)."""
    def _factory():
        def _decorator(handler):
            @wraps(handler)
            async def _wrapper(*args, **kwargs):
                return await handler(*args, **kwargs)
            return _wrapper
        return _decorator
    return _factory


# ---------------------------------------------------------------------------
# Unit tests: _get_org_id
# ---------------------------------------------------------------------------

class TestGetOrgId:
    """Tests for FormAPIHandler._get_org_id()."""

    def test_returns_org_id_from_first_organization(self, handler, mock_auth_user):
        """Extract org_id from user.organizations[0].org_id."""
        req = _make_mock_request(user=mock_auth_user)
        result = handler._get_org_id(req)
        assert result == "42"

    def test_returns_none_when_no_organizations(self, handler):
        """Returns None when user.organizations is empty."""
        user = MagicMock()
        user.organizations = []
        req = _make_mock_request(user=user)
        result = handler._get_org_id(req)
        assert result is None

    def test_returns_none_when_no_user(self, handler):
        """Returns None when request.user is None (unauthenticated)."""
        req = _make_mock_request(user=None)
        result = handler._get_org_id(req)
        assert result is None

    def test_returns_none_when_user_attribute_missing(self, handler):
        """Returns None gracefully when request has no user attribute at all."""
        req = MagicMock(spec=web.Request)
        # spec=web.Request won't have .user unless we set it
        del req.user  # remove the attribute
        result = handler._get_org_id(req)
        assert result is None


# ---------------------------------------------------------------------------
# Unit tests: _get_programs
# ---------------------------------------------------------------------------

class TestGetPrograms:
    """Tests for FormAPIHandler._get_programs()."""

    def test_returns_programs_from_session(self, handler, mock_session):
        """Extract programs list from session dict."""
        req = _make_mock_request(session=mock_session)
        result = handler._get_programs(req)
        assert result == ["program-a", "program-b"]

    def test_returns_empty_when_no_programs_key(self, handler):
        """Returns [] when session exists but has no 'programs' key."""
        session = {"session": {"username": "alice"}}
        req = _make_mock_request(session=session)
        result = handler._get_programs(req)
        assert result == []

    def test_returns_empty_when_no_inner_session_key(self, handler):
        """Returns [] when session dict has no nested 'session' key."""
        req = _make_mock_request(session={})
        result = handler._get_programs(req)
        assert result == []

    def test_returns_empty_when_no_session(self, handler):
        """Returns [] when request has no session attribute."""
        req = MagicMock(spec=web.Request)
        req.session = None
        req.get = MagicMock(return_value=None)
        result = handler._get_programs(req)
        assert result == []


# ---------------------------------------------------------------------------
# Unit tests: load_from_db org_id resolution
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
class TestLoadFromDbOrgId:
    """Tests for load_from_db org_id resolution (body vs session precedence)."""

    async def test_body_orgid_takes_precedence(self, handler, mock_auth_user):
        """When body has orgid=99, use 99 over session org_id=42."""
        # Patch _db_tool.execute to return a failure (no DB) so we don't
        # need a real database — we just verify the orgid resolution.
        with patch.object(handler._db_tool, "execute", new_callable=AsyncMock) as mock_exec:
            mock_exec.return_value = MagicMock(
                success=False,
                metadata={"error": "not found: test"},
            )
            req = _make_mock_request(
                user=mock_auth_user,
                json_body={"formid": 1, "orgid": 99},
            )
            await handler.load_from_db(req)
            # _db_tool.execute must have been called with orgid=99 (body wins)
            mock_exec.assert_awaited_once()
            call_kwargs = mock_exec.call_args.kwargs
            assert call_kwargs.get("orgid") == 99

    async def test_falls_back_to_session_org(self, handler, mock_auth_user):
        """When body omits orgid, fall back to user.organizations[0].org_id (42)."""
        with patch.object(handler._db_tool, "execute", new_callable=AsyncMock) as mock_exec:
            mock_exec.return_value = MagicMock(
                success=False,
                metadata={"error": "not found: test"},
            )
            req = _make_mock_request(
                user=mock_auth_user,
                json_body={"formid": 1},  # no orgid
            )
            await handler.load_from_db(req)
            mock_exec.assert_awaited_once()
            call_kwargs = mock_exec.call_args.kwargs
            assert call_kwargs.get("orgid") == 42

    async def test_400_when_no_org_available(self, handler):
        """Returns 400 when neither body nor session has org_id."""
        req = _make_mock_request(
            user=None,
            json_body={"formid": 1},  # no orgid, no user
        )
        resp = await handler.load_from_db(req)
        assert resp.status == 400
        import json as _json
        body = _json.loads(resp.body)
        assert "orgid" in body.get("error", "").lower() or "required" in body.get("error", "").lower()

    async def test_400_when_no_formid(self, handler, mock_auth_user):
        """Returns 400 when formid is missing from body."""
        req = _make_mock_request(
            user=mock_auth_user,
            json_body={"orgid": 42},  # no formid
        )
        resp = await handler.load_from_db(req)
        assert resp.status == 400


# ---------------------------------------------------------------------------
# Route integration tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
class TestRouteAuth:
    """Integration tests for route authentication.

    Uses a simplified is_authenticated mock that checks
    request.get("authenticated", False) and raises 401 if not set.
    """

    @pytest.fixture
    def auth_app(self, registry):
        """aiohttp app with form routes and simple auth mock."""
        with (
            patch(
                "parrot.formdesigner.handlers.routes.is_authenticated",
                side_effect=_make_simple_is_authenticated(),
            ),
            patch(
                "parrot.formdesigner.handlers.routes.user_session",
                side_effect=_make_simple_user_session(),
            ),
            patch(
                "parrot.formdesigner.handlers.routes._AUTH_AVAILABLE",
                True,
            ),
        ):
            app = web.Application()
            setup_form_routes(app, registry=registry)
            return app

    @pytest.fixture
    def no_auth_app(self, registry):
        """aiohttp app with form routes and auth disabled (standalone mode)."""
        with patch(
            "parrot.formdesigner.handlers.routes._AUTH_AVAILABLE",
            False,
        ):
            app = web.Application()
            setup_form_routes(app, registry=registry)
            return app

    async def test_api_list_requires_auth(self, aiohttp_client, auth_app):
        """GET /api/v1/forms returns 401 without authenticated session."""
        client = await aiohttp_client(auth_app)
        resp = await client.get("/api/v1/forms")
        assert resp.status == 401

    async def test_api_get_form_requires_auth(self, aiohttp_client, auth_app):
        """GET /api/v1/forms/{id} returns 401 without authenticated session."""
        client = await aiohttp_client(auth_app)
        resp = await client.get("/api/v1/forms/some-form")
        assert resp.status == 401

    async def test_api_create_form_requires_auth(self, aiohttp_client, auth_app):
        """POST /api/v1/forms returns 401 without authenticated session."""
        client = await aiohttp_client(auth_app)
        resp = await client.post("/api/v1/forms", json={"prompt": "test"})
        assert resp.status == 401

    async def test_api_load_from_db_requires_auth(self, aiohttp_client, auth_app):
        """POST /api/v1/forms/from-db returns 401 without authenticated session."""
        client = await aiohttp_client(auth_app)
        resp = await client.post("/api/v1/forms/from-db", json={"formid": 1})
        assert resp.status == 401

    async def test_page_index_requires_auth(self, aiohttp_client, auth_app):
        """GET / returns 401 without authenticated session."""
        client = await aiohttp_client(auth_app)
        resp = await client.get("/")
        assert resp.status == 401

    async def test_page_gallery_requires_auth(self, aiohttp_client, auth_app):
        """GET /gallery returns 401 without authenticated session."""
        client = await aiohttp_client(auth_app)
        resp = await client.get("/gallery")
        assert resp.status == 401

    async def test_telegram_route_no_auth_required(self, aiohttp_client, auth_app):
        """GET /forms/{id}/telegram is accessible without authentication."""
        client = await aiohttp_client(auth_app)
        # TelegramWebAppHandler.serve_webapp returns 404 for unknown form_id,
        # but it should NOT return 401 (no auth required).
        resp = await client.get("/forms/unknown-form/telegram")
        assert resp.status != 401, "Telegram route should not require auth"

    async def test_telegram_submit_no_auth_required(self, aiohttp_client, auth_app):
        """POST /api/v1/forms/{id}/telegram-submit is accessible without auth."""
        client = await aiohttp_client(auth_app)
        resp = await client.post(
            "/api/v1/forms/unknown-form/telegram-submit",
            json={"data": "test"},
        )
        assert resp.status != 401, "Telegram submit route should not require auth"


# ---------------------------------------------------------------------------
# Backward compatibility: no navigator_auth installed
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
class TestNoAuthBackwardCompat:
    """When navigator_auth is not installed, routes work without auth."""

    async def test_api_routes_work_without_auth(self, aiohttp_client, registry):
        """Routes accessible without auth when navigator_auth is unavailable."""
        with patch(
            "parrot.formdesigner.handlers.routes._AUTH_AVAILABLE",
            False,
        ):
            app = web.Application()
            setup_form_routes(app, registry=registry)

        client = await aiohttp_client(app)
        resp = await client.get("/api/v1/forms")
        # Should return 200 (no auth guard), not 401
        assert resp.status == 200
        data = await resp.json()
        assert "forms" in data

    async def test_page_routes_work_without_auth(self, aiohttp_client, registry):
        """Page routes accessible without auth when navigator_auth is unavailable."""
        with patch(
            "parrot.formdesigner.handlers.routes._AUTH_AVAILABLE",
            False,
        ):
            app = web.Application()
            setup_form_routes(app, registry=registry)

        client = await aiohttp_client(app)
        resp = await client.get("/")
        assert resp.status == 200
