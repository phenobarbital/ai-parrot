"""The tenant secrets API, end to end over HTTP against Postgres.

The store is passed into ``setup_saas_api`` rather than left to build itself,
so the suite's fixed master keys are used and no vault environment is needed.
"""
from __future__ import annotations

import logging

import pytest
from aiohttp import web
from asyncdb import AsyncDB

from parrot_saas.handlers.setup import setup_saas_api
from parrot_saas.handlers.tenants import APP_TENANT_REPOSITORY, APP_TENANT_RUNTIMES
from parrot_saas.tenancy.middleware import TENANT_HEADER

pytestmark = pytest.mark.integration

CONTROL = "/api/v1/saas/control/tenants"
SECRETS = "/api/v1/saas/secrets"
ANTHROPIC = "anthropic:api_key"
SECRET = "sk-ant-api03-never-log-me-or-echo-me-back"
HDR = {TENANT_HEADER: "bar-pepe"}


@pytest.fixture
async def client(aiohttp_client, test_dsn: str, unique_schema: str, secret_store):
    """A wired SaaS app sharing the schema with the fixture's secret store."""
    app = web.Application()
    setup_saas_api(
        app,
        dsn=test_dsn,
        schema=unique_schema,
        secret_store=secret_store,
        require_auth=False,  # navigator-auth is not configured in this app
    )
    http = await aiohttp_client(app)
    await http.post(CONTROL, json={"tenant_id": "bar-pepe", "name": "Bar Pepe"})
    try:
        yield http
    finally:
        conn = AsyncDB("pg", dsn=test_dsn)
        async with await conn.connection():
            await conn.execute(f"DROP SCHEMA IF EXISTS {unique_schema} CASCADE")


async def _put(client, key: str = ANTHROPIC, value: str = SECRET):
    """Store a secret for the fixture tenant."""
    return await client.put(f"{SECRETS}/{key}", json={"value": value}, headers=HDR)


# ---------------------------------------------------------------------------
# The round trip
# ---------------------------------------------------------------------------


async def test_put_creates_then_replaces(client) -> None:
    """A first upload is a creation; a second is a replacement."""
    first = await _put(client)
    second = await _put(client, value="sk-ant-a-different-value")

    assert first.status == 201
    assert second.status == 200
    assert (await first.json())["fingerprint"] != (await second.json())["fingerprint"]


async def test_the_same_value_keeps_its_fingerprint(client) -> None:
    """The fingerprint is what lets a client tell whether anything changed."""
    first = await (await _put(client)).json()
    again = await (await _put(client)).json()

    assert first["fingerprint"] == again["fingerprint"]


async def test_list_reports_metadata(client) -> None:
    """The listing names the keys and advertises the ones we understand."""
    await _put(client)

    body = await (await client.get(SECRETS, headers=HDR)).json()

    assert body["count"] == 1
    assert body["secrets"][0]["key"] == ANTHROPIC
    assert "google:api_key" in body["known_keys"]


async def test_get_item_and_unknown(client) -> None:
    """One secret's metadata, and a clear 404 for one that is not there."""
    await _put(client)

    ok = await client.get(f"{SECRETS}/{ANTHROPIC}", headers=HDR)
    missing = await client.get(f"{SECRETS}/google:api_key", headers=HDR)

    assert ok.status == 200
    assert (await ok.json())["key"] == ANTHROPIC
    assert missing.status == 404
    assert (await missing.json())["error"] == "unknown_secret"


async def test_delete_then_gone(client) -> None:
    """Removing a secret is a 204, and removing it twice is a 404."""
    await _put(client)

    first = await client.delete(f"{SECRETS}/{ANTHROPIC}", headers=HDR)
    second = await client.delete(f"{SECRETS}/{ANTHROPIC}", headers=HDR)

    assert first.status == 204
    assert second.status == 404
    assert (await (await client.get(SECRETS, headers=HDR)).json())["count"] == 0


# ---------------------------------------------------------------------------
# Values never come back out
# ---------------------------------------------------------------------------


async def test_no_response_ever_carries_the_value(client) -> None:
    """Asserted on the raw bodies, so a new field cannot slip a value through."""
    put = await _put(client)
    listing = await client.get(SECRETS, headers=HDR)
    item = await client.get(f"{SECRETS}/{ANTHROPIC}", headers=HDR)

    for response in (put, listing, item):
        assert SECRET not in await response.text()


async def test_the_value_never_reaches_the_logs(client, caplog) -> None:
    """Not on write, not on rotation, not on delete."""
    caplog.set_level(logging.DEBUG)

    await _put(client)
    await client.post(f"{SECRETS}/rotate-dek", headers=HDR)
    await client.delete(f"{SECRETS}/{ANTHROPIC}", headers=HDR)

    combined = "\n".join(record.getMessage() for record in caplog.records)
    assert SECRET not in combined


# ---------------------------------------------------------------------------
# Isolation
# ---------------------------------------------------------------------------


async def test_tenants_cannot_see_each_other(client) -> None:
    """The tenant comes from the middleware, so each request serves its own."""
    await client.post(CONTROL, json={"tenant_id": "hotel-x", "name": "Hotel X"})
    await _put(client)
    await client.put(
        f"{SECRETS}/google:api_key",
        json={"value": "AIza-hotel-x-only"},
        headers={TENANT_HEADER: "hotel-x"},
    )

    mine = await (await client.get(SECRETS, headers=HDR)).json()
    theirs = await (
        await client.get(SECRETS, headers={TENANT_HEADER: "hotel-x"})
    ).json()

    assert [s["key"] for s in mine["secrets"]] == [ANTHROPIC]
    assert [s["key"] for s in theirs["secrets"]] == ["google:api_key"]


async def test_a_request_without_a_tenant_is_refused(client) -> None:
    """No header, no tenant, no secrets — the middleware fails closed."""
    resp = await client.get(SECRETS)

    assert resp.status == 400
    assert (await resp.json())["error"] == "tenant_required"


async def test_a_body_cannot_choose_the_tenant(client) -> None:
    """A tenant_id in the payload must be inert, not authoritative."""
    await client.post(CONTROL, json={"tenant_id": "hotel-x", "name": "Hotel X"})

    await client.put(
        f"{SECRETS}/{ANTHROPIC}",
        json={"value": SECRET, "tenant_id": "hotel-x"},
        headers=HDR,
    )

    theirs = await (
        await client.get(SECRETS, headers={TENANT_HEADER: "hotel-x"})
    ).json()
    assert theirs["count"] == 0


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "key",
    [
        "Anthropic:Api_Key",  # uppercase
        "anthropic",  # single segment
        "a:b:c:d",  # four segments
        "anthropic:api key",  # space
        "x" * 200 + ":key",  # too long
    ],
)
async def test_invalid_keys_are_refused(client, key: str) -> None:
    """The key is bound into the ciphertext's AAD; it is not a free label."""
    resp = await client.put(f"{SECRETS}/{key}", json={"value": SECRET}, headers=HDR)

    assert resp.status == 400
    assert (await resp.json())["error"] == "invalid_key"


@pytest.mark.parametrize(
    "payload", [{}, {"value": ""}, {"value": "   "}, {"value": 42}, {"value": None}]
)
async def test_invalid_values_are_refused(client, payload: dict) -> None:
    """An empty or non-string value must not reach the store."""
    resp = await client.put(f"{SECRETS}/{ANTHROPIC}", json=payload, headers=HDR)

    assert resp.status == 400
    assert (await resp.json())["error"] == "invalid_value"


async def test_an_oversized_value_is_refused(client) -> None:
    """One request must not be able to write an unbounded encrypted row."""
    resp = await client.put(
        f"{SECRETS}/{ANTHROPIC}", json={"value": "x" * 9000}, headers=HDR
    )

    assert resp.status == 400


async def test_a_malformed_body_is_not_an_empty_one(client) -> None:
    """``BaseView.get_json`` would report both as ``None``."""
    resp = await client.put(
        f"{SECRETS}/{ANTHROPIC}",
        data="{not json",
        headers={**HDR, "Content-Type": "application/json"},
    )

    assert resp.status == 400
    assert (await resp.json())["error"] == "invalid_json"


# ---------------------------------------------------------------------------
# Rotation and routing
# ---------------------------------------------------------------------------


async def test_rotation_preserves_the_values(client, secret_store) -> None:
    """Rotating the data key re-encrypts; it must not lose anything."""
    await _put(client)
    await client.put(
        f"{SECRETS}/google:api_key", json={"value": "AIza-second"}, headers=HDR
    )

    resp = await client.post(f"{SECRETS}/rotate-dek", headers=HDR)

    assert (await resp.json())["rotated"] == 2
    assert await secret_store.get("bar-pepe", ANTHROPIC) == SECRET
    assert await secret_store.get("bar-pepe", "google:api_key") == "AIza-second"


async def test_rotate_dek_is_not_swallowed_by_the_key_route(client) -> None:
    """The static path is registered first so ``{key}`` cannot capture it."""
    resp = await client.post(f"{SECRETS}/rotate-dek", headers=HDR)

    assert resp.status == 200
    assert "rotated" in await resp.json()


# ---------------------------------------------------------------------------
# Runtime invalidation — what makes an upload take effect
# ---------------------------------------------------------------------------


async def _warm_runtime(client):
    """Build and cache the fixture tenant's runtime."""
    repo = client.app[APP_TENANT_REPOSITORY]
    cache = client.app[APP_TENANT_RUNTIMES]
    tenant = await repo.get("bar-pepe")
    await cache.get(tenant.to_context())
    assert "bar-pepe" in cache
    return cache


async def test_put_invalidates_the_cached_runtime(client) -> None:
    """Without this an upload appears to do nothing for half an hour.

    A live runtime holds agents built from the previous credentials — or none
    at all, for a tenant uploading its first key — so the eviction is what
    makes the change take effect on the next request.
    """
    cache = await _warm_runtime(client)

    await _put(client)

    assert "bar-pepe" not in cache


async def test_delete_invalidates_the_cached_runtime(client) -> None:
    """Revoking a credential must stop it being used, not wait for a TTL."""
    await _put(client)
    cache = await _warm_runtime(client)

    await client.delete(f"{SECRETS}/{ANTHROPIC}", headers=HDR)

    assert "bar-pepe" not in cache


async def test_rotation_invalidates_the_cached_runtime(client) -> None:
    """Rotation rewrites every row of the tenant; rebuild rather than guess."""
    await _put(client)
    cache = await _warm_runtime(client)

    await client.post(f"{SECRETS}/rotate-dek", headers=HDR)

    assert "bar-pepe" not in cache


# ---------------------------------------------------------------------------
# The whole point: an upload produces a working agent
# ---------------------------------------------------------------------------


async def test_uploading_a_key_gives_the_tenant_its_agent(
    client, monkeypatch
) -> None:
    """Onboard, upload, and the next runtime carries a BYOK-configured agent.

    This is the loop the secrets API exists to close, and every link in it can
    fail quietly: a tenant with no key builds an agent-less runtime, an upload
    that skipped the eviction would keep serving that stale runtime, and a key
    that failed to reach the client would produce an agent authenticated as
    the platform. Asserting on the key inside the constructed client covers
    all three at once.
    """
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-PLATFORM-DO-NOT-USE")
    repo = client.app[APP_TENANT_REPOSITORY]
    cache = client.app[APP_TENANT_RUNTIMES]
    context = (await repo.get("bar-pepe")).to_context()

    before = await cache.get(context)
    assert before.agents == {}  # nothing uploaded yet

    await _put(client)  # evicts the runtime as a side effect
    after = await cache.get(context)

    assert "reply_draft" in after.agents
    assert after.agents["reply_draft"]._llm._backend.api_key == SECRET
