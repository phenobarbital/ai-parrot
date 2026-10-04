"""FEAT-605 M4 — Studio mount hooks (prefix, view_wrapper, idempotency)."""
from __future__ import annotations

from aiohttp import web
from parrot.handlers.studio import STUDIO_PREFIX, setup_studio_routes

TENANT_PREFIX = "/api/v1/{tenant}/astudio"


def _paths(app: web.Application) -> list[str]:
    return [r.resource.canonical for r in app.router.routes() if r.resource is not None]


def _make_wrapper(calls: list, skip: str | None = None):
    def wrapper(cls):
        calls.append(cls)
        if skip is not None and cls.__name__ == skip:
            return None

        class Wrapped(cls):  # real subclass standing in for a host seam prologue
            pass

        Wrapped.__name__ = f"Wrapped{cls.__name__}"
        return Wrapped

    return wrapper


async def test_prefixed_routes_resolve_with_router_tenant():
    app = web.Application()
    setup_studio_routes(app, prefix=TENANT_PREFIX)
    paths = _paths(app)
    assert paths and all(p.startswith(TENANT_PREFIX) for p in paths)
    from aiohttp.test_utils import make_mocked_request

    req = make_mocked_request("GET", "/api/v1/acme/astudio/agents", app=app)
    match = await app.router.resolve(req)
    assert match.http_exception is None
    assert match["tenant"] == "acme"


def test_wrapper_called_once_per_class():
    app, calls = web.Application(), []
    setup_studio_routes(app, view_wrapper=_make_wrapper(calls))
    assert len(calls) == len(set(calls)) > 1
    for route in app.router.routes():
        if route.resource is not None and route.method != "HEAD":
            assert route.handler.__name__.startswith("Wrapped")


def test_wrapper_none_skips_class():
    app, calls = web.Application(), []
    setup_studio_routes(app, view_wrapper=_make_wrapper(calls, skip="StudioKeysHandler"))
    paths = _paths(app)
    assert not any("/keys" in p for p in paths)
    assert any(p.endswith("/agents") for p in paths)


def test_setup_twice_single_hook():
    app = web.Application()
    setup_studio_routes(app)
    routes_once, hooks_once = len(app.router.routes()), len(app.on_startup)
    setup_studio_routes(app)
    assert (len(app.router.routes()), len(app.on_startup)) == (routes_once, hooks_once)
    setup_studio_routes(app, prefix=TENANT_PREFIX)
    assert len(app.on_startup) == hooks_once
    assert len(app.router.routes()) > routes_once


def test_default_prefix_unchanged():
    app = web.Application()
    setup_studio_routes(app)
    assert all(p == STUDIO_PREFIX or p.startswith(f"{STUDIO_PREFIX}/") for p in _paths(app))
