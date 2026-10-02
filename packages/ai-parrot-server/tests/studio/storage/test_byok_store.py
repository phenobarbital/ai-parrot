"""FEAT-621 phase 2 — test_byok_pg_roundtrip (AC21), M11 (spec §2.10).

Real Postgres pool, real aiohttp app with a real ``SessionData`` middleware, real vault ``KeyRing``.
DocumentDB is replaced by a class that raises on construction: any contact with it fails the test.
"""
from __future__ import annotations

import pytest
from aiohttp import web
from navigator_session.data import SessionData
from navigator_session.vault import KeyRing

import parrot.auth.broker as broker_module
import parrot.interfaces.documentdb as documentdb_module
from parrot.auth.broker import _UserLLMKeyResolver
from parrot.handlers.studio import byok as byok_module
from parrot.handlers.studio import setup_studio_routes
from parrot.handlers.studio.byok import resolve_user_api_key
from parrot.handlers.studio.storage import byok_store as store_module
from parrot.handlers.studio.storage.byok_store import PgUserLLMKeyStore, register_byok_store
from parrot.security.credentials_utils import decrypt_credential, encrypt_credential, llm_key_context

KEYRING = KeyRing({1: b"1" * 32, 3: b"3" * 32}, 3)
KEY = "sk-ant-abcdef1234"


class _DocumentDbForbidden:
    def __init__(self, *a, **k):
        raise AssertionError("DocumentDB was contacted with BYOK_STORE=postgres")


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setattr(store_module, "get_vault_keyring", lambda: KEYRING)
    monkeypatch.setattr(byok_module, "get_vault_keyring", lambda: KEYRING)
    import parrot.security.vault_utils as vault_utils

    monkeypatch.setattr(vault_utils, "get_vault_keyring", lambda: KEYRING)
    monkeypatch.setattr(documentdb_module, "DocumentDb", _DocumentDbForbidden)
    monkeypatch.setattr(byok_module, "DocumentDb", _DocumentDbForbidden)
    monkeypatch.setenv("BYOK_STORE", "postgres")
    yield
    register_byok_store(None)


@pytest.fixture
async def pool(studio_pool):
    async with studio_pool.acquire() as conn:
        await conn.execute("TRUNCATE navigator.ai_user_llm_keys")
    yield studio_pool
    async with studio_pool.acquire() as conn:
        await conn.execute("TRUNCATE navigator.ai_user_llm_keys")


async def _row(pool, user_id="u1", provider="anthropic"):
    async with pool.acquire() as conn:
        return await conn.fetch_one(
            "SELECT * FROM navigator.ai_user_llm_keys WHERE user_id=$1 AND provider=$2", user_id, provider
        )


async def test_byok_pg_roundtrip(pool):
    store = PgUserLLMKeyStore(pool)
    await store.put("u1", "anthropic", KEY)
    row = await _row(pool)
    assert decrypt_credential(row["api_key_enc"], llm_key_context("u1", "anthropic"), KEYRING) == {"api_key": KEY}
    assert row["key_id"] == 3 and row["masked"] == "sk-…1234" and KEY not in row["masked"]
    assert await store.get("u1", "anthropic") == KEY
    assert await store.get("u1", "openai") is None
    assert await store.get("u2", "anthropic") is None
    listed = await store.list_masked("u1")
    assert [(k["provider"], k["masked"]) for k in listed] == [("anthropic", "sk-…1234")]
    assert await store.delete("u1", "anthropic") is True
    assert await store.delete("u1", "anthropic") is False
    assert await store.get("u1", "anthropic") is None


async def test_put_upserts_and_keeps_created_at(pool):
    store = PgUserLLMKeyStore(pool)
    await store.put("u1", "anthropic", KEY)
    first = await _row(pool)
    await store.put("u1", "anthropic", "sk-ant-rotated-9999")
    second = await _row(pool)
    assert second["created_at"] == first["created_at"]
    assert second["masked"] == "sk-…9999"
    assert await store.get("u1", "anthropic") == "sk-ant-rotated-9999"
    assert len(await store.list_masked("u1")) == 1


async def test_documentdb_ciphertext_copied_verbatim_decrypts(pool):
    sealed = encrypt_credential({"api_key": KEY}, llm_key_context("u1", "openai"), KEYRING, key_id=1)
    async with pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO navigator.ai_user_llm_keys (user_id, provider, api_key_enc, key_id, masked) "
            "VALUES ($1, $2, $3, $4, $5)",
            "u1", "openai", sealed, 1, "sk-…1234",
        )
    assert await PgUserLLMKeyStore(pool).get("u1", "openai") == KEY


async def test_startup_registers_byok_store_for_core_resolver_without_keys_call(pool, monkeypatch):
    """D4: ``ensure_studio_storage`` registers the store; the real core factory/resolver finds the key, no /keys call."""
    from parrot.auth.broker import CredentialResolverFactory
    from parrot.handlers.studio.storage import backend as backend_module

    monkeypatch.setenv("PARROT_STUDIO_STORAGE", "database")
    await PgUserLLMKeyStore(pool).put("u1", "anthropic", KEY)          # a sealed key already sits in Postgres
    register_byok_store(None)                                          # nothing registered yet
    app = web.Application()
    app["database"] = pool
    assert (await backend_module.ensure_studio_storage(app)).backend == "database"
    resolver = CredentialResolverFactory().build_user_llm_key_resolver()
    assert await resolver.resolve("Anthropic", "u1") == KEY
    assert await resolver.resolve("openai", "u1") is None
    assert await resolve_user_api_key(app, "u1", "anthropic") == KEY


async def test_resolver_fails_closed_when_postgres_store_unregistered(pool):
    register_byok_store(None)
    assert await _UserLLMKeyResolver().resolve("anthropic", "u1") is None


async def test_resolver_fails_closed_on_store_error(pool):
    class _Broken:
        async def get(self, *_a):
            raise RuntimeError("boom")

    broker_module.set_user_llm_key_store(_Broken())
    assert await _UserLLMKeyResolver().resolve("anthropic", "u1") is None


async def test_documentdb_setting_ignores_registered_store(pool, monkeypatch):
    monkeypatch.setenv("BYOK_STORE", "documentdb")
    await PgUserLLMKeyStore(pool).put("u1", "anthropic", KEY)
    register_byok_store(PgUserLLMKeyStore(pool))
    touched: list[bool] = []

    class _Counting:
        def __init__(self, *a, **k):
            touched.append(True)
            raise RuntimeError("documentdb down")

    monkeypatch.setattr(documentdb_module, "DocumentDb", _Counting)
    assert await _UserLLMKeyResolver().resolve("anthropic", "u1") is None
    assert touched == [True]


def _app(pool) -> web.Application:
    sessions: dict[str, SessionData] = {}

    @web.middleware
    async def _session(request, handler):
        user = request.headers.get("X-User", "u1")
        request["NAV_SESSION"] = sessions.setdefault(
            user, SessionData(data={"session": {"user_id": user, "groups": [], "superuser": True}})
        )
        request["authenticated"] = True
        return await handler(request)

    app = web.Application(middlewares=[_session])
    app["database"] = pool
    setup_studio_routes(app)
    return app


async def test_keys_handler_round_trip_through_postgres(aiohttp_client, pool):
    client = await aiohttp_client(_app(pool))
    resp = await client.post("/api/v1/astudio/keys", json={"provider": "anthropic", "api_key": KEY})
    assert resp.status == 201, await resp.text()
    assert (await resp.json())["masked"] == "sk-…1234"
    assert await PgUserLLMKeyStore(pool).get("u1", "anthropic") == KEY
    resp = await client.get("/api/v1/astudio/keys")
    body = await resp.json()
    assert body["count"] == 1 and body["keys"][0]["masked"] == "sk-…1234" and KEY not in str(body)
    other = await client.get("/api/v1/astudio/keys", headers={"X-User": "u2"})
    assert (await other.json())["count"] == 0
    resp = await client.delete("/api/v1/astudio/keys/anthropic")
    assert resp.status == 200
    assert await PgUserLLMKeyStore(pool).get("u1", "anthropic") is None


async def test_list_masked_excludes_quarantined_rows(pool):
    """A quarantine run renames ``provider`` with ``#quarantined:<run>``; such rows are not live keys."""
    from parrot.handlers.studio.storage.vault_targets import QUARANTINE_MARK

    store = PgUserLLMKeyStore(pool)
    await store.put("u1", "anthropic", KEY)
    await store.put("u1", "openai", "sk-openai-5678")
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE navigator.ai_user_llm_keys SET provider = provider || $1 WHERE user_id = 'u1' AND provider = 'openai'",
            QUARANTINE_MARK + "run1",
        )
    assert [k["provider"] for k in await store.list_masked("u1")] == ["anthropic"]
