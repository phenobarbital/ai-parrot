"""Tenant resolution: strategies, exemptions, and failing closed.

Runs against a plain ``web.Application`` with an in-memory repository, the
idiom already used by ``packages/ai-parrot/tests/handlers/test_infographic_handler.py``.
No navigator app, no database.
"""
from __future__ import annotations

from typing import Optional

import pytest
from aiohttp import web

from parrot_saas.tenancy.context import TenantStatus
from parrot_saas.tenancy.middleware import (
    TENANT_HEADER,
    current_tenant,
    tenant_resolution_middleware,
)
from parrot_saas.tenancy.models import Tenant


class _Repo:
    """In-memory stand-in exposing the repository's ``get`` coroutine."""

    def __init__(self, *tenants: Tenant) -> None:
        self._by_id = {t.tenant_id: t for t in tenants}
        self.lookups: list[str] = []

    async def get(self, tenant_id: str) -> Optional[Tenant]:
        self.lookups.append(tenant_id)
        return self._by_id.get(tenant_id)


def _app(repo: _Repo, **kwargs) -> web.Application:
    """Build an app whose one route echoes the resolved tenant."""

    async def _echo(request: web.Request) -> web.Response:
        tenant = current_tenant(request)
        return web.json_response(
            {"tenant_id": tenant.tenant_id, "name": tenant.name}
        )

    async def _open(request: web.Request) -> web.Response:
        return web.json_response({"ok": True})

    app = web.Application(
        middlewares=[tenant_resolution_middleware(repository=repo, **kwargs)]
    )
    app.router.add_get("/api/v1/saas/echo", _echo)
    app.router.add_get("/health", _open)
    app.router.add_get("/api/v1/saas/control/tenants", _open)
    app.router.add_post("/api/v1/saas/reviews/webhook/mock", _open)
    return app


@pytest.fixture
def repo() -> _Repo:
    """An active tenant plus a suspended one."""
    return _Repo(
        Tenant(tenant_id="bar-pepe", name="Bar Pepe"),
        Tenant(
            tenant_id="hotel-x", name="Hotel X", status=TenantStatus.SUSPENDED
        ),
    )


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------


async def test_header_strategy(aiohttp_client, repo: _Repo) -> None:
    """The header is the default, primary strategy."""
    client = await aiohttp_client(_app(repo))

    resp = await client.get(
        "/api/v1/saas/echo", headers={TENANT_HEADER: "bar-pepe"}
    )

    assert resp.status == 200
    assert (await resp.json())["tenant_id"] == "bar-pepe"


async def test_header_is_case_insensitive(aiohttp_client, repo: _Repo) -> None:
    """Slugs are lowercase; a shouted header still resolves."""
    client = await aiohttp_client(_app(repo))

    resp = await client.get(
        "/api/v1/saas/echo", headers={TENANT_HEADER: "  BAR-PEPE "}
    )

    assert resp.status == 200


async def test_subdomain_strategy(aiohttp_client, repo: _Repo) -> None:
    """The left-most host label resolves when no header is sent."""
    client = await aiohttp_client(_app(repo))

    resp = await client.get(
        "/api/v1/saas/echo", headers={"Host": "bar-pepe.example.com"}
    )

    assert resp.status == 200
    assert (await resp.json())["tenant_id"] == "bar-pepe"


@pytest.mark.parametrize("host", ["example.com", "localhost:8080", "www.example.com"])
async def test_subdomain_ignores_non_tenant_hosts(
    aiohttp_client, repo: _Repo, host: str
) -> None:
    """A bare domain must not resolve its own name as a tenant."""
    client = await aiohttp_client(_app(repo))

    resp = await client.get("/api/v1/saas/echo", headers={"Host": host})

    assert resp.status == 400
    assert (await resp.json())["error"] == "tenant_required"


async def test_header_wins_over_subdomain(aiohttp_client, repo: _Repo) -> None:
    """Strategies are tried in order."""
    client = await aiohttp_client(_app(repo))

    resp = await client.get(
        "/api/v1/saas/echo",
        headers={TENANT_HEADER: "bar-pepe", "Host": "hotel-x.example.com"},
    )

    assert (await resp.json())["tenant_id"] == "bar-pepe"


def test_unknown_strategy_is_rejected_at_build_time(repo: _Repo) -> None:
    """A typo in the configuration fails at start-up, not per request."""
    with pytest.raises(ValueError, match="unknown tenant resolution strategy"):
        tenant_resolution_middleware(repository=repo, strategies=("magic",))


def test_claim_strategy_is_available_but_not_default() -> None:
    """No tenant claim exists in this deployment yet.

    ``programs`` is the nearest multi-tenant signal in a session and is not a
    tenant, so reading a claim must be an explicit opt-in rather than a
    default that silently resolves nothing.
    """
    from parrot_saas.tenancy.middleware import DEFAULT_STRATEGIES

    assert "claim" not in DEFAULT_STRATEGIES
    tenant_resolution_middleware(
        repository=_Repo(), strategies=("header", "claim")
    )


# ---------------------------------------------------------------------------
# Failing closed
# ---------------------------------------------------------------------------


async def test_missing_tenant_is_400(aiohttp_client, repo: _Repo) -> None:
    """No tenant is an error, never a default.

    The layers around this one both fail open — abac_middleware passes
    unauthenticated requests through, and setup_pbac degrades to no policy
    engine when its directory is missing — so this is the isolation boundary.
    """
    client = await aiohttp_client(_app(repo))

    resp = await client.get("/api/v1/saas/echo")

    assert resp.status == 400
    assert (await resp.json())["error"] == "tenant_required"


async def test_malformed_slug_is_rejected_before_the_database(
    aiohttp_client, repo: _Repo
) -> None:
    """A bad slug is refused without a lookup."""
    client = await aiohttp_client(_app(repo))

    resp = await client.get(
        "/api/v1/saas/echo", headers={TENANT_HEADER: "Robert'); DROP TABLE--"}
    )

    assert resp.status == 400
    assert (await resp.json())["error"] == "tenant_invalid"
    assert repo.lookups == []


async def test_unknown_tenant_is_404(aiohttp_client, repo: _Repo) -> None:
    """An unrecognised slug is refused."""
    client = await aiohttp_client(_app(repo))

    resp = await client.get(
        "/api/v1/saas/echo", headers={TENANT_HEADER: "nobody-here"}
    )

    assert resp.status == 404
    assert (await resp.json())["error"] == "unknown_tenant"


async def test_suspended_tenant_is_403(aiohttp_client, repo: _Repo) -> None:
    """A suspended tenant exists but may not serve traffic."""
    client = await aiohttp_client(_app(repo))

    resp = await client.get(
        "/api/v1/saas/echo", headers={TENANT_HEADER: "hotel-x"}
    )

    assert resp.status == 403
    assert (await resp.json())["error"] == "tenant_suspended"


# ---------------------------------------------------------------------------
# Exemptions
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "path", ["/health", "/api/v1/saas/control/tenants"]
)
async def test_exempt_prefixes_skip_resolution(
    aiohttp_client, repo: _Repo, path: str
) -> None:
    """The control plane and health checks carry no tenant."""
    client = await aiohttp_client(_app(repo))

    resp = await client.get(path)

    assert resp.status == 200
    assert repo.lookups == []


async def test_exempt_patterns_cover_signed_webhooks(
    aiohttp_client, repo: _Repo
) -> None:
    """A webhook authenticated by HMAC needs no tenant header."""
    client = await aiohttp_client(
        _app(repo, exempt_patterns=("/api/v1/saas/reviews/webhook/*",))
    )

    resp = await client.post("/api/v1/saas/reviews/webhook/mock")

    assert resp.status == 200


# ---------------------------------------------------------------------------
# current_tenant
# ---------------------------------------------------------------------------


async def test_current_tenant_raises_on_an_exempt_route(
    aiohttp_client, repo: _Repo
) -> None:
    """Reading a tenant where none was resolved must be loud.

    A handler that expected a tenant and silently got ``None`` is how
    cross-tenant reads happen.
    """

    async def _bad(request: web.Request) -> web.Response:
        current_tenant(request)
        return web.json_response({})

    app = web.Application(
        middlewares=[tenant_resolution_middleware(repository=repo)]
    )
    app.router.add_get("/health/oops", _bad)
    client = await aiohttp_client(app)

    resp = await client.get("/health/oops")

    assert resp.status == 500
