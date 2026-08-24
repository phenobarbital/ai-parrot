"""Negative-path integration suite for SaaS Auth Hardening (FEAT-446 S0).

Implements the spec's §4 Integration Tests table verbatim (one test per
row): proves the previously-open crew/flow-authoring/streaming surface now
rejects anonymous callers, that client-supplied tenant values are ignored
in favor of the session, that SaaS mode never falls back to ``"global"``,
that the self-managed OpenAI-compat bearer scheme still rejects
unauthenticated callers (no code change expected — a probe only), and that
``/ws/user`` is gated correctly by ``PARROT_SAAS_MODE``.

Two testing strategies are used, matched to what each row needs:

- **Anonymous-rejection rows** (`test_crew_routes_reject_anonymous`,
  `test_stream_routes_reject_anonymous`, `test_v1_bearer_scheme_rejects`)
  build a real aiohttp app with the actual production
  ``navigator_auth.AuthHandler().setup(app)`` — the real session +
  auth + security middleware chain — and the real handler routes, then
  hit them with no credentials at all. This is the strongest possible
  proof: no part of the auth stack is faked. (This machine's dev
  environment has local Postgres/Redis available, which
  ``AuthHandler.setup()`` uses for its own bookkeeping; these are the
  project's own baseline dev-stack services, not third-party "live"
  services per the `live` pytest marker's meaning.)
- **Authenticated rows** (`test_body_tenant_ignored`,
  `test_no_global_default_in_saas_mode`) need a caller whose session
  carries a *controllable* tenant claim, which none of navigator-auth's
  bundled backends provide out of the box (``NoAuth`` mints a random
  anonymous identity with no ``tenant_id``/``programs``). These tests
  substitute the session SOURCE with a controlled fake (matching the
  exact `request.session` contract navigator-auth's own
  ``user_session()`` decorator populates and ``_tenancy.py`` reads) via
  ``request["authenticated"] = True`` (``is_authenticated()``'s own
  documented short-circuit — not a hack) plus monkeypatching
  ``navigator_auth.decorators.get_session``. The real production
  ``CrewHandler``/`resolve_session_tenant` code still runs unmodified;
  only the session's origin is substituted, exactly the way
  TASK-2322/TASK-2323/TASK-2324's own unit suites already prove
  ``resolve_session_tenant`` and the class-level decorators work in
  isolation — this suite proves they compose correctly end-to-end.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from aiohttp import web
from navigator_auth import AuthHandler
from navigator_auth.conf import AUTH_SESSION_OBJECT, exclude_list
from parrot import conf
from parrot.handlers.crew.execution_handler import CrewExecutionHandler
from parrot.handlers.crew.execution_history_handler import CrewExecutionHistoryHandler
from parrot.handlers.crew.handler import CrewHandler
from parrot.handlers.flow_authoring import FlowAuthoringHandler
from parrot.handlers.openai_compat import register_openai_compat_routes
from parrot.handlers.stream import StreamHandler
from parrot.handlers.user import UserSocketManager

# ---------------------------------------------------------------------------
# Shared fixtures / helpers
# ---------------------------------------------------------------------------


class _FakeSession(dict):
    """Minimal session stand-in matching the contract ``_tenancy.py`` and
    ``user_session()`` both read: dict-like ``.get()``, plus ``.decode()``
    for the navigator_session-style ``session.decode('user')`` access.
    """

    def decode(self, key):
        return self.get(f"__decoded_{key}__")


@pytest.fixture(autouse=True)
def _reset_saas_mode(monkeypatch):
    monkeypatch.setattr(conf, "PARROT_SAAS_MODE", False)
    yield


@pytest.fixture(autouse=True)
def _clean_exclude_list():
    """``exclude_list`` is shared, mutable, process-global state."""
    before = list(exclude_list)
    yield
    exclude_list[:] = before


def _full_auth_app() -> web.Application:
    """Build an app wired with the REAL production navigator-auth stack.

    No credentials of any kind are configured, so every non-excluded
    route is closed to anonymous callers.
    """
    app = web.Application()
    AuthHandler(app_name="auth").setup(app)
    return app


@pytest.fixture
def anon_app():
    """Real auth stack + every route this feature closed (crew, execution,
    execution history, flow authoring, streaming).
    """
    app = _full_auth_app()
    app["bot_manager"] = MagicMock()
    CrewHandler.configure(app, "/api/v1/crew")
    CrewExecutionHandler.configure(app, "/api/v1/crews")
    CrewExecutionHistoryHandler.configure(app, "/api/v1/crew/executions")
    FlowAuthoringHandler.setup(app, route="/api/v1/flows/authoring")
    stream_handler = StreamHandler()
    stream_handler.configure_routes(app)
    return app


@pytest.fixture
def authenticated_app(monkeypatch):
    """A minimal app with only ``CrewHandler`` mounted, where every
    request is treated as authenticated and its session is fully
    controlled per-test via ``app["_test_session"]``.
    """

    @web.middleware
    async def _mark_authenticated(request: web.Request, handler):
        request["authenticated"] = True
        return await handler(request)

    async def _fake_get_session(request, new=False):
        return request.app["_test_session"]

    monkeypatch.setattr(
        "navigator_auth.decorators.get_session", _fake_get_session
    )

    app = web.Application(middlewares=[_mark_authenticated])
    app["_test_session"] = _FakeSession()
    app["bot_manager"] = MagicMock()
    app["bot_manager"].sync_crews = AsyncMock()
    app["bot_manager"].list_crews = MagicMock(return_value={})
    CrewHandler.configure(app, "/api/v1/crew")
    return app


def _set_session(app: web.Application, userinfo: dict) -> None:
    app["_test_session"] = _FakeSession({AUTH_SESSION_OBJECT: userinfo})


# ---------------------------------------------------------------------------
# spec §4: test_crew_routes_reject_anonymous
# ---------------------------------------------------------------------------


class TestCrewRoutesRejectAnonymous:
    """Every route under /api/v1/crew, /api/v1/crews,
    /api/v1/crew/executions, /api/v1/flows/authoring returns 401/403
    without credentials.
    """

    @pytest.mark.parametrize(
        "method,path",
        [
            ("get", "/api/v1/crew"),
            ("put", "/api/v1/crew"),
            ("delete", "/api/v1/crew"),
            ("get", "/api/v1/crews"),
            ("post", "/api/v1/crews"),
            ("get", "/api/v1/crew/executions"),
            ("post", "/api/v1/crew/executions/exec-1/replay"),
            ("delete", "/api/v1/crew/executions/exec-1"),
            ("get", "/api/v1/flows/authoring"),
            ("post", "/api/v1/flows/authoring"),
        ],
    )
    async def test_route_rejects_anonymous(self, aiohttp_client, anon_app, method, path):
        client = await aiohttp_client(anon_app)
        resp = await client.request(method, path, json={})
        assert resp.status in (401, 403), f"{method.upper()} {path} -> {resp.status}"


# ---------------------------------------------------------------------------
# spec §4: test_stream_routes_reject_anonymous
# ---------------------------------------------------------------------------


class TestStreamRoutesRejectAnonymous:
    """The four /bots/{id}/stream/* routes reject anonymous callers now
    that TASK-2324 removed their exclude_list entries.
    """

    @pytest.mark.parametrize(
        "method,path",
        [
            ("post", "/bots/bot-1/stream/sse"),
            ("post", "/bots/bot-1/stream/ndjson"),
            ("post", "/bots/bot-1/stream/chunked"),
            ("get", "/bots/bot-1/stream/ws"),
        ],
    )
    async def test_stream_route_rejects_anonymous(
        self, aiohttp_client, anon_app, method, path
    ):
        client = await aiohttp_client(anon_app)
        resp = await client.request(method, path, json={"prompt": "hi"})
        assert resp.status in (401, 403), f"{method.upper()} {path} -> {resp.status}"


# ---------------------------------------------------------------------------
# spec §4: test_body_tenant_ignored
# ---------------------------------------------------------------------------


class TestBodyTenantIgnored:
    """An authenticated request with `tenant` in body/query executes
    against the session tenant, not the supplied one; conflicting value
    is rejected with 400.
    """

    async def test_matching_declared_tenant_passes(self, aiohttp_client, authenticated_app):
        _set_session(authenticated_app, {"tenant_id": "acme"})
        client = await aiohttp_client(authenticated_app)

        resp = await client.get("/api/v1/crew", params={"tenant": "acme"})

        assert resp.status == 200
        data = await resp.json()
        assert data["crews"] == []

    async def test_no_declared_tenant_uses_session(self, aiohttp_client, authenticated_app):
        _set_session(authenticated_app, {"tenant_id": "acme"})
        client = await aiohttp_client(authenticated_app)

        resp = await client.get("/api/v1/crew")

        assert resp.status == 200
        authenticated_app["bot_manager"].list_crews.assert_called_with(tenant="acme")

    async def test_conflicting_declared_tenant_rejected(
        self, aiohttp_client, authenticated_app
    ):
        _set_session(authenticated_app, {"tenant_id": "acme"})
        client = await aiohttp_client(authenticated_app)

        resp = await client.get("/api/v1/crew", params={"tenant": "someone-elses-tenant"})

        assert resp.status == 400


# ---------------------------------------------------------------------------
# spec §4: test_no_global_default_in_saas_mode
# ---------------------------------------------------------------------------


class TestNoGlobalDefaultInSaasMode:
    """flag true + session without tenant -> 403, never "global"."""

    async def test_unresolvable_tenant_403_in_saas_mode(
        self, aiohttp_client, authenticated_app, monkeypatch
    ):
        monkeypatch.setattr(conf, "PARROT_SAAS_MODE", True)
        _set_session(authenticated_app, {})  # no tenant_id, no programs
        client = await aiohttp_client(authenticated_app)

        resp = await client.get("/api/v1/crew")

        assert resp.status == 403

    async def test_unresolvable_tenant_legacy_global(self, aiohttp_client, authenticated_app):
        # PARROT_SAAS_MODE is False (autouse _reset_saas_mode fixture).
        _set_session(authenticated_app, {})
        client = await aiohttp_client(authenticated_app)

        resp = await client.get("/api/v1/crew")

        assert resp.status == 200
        authenticated_app["bot_manager"].list_crews.assert_called_with(tenant="global")


# ---------------------------------------------------------------------------
# spec §4: test_v1_bearer_scheme_rejects
# ---------------------------------------------------------------------------


class TestV1BearerSchemeRejects:
    """`/v1/chat/completions/{session_id}` and `/v1/models` without
    `Bearer` -> 401 (proves the self-managed scheme is fail-closed; no
    code change expected here — probe only, per spec §1 Non-Goals).
    """

    @pytest.fixture
    def openai_compat_app(self):
        app = web.Application()
        register_openai_compat_routes(app.router)
        return app

    async def test_chat_completions_without_bearer_401(
        self, aiohttp_client, openai_compat_app
    ):
        client = await aiohttp_client(openai_compat_app)
        resp = await client.post(
            "/v1/chat/completions/some-session", json={"messages": []}
        )
        assert resp.status == 401

    async def test_models_without_bearer_401(self, aiohttp_client, openai_compat_app):
        client = await aiohttp_client(openai_compat_app)
        resp = await client.get("/v1/models")
        assert resp.status == 401


# ---------------------------------------------------------------------------
# spec §4: test_ws_user_gated
# ---------------------------------------------------------------------------


class TestWsUserGated:
    """`/ws/user` is excluded from the auth middleware only when
    PARROT_SAAS_MODE is false.
    """

    def test_excluded_when_legacy(self, monkeypatch):
        monkeypatch.setattr(conf, "PARROT_SAAS_MODE", False)
        app = web.Application()

        UserSocketManager(app, route_prefix="/ws/user_saas_it_legacy")

        assert "/ws/user_saas_it_legacy" in exclude_list

    def test_not_excluded_when_saas_mode(self, monkeypatch):
        monkeypatch.setattr(conf, "PARROT_SAAS_MODE", True)
        app = web.Application()

        UserSocketManager(app, route_prefix="/ws/user_saas_it_saas")

        assert "/ws/user_saas_it_saas" not in exclude_list
