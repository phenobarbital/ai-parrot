"""Tests for IdentityMappingService (FEAT-108 / TASK-760, FEAT-729 / TASK-4664).

The write-path tests run against a REAL Postgres: mocking the pool is
exactly what hid the 42P10 (``ON CONFLICT (user_id, auth_provider)`` with
no matching unique index) for the lifetime of the old code.

Isolation: every test runs inside one transaction that is rolled back, so
nothing is ever committed (the ``auth.users`` FK is ``DEFERRABLE
INITIALLY DEFERRED`` and therefore never checked). The DSN comes from
``IDENTITY_PG_DSN`` (fallback: ``parrot.conf.default_dsn``); the suite
skips when Postgres is unreachable or the table predates navigator-auth
0.28.8.
"""

from __future__ import annotations

import os
import uuid
from typing import Any, AsyncIterator

import pytest

from parrot.services.identity_mapping import (
    IdentityMappingService,
    _decode_auth_data,
)


class TestDecodeAuthData:
    """_decode_auth_data helper handles dict, str, bytes, None, bad JSON."""

    def test_none(self):
        assert _decode_auth_data(None) == {}

    def test_dict_passthrough(self):
        d = {"key": "value"}
        assert _decode_auth_data(d) == d

    def test_json_string(self):
        assert _decode_auth_data('{"a": 1}') == {"a": 1}

    def test_json_bytes(self):
        assert _decode_auth_data(b'{"a": 1}') == {"a": 1}

    def test_malformed_json_returns_empty(self):
        assert _decode_auth_data("not json") == {}


# --------------------------------------------------------------------------
# Real-Postgres fixture
# --------------------------------------------------------------------------


def _dsn() -> str | None:
    dsn = os.environ.get("IDENTITY_PG_DSN")
    if dsn:
        return dsn
    try:
        from parrot.conf import default_dsn

        return default_dsn or None
    except Exception:  # noqa: BLE001
        return None


# Shape of auth.user_identities after navigator-auth 0.28.8 (verified on the
# dev database 2026-10-23), minus the FK to auth.users.
_LIVE_SCHEMA_DDL = """
CREATE SCHEMA IF NOT EXISTS auth;
CREATE TABLE auth.user_identities (
    identity_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id bigint NOT NULL,
    auth_provider varchar,
    auth_data jsonb,
    attributes jsonb,
    created_at timestamptz,
    provider_user_id varchar,
    scopes jsonb,
    access_token bytea,
    refresh_token bytea,
    id_token bytea,
    token_type varchar,
    expires_at timestamptz,
    refreshed_at timestamptz,
    enabled boolean DEFAULT true,
    key_version integer,
    display_name varchar,
    title varchar,
    nickname varchar,
    email varchar,
    phone varchar,
    short_bio text,
    avatar text
);
CREATE INDEX idx_user_identities_user ON auth.user_identities (user_id, auth_provider);
CREATE UNIQUE INDEX uq_user_identities_provider_account
    ON auth.user_identities (user_id, auth_provider, provider_user_id)
    WHERE provider_user_id IS NOT NULL;
"""


class _SingleConnPool:
    """Pool facade over one connection, supporting every acquire pattern.

    ``async with pool.acquire()`` (IdentityMappingService) and
    ``async with await pool.acquire()`` (navigator-auth IdentityStore) both
    yield the same connection, so every write shares the test transaction.
    """

    def __init__(self, conn: Any) -> None:
        self._conn = conn

    def acquire(self) -> "_SingleConnPool._Ctx":
        return _SingleConnPool._Ctx(self._conn)

    class _Ctx:
        def __init__(self, conn: Any) -> None:
            self._conn = conn

        def __await__(self):
            async def _self():
                return self

            return _self().__await__()

        async def __aenter__(self) -> Any:
            return self._conn

        async def __aexit__(self, *exc: Any) -> bool:
            return False


@pytest.fixture
async def authdb_pool() -> AsyncIterator[_SingleConnPool]:
    """A pool bound to one asyncdb connection inside a rolled-back transaction."""
    dsn = _dsn()
    if not dsn:
        pytest.skip("no Postgres DSN (set IDENTITY_PG_DSN)")
    try:
        from asyncdb import AsyncDB

        db = AsyncDB("pg", dsn=dsn, timeout=10)
        await db.connection()
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"Postgres unreachable: {exc}")
    raw = db.engine()
    exists = await raw.fetchval("SELECT to_regclass('auth.user_identities') IS NOT NULL")
    has_index = await raw.fetchval(
        "SELECT count(*) FROM pg_indexes WHERE schemaname='auth' "
        "AND tablename='user_identities' AND indexdef LIKE '%provider_user_id%'"
    )
    if exists and not has_index:
        await db.close()
        pytest.skip("auth.user_identities predates navigator-auth 0.28.8")
    tx = raw.transaction()
    await tx.start()
    if not exists:
        # Scratch database: create the post-0.28.8 table inside the
        # transaction (DDL is transactional, so the rollback removes it).
        await raw.execute(_LIVE_SCHEMA_DDL)
    try:
        yield _SingleConnPool(db)
    finally:
        await tx.rollback()
        await db.close()


def _uid() -> str:
    """A random bigint-compatible user id (never committed)."""
    return str(9_000_000_000 + uuid.uuid4().int % 1_000_000_000)


async def _rows(pool: _SingleConnPool, user_id: str, provider: str) -> list:
    async with pool.acquire() as conn:
        return await conn.engine().fetch(
            "SELECT * FROM auth.user_identities WHERE user_id = $1::text::bigint AND auth_provider = $2",
            user_id,
            provider,
        )


class TestUpsertAgainstRealPostgres:
    async def test_row_lands_and_reads_back(self, authdb_pool):
        """The write the 42P10 used to kill now produces a readable row."""
        service = IdentityMappingService(authdb_pool)
        user = _uid()
        tg_id = f"tg-{uuid.uuid4().hex[:8]}"
        await service.upsert_identity(
            nav_user_id=user,
            auth_provider="telegram",
            provider_user_id=tg_id,
            auth_data={"telegram_id": tg_id, "username": "jdoe"},
            display_name="John",
            email="j@example.com",
        )
        found = await service.get_identity(user, "telegram")
        assert found is not None
        assert found["provider_user_id"] == tg_id
        assert found["auth_data"] == {"telegram_id": tg_id, "username": "jdoe"}
        assert found["display_name"] == "John"
        assert found["email"] == "j@example.com"
        assert [r["auth_provider"] for r in await service.get_all_identities(user)] == ["telegram"]

        await service.delete_identity(user, "telegram")
        assert await service.get_identity(user, "telegram") is None

    async def test_second_write_updates_in_place(self, authdb_pool):
        """Same triple upserts rather than erroring or duplicating."""
        service = IdentityMappingService(authdb_pool)
        user = _uid()
        for tenant in ("t-1", "t-2"):
            await service.upsert_identity(
                nav_user_id=user,
                auth_provider="msteams",
                provider_user_id="aad-1",
                auth_data={"aad_object_id": "aad-1", "tenant_id": tenant},
            )
        rows = await _rows(authdb_pool, user, "msteams")
        assert len(rows) == 1
        assert _decode_auth_data(rows[0]["auth_data"])["tenant_id"] == "t-2"

        # A second account on the same provider is a second row (no unique
        # index on (user_id, auth_provider)).
        await service.upsert_identity(
            nav_user_id=user,
            auth_provider="msteams",
            provider_user_id="aad-2",
            auth_data={"aad_object_id": "aad-2"},
        )
        assert len(await _rows(authdb_pool, user, "msteams")) == 2

    async def test_null_provider_user_id_is_rejected(self, authdb_pool):
        """A NULL falls outside the partial index, so it must not be allowed."""
        service = IdentityMappingService(authdb_pool)
        user = _uid()
        for bad in (None, ""):
            with pytest.raises(ValueError):
                await service.upsert_identity(
                    nav_user_id=user,
                    auth_provider="slack",
                    provider_user_id=bad,
                    auth_data={"slack_user_id": "U1"},
                )
        assert await _rows(authdb_pool, user, "slack") == []

    async def test_write_failure_raises(self, authdb_pool):
        """A failing write propagates instead of being swallowed."""
        service = IdentityMappingService(authdb_pool)
        with pytest.raises(Exception):
            await service.upsert_identity(
                nav_user_id="not-a-bigint",
                auth_provider="slack",
                provider_user_id="U1",
                auth_data={},
            )


def _navigator_auth_version() -> tuple:
    from importlib.metadata import PackageNotFoundError, version

    try:
        return tuple(int(p) for p in version("navigator-auth").split(".")[:3])
    except (PackageNotFoundError, ValueError):
        return (0,)


class TestJiraCredentialPath:
    # navigator-auth 0.28.7 + python-datamodel 0.11.0: UserIdentity rejects
    # ``id_token=None`` ("Cannot convert None to bytes"), so a first insert of a
    # credential without an id_token (Jira 3LO never issues one) fails inside
    # IdentityStore.save_linked_identity. The task contract targets 0.28.8;
    # strict xfail flips to a real failure signal once the fixed version runs.
    @pytest.mark.xfail(
        _navigator_auth_version() < (0, 28, 8),
        reason="navigator-auth < 0.28.8 cannot insert a credential without id_token",
        strict=True,
    )
    async def test_token_is_ciphered_not_in_auth_data(self, authdb_pool):
        """The Jira site stores through IdentityStore; auth_data stays clean."""
        from navigator_auth.identity.crypto import IdentityCipher
        from navigator_auth.identity.store import IdentityStore
        from navigator_auth.identity.types import TokenResponse

        store = IdentityStore(authdb_pool, cipher=IdentityCipher(master_keys={1: os.urandom(32)}))
        service = IdentityMappingService(authdb_pool, identity_store=store)
        user = _uid()
        secret = f"atl-access-{uuid.uuid4().hex}"
        await service.upsert_identity(
            nav_user_id=user,
            auth_provider="jira",
            provider_user_id="acc-789",
            auth_data={"account_id": "acc-789", "cloud_id": "cloud-abc", "site_url": "https://x.atlassian.net"},
            display_name="Jane",
            email="jane@example.com",
            token=TokenResponse(access_token=secret, refresh_token="atl-refresh"),
        )
        rows = await _rows(authdb_pool, user, "jira")
        assert len(rows) == 1
        row = rows[0]
        auth_data = _decode_auth_data(row["auth_data"])
        assert auth_data["cloud_id"] == "cloud-abc"
        assert secret not in str(auth_data)
        assert "access_token" not in auth_data
        assert secret.encode() not in bytes(row["access_token"])

        identity = await store.get_by_provider(int(user), "jira")
        assert identity is not None
        credential = store.decrypt_credential(identity)
        assert credential.access_token == secret
        assert credential.refresh_token == "atl-refresh"
        assert credential.provider_user_id == "acc-789"

    async def test_secret_in_auth_data_is_rejected(self, authdb_pool):
        """auth_data never carries a cleartext token."""
        service = IdentityMappingService(authdb_pool)
        with pytest.raises(ValueError):
            await service.upsert_identity(
                nav_user_id=_uid(),
                auth_provider="jira",
                provider_user_id="acc-1",
                auth_data={"access_token": "leak"},
            )
