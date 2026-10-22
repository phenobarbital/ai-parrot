"""FEAT-605 M5 — GET {prefix}/me per scope state."""
from __future__ import annotations

from aiohttp import web
from navigator_session.data import SessionData
from parrot.handlers.scope import RequestScope
from parrot.handlers.studio import setup_studio_routes

PREFIX = "/api/v1/{tenant}/astudio"
URL = "/api/v1/acme/astudio/me"


class _Resolver:
    def __init__(self, scope: RequestScope) -> None:
        self.scope = scope

    async def resolve(self, request):
        return self.scope


def _scope(**kw) -> RequestScope:
    base = dict(user_id="7", tenant="acme", groups=frozenset({"g"}))
    base.update(kw)
    return RequestScope(**base)


def _mw(with_session: bool = True):
    @web.middleware
    async def mw(request, handler):
        if with_session:
            request["NAV_SESSION"] = SessionData(
                data={"session": {"user_id": 7, "programs": ["acme"], "groups": [], "superuser": False}}
            )
        else:  # a session object with no user in it
            request["NAV_SESSION"] = SessionData(data={"session": {}})
        request["authenticated"] = True
        return await handler(request)

    return mw


def _app(scope: RequestScope | None, *, prefix: str = PREFIX, with_session: bool = True) -> web.Application:
    app = web.Application(middlewares=[_mw(with_session)])
    if scope is not None:
        app["scope_resolver"] = _Resolver(scope)
    setup_studio_routes(app, prefix=prefix)
    return app


async def test_me_returns_scope_flags(aiohttp_client):
    client = await aiohttp_client(_app(_scope(may_author=False, may_administer=True, is_superuser=True)))
    resp = await client.get(URL)
    assert resp.status == 200
    assert await resp.json() == {
        "user_id": "7", "tenant": "acme", "may_author": False, "may_administer": True,
        "enabled": True, "is_superuser": True,
    }


async def test_me_when_disabled(aiohttp_client):
    client = await aiohttp_client(_app(_scope(studio_enabled=False)))
    resp = await client.get(URL)
    assert resp.status == 200
    assert (await resp.json())["enabled"] is False
    # other routes stay disabled
    assert (await client.get("/api/v1/acme/astudio/agents")).status == 404


async def test_me_tenant_mismatch_403(aiohttp_client):
    client = await aiohttp_client(_app(_scope()))
    resp = await client.get("/api/v1/other/astudio/me")
    assert resp.status == 403
    assert (await resp.json())["code"] == "tenant_mismatch"


async def test_me_no_resolver_defaults(aiohttp_client):
    client = await aiohttp_client(_app(None, prefix="/api/v1/astudio"))
    resp = await client.get("/api/v1/astudio/me")
    assert resp.status == 200
    body = await resp.json()
    assert body["enabled"] is True and body["may_administer"] is False and body["is_superuser"] is False
    assert body["tenant"] == "acme"  # default session scope: exactly one program ⇒ that tenant


async def test_me_unauthenticated_401(aiohttp_client):
    client = await aiohttp_client(_app(_scope(), with_session=False))
    resp = await client.get(URL)
    # navigator's get_userid answers 403 for a session without a user; a missing session is 401.
    assert resp.status in (401, 403)
    assert "tenant" not in await resp.text()


async def test_me_route_registered_first():
    app = _app(None, prefix="/api/v1/astudio")
    first = next(r.resource.canonical for r in app.router.routes() if r.resource is not None)
    assert first == "/api/v1/astudio/me"
