"""Credentials handler vault-store dispatch coverage."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio
from navigator_session.vault import KeyRing

from parrot.handlers.credentials import CredentialsHandler
from parrot.handlers.studio.storage.vault_store import PgVaultCredentialStore
from parrot.security import vault_utils
from parrot.userstore.testing import redis_test_settings

KEYRING = KeyRing({1: b"1" * 32}, 1)


@pytest_asyncio.fixture
async def redis_vault(monkeypatch: pytest.MonkeyPatch):
    """Use an isolated Redis vault and deterministic encryption key."""
    monkeypatch.delenv("VAULT_STORE", raising=False)
    monkeypatch.delenv("PARROT_USER_STORE", raising=False)
    monkeypatch.setattr(vault_utils, "_PG_VAULT_STORE", None)
    monkeypatch.setattr(vault_utils, "_REDIS_VAULT_STORE", None)
    monkeypatch.setattr(vault_utils, "get_vault_keyring", lambda: KEYRING)
    async with redis_test_settings(monkeypatch):
        yield


def _handler(session: dict[str, object], name: str | None = None) -> CredentialsHandler:
    """Construct a direct-invocation handler with simple response doubles."""
    handler = CredentialsHandler.__new__(CredentialsHandler)
    handler.logger = MagicMock()
    handler._session = session
    handler.request = MagicMock()
    handler.request.match_info.get = MagicMock(return_value=name)
    handler.json_response = MagicMock(side_effect=lambda data, status=200: MagicMock(status=status, data=data))
    handler.error = MagicMock(side_effect=lambda message, status=400: MagicMock(status=status, message=message))
    return handler


async def test_credentials_handler_uses_vault_utils(redis_vault) -> None:
    """All handler verbs dispatch to the Redis-selected vault store."""
    session: dict[str, object] = {"user_id": "u1"}
    missing = await _handler(session, "pg").get()
    assert missing.status == 404

    create = _handler(session)
    create.request.json = AsyncMock(return_value={"name": "pg", "driver": "pg", "params": {"host": "one"}})
    assert (await create.post()).status == 201
    assert (await create.post()).status == 409
    found = await _handler(session, "pg").get()
    assert found.status == 200 and found.data["params"] == {"host": "one"}
    assert (await _handler(session, "pg").delete()).status == 200
    assert (await _handler(session, "pg").get()).status == 404


async def test_credentials_put_no_duplicate(redis_vault) -> None:
    """A repeated PUT updates the single stored Redis credential."""
    session: dict[str, object] = {"user_id": "u1"}
    await vault_utils.store_vault_credential("u1", "pg", {"driver": "pg", "params": {"host": "one"}})
    for host in ("two", "three"):
        handler = _handler(session, "pg")
        handler.request.json = AsyncMock(return_value={"name": "ignored", "driver": "pg", "params": {"host": host}})
        assert (await handler.put()).status == 200
    assert await vault_utils.list_vault_credentials("u1") == {"pg": {"driver": "pg", "params": {"host": "three"}}}


async def test_pg_vault_list_and_exists(monkeypatch: pytest.MonkeyPatch) -> None:
    """Postgres listing decrypts rows and existence probes the configured key."""
    rows = [
        {
            "name": "pg",
            "credential": vault_utils.encrypt_credential(
                {"driver": "pg", "params": {}}, vault_utils.credential_context("u1", "pg"), KEYRING
            ),
        }
    ]
    conn = MagicMock()
    conn.fetch_all = AsyncMock(return_value=rows)
    conn.fetch_one = AsyncMock(return_value=rows[0])
    pool = MagicMock()
    pool.acquire.return_value.__aenter__ = AsyncMock(return_value=conn)
    pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)
    from parrot.handlers.studio.storage import vault_store

    monkeypatch.setattr(vault_store, "get_vault_keyring", lambda: KEYRING)
    store = PgVaultCredentialStore(pool)
    assert await store.list_credentials("u1") == {"pg": {"driver": "pg", "params": {}}}
    assert await store.exists("u1", "pg") is True
