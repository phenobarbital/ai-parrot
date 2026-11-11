"""Redis and backend-dispatch coverage for vault credentials."""

from __future__ import annotations

import pytest
import pytest_asyncio
from navigator_session.vault import KeyRing

from parrot.security import vault_utils
from parrot.security.credentials_utils import credential_context, encrypt_credential
from parrot.userstore import RedisDocumentStore
from parrot.userstore.collections import USER_CREDENTIALS
from parrot.userstore.testing import redis_test_settings

KEYRING = KeyRing({1: b"1" * 32}, 1)


@pytest.fixture
def keyring(monkeypatch: pytest.MonkeyPatch):
    """Install an isolated keyring and clear the cached ring around each test."""
    vault_utils.reset_vault_keyring()
    monkeypatch.setattr(vault_utils, "get_vault_keyring", lambda: KEYRING)
    yield KEYRING
    vault_utils.reset_vault_keyring()


@pytest_asyncio.fixture
async def redis_vault(monkeypatch: pytest.MonkeyPatch, keyring: KeyRing):
    """Configure an isolated Redis namespace and reset both store globals."""
    monkeypatch.delenv("VAULT_STORE", raising=False)
    monkeypatch.delenv("PARROT_USER_STORE", raising=False)
    monkeypatch.setattr(vault_utils, "_PG_VAULT_STORE", None)
    monkeypatch.setattr(vault_utils, "_REDIS_VAULT_STORE", None)
    async with redis_test_settings(monkeypatch):
        yield


async def test_redis_vault_round_trip_and_rewrite(redis_vault) -> None:
    """Redis supports CRUD, listing, existence checks, and stable creation time."""
    await vault_utils.store_vault_credential("u1", "jira", {"token": "first"})
    documents = RedisDocumentStore(USER_CREDENTIALS)
    first = await documents.get({"user_id": "u1", "name": "jira"})
    assert first is not None
    assert await vault_utils.retrieve_vault_credential("u1", "jira") == {"token": "first"}
    assert await vault_utils.list_vault_credentials("u1") == {"jira": {"token": "first"}}
    assert await vault_utils.vault_credential_exists("u1", "jira") is True

    await vault_utils.store_vault_credential("u1", "jira", {"token": "second"})
    rewritten = await documents.get({"user_id": "u1", "name": "jira"})
    assert rewritten is not None
    assert rewritten["created_at"] == first["created_at"]
    assert rewritten["updated_at"] >= first["updated_at"]
    assert await vault_utils.retrieve_vault_credential("u1", "jira") == {"token": "second"}

    await vault_utils.delete_vault_credential("u1", "jira")
    assert await vault_utils.vault_credential_exists("u1", "jira") is False
    with pytest.raises(KeyError, match="Vault credential 'jira' not found for user 'u1'"):
        await vault_utils.retrieve_vault_credential("u1", "jira")


async def test_redis_list_skips_undecryptable_credentials(redis_vault, caplog: pytest.LogCaptureFixture) -> None:
    """One invalid ciphertext does not prevent valid credentials from being listed."""
    await vault_utils.store_vault_credential("u1", "valid", {"token": "ok"})
    documents = RedisDocumentStore(USER_CREDENTIALS)
    await documents.put(
        {
            "user_id": "u1",
            "name": "invalid",
            "credential": "not-base64",
            "created_at": "2026-01-01T00:00:00+00:00",
            "updated_at": "2026-01-01T00:00:00+00:00",
        }
    )
    assert await vault_utils.list_vault_credentials("u1") == {"valid": {"token": "ok"}}
    assert "Skipping undecryptable credential 'invalid'" in caplog.text
    assert "not-base64" not in caplog.text


async def test_postgres_without_registered_store_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    """Explicit Postgres selection cannot silently fall back to DocumentDB."""
    monkeypatch.setenv("VAULT_STORE", "postgres")
    monkeypatch.setattr(vault_utils, "_PG_VAULT_STORE", None)

    class ForbiddenDocumentDb:
        """Raise if fail-closed dispatch contacts DocumentDB."""

        def __init__(self) -> None:
            raise AssertionError("DocumentDB was contacted")

    monkeypatch.setattr(vault_utils, "DocumentDb", ForbiddenDocumentDb)
    with pytest.raises(RuntimeError, match="no Postgres vault store is registered"):
        await vault_utils.retrieve_vault_credential("u1", "jira")


async def test_documentdb_inline_paths_are_preserved(monkeypatch: pytest.MonkeyPatch, keyring: KeyRing) -> None:
    """Explicit DocumentDB selection uses the existing inline CRUD and new helper paths."""
    monkeypatch.setenv("VAULT_STORE", "documentdb")
    monkeypatch.setattr(vault_utils, "_PG_VAULT_STORE", None)
    documents: list[dict] = []

    class FakeDocumentDb:
        """Minimal async DocumentDB double for vault operations."""

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, traceback):
            return None

        async def read(self, collection, query, limit=None, **kwargs):
            matches = [doc.copy() for doc in documents if all(doc.get(key) == value for key, value in query.items())]
            return matches[:limit] if limit else matches

        async def read_one(self, collection, query, **kwargs):
            matches = await self.read(collection, query, limit=1)
            return matches[0] if matches else None

        async def write(self, collection, document):
            documents.append(document.copy())

        async def update_one(self, collection, query, update):
            document = next(doc for doc in documents if all(doc.get(key) == value for key, value in query.items()))
            document.update(update["$set"])

        async def delete(self, collection, query):
            documents[:] = [doc for doc in documents if not all(doc.get(key) == value for key, value in query.items())]

    monkeypatch.setattr(vault_utils, "DocumentDb", FakeDocumentDb)
    await vault_utils.store_vault_credential("u1", "jira", {"token": "secret"})
    assert await vault_utils.retrieve_vault_credential("u1", "jira") == {"token": "secret"}
    assert await vault_utils.list_vault_credentials("u1") == {"jira": {"token": "secret"}}
    assert await vault_utils.vault_credential_exists("u1", "jira") is True
    await vault_utils.delete_vault_credential("u1", "jira")
    assert documents == []


async def test_documentdb_list_skips_undecryptable(monkeypatch: pytest.MonkeyPatch, keyring: KeyRing) -> None:
    """DocumentDB listing isolates decryption failures per credential."""
    monkeypatch.setenv("VAULT_STORE", "documentdb")
    valid = encrypt_credential({"token": "ok"}, credential_context("u1", "valid"), keyring)

    class FakeDocumentDb:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, traceback):
            return None

        async def read(self, collection, query):
            return [
                {"user_id": "u1", "name": "valid", "credential": valid},
                {"user_id": "u1", "name": "invalid", "credential": "invalid"},
            ]

    monkeypatch.setattr(vault_utils, "DocumentDb", FakeDocumentDb)
    assert await vault_utils.list_vault_credentials("u1") == {"valid": {"token": "ok"}}
