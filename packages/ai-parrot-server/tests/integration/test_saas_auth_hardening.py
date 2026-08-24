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

from datetime import UTC
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


# ---------------------------------------------------------------------------
# Code-review fix (post-implementation): PUT /api/v1/crew tenant isolation.
#
# The original FEAT-446 pass tenant-scoped CrewHandler.get()/delete() via
# resolve_session_tenant() but left put() (crew create/update) reading
# `tenant = crew_def.tenant` straight from the request body — a caller of
# any tenant could create/overwrite/delete another tenant's crew by
# setting "tenant" in the payload. Fixed to resolve the tenant from the
# session exactly like get()/delete(), with the body value only used for
# the declared-mismatch check.
# ---------------------------------------------------------------------------


class TestCrewPutTenantIsolation:
    async def test_declared_tenant_mismatch_rejected(
        self, aiohttp_client, authenticated_app
    ):
        _set_session(authenticated_app, {"tenant_id": "acme"})
        client = await aiohttp_client(authenticated_app)

        resp = await client.put(
            "/api/v1/crew",
            json={"name": "victim-crew", "agents": [], "tenant": "victim-tenant"},
        )

        assert resp.status == 400

    async def test_creates_under_session_tenant_when_body_omits_tenant(
        self, aiohttp_client, authenticated_app
    ):
        _set_session(authenticated_app, {"tenant_id": "acme"})
        authenticated_app["bot_manager"].add_crew = AsyncMock()
        client = await aiohttp_client(authenticated_app)

        resp = await client.put("/api/v1/crew", json={"name": "my-crew", "agents": []})

        assert resp.status == 201
        body = await resp.json()
        assert body["tenant"] == "acme"
        call_args = authenticated_app["bot_manager"].add_crew.call_args
        persisted_def = call_args.args[2]
        assert persisted_def.tenant == "acme"

    async def test_creates_under_session_tenant_when_body_tenant_matches(
        self, aiohttp_client, authenticated_app
    ):
        _set_session(authenticated_app, {"tenant_id": "acme"})
        authenticated_app["bot_manager"].add_crew = AsyncMock()
        client = await aiohttp_client(authenticated_app)

        resp = await client.put(
            "/api/v1/crew", json={"name": "my-crew", "agents": [], "tenant": "acme"}
        )

        assert resp.status == 201
        body = await resp.json()
        assert body["tenant"] == "acme"


# ---------------------------------------------------------------------------
# Code-review fix (post-implementation): CrewExecutionHandler job/crew
# read+interact paths (get/patch/put) were not tenant-scoped at all —
# only execute_crew() (POST) resolved a tenant. Any authenticated caller,
# regardless of tenant, could poll/interact with any other tenant's job
# given its job_id. Fixed by tagging every job with its owning tenant
# (already done via `job.metadata['tenant']` at creation) and checking it
# on every read/interact path, hiding cross-tenant existence as a 404
# exactly like a genuinely-missing job.
# ---------------------------------------------------------------------------


@pytest.fixture
def authenticated_execution_app(monkeypatch):
    """A minimal app with only ``CrewExecutionHandler`` mounted, session
    fully controlled per-test via ``app["_test_session"]`` (see
    ``authenticated_app`` above for the mechanism).
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
    CrewExecutionHandler.configure(app, "/api/v1/crews")
    return app


def _plant_job(app: web.Application, *, job_id: str, tenant: str, status=None):
    """Register a job (and, for the detail/interact paths, a matching
    ``_active_crews`` entry) directly on the handler class, bypassing
    execute_crew()'s full LLM-execution path — this test only needs to
    prove the tenant *check* on the read/interact side.
    """
    from datetime import datetime

    from parrot.handlers.crew.models import JobStatus

    job = app["_job_manager"].create_job(
        job_id=job_id, obj_id="some-crew", query="hi", execution_mode="sequential"
    )
    job.metadata["tenant"] = tenant
    job.status = status or JobStatus.COMPLETED
    if job.status == JobStatus.COMPLETED:
        job.completed_at = datetime.now(UTC)
    fake_crew = MagicMock()
    fake_crew.name = "Test Crew"
    fake_crew.get_agent_statuses = MagicMock(return_value={"agent-1": "done"})
    CrewExecutionHandler._active_crews[job_id] = fake_crew
    return job


class TestExecutionHandlerTenantIsolation:
    @pytest.fixture(autouse=True)
    def _job_manager(self, authenticated_execution_app):
        from parrot.handlers.jobs.job import JobManager

        jm = JobManager(id="test-execution-tenant-isolation")
        authenticated_execution_app["job_manager"] = jm
        authenticated_execution_app["_job_manager"] = jm
        yield jm
        CrewExecutionHandler._active_crews.clear()

    async def test_get_detail_cross_tenant_hidden(
        self, aiohttp_client, authenticated_execution_app
    ):
        job = _plant_job(authenticated_execution_app, job_id="job-1", tenant="acme")
        _set_session(authenticated_execution_app, {"tenant_id": "beta"})
        client = await aiohttp_client(authenticated_execution_app)

        resp = await client.get(f"/api/v1/crews/{job.job_id}/some-crew")

        assert resp.status == 404

    async def test_get_detail_same_tenant_allowed(
        self, aiohttp_client, authenticated_execution_app
    ):
        job = _plant_job(authenticated_execution_app, job_id="job-2", tenant="acme")
        _set_session(authenticated_execution_app, {"tenant_id": "acme"})
        client = await aiohttp_client(authenticated_execution_app)

        resp = await client.get(f"/api/v1/crews/{job.job_id}/some-crew")

        assert resp.status == 200

    async def test_active_jobs_list_excludes_other_tenants(
        self, aiohttp_client, authenticated_execution_app
    ):
        from parrot.handlers.crew.models import JobStatus

        _plant_job(
            authenticated_execution_app,
            job_id="job-mine",
            tenant="acme",
            status=JobStatus.RUNNING,
        )
        _plant_job(
            authenticated_execution_app,
            job_id="job-not-mine",
            tenant="beta",
            status=JobStatus.RUNNING,
        )
        _set_session(authenticated_execution_app, {"tenant_id": "acme"})
        client = await aiohttp_client(authenticated_execution_app)

        resp = await client.get("/api/v1/crews", params={"mode": "active_jobs"})

        assert resp.status == 200
        body = await resp.json()
        job_ids = {j["job_id"] for j in body}
        assert "job-mine" in job_ids
        assert "job-not-mine" not in job_ids

    async def test_patch_cross_tenant_hidden(
        self, aiohttp_client, authenticated_execution_app
    ):
        job = _plant_job(authenticated_execution_app, job_id="job-3", tenant="acme")
        _set_session(authenticated_execution_app, {"tenant_id": "beta"})
        client = await aiohttp_client(authenticated_execution_app)

        resp = await client.patch("/api/v1/crews", params={"job_id": job.job_id})

        assert resp.status == 404

    async def test_patch_same_tenant_allowed(
        self, aiohttp_client, authenticated_execution_app
    ):
        job = _plant_job(authenticated_execution_app, job_id="job-4", tenant="acme")
        _set_session(authenticated_execution_app, {"tenant_id": "acme"})
        client = await aiohttp_client(authenticated_execution_app)

        resp = await client.patch("/api/v1/crews", params={"job_id": job.job_id})

        assert resp.status == 200

    async def test_put_interact_cross_tenant_hidden(
        self, aiohttp_client, authenticated_execution_app
    ):
        job = _plant_job(authenticated_execution_app, job_id="job-5", tenant="acme")
        _set_session(authenticated_execution_app, {"tenant_id": "beta"})
        client = await aiohttp_client(authenticated_execution_app)

        resp = await client.put(
            f"/api/v1/crews/{job.job_id}/some-crew/ask",
            json={"question": "how are you"},
        )

        assert resp.status == 404
