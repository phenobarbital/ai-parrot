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


class _PoolAdapter:
    """Adapt asyncpg's pool acquire context to asyncdb's awaitable acquire API."""

    def __init__(self, pool: Any) -> None:
        self._pool = pool

    async def acquire(self):
        return self._pool.acquire()


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
    try:
        yield IdentityVaultCredentialStore(_PoolAdapter(pool)), user_id, provider
    finally:
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
    await store.save(user_id, provider, _payload("account-a", "token-a"), minted=True, principal=None, state_payload=None)
    await store.save(user_id, provider, _payload("account-b", "token-b"), minted=True, principal=None, state_payload=None)
    loaded = await store.load(user_id, provider)
    assert loaded is not None
    assert loaded["account_id"] == "account-b"
    assert loaded["access_token"] == "token-b"


@pytest.mark.asyncio
async def test_failure_inside_replacement_keeps_a(store_db) -> None:
    """A validation failure before SQL leaves the previously selected grant intact."""
    store, user_id, provider = store_db
    await store.save(user_id, provider, _payload("account-a", "token-a"), minted=True, principal=None, state_payload=None)
    with pytest.raises(ValueError, match="account_id"):
        await store.save(user_id, provider, {"access_token": "broken"}, minted=True, principal=None, state_payload=None)
    loaded = await store.load(user_id, provider)
    assert loaded is not None
    assert loaded["account_id"] == "account-a"


@pytest.mark.asyncio
async def test_disconnect_then_cold_load_returns_none(store_db) -> None:
    """Deleting a provider removes its durable row and cold load returns no grant."""
    store, user_id, provider = store_db
    await store.save(user_id, provider, _payload("account-a", "token-a"), minted=True, principal=None, state_payload=None)
    await store.delete(user_id, provider)
    assert await store.load(user_id, provider) is None
