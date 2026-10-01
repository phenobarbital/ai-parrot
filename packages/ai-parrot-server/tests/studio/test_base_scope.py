"""FEAT-605 M3 — StudioBaseView scope, check order and identity (routed, real SessionData)."""
from __future__ import annotations

from aiohttp import web
from navigator_session.data import SessionData
from parrot.handlers.scope import RequestScope
from parrot.handlers.studio import setup_studio_routes
from parrot.handlers.studio._base import StudioBaseView

PREFIX = "/api/v1/{tenant}/astudio"


class _Resolver:
    """Real ScopeResolver returning a configurable RequestScope (never a Mock)."""

    def __init__(self, scope: RequestScope) -> None:
        self.scope = scope

    async def resolve(self, request):
        return self.scope


@web.middleware
async def _session_mw(request, handler):
    request["NAV_SESSION"] = SessionData(
        data={"session": {"user_id": 7, "programs": ["acme"], "groups": ["session-g"], "superuser": False}}
    )
    request["authenticated"] = True
    return await handler(request)


class _ProbeView(StudioBaseView):
    """Minimal real StudioBaseView subclass exposing the resolved identity."""

    async def get(self):
        user = await self._get_user()
        return self.json_response(
            {
                "user_id": user.user_id,
                "groups": user.groups,
                "is_superuser": user.is_superuser,
                "tenant": user.tenant,
                "may_author": user.may_author,
                "may_administer": user.may_administer,
            }
        )


def _scope(**kw) -> RequestScope:
    base = dict(user_id="7", tenant="acme", groups=frozenset({"g1", "g2"}))
    base.update(kw)
    return RequestScope(**base)


def _app(scope: RequestScope | None, *, wrapper=None, prefix: str = PREFIX) -> web.Application:
    app = web.Application(middlewares=[_session_mw])
    if scope is not None:
        app["scope_resolver"] = _Resolver(scope)
    setup_studio_routes(app, prefix=prefix, view_wrapper=wrapper)
    app.router.add_view(f"{prefix}/_probe", _ProbeView)
    return app


async def test_tenant_mismatch_403(aiohttp_client):
    client = await aiohttp_client(_app(_scope()))
    resp = await client.get("/api/v1/other/astudio/agents")
    assert resp.status == 403
    assert (await resp.json())["code"] == "tenant_mismatch"


async def test_tenant_none_on_prefixed_route_403(aiohttp_client):
    client = await aiohttp_client(_app(_scope(tenant=None)))
    resp = await client.get("/api/v1/acme/astudio/agents")
    assert resp.status == 403
    assert (await resp.json())["code"] == "tenant_mismatch"


async def test_tenant_mismatch_wins_over_studio_disabled(aiohttp_client):
    client = await aiohttp_client(_app(_scope(studio_enabled=False)))
    resp = await client.get("/api/v1/other/astudio/agents")
    assert resp.status == 403


async def test_studio_disabled_404(aiohttp_client):
    client = await aiohttp_client(_app(_scope(studio_enabled=False)))
    resp = await client.get("/api/v1/acme/astudio/agents")
    assert resp.status == 404
    assert (await resp.json())["code"] == "studio_disabled"


async def test_studio_disabled_applies_to_unprefixed_opted_in_mount(aiohttp_client):
    client = await aiohttp_client(_app(_scope(studio_enabled=False), prefix="/api/v1/astudio"))
    resp = await client.get("/api/v1/astudio/_probe")
    assert resp.status == 404
    assert (await resp.json())["code"] == "studio_disabled"


async def test_identity_from_scope_when_opted_in(aiohttp_client):
    scope = _scope(is_superuser=True, may_author=False, may_administer=True)
    client = await aiohttp_client(_app(scope))
    resp = await client.get("/api/v1/acme/astudio/_probe")
    assert resp.status == 200
    body = await resp.json()
    assert body["is_superuser"] is True and body["tenant"] == "acme"
    assert body["groups"] == ["g1", "g2"]  # from the scope, not the session's ["session-g"]
    assert body["may_author"] is False and body["may_administer"] is True


async def test_wrapper_prologue_runs_before_scope(aiohttp_client):
    class _StashResolver:
        async def resolve(self, request):
            # The host seam's prologue stashed the tenant on the request before scope resolution.
            return _scope(tenant=request.get("seam_tenant"))

    def wrapper(cls):
        class Seamed(cls):
            async def _iter(self):
                self.request["seam_tenant"] = self.request.match_info["tenant"]
                return await super()._iter()

        return Seamed

    app = web.Application(middlewares=[_session_mw])
    app["scope_resolver"] = _StashResolver()
    setup_studio_routes(app, prefix=PREFIX, view_wrapper=wrapper)
    client = await aiohttp_client(app)
    resp = await client.get("/api/v1/acme/astudio/skills/resync")
    # Without the prologue running first the resolver would answer tenant=None => 403.
    assert resp.status != 403


async def test_plain_host_unchanged(aiohttp_client):
    app = web.Application(middlewares=[_session_mw])
    setup_studio_routes(app, prefix="/api/v1/astudio")
    app.router.add_view("/api/v1/astudio/_probe", _ProbeView)
    client = await aiohttp_client(app)
    resp = await client.get("/api/v1/astudio/_probe")
    assert resp.status == 200
    body = await resp.json()
    assert body["groups"] == ["session-g"] and body["tenant"] is None
    assert body["may_author"] is True and body["may_administer"] is False


class _HelperView(StudioBaseView):
    async def get(self):
        kind = self.request.query["k"]
        if kind == "author":
            return await self._require_author() or self.json_response({"ok": True})
        if kind == "taken":
            return self._name_taken("foo")
        return self._not_found("agent", "foo")


async def test_helper_bodies(aiohttp_client):
    app = _app(_scope(may_author=False))
    app.router.add_view(f"{PREFIX}/_h", _HelperView)
    client = await aiohttp_client(app)
    resp = await client.get("/api/v1/acme/astudio/_h?k=author")
    assert resp.status == 403 and (await resp.json())["code"] == "authoring_denied"
    resp = await client.get("/api/v1/acme/astudio/_h?k=taken")
    body = await resp.json()
    assert resp.status == 409 and body["code"] == "name_taken"
    assert body["message"] == "Name 'foo' is not available."
    resp = await client.get("/api/v1/acme/astudio/_h?k=nf")
    body = await resp.json()
    assert resp.status == 404 and body["code"] == "not_found" and body["message"] == "Agent 'foo' not found."


async def test_require_author_noop_on_plain_host(aiohttp_client):
    app = web.Application(middlewares=[_session_mw])
    app.router.add_view("/_h", _HelperView)
    client = await aiohttp_client(app)
    resp = await client.get("/_h?k=author")
    assert resp.status == 200
