"""FEAT-621 phase 2 — test_vault_pg_roundtrip (AC21, vault half) + rotation targets, M12 (spec §2.10).

Real Postgres pool and a real vault ``KeyRing``. DocumentDB is replaced by a class that raises on construction:
any contact with it fails the test.
"""
from __future__ import annotations

import importlib
import tomllib
from pathlib import Path

import pytest
from aiohttp import web
from navigator_session.vault import KeyRing
from navigator_session.vault.key_rotation import rotate_master_key
from navigator_session.vault.registry import ProtectedTarget

import parrot.security.vault_utils as vault_utils
from parrot.handlers.studio.storage import backend as backend_module
from parrot.handlers.studio.storage import vault_store as store_module
from parrot.handlers.studio.storage import vault_targets as targets_module
from parrot.handlers.studio.storage.vault_store import PgVaultCredentialStore, register_vault_store
from parrot.handlers.studio.storage.vault_targets import PgUserCredentialsTarget, PgUserLlmKeysTarget
from parrot.security.credentials_utils import (
    credential_context,
    decrypt_credential,
    encrypt_credential,
    llm_key_context,
)

KEYRING = KeyRing({1: b"1" * 32, 3: b"3" * 32}, 3)
OLD_RING = KeyRing({1: b"1" * 32, 3: b"3" * 32}, 1)
SECRET = {"api_key": "sk-123", "note": "ñ"}
PYPROJECT = Path(__file__).resolve().parents[3] / "pyproject.toml"


class _DocumentDbForbidden:
    def __init__(self, *a, **k):
        raise AssertionError("DocumentDB was contacted with VAULT_STORE=postgres")


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setattr(store_module, "get_vault_keyring", lambda: KEYRING)
    monkeypatch.setattr(vault_utils, "get_vault_keyring", lambda: KEYRING)
    monkeypatch.setattr(vault_utils, "DocumentDb", _DocumentDbForbidden)
    yield
    register_vault_store(None)


@pytest.fixture
async def pool(studio_pool):
    tables = "navigator.ai_user_credentials, navigator.ai_user_llm_keys"
    async with studio_pool.acquire() as conn:
        await conn.execute(f"TRUNCATE {tables}")
    yield studio_pool
    async with studio_pool.acquire() as conn:
        await conn.execute(f"TRUNCATE {tables}")


async def _row(pool, user_id="u1", name="mcp_x_agent-1"):
    async with pool.acquire() as conn:
        return await conn.fetch_one(
            "SELECT * FROM navigator.ai_user_credentials WHERE user_id=$1 AND name=$2", user_id, name
        )


async def test_vault_pg_roundtrip(pool):
    register_vault_store(PgVaultCredentialStore(pool))
    await vault_utils.store_vault_credential("u1", "mcp_x_agent-1", SECRET)
    row = await _row(pool)
    assert decrypt_credential(row["credential"], credential_context("u1", "mcp_x_agent-1"), KEYRING) == SECRET
    assert "sk-123" not in row["credential"]
    assert await vault_utils.retrieve_vault_credential("u1", "mcp_x_agent-1") == SECRET
    created = row["created_at"]
    await vault_utils.store_vault_credential("u1", "mcp_x_agent-1", {"api_key": "sk-new"})
    again = await _row(pool)
    assert again["created_at"] == created and again["credential"] != row["credential"]
    assert (await vault_utils.retrieve_vault_credential("u1", "mcp_x_agent-1")) == {"api_key": "sk-new"}
    with pytest.raises(KeyError):
        await vault_utils.retrieve_vault_credential("u2", "mcp_x_agent-1")
    await vault_utils.delete_vault_credential("u1", "mcp_x_agent-1")
    await vault_utils.delete_vault_credential("u1", "mcp_x_agent-1")  # absent is not an error
    assert await _row(pool) is None
    with pytest.raises(KeyError):
        await vault_utils.retrieve_vault_credential("u1", "mcp_x_agent-1")


async def test_vault_pg_aad_rejects_swapped_row(pool):
    """A ciphertext copied to another user fails to open (same AAD as DocumentDB)."""
    store = PgVaultCredentialStore(pool)
    await store.store("u1", "n", SECRET)
    async with pool.acquire() as conn:
        await conn.fetch_one(
            "UPDATE navigator.ai_user_credentials SET user_id='u2' WHERE user_id='u1' RETURNING name"
        )
    with pytest.raises(Exception):  # VaultCryptoError
        await store.retrieve("u2", "n")


async def test_default_stays_documentdb():
    """Without a registered store the DocumentDB path is used (switch default ``documentdb``)."""
    with pytest.raises(AssertionError, match="DocumentDB was contacted"):
        await vault_utils.retrieve_vault_credential("u1", "n")


async def test_startup_registers_store_only_when_switch_is_postgres(pool, monkeypatch):
    monkeypatch.setenv("VAULT_STORE", "postgres")
    monkeypatch.setenv("PARROT_STUDIO_STORAGE", "database")
    app = web.Application()
    app["database"] = pool
    storage = await backend_module.ensure_studio_storage(app)
    assert storage.backend == "database", storage.reason
    assert vault_utils._PG_VAULT_STORE is not None
    await vault_utils.store_vault_credential("u1", "via-startup", SECRET)
    assert (await _row(pool, name="via-startup")) is not None
    register_vault_store(None)
    monkeypatch.setenv("VAULT_STORE", "documentdb")
    app2 = web.Application()
    app2["database"] = pool
    await backend_module.ensure_studio_storage(app2)
    assert vault_utils._PG_VAULT_STORE is None


async def test_startup_fails_closed_when_backend_is_not_database(pool, monkeypatch):
    """VAULT_STORE=postgres on a host whose studio backend is the filesystem must not stay on DocumentDB."""
    monkeypatch.setenv("VAULT_STORE", "postgres")
    monkeypatch.setenv("PARROT_STUDIO_STORAGE", "filesystem")
    app = web.Application()
    app["database"] = pool
    with pytest.raises(backend_module.StudioStorageMisconfigured, match="VAULT_STORE"):
        await backend_module.ensure_studio_storage(app)
    assert vault_utils._PG_VAULT_STORE is None


def test_vault_targets_entry_points_load():
    """Both entry points are declared next to ``parrot_users_bots`` and load as ``ProtectedTarget`` factories."""
    declared = tomllib.loads(PYPROJECT.read_text())["project"]["entry-points"]["navigator_session.vault_targets"]
    assert "parrot_users_bots" in declared
    expected = {
        "parrot_studio_user_credentials": PgUserCredentialsTarget,
        "parrot_studio_user_llm_keys": PgUserLlmKeysTarget,
    }
    for ep_name, cls in expected.items():
        module, _, attr = declared[ep_name].partition(":")
        factory = getattr(importlib.import_module(module), attr)
        assert factory({}) is None and factory({"db_pool": None}) is None
        target = factory({"parrot_db_pool": object()})
        assert isinstance(target, cls) and isinstance(target, ProtectedTarget)
    factories = (targets_module.user_credentials_factory, targets_module.user_llm_keys_factory)
    names = {f({"db_pool": object()}).name for f in factories}
    assert names == {"pg:ai_user_credentials", "pg:ai_user_llm_keys"}


async def _llm_key(pool, user_id, provider, ring):
    sealed = encrypt_credential({"api_key": "sk-ant"}, llm_key_context(user_id, provider), ring)
    async with pool.acquire() as conn:
        await conn.fetch_one(
            "INSERT INTO navigator.ai_user_llm_keys (user_id, provider, api_key_enc, key_id, masked) "
            "VALUES ($1,$2,$3,$4,'m') RETURNING provider", user_id, provider, sealed, ring.active_key_id,
        )


async def test_rotation_reseals_both_tables_and_quarantine_restores(pool, monkeypatch):
    monkey_store = PgVaultCredentialStore(pool)  # sealed under OLD_RING (active key 1) below
    for i in range(5):  # more rows than the batch size: keyset pagination
        monkeypatch.setattr(store_module, "get_vault_keyring", lambda: OLD_RING)
        await monkey_store.store(f"u{i}", f"n{i}", {"api_key": f"k{i}"})
    await _llm_key(pool, "u1", "anthropic", OLD_RING)
    creds, keys = PgUserCredentialsTarget(pool), PgUserLlmKeysTarget(pool)
    results = await rotate_master_key([creds, keys], 1, 3, KEYRING, batch_size=2)
    assert results[creds.name]["rotated"] == 5 and results[creds.name]["errors"] == 0
    assert results[keys.name]["rotated"] == 1 and results[keys.name]["errors"] == 0
    monkeypatch.setattr(store_module, "get_vault_keyring", lambda: KEYRING)
    assert await monkey_store.retrieve("u3", "n3") == {"api_key": "k3"}
    async with pool.acquire() as conn:
        key = await conn.fetch_one("SELECT key_id FROM navigator.ai_user_llm_keys WHERE user_id='u1'")
    assert key["key_id"] == 3
    again = await rotate_master_key([creds, keys], 1, 3, KEYRING)
    assert again[creds.name]["skipped"] == 5

    rows = [r async for batch in creds.iter_batches(10) for r in batch]
    victim = next(r for r in rows if r.identity["name"] == "n2")
    records: list[dict] = []

    class _Sink:
        async def write(self, target, record):
            records.append(record)

    assert await creds.export_raw(_Sink()) == 5
    await creds.quarantine(victim, "bad", "run1")
    with pytest.raises(KeyError):
        await monkey_store.retrieve("u2", "n2")
    assert len([r async for b in creds.iter_batches(10) for r in b]) == 4

    class _Source:
        async def read(self, target):
            for rec in records:
                yield rec

    assert await creds.restore_raw(_Source()) == 5
    assert await monkey_store.retrieve("u2", "n2") == {"api_key": "k2"}
    async with pool.acquire() as conn:
        left = await conn.fetch_all("SELECT name FROM navigator.ai_user_credentials WHERE name LIKE '%#quarantined:%'")
    assert not left
