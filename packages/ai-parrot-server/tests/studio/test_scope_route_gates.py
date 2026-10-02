"""FEAT-605 W1.3 — execute authoring gate and resync superuser-from-scope."""
from __future__ import annotations

from aiohttp import web
from navigator_session.data import SessionData
from parrot.handlers.scope import RequestScope
from parrot.handlers.studio import setup_studio_routes

PREFIX = "/api/v1/{tenant}/astudio"
BASE = "/api/v1/acme/astudio"


class _Resolver:
    def __init__(self, scope: RequestScope) -> None:
        self.scope = scope

    async def resolve(self, request):
        return self.scope


@web.middleware
async def _mw(request, handler):
    request["NAV_SESSION"] = SessionData(
        data={"session": {"user_id": 7, "programs": ["acme"], "groups": [], "superuser": False}}
    )
    request["authenticated"] = True
    return await handler(request)


def _scope(**kw) -> RequestScope:
    base = dict(user_id="7", tenant="acme", groups=frozenset())
    base.update(kw)
    return RequestScope(**base)


def _app(scope: RequestScope | None) -> web.Application:
    app = web.Application(middlewares=[_mw])
    if scope is not None:
        app["scope_resolver"] = _Resolver(scope)
        setup_studio_routes(app, prefix=PREFIX)
    else:
        setup_studio_routes(app)
    return app


async def test_execute_authoring_denied_when_opted_in(aiohttp_client):
    client = await aiohttp_client(_app(_scope(may_author=False)))
    resp = await client.post(f"{BASE}/tools/anything/execute", json={})
    assert resp.status == 403
    assert (await resp.json())["code"] == "authoring_denied"


async def test_execute_authoring_allowed_passes_gate(aiohttp_client):
    client = await aiohttp_client(_app(_scope(may_author=True)))
    resp = await client.post(f"{BASE}/tools/no_such_tool_xyz/execute", json={})
    assert resp.status == 404 and (await resp.json())["code"] == "not_found"


async def test_execute_plain_host_unchanged(aiohttp_client):
    client = await aiohttp_client(_app(None))
    resp = await client.post("/api/v1/astudio/tools/no_such_tool_xyz/execute", json={})
    assert resp.status == 404 and (await resp.json())["code"] == "not_found"


async def test_resync_may_administer_alone_403(aiohttp_client):
    client = await aiohttp_client(_app(_scope(may_administer=True, is_superuser=False)))
    resp = await client.post(f"{BASE}/skills/resync")
    assert resp.status == 403
    assert (await resp.json())["code"] == "admin_required"


async def test_resync_scope_superuser_allowed(aiohttp_client):
    client = await aiohttp_client(_app(_scope(is_superuser=True)))
    resp = await client.post(f"{BASE}/skills/resync")
    # No database on the app: the 503 branch proves the superuser gate passed.
    assert resp.status == 503
    assert (await resp.json())["code"] == "unavailable"
