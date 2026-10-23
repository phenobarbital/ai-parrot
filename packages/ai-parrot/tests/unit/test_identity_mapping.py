"""Tests for IdentityMappingService (FEAT-108 / TASK-760, TASK-4664).

The write path is exercised against a **real** Postgres: the pool-mocking
tests this file used to hold are exactly why ``issue:0115386145f2`` — every
single ``upsert_identity`` call failing with ``42P10`` — stayed invisible for
the lifetime of the code. A mock cannot have a unique index.

Point ``TEST_AUTHDB_DSN`` at a database carrying the navigator ``auth``
schema to run them (e.g.
``postgres://user:pwd@127.0.0.1:5432/navigator``); without it the
database-backed tests skip.
"""
import json
import os
import uuid

import pytest

from parrot.services.identity_mapping import (
    IdentityMappingService,
    IdentityWriteError,
    _coerce_user_id,
    _decode_auth_data,
)

DSN = os.environ.get("TEST_AUTHDB_DSN", "")

requires_authdb = pytest.mark.skipif(
    not DSN, reason="TEST_AUTHDB_DSN not set"
)


@pytest.fixture
async def authdb_pool():
    """A real asyncdb pool — the driver production injects as ``app['authdb']``.

    Function-scoped on purpose: pytest-asyncio gives each test its own event
    loop, and an asyncpg pool cannot be shared across loops.
    """
    if not DSN:
        pytest.skip("TEST_AUTHDB_DSN not set")
    from asyncdb import AsyncPool

    pool = AsyncPool("pg", dsn=DSN)
    try:
        await pool.connect()
        async with await pool.acquire() as conn:
            await conn.fetch_one("SELECT 1 AS ok")
    except Exception as err:  # noqa: BLE001 — unreachable DB is a skip, not a failure
        pytest.skip(f"auth database unreachable: {err}")
    yield pool
    await pool.close()


@pytest.fixture
async def owner_id(authdb_pool):
    """An existing ``auth.users`` row to hang identities off (FK target)."""
    async with await authdb_pool.acquire() as conn:
        row = await conn.fetch_one(
            "SELECT user_id FROM auth.users ORDER BY user_id LIMIT 1"
        )
    if row is None:
        pytest.skip("auth.users is empty")
    return row["user_id"]


@pytest.fixture
async def provider(authdb_pool):
    """A provider key unique to this test, cleaned up afterwards."""
    name = f"pytest-{uuid.uuid4().hex[:10]}"
    yield name
    async with await authdb_pool.acquire() as conn:
        await conn.execute(
            "DELETE FROM auth.user_identities WHERE auth_provider = $1", name
        )


@pytest.fixture
def service(authdb_pool):
    return IdentityMappingService(authdb_pool)


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


class TestCoerceUserId:
    """``auth.user_identities.user_id`` is bigint; a bound str is rejected."""

    def test_digit_string_becomes_int(self):
        assert _coerce_user_id("35") == 35

    def test_int_passthrough(self):
        assert _coerce_user_id(35) == 35

    def test_uuid_like_passthrough(self):
        value = "7b3c1a4e-0000-4000-8000-000000000000"
        assert _coerce_user_id(value) == value


class TestProviderUserIdIsRequired:
    """A NULL falls outside the partial index, so it must not be allowed."""

    async def test_none_is_rejected(self):
        service = IdentityMappingService(db_pool=None)
        with pytest.raises(IdentityWriteError, match="provider_user_id is required"):
            await service.upsert_identity(
                nav_user_id="1",
                auth_provider="telegram",
                provider_user_id=None,
                auth_data={},
            )

    async def test_blank_is_rejected(self):
        service = IdentityMappingService(db_pool=None)
        with pytest.raises(IdentityWriteError, match="provider_user_id is empty"):
            await service.upsert_identity(
                nav_user_id="1",
                auth_provider="telegram",
                provider_user_id="   ",
                auth_data={},
            )


@requires_authdb
class TestUpsertAgainstRealPostgres:
    """The writes the 42P10 used to kill, against the real table."""

    async def test_row_lands_and_reads_back(self, service, owner_id, provider):
        written = await service.upsert_identity(
            nav_user_id=owner_id,
            auth_provider=provider,
            provider_user_id="acct-1",
            auth_data={"telegram_id": 483920114, "username": "jane"},
            display_name="Jane Doe",
            email="jane@example.com",
        )
        assert written["provider_user_id"] == "acct-1"

        stored = await service.get_identity(owner_id, provider, "acct-1")
        assert stored is not None
        assert stored["auth_data"] == {"telegram_id": 483920114, "username": "jane"}
        assert stored["display_name"] == "Jane Doe"
        assert stored["email"] == "jane@example.com"
        assert stored["identity_id"] == written["identity_id"]

    async def test_second_write_updates_in_place(self, service, owner_id, provider):
        first = await service.upsert_identity(
            nav_user_id=owner_id,
            auth_provider=provider,
            provider_user_id="acct-1",
            auth_data={"v": 1},
            display_name="Jane Doe",
        )
        second = await service.upsert_identity(
            nav_user_id=owner_id,
            auth_provider=provider,
            provider_user_id="acct-1",
            auth_data={"v": 2},
        )
        assert second["identity_id"] == first["identity_id"]
        assert second["auth_data"] == {"v": 2}
        # COALESCE keeps a value the second write did not carry.
        assert second["display_name"] == "Jane Doe"

        rows = [
            row
            for row in await service.get_all_identities(owner_id)
            if row["auth_provider"] == provider
        ]
        assert len(rows) == 1

    async def test_string_user_id_is_accepted(self, service, owner_id, provider):
        """Every call site passes ``str(nav_user_id)`` into a bigint column."""
        await service.upsert_identity(
            nav_user_id=str(owner_id),
            auth_provider=provider,
            provider_user_id="acct-str",
            auth_data={"from": "string"},
        )
        stored = await service.get_identity(str(owner_id), provider, "acct-str")
        assert stored is not None and stored["auth_data"] == {"from": "string"}

    async def test_two_accounts_on_one_provider_coexist(
        self, service, owner_id, provider
    ):
        """The partial index keys on the account, not just the provider."""
        await service.upsert_identity(
            nav_user_id=owner_id,
            auth_provider=provider,
            provider_user_id="acct-a",
            auth_data={"n": "a"},
        )
        await service.upsert_identity(
            nav_user_id=owner_id,
            auth_provider=provider,
            provider_user_id="acct-b",
            auth_data={"n": "b"},
        )
        rows = [
            row
            for row in await service.get_all_identities(owner_id)
            if row["auth_provider"] == provider
        ]
        assert {r["provider_user_id"] for r in rows} == {"acct-a", "acct-b"}

    async def test_delete_is_account_scoped(self, service, owner_id, provider):
        for account in ("acct-a", "acct-b"):
            await service.upsert_identity(
                nav_user_id=owner_id,
                auth_provider=provider,
                provider_user_id=account,
                auth_data={},
            )
        await service.delete_identity(owner_id, provider, "acct-a")
        rows = [
            row
            for row in await service.get_all_identities(owner_id)
            if row["auth_provider"] == provider
        ]
        assert [r["provider_user_id"] for r in rows] == ["acct-b"]

    async def test_write_failure_raises_instead_of_being_swallowed(
        self, service, provider
    ):
        """asyncdb's execute() returns errors instead of raising — the service
        must not inherit that silence (the second half of the original bug)."""
        with pytest.raises(IdentityWriteError):
            await service.upsert_identity(
                nav_user_id=-99_999_999,  # no such auth.users row -> FK violation
                auth_provider=provider,
                provider_user_id="acct-x",
                auth_data={},
            )


@requires_authdb
class TestJiraCredentialPath:
    """The Jira site stores through IdentityStore; auth_data stays clean."""

    @pytest.fixture
    def token_response(self):
        try:
            from navigator_auth.identity.crypto import IdentityCipher
            from navigator_auth.identity.types import TokenResponse
        except ImportError as err:  # pragma: no cover
            pytest.skip(f"navigator-auth identity vault unavailable: {err}")
        try:
            IdentityCipher()
        except Exception as err:  # noqa: BLE001 — missing vault keys is a skip
            pytest.skip(f"vault master keys not configured: {err}")
        return TokenResponse(
            access_token="jira-access-token-secret",
            refresh_token="jira-refresh-token-secret",
            scopes=["read:jira-work", "offline_access"],
            provider_user_id="5f1a:acct",
        )

    async def test_token_is_ciphered_not_in_auth_data(
        self, service, authdb_pool, owner_id, provider, token_response
    ):
        from navigator_auth.identity.store import IdentityStore

        await service.upsert_identity(
            nav_user_id=owner_id,
            auth_provider=provider,
            provider_user_id="5f1a:acct",
            auth_data={
                "account_id": "5f1a:acct",
                "cloud_id": "cloud-123",
                "site_url": "https://example.atlassian.net",
            },
            display_name="Jane Doe",
            email="jane@example.com",
            token=token_response,
        )

        stored = await service.get_identity(owner_id, provider, "5f1a:acct")
        assert stored is not None
        serialized = json.dumps(stored["auth_data"])
        assert "jira-access-token-secret" not in serialized
        assert "jira-refresh-token-secret" not in serialized
        # The provider coordinates IdentityStore drops are merged back in.
        assert stored["auth_data"]["cloud_id"] == "cloud-123"
        assert stored["display_name"] == "Jane Doe"

        store = IdentityStore(authdb_pool)
        identity = await store.get_for_provider_account(
            owner_id, provider, "5f1a:acct"
        )
        assert identity is not None
        assert isinstance(identity.access_token, (bytes, bytearray, memoryview))
        # decrypt_credential is sync (the task contract listed it as async).
        opened = store.decrypt_credential(identity)
        assert opened.access_token == "jira-access-token-secret"
        assert opened.refresh_token == "jira-refresh-token-secret"

    async def test_mismatched_account_is_refused(
        self, service, owner_id, provider, token_response
    ):
        """A token sealed for another account must not be written."""
        with pytest.raises(IdentityWriteError, match="does not match"):
            await service.upsert_identity(
                nav_user_id=owner_id,
                auth_provider=provider,
                provider_user_id="some-other-account",
                auth_data={},
                token=token_response,
            )
