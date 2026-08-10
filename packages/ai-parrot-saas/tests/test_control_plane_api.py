"""Control-plane tenant CRUD over HTTP, end to end against Postgres.

Uses ``setup_saas_api`` itself rather than registering the views by hand, so
the wiring — app keys, route registration, start-up schema creation, cleanup —
is exercised too.
"""
from __future__ import annotations

import pytest
from aiohttp import web
from asyncdb import AsyncDB

from parrot_saas.handlers.setup import setup_saas_api
from parrot_saas.handlers.tenants import (
    APP_TENANT_REPOSITORY,
    APP_TENANT_RUNTIMES,
)
from parrot_saas.tenancy.middleware import TENANT_HEADER, current_tenant

pytestmark = pytest.mark.integration

CONTROL = "/api/v1/saas/control/tenants"


@pytest.fixture
async def client(aiohttp_client, test_dsn: str, unique_schema: str):
    """A wired SaaS app on a throwaway schema, plus a tenant-scoped echo route."""

    async def _echo(request: web.Request) -> web.Response:
        return web.json_response({"tenant_id": current_tenant(request).tenant_id})

    app = web.Application()
    setup_saas_api(
        app,
        dsn=test_dsn,
        schema=unique_schema,
        require_auth=False,  # navigator-auth is not configured in this app
    )
    app.router.add_get("/api/v1/saas/echo", _echo)
    try:
        yield await aiohttp_client(app)
    finally:
        conn = AsyncDB("pg", dsn=test_dsn)
        async with await conn.connection():
            await conn.execute(f"DROP SCHEMA IF EXISTS {unique_schema} CASCADE")


# ---------------------------------------------------------------------------
# Wiring
# ---------------------------------------------------------------------------


async def test_setup_publishes_its_services(client) -> None:
    """The app carries the repository and runtime cache for other handlers."""
    assert APP_TENANT_REPOSITORY in client.app
    assert APP_TENANT_RUNTIMES in client.app


async def test_setup_requires_auth_by_default() -> None:
    """The control plane must not be open by default.

    ``require_auth`` is a test affordance; production must get the decorators
    without asking.
    """
    import inspect

    default = inspect.signature(setup_saas_api).parameters["require_auth"].default
    assert default is True


# ---------------------------------------------------------------------------
# Create
# ---------------------------------------------------------------------------


async def test_create_returns_201(client) -> None:
    """Onboarding a tenant returns the stored record."""
    resp = await client.post(
        CONTROL,
        json={
            "tenant_id": "bar-pepe",
            "name": "Bar Pepe",
            "timezone": "Europe/Madrid",
        },
    )

    assert resp.status == 201
    body = await resp.json()
    assert body["tenant_id"] == "bar-pepe"
    assert body["timezone"] == "Europe/Madrid"
    assert body["status"] == "active"


async def test_duplicate_returns_409_not_400(client) -> None:
    """A duplicate slug must reach the client as 409.

    ``BaseView.error()`` maps every unlisted status to 400, so a 409 built
    through it would arrive as 400 — a mistake already present elsewhere in
    the repository. This asserts the handler avoids that path.
    """
    await client.post(CONTROL, json={"tenant_id": "bar-pepe", "name": "A"})

    resp = await client.post(CONTROL, json={"tenant_id": "bar-pepe", "name": "B"})

    assert resp.status == 409
    assert (await resp.json())["error"] == "tenant_exists"


async def test_invalid_slug_returns_400_with_details(client) -> None:
    """Validation failures name the offending field."""
    resp = await client.post(CONTROL, json={"tenant_id": "Bar Pepe", "name": "x"})

    assert resp.status == 400
    body = await resp.json()
    assert body["error"] == "validation_error"
    assert any(d["field"] == "tenant_id" for d in body["details"])


async def test_missing_required_field_returns_400(client) -> None:
    """A payload without a name is refused."""
    resp = await client.post(CONTROL, json={"tenant_id": "bar-pepe"})

    assert resp.status == 400
    assert (await resp.json())["error"] == "validation_error"


async def test_malformed_json_is_distinguished_from_empty(client) -> None:
    """A broken body is an error, not an empty payload.

    ``BaseView.get_json`` swallows a decode error and returns ``None``, which
    would make a corrupt body look like an empty one.
    """
    resp = await client.post(
        CONTROL, data="{not json", headers={"Content-Type": "application/json"}
    )

    assert resp.status == 400
    assert (await resp.json())["error"] == "invalid_json"


# ---------------------------------------------------------------------------
# Read / list
# ---------------------------------------------------------------------------


async def test_get_and_unknown(client) -> None:
    """Reading a tenant, and a clear 404 for one that does not exist."""
    await client.post(CONTROL, json={"tenant_id": "bar-pepe", "name": "Bar Pepe"})

    ok = await client.get(f"{CONTROL}/bar-pepe")
    missing = await client.get(f"{CONTROL}/nobody-here")

    assert ok.status == 200
    assert (await ok.json())["name"] == "Bar Pepe"
    assert missing.status == 404
    assert (await missing.json())["error"] == "unknown_tenant"


async def test_list_and_status_filter(client) -> None:
    """The listing spans tenants and filters by lifecycle."""
    await client.post(CONTROL, json={"tenant_id": "aaa-bar", "name": "A"})
    await client.post(CONTROL, json={"tenant_id": "zzz-hotel", "name": "Z"})
    await client.delete(f"{CONTROL}/zzz-hotel")

    everyone = await (await client.get(CONTROL)).json()
    active = await (await client.get(f"{CONTROL}?status=active")).json()

    assert everyone["count"] == 2
    assert [t["tenant_id"] for t in active["tenants"]] == ["aaa-bar"]


async def test_invalid_status_filter_is_400(client) -> None:
    """An unknown lifecycle value is refused rather than ignored."""
    resp = await client.get(f"{CONTROL}?status=banana")

    assert resp.status == 400
    assert (await resp.json())["error"] == "invalid_status"


# ---------------------------------------------------------------------------
# Update / delete
# ---------------------------------------------------------------------------


async def test_patch_applies_only_given_fields(client) -> None:
    """A partial patch leaves the rest of the record alone."""
    await client.post(
        CONTROL,
        json={"tenant_id": "bar-pepe", "name": "Bar Pepe", "locale": "es"},
    )

    resp = await client.patch(f"{CONTROL}/bar-pepe", json={"name": "Bar Pepe II"})

    assert resp.status == 200
    body = await resp.json()
    assert body["name"] == "Bar Pepe II"
    assert body["locale"] == "es"


async def test_patch_invalidates_the_cached_runtime(client) -> None:
    """A settings change must take effect, not wait for the cache to expire.

    A live runtime holds agents built from the old settings, so without this
    the change would appear to do nothing.
    """
    await client.post(CONTROL, json={"tenant_id": "bar-pepe", "name": "x"})
    cache = client.app[APP_TENANT_RUNTIMES]
    repo = client.app[APP_TENANT_REPOSITORY]
    tenant = await repo.get("bar-pepe")
    runtime = await cache.get(tenant.to_context())
    assert "bar-pepe" in cache

    await client.patch(
        f"{CONTROL}/bar-pepe", json={"settings": {"max_revise_rounds": 5}}
    )

    assert "bar-pepe" not in cache
    assert runtime.closed is True


async def test_patch_unknown_is_404(client) -> None:
    """Patching a missing tenant must not create one."""
    resp = await client.patch(f"{CONTROL}/nobody-here", json={"name": "x"})

    assert resp.status == 404


async def test_delete_is_a_soft_suspend(client) -> None:
    """Retiring keeps the row so its coupons and stacks are not orphaned."""
    await client.post(CONTROL, json={"tenant_id": "bar-pepe", "name": "x"})

    resp = await client.delete(f"{CONTROL}/bar-pepe")

    assert resp.status == 200
    assert (await resp.json())["status"] == "suspended"
    still_there = await client.get(f"{CONTROL}/bar-pepe")
    assert still_there.status == 200


# ---------------------------------------------------------------------------
# Isolation, over the wire
# ---------------------------------------------------------------------------


async def test_runtime_routes_resolve_the_requested_tenant(client) -> None:
    """A tenant-scoped route serves whichever tenant the request names."""
    await client.post(CONTROL, json={"tenant_id": "bar-pepe", "name": "A"})
    await client.post(CONTROL, json={"tenant_id": "hotel-x", "name": "B"})

    first = await client.get(
        "/api/v1/saas/echo", headers={TENANT_HEADER: "bar-pepe"}
    )
    second = await client.get(
        "/api/v1/saas/echo", headers={TENANT_HEADER: "hotel-x"}
    )

    assert (await first.json())["tenant_id"] == "bar-pepe"
    assert (await second.json())["tenant_id"] == "hotel-x"


async def test_suspended_tenant_cannot_use_runtime_routes(client) -> None:
    """Retiring a tenant actually stops it serving traffic."""
    await client.post(CONTROL, json={"tenant_id": "bar-pepe", "name": "A"})
    await client.delete(f"{CONTROL}/bar-pepe")

    resp = await client.get(
        "/api/v1/saas/echo", headers={TENANT_HEADER: "bar-pepe"}
    )

    assert resp.status == 403
    assert (await resp.json())["error"] == "tenant_suspended"


async def test_control_plane_is_exempt_from_tenant_resolution(client) -> None:
    """The control plane works without a tenant header."""
    resp = await client.get(CONTROL)

    assert resp.status == 200
