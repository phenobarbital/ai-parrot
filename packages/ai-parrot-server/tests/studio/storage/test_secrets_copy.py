"""FEAT-621 phase 2 — DocumentDB → Postgres secrets copy (spec §2.10, AC21).

Real Postgres pool and a real vault ``KeyRing``. NO DocumentDB is available in CI, so the SOURCE is an in-memory
stand-in (``_FakeDocumentDb``) implemented here: an async context manager whose ``read(collection, query)`` returns
copies of the seeded documents, the only DocumentDB surface ``secrets_copy`` uses. What is *not* exercised is the
real DocumentDB driver (``DocumentDb.read`` against a live server).
"""
from __future__ import annotations

import asyncio
import copy
import logging
import os
from datetime import datetime

import pytest
from navigator_session.vault import KeyRing

from parrot.handlers.studio.storage import byok_store as byok_module
from parrot.handlers.studio.storage import secrets_copy as copy_module
from parrot.handlers.studio.storage import vault_store as vault_module
from parrot.handlers.studio.storage.byok_store import PgUserLLMKeyStore
from parrot.handlers.studio.storage.overrides_store import PgToolkitOverrideStore
from parrot.handlers.studio.storage.secrets_copy import DSN_ENV, copy_secrets, main
from parrot.handlers.studio.storage.vault_store import PgVaultCredentialStore
from parrot.security.credentials_utils import credential_context, encrypt_credential, llm_key_context

KEYRING = KeyRing({1: b"1" * 32, 3: b"3" * 32}, 3)
API_KEY = "sk-ant-SECRETKEY1234"
VAULT_SECRET = {"password": "hunter2-VAULT", "note": "ñ"}
CREATED = "2025-01-02T03:04:05+00:00"
UPDATED = "2025-02-03T04:05:06+00:00"
TABLES = ("ai_user_llm_keys", "ai_user_credentials", "ai_user_toolkit_overrides")


class _FakeDocumentDb:
    """In-memory stand-in for ``parrot.interfaces.documentdb.DocumentDb`` (read-only surface)."""

    def __init__(self, collections: dict[str, list[dict]]) -> None:
        self.collections = collections

    async def __aenter__(self) -> "_FakeDocumentDb":
        return self

    async def __aexit__(self, *exc) -> None:
        return None

    async def read(self, collection: str, query: dict | None = None) -> list[dict]:
        assert not query, "the copy reads whole collections"
        return copy.deepcopy(self.collections.get(collection, []))


def _seed() -> dict[str, list[dict]]:
    # BYOK sealed under key id 1 (not the active 3): a re-encrypting copy would change it.
    byok_sealed = encrypt_credential({"api_key": API_KEY}, llm_key_context("u1", "anthropic"), KEYRING, key_id=1)
    vault_sealed = encrypt_credential(VAULT_SECRET, credential_context("u1", "toolkit_x_studio-agent:abc"), KEYRING)
    return {
        "user_llm_keys": [{
            "_id": "oid1", "user_id": "u1", "provider": "anthropic", "api_key": byok_sealed,
            "created_at": CREATED, "updated_at": UPDATED,
        }],
        "user_credentials": [{
            "_id": "oid2", "user_id": "u1", "name": "toolkit_x_studio-agent:abc", "credential": vault_sealed,
            "created_at": CREATED, "updated_at": UPDATED,
        }],
        "user_toolkit_configs": [{
            "_id": "oid3", "user_id": "u1", "agent_id": "studio-agent:abc", "slug": "x",
            "params": {"region": "eu"}, "secret_refs": {"password": "toolkit_x_studio-agent:abc"},
            "updated_at": UPDATED,
        }],
    }


@pytest.fixture(autouse=True)
def _keyring(monkeypatch):
    for module in (copy_module, byok_module, vault_module):
        monkeypatch.setattr(module, "get_vault_keyring", lambda: KEYRING)


@pytest.fixture
async def pool(studio_pool):
    async def _truncate():
        async with studio_pool.acquire() as conn:
            for table in TABLES:
                await conn.execute(f"TRUNCATE navigator.{table}")

    await _truncate()
    yield studio_pool
    await _truncate()


async def _count(pool, table: str) -> int:
    async with pool.acquire() as conn:
        row = await conn.fetch_one(f"SELECT count(*) AS n FROM navigator.{table}")
    return row["n"]


async def _run(pool, seed=None, **flags):
    flags = {"byok": True, "vault": True, "overrides": True, "dry_run": False, **flags}
    return await copy_secrets(pool, source=_FakeDocumentDb(seed or _seed()), **flags)


async def test_copy_verbatim_and_decrypts(pool):
    seed = _seed()
    counts = await _run(pool, seed)
    assert counts == {"byok": 1, "vault": 1, "overrides": 1, "skipped": 0, "failed": 0}
    async with pool.acquire() as conn:
        key_row = await conn.fetch_one("SELECT * FROM navigator.ai_user_llm_keys")
        cred_row = await conn.fetch_one("SELECT * FROM navigator.ai_user_credentials")
    # byte-compatible: the stored ciphertext IS the DocumentDB string, still sealed under its original key id
    assert key_row["api_key_enc"] == seed["user_llm_keys"][0]["api_key"]
    assert key_row["key_id"] == 1 and key_row["masked"] == "sk-…1234"
    assert cred_row["credential"] == seed["user_credentials"][0]["credential"]
    assert key_row["created_at"].isoformat() == CREATED and cred_row["updated_at"].isoformat() == UPDATED
    # and the Postgres stores open them
    assert await PgUserLLMKeyStore(pool).get("u1", "anthropic") == API_KEY
    assert await PgVaultCredentialStore(pool).retrieve("u1", "toolkit_x_studio-agent:abc") == VAULT_SECRET
    [override] = await PgToolkitOverrideStore(pool).load("u1", "studio-agent:abc")
    assert override.params == {"region": "eu"} and override.secret_refs == {"password": "toolkit_x_studio-agent:abc"}
    assert override.updated_at == UPDATED


async def test_dry_run_writes_nothing(pool):
    counts = await _run(pool, dry_run=True)
    assert counts == {"byok": 1, "vault": 1, "overrides": 1, "skipped": 0, "failed": 0}
    assert [await _count(pool, t) for t in TABLES] == [0, 0, 0]


async def test_switches_select_collections(pool):
    counts = await _run(pool, byok=False, vault=True, overrides=False)
    assert counts == {"byok": 0, "vault": 1, "overrides": 0, "skipped": 0, "failed": 0}
    assert [await _count(pool, t) for t in TABLES] == [0, 1, 0]


async def test_no_values_logged_and_bad_docs_counted(pool, caplog):
    seed = _seed()
    bad_sealed = encrypt_credential({"api_key": "sk-OTHER-USER-KEY"}, llm_key_context("u2", "openai"), KEYRING)
    # sealed for u2 but filed under u1: the AAD check fails, the document is reported, never copied
    seed["user_llm_keys"].append({"user_id": "u1", "provider": "openai", "api_key": bad_sealed})
    # malformed (no provider): reported through the KeyError path, ciphertext must not leak either
    malformed_sealed = encrypt_credential({"api_key": "sk-MALFORMED"}, llm_key_context("u1", "x"), KEYRING)
    seed["user_llm_keys"].append({"user_id": "u1", "api_key": malformed_sealed})
    caplog.set_level(logging.DEBUG)
    counts = await _run(pool, seed)
    assert counts["byok"] == 1 and counts["failed"] == 2
    assert await _count(pool, "ai_user_llm_keys") == 1
    secrets = [API_KEY, "hunter2-VAULT", "sk-OTHER-USER-KEY", bad_sealed, malformed_sealed, "sk-MALFORMED"]
    secrets += [seed["user_llm_keys"][0]["api_key"], seed["user_credentials"][0]["credential"]]
    for secret in secrets:
        assert secret not in caplog.text
    assert "u1" in caplog.text and "openai" in caplog.text  # identities (not values) are what gets logged


EDITED = "2024-01-01T00:00:00+00:00"
NEWER = "2031-01-01T00:00:00+00:00"
OLDER = "2020-01-01T00:00:00+00:00"
_EDIT_SQL = {
    "ai_user_llm_keys": "UPDATE navigator.ai_user_llm_keys SET api_key_enc = 'USER-EDITED', masked = 'edited', "
                        "updated_at = $1::timestamptz",
    "ai_user_credentials": "UPDATE navigator.ai_user_credentials SET credential = 'USER-EDITED', "
                           "updated_at = $1::timestamptz",
    "ai_user_toolkit_overrides": "UPDATE navigator.ai_user_toolkit_overrides SET params = '{\"edited\": true}'::jsonb, "
                                 "updated_at = $1::timestamptz",
}
_READ_SQL = {
    "ai_user_llm_keys": "SELECT api_key_enc AS v, updated_at FROM navigator.ai_user_llm_keys",
    "ai_user_credentials": "SELECT credential AS v, updated_at FROM navigator.ai_user_credentials",
    "ai_user_toolkit_overrides": "SELECT params::text AS v, updated_at FROM navigator.ai_user_toolkit_overrides",
}


async def _edit_all(pool, when: str) -> None:
    async with pool.acquire() as conn:
        for table, sql in _EDIT_SQL.items():
            await conn.execute(sql, datetime.fromisoformat(when))


async def _snapshot(pool) -> dict:
    async with pool.acquire() as conn:
        return {t: dict(await conn.fetch_one(sql)) for t, sql in _READ_SQL.items()}


def _with_updated(seed: dict, when: str) -> dict:
    for docs in seed.values():
        for doc in docs:
            doc["updated_at"] = when
    return seed


async def test_rerun_after_cutover_never_overwrites_edited_rows(pool):
    await _run(pool)
    await _edit_all(pool, EDITED)
    before = await _snapshot(pool)
    # even a strictly newer source must not win without --overwrite
    counts = await _run(pool, _with_updated(_seed(), NEWER))
    assert counts == {"byok": 0, "vault": 0, "overrides": 0, "skipped": 3, "failed": 0}
    assert await _snapshot(pool) == before
    assert [await _count(pool, t) for t in TABLES] == [1, 1, 1]


async def test_overwrite_updates_only_strictly_newer(pool):
    await _run(pool)
    await _edit_all(pool, EDITED)
    before = await _snapshot(pool)
    for older in (OLDER, EDITED):  # older and EQUAL sources leave the row untouched
        counts = await _run(pool, _with_updated(_seed(), older), overwrite=True)
        assert counts["skipped"] == 3 and counts["byok"] == counts["vault"] == counts["overrides"] == 0
        assert await _snapshot(pool) == before
    seed = _with_updated(_seed(), NEWER)
    counts = await _run(pool, seed, overwrite=True)
    assert counts == {"byok": 1, "vault": 1, "overrides": 1, "skipped": 0, "failed": 0}
    after = await _snapshot(pool)
    assert after["ai_user_llm_keys"]["v"] == seed["user_llm_keys"][0]["api_key"]
    assert after["ai_user_credentials"]["v"] == seed["user_credentials"][0]["credential"]
    assert "region" in after["ai_user_toolkit_overrides"]["v"]
    assert all(row["updated_at"].isoformat() == NEWER for row in after.values())  # timestamp preserved


async def test_overwrite_undated_source_never_wins(pool):
    await _run(pool)
    await _edit_all(pool, EDITED)
    before = await _snapshot(pool)
    seed = _seed()
    for docs in seed.values():
        for doc in docs:
            doc.pop("updated_at", None)
            doc.pop("created_at", None)
    counts = await _run(pool, seed, overwrite=True)
    assert counts["skipped"] == 3 and await _snapshot(pool) == before


def _seed_with_failures() -> dict:
    seed = _seed()
    wrong_aad = encrypt_credential({"api_key": "sk-OTHER-USER-KEY"}, llm_key_context("u2", "openai"), KEYRING)
    seed["user_llm_keys"].append({"user_id": "u1", "provider": "openai", "api_key": wrong_aad})
    seed["user_llm_keys"].append({"user_id": "u1", "api_key": wrong_aad})  # malformed: no provider
    vault_wrong = encrypt_credential(VAULT_SECRET, credential_context("u2", "other"), KEYRING)
    seed["user_credentials"].append({"user_id": "u1", "name": "v2", "credential": vault_wrong})
    seed["user_credentials"].append({"user_id": "u1", "name": "v3", "credential": "not-a-ciphertext"})
    seed["user_toolkit_configs"].append({"user_id": "u1", "slug": "no-agent"})  # malformed override
    return seed


async def test_dry_run_predicts_failures_like_a_real_run_and_writes_nothing(pool):
    dry = await _run(pool, _seed_with_failures(), dry_run=True)
    assert [await _count(pool, t) for t in TABLES] == [0, 0, 0]
    real = await _run(pool, _seed_with_failures())
    assert dry == real == {"byok": 1, "vault": 1, "overrides": 1, "skipped": 0, "failed": 5}


async def test_dry_run_without_keyring_reports_clear_error_and_counts_failed(pool, monkeypatch, caplog):
    def _missing():
        raise RuntimeError("Vault keys are not configured: boom")

    monkeypatch.setattr(copy_module, "get_vault_keyring", _missing)
    caplog.set_level(logging.DEBUG)
    counts = await _run(pool, dry_run=True)
    assert counts == {"byok": 0, "vault": 0, "overrides": 1, "skipped": 0, "failed": 2}
    assert "vault keyring unavailable" in caplog.text and "VAULT_MASTER_KEY" in caplog.text
    assert "Traceback" not in caplog.text and [await _count(pool, t) for t in TABLES] == [0, 0, 0]


def test_cli_rejects_dsn_argument(monkeypatch, capsys):
    monkeypatch.setenv(DSN_ENV, "postgresql://u:pw@h/db")
    with pytest.raises(SystemExit) as exc:
        main(["--dsn", "postgresql://u:SECRETPW@h/db"])
    err = capsys.readouterr().err
    assert exc.value.code == 2 and "--dsn is not accepted" in err and "SECRETPW" not in err


def test_cli_requires_dsn_env(monkeypatch, capsys):
    monkeypatch.delenv(DSN_ENV, raising=False)
    with pytest.raises(SystemExit) as exc:
        main(["--dry-run"])
    assert exc.value.code == 2 and DSN_ENV in capsys.readouterr().err


def _fake_source(monkeypatch) -> None:
    real_copy = copy_module.copy_secrets

    async def _with_fake(pool_, **kwargs):
        return await real_copy(pool_, source=_FakeDocumentDb(_seed()), **kwargs)

    monkeypatch.setattr(copy_module, "copy_secrets", _with_fake)


async def test_cli_reads_dsn_from_env_and_never_logs_it(pool, monkeypatch, capsys, caplog):
    dsn = os.environ["TEST_STUDIO_PG_DSN"]
    monkeypatch.setenv(DSN_ENV, dsn)
    _fake_source(monkeypatch)
    caplog.set_level(logging.DEBUG)
    code = await asyncio.to_thread(main, ["--byok"])  # asyncio.run needs its own thread inside a running loop
    out = capsys.readouterr()
    assert code == 0 and await _count(pool, "ai_user_llm_keys") == 1
    password = dsn.split("@")[0].rsplit(":", 1)[-1]
    for text in (out.out, out.err, caplog.text):
        assert dsn not in text and (len(password) < 4 or password not in text)


async def test_cli_connects_with_the_env_dsn_only(monkeypatch):
    """A DSN that cannot connect in the env must be the one used (not any other configured DSN)."""
    monkeypatch.setenv(DSN_ENV, "postgresql://nobody:pw@127.0.0.1:1/none")
    _fake_source(monkeypatch)  # the source is faked, so only the unreachable DSN can make this raise
    with pytest.raises(Exception):  # noqa: B017 — the driver's connection error type is not part of the contract
        await asyncio.to_thread(main, ["--dry-run", "--overrides"])


def test_cli_flags():
    args = copy_module._build_parser().parse_args(["--dry-run", "--overwrite", "--byok"])
    assert args.dry_run and args.overwrite and args.byok and not args.vault and not args.overrides
