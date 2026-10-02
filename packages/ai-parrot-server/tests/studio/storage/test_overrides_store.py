"""FEAT-621 phase 2 — per-user toolkit overrides in Postgres (AC21, overrides half) + combined vault/overrides test.

Real Postgres pool. DocumentDB is replaced by a class that raises on construction: any contact fails the test.
"""
from __future__ import annotations

import pytest
from aiohttp import web
from navigator_session.vault import KeyRing

import parrot.security.vault_utils as vault_utils
from parrot.handlers import toolkit_persistence
from parrot.handlers.studio.storage import backend as backend_module
from parrot.handlers.studio.storage import vault_store as vault_store_module
from parrot.handlers.studio.storage.overrides_store import PgToolkitOverrideStore, register_override_store
from parrot.handlers.studio.storage.vault_store import register_vault_store
from parrot.handlers.toolkit_persistence import ToolkitConfigService, UserToolkitOverride
from parrot.security.credentials_utils import credential_context, decrypt_credential
from parrot.tools.spec import SECRET_MASK

from parrot.handlers.studio import tooling_store as tooling_store_module
from parrot.handlers.studio.storage.services import tooling as tooling_module

from ..test_tooling_db_mode import (  # noqa: F401  (fixtures and helpers of the v1 identity scenario)
    SCHEMA,
    _configure,
    _JiraToolkit,
    _tenant_agent,
    _tenant_app,
    allow_tenant_tooling,
    pool,
)

KEYRING = KeyRing({1: b"1" * 32}, 1)
REF = "studio-agent:11111111-1111-1111-1111-111111111111"


class _DocumentDbForbidden:
    def __init__(self, *a, **k):
        raise AssertionError("DocumentDB was contacted with TOOLKIT_OVERRIDES_STORE=postgres")


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setattr(toolkit_persistence, "DocumentDb", _DocumentDbForbidden)
    monkeypatch.setattr(vault_utils, "DocumentDb", _DocumentDbForbidden)
    monkeypatch.setattr(vault_utils, "get_vault_keyring", lambda: KEYRING)
    monkeypatch.setattr(vault_store_module, "get_vault_keyring", lambda: KEYRING)
    yield
    register_override_store(None)
    register_vault_store(None)


@pytest.fixture
async def store(pool):  # noqa: F811
    async with pool.acquire() as conn:
        await conn.execute("TRUNCATE navigator.ai_user_toolkit_overrides, navigator.ai_user_credentials")
    store = PgToolkitOverrideStore(pool)
    register_override_store(store)
    yield store
    async with pool.acquire() as conn:
        await conn.execute("TRUNCATE navigator.ai_user_toolkit_overrides, navigator.ai_user_credentials")


def _ov(user="u1", agent=REF, slug="jira", **extra) -> UserToolkitOverride:
    return UserToolkitOverride(user_id=user, agent_id=agent, slug=slug, **extra)


async def test_overrides_pg_roundtrip(store):
    svc = ToolkitConfigService()
    assert await svc.load("u1", REF) == [] and await svc.revision("u1", REF) == ""
    first = _ov(params={"server_url": "https://x", "n": 1}, secret_refs={"token": "toolkit_jira_x_user"})
    await svc.save(first)
    assert await svc.load("u1", REF) == [first]
    assert await svc.revision("u1", REF) == first.updated_at
    second = _ov(params={"server_url": "https://y"}, updated_at="2030-01-01T00:00:00+00:00")
    await svc.save(second)  # upsert on (user_id, agent_ref, slug)
    assert await svc.load("u1", REF) == [second]
    assert await svc.revision("u1", REF) == "2030-01-01T00:00:00+00:00"
    await svc.save(_ov(user="u2", params={"a": 1}))
    await svc.save(_ov(slug="other"))
    assert sorted(o.slug for o in await svc.load("u1", REF)) == ["jira", "other"]
    assert [o.params for o in await svc.load("u2", REF)] == [{"a": 1}]
    assert await svc.remove("u1", REF, "jira") is True
    assert await svc.remove("u1", REF, "jira") is False
    assert [o.slug for o in await svc.load("u1", REF)] == ["other"]


async def test_purge_agent_pg(store):
    svc = ToolkitConfigService()
    other = "studio-agent:22222222-2222-2222-2222-222222222222"
    await svc.save(_ov(user="u1", secret_refs={"token": "r1"}))
    await svc.save(_ov(user="u2", slug="gh"))
    await svc.save(_ov(user="u1", agent=other))
    purged = await svc.purge_agent(REF)
    assert sorted((o.user_id, o.slug) for o in purged) == [("u1", "jira"), ("u2", "gh")]
    assert next(o for o in purged if o.user_id == "u1").secret_refs == {"token": "r1"}
    assert await svc.load("u1", REF) == [] and await svc.load("u2", REF) == []
    assert len(await svc.load("u1", other)) == 1  # another agent's override is untouched
    assert await svc.purge_agent(REF) == []


async def test_default_stays_documentdb():
    """Without a registered store the DocumentDB path is used (switch default ``documentdb``)."""
    with pytest.raises(AssertionError, match="DocumentDB was contacted"):
        await ToolkitConfigService().load("u1", REF)


async def test_startup_registers_store_only_when_switch_is_postgres(pool, monkeypatch):  # noqa: F811
    monkeypatch.setenv("TOOLKIT_OVERRIDES_STORE", "postgres")
    monkeypatch.setenv("PARROT_STUDIO_STORAGE", "database")
    app = web.Application()
    app["database"] = pool
    storage = await backend_module.ensure_studio_storage(app)
    assert storage.backend == "database", storage.reason
    assert toolkit_persistence._PG_OVERRIDES is not None
    register_override_store(None)
    monkeypatch.setenv("TOOLKIT_OVERRIDES_STORE", "documentdb")
    app2 = web.Application()
    app2["database"] = pool
    await backend_module.ensure_studio_storage(app2)
    assert toolkit_persistence._PG_OVERRIDES is None
    monkeypatch.setenv("TOOLKIT_OVERRIDES_STORE", "postgres")
    monkeypatch.setenv("PARROT_STUDIO_STORAGE", "filesystem")
    app3 = web.Application()
    app3["database"] = pool
    assert (await backend_module.ensure_studio_storage(app3)).backend == "filesystem"
    assert toolkit_persistence._PG_OVERRIDES is None


async def test_vault_and_overrides_pg_roundtrip(aiohttp_client, pool, store, allow_tenant_tooling, monkeypatch):  # noqa: F811
    """AC21: the cross-tenant identity scenario, with both switches on, over real Postgres stores only."""
    for module in (tooling_store_module, tooling_module):
        monkeypatch.setattr(module, "toolkit_schema_for", lambda slug: (_JiraToolkit, SCHEMA))
    register_vault_store(vault_store_module.PgVaultCredentialStore(pool))
    client = await aiohttp_client(_tenant_app(pool, "acme", "beta"))
    acme_id, beta_id = await _tenant_agent(client, "acme"), await _tenant_agent(client, "beta")
    await _configure(client, "acme", "A")
    await _configure(client, "beta", "B")
    ref_a, ref_b = f"studio-agent:{acme_id}", f"studio-agent:{beta_id}"

    async def secret(name):
        return await vault_utils.retrieve_vault_credential("u1", name)

    assert await secret(f"toolkit_jira_{ref_a}") == {"token": "A"}
    assert await secret(f"toolkit_jira_{ref_b}") == {"token": "B"}
    assert await secret(f"mcp_agent_docs_{ref_a}") == {"headers": {"X-Key": "h-A"}}
    assert await secret(f"toolkit_jira_{ref_a}_user") == {"token": "me-A"}
    assert await secret(f"toolkit_jira_{ref_b}_user") == {"token": "me-B"}
    with pytest.raises(KeyError):
        await secret("toolkit_jira_sales")
    async with pool.acquire() as conn:
        rows = await conn.fetch_all("SELECT agent_ref FROM navigator.ai_user_toolkit_overrides")
        cred = await conn.fetch_one(
            "SELECT credential FROM navigator.ai_user_credentials WHERE name = $1", f"toolkit_jira_{ref_a}"
        )
    assert {r["agent_ref"] for r in rows} == {ref_a, ref_b}
    assert "A" != cred["credential"] and decrypt_credential(
        cred["credential"], credential_context("u1", f"toolkit_jira_{ref_a}"), KEYRING
    ) == {"token": "A"}
    for tenant in ("acme", "beta"):
        body = await (await client.get(f"/{tenant}/agents/sales/toolkits/jira/me")).json()
        assert body["configured"] is True and body["params"] == {"token": SECRET_MASK}
    assert (await client.delete("/acme/agents/sales")).status == 200
    async with pool.acquire() as conn:
        left = await conn.fetch_all("SELECT agent_ref FROM navigator.ai_user_toolkit_overrides")
        names = await conn.fetch_all("SELECT name FROM navigator.ai_user_credentials")
    assert {r["agent_ref"] for r in left} == {ref_b}
    assert not [r for r in names if ref_a in r["name"]]
    assert await secret(f"toolkit_jira_{ref_b}_user") == {"token": "me-B"}
    await _tenant_agent(client, "acme")
    resp = await client.put("/acme/agents/sales/toolkits/jira", json={"params": {"server_url": "https://x"},
                                                                       "user_overridable": ["token"]})
    assert resp.status == 200
    fresh = await (await client.get("/acme/agents/sales/toolkits/jira/me")).json()
    assert fresh["configured"] is False and fresh["params"] == {}
