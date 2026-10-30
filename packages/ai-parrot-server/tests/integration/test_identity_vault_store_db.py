"""Real-Postgres AC-12 coverage for the Identity Vault credential store.

The suite is opt-in because it writes to an existing navigator-auth database:
set ``IDENTITY_PG_DSN``, ``IDENTITY_TEST_USER_ID`` and
``IDENTITY_VAULT_STORE_DB_TESTS=1`` to run it.
"""

from __future__ import annotations

import os
import uuid
from typing import Any, AsyncIterator

import pytest

from parrot.services.identity_credential_sink import IdentityVaultCredentialStore

asyncpg = pytest.importorskip("asyncpg")


@pytest.fixture
async def store_db() -> AsyncIterator[tuple[IdentityVaultCredentialStore, str, str]]:
    """Yield a store for an existing test user, skipping unreachable databases."""
    if os.getenv("IDENTITY_VAULT_STORE_DB_TESTS") != "1":
        pytest.skip("real Identity Vault tests are opt-in")
    dsn = os.getenv("IDENTITY_PG_DSN")
    user_id = os.getenv("IDENTITY_TEST_USER_ID")
    if not dsn or not user_id:
        pytest.skip("IDENTITY_PG_DSN and IDENTITY_TEST_USER_ID are required")
    try:
        pool = await asyncpg.create_pool(dsn)
        async with pool.acquire() as connection:
            exists = await connection.fetchval("SELECT to_regclass('auth.user_identities')")
            if not exists:
                pytest.skip("auth.user_identities is unavailable")
    except Exception as exc:  # pragma: no cover - depends on external Postgres
        pytest.skip(f"auth database is unreachable: {exc}")
    provider = f"task-4950-{uuid.uuid4()}"
    # The store reads through navigator-auth's IdentityStore, which needs the real asyncdb pool API.
    from asyncdb import AsyncPool

    store_pool = AsyncPool("pg", dsn=dsn)
    await store_pool.connect()
    try:
        yield IdentityVaultCredentialStore(store_pool), user_id, provider
    finally:
        await store_pool.close()
        async with pool.acquire() as connection:
            await connection.execute(
                "DELETE FROM auth.user_identities WHERE user_id = $1::bigint AND auth_provider = $2",
                int(user_id),
                provider,
            )
        await pool.close()


def _payload(account_id: str, access_token: str) -> dict[str, Any]:
    """Build a provider-neutral encrypted credential payload."""
    return {
        "account_id": account_id,
        "access_token": access_token,
        "refresh_token": f"refresh-{account_id}",
        "expires_at": 2_000_000_000,
        "scopes": ["read"],
        "display_name": "Task 4950",
        "email": "task-4950@example.test",
    }


@pytest.mark.asyncio
async def test_replace_a_with_b_then_cold_load_returns_b(store_db) -> None:
    """A minted reconnect leaves only account B and reloads it from Postgres."""
    store, user_id, provider = store_db
    await store.save(
        user_id, provider, _payload("account-a", "token-a"), minted=True, principal=None, state_payload=None
    )
    await store.save(
        user_id, provider, _payload("account-b", "token-b"), minted=True, principal=None, state_payload=None
    )
    loaded = await store.load(user_id, provider)
    assert loaded is not None
    assert loaded["account_id"] == "account-b"
    assert loaded["access_token"] == "token-b"


@pytest.mark.asyncio
async def test_failure_inside_replacement_keeps_a(store_db) -> None:
    """A validation failure before SQL leaves the previously selected grant intact."""
    store, user_id, provider = store_db
    await store.save(
        user_id, provider, _payload("account-a", "token-a"), minted=True, principal=None, state_payload=None
    )
    with pytest.raises(ValueError, match="account_id"):
        await store.save(user_id, provider, {"access_token": "broken"}, minted=True, principal=None, state_payload=None)
    loaded = await store.load(user_id, provider)
    assert loaded is not None
    assert loaded["account_id"] == "account-a"


@pytest.mark.asyncio
async def test_disconnect_then_cold_load_returns_none(store_db) -> None:
    """Deleting a provider removes its durable row and cold load returns no grant."""
    store, user_id, provider = store_db
    await store.save(
        user_id, provider, _payload("account-a", "token-a"), minted=True, principal=None, state_payload=None
    )
    await store.delete(user_id, provider)
    assert await store.load(user_id, provider) is None


@pytest.mark.asyncio
async def test_refresh_updates_selected_row_and_stale_account_fails_closed(store_db) -> None:
    """A refresh persists on the selected account; a stale/missing one raises and changes nothing."""
    from parrot.services.identity_credential_sink import StaleCredentialError

    store, user_id, provider = store_db
    await store.save(
        user_id, provider, _payload("account-a", "token-a"), minted=True, principal=None, state_payload=None
    )
    refreshed = {"account_id": "account-a", "access_token": "token-a2", "expires_at": 2_100_000_000}
    await store.save(user_id, provider, refreshed, minted=False, principal=None, state_payload=None)
    loaded = await store.load(user_id, provider)
    assert loaded is not None and loaded["access_token"] == "token-a2"
    assert loaded["refresh_token"] == "refresh-account-a"  # untouched when the response carries none

    stale = {"account_id": "account-OLD", "access_token": "token-old", "expires_at": 2_100_000_000}
    with pytest.raises(StaleCredentialError):
        await store.save(user_id, provider, stale, minted=False, principal=None, state_payload=None)
    again = await store.load(user_id, provider)
    assert again is not None and again["access_token"] == "token-a2"

    await store.delete(user_id, provider)
    with pytest.raises(StaleCredentialError):
        await store.save(user_id, provider, refreshed, minted=False, principal=None, state_payload=None)
    assert await store.load(user_id, provider) is None


@pytest.mark.asyncio
async def test_legacy_migration_upsert_creates_the_durable_row(store_db) -> None:
    """minted=True (used by legacy migration) creates the row when none exists; minted=False cannot."""
    from parrot.services.identity_credential_sink import StaleCredentialError

    store, user_id, provider = store_db
    payload = _payload("account-m", "token-m")
    with pytest.raises(StaleCredentialError):
        await store.save(user_id, provider, payload, minted=False, principal=None, state_payload=None)
    await store.save(user_id, provider, payload, minted=True, principal=None, state_payload=None)
    loaded = await store.load(user_id, provider)
    assert loaded is not None and loaded["access_token"] == "token-m"


@pytest.mark.asyncio
async def test_reseal_preserves_metadata_and_verifies_against_a_fresh_row(store_db) -> None:
    """Re-seal keeps enabled/scopes/expiry; the fresh re-read verifies under the active key only."""
    from navigator_auth.identity.crypto import IdentityCipher

    from parrot.services.identity_credential_sink import (
        _raw_connection,
        fetch_credential_row,
        list_credential_rows,
        reseal_identity_row,
        verify_active_only,
    )

    store, user_id, provider = store_db
    await store.save(
        user_id, provider, _payload("account-r", "token-r"), minted=True, principal=None, state_payload=None
    )
    pool = store._db_pool
    async with await pool.acquire() as conn:
        await _raw_connection(conn).execute(
            "UPDATE auth.user_identities SET enabled = FALSE WHERE user_id = $1::bigint AND auth_provider = $2",
            int(user_id),
            provider,
        )
    rows = await list_credential_rows(pool, [provider])
    assert len(rows) == 1 and rows[0]["enabled"] is False  # disabled rows are included

    cipher = IdentityCipher()
    await reseal_identity_row(pool, rows[0], cipher=cipher)
    fresh = await fetch_credential_row(pool, rows[0]["identity_id"])
    assert fresh is not None
    assert fresh["enabled"] is False  # metadata preserved
    assert verify_active_only(fresh, active_cipher=cipher) is True
    assert await fetch_credential_row(pool, "00000000-0000-0000-0000-000000000000") is None
