"""Unit tests for the transactional Identity Vault credential store."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from parrot.services.identity_credential_sink import IdentityVaultCredentialStore


class _Transaction:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, traceback):
        return False


class _RawConnection:
    def __init__(self):
        self.rows = []
        self.executed = []

    def transaction(self):
        return _Transaction()

    async def fetch(self, query, *args):
        if query.startswith("SELECT"):
            return [
                {"identity_id": row["identity_id"], "provider_user_id": row["provider_user_id"]}
                for row in self.rows
                if row["user_id"] == args[0] and row["auth_provider"] == args[1]
            ]
        return []

    async def fetchrow(self, query, *args):
        rows = await self.fetch(query.replace("LIMIT 1 FOR UPDATE", "FOR UPDATE"), *args)
        return rows[0] if rows else None

    async def execute(self, query, *args):
        self.executed.append((query, args))
        if query.startswith("INSERT"):
            columns = query.split("(", 1)[1].split(")", 1)[0].split(", ")
            self.rows.append(dict(zip(columns, args, strict=False)))
        elif query.startswith("UPDATE"):
            identity_id = args[0]
            row = next(row for row in self.rows if row["identity_id"] == identity_id)
            if "user_id = $2" in query:
                values = args[2:]
            else:
                values = args[1:]
            assignments = query.split(" SET ", 1)[1].split(" WHERE ", 1)[0].split(", ")
            for assignment, value in zip(assignments, values, strict=False):
                row[assignment.split(" = ", 1)[0]] = value
        elif query.startswith("DELETE"):
            if "identity_id <> $3" in query:
                self.rows = [row for row in self.rows if row["identity_id"] == args[2]]
            else:
                self.rows = [
                    row for row in self.rows if not (row["user_id"] == args[0] and row["auth_provider"] == args[1])
                ]
        return "OK"


class _ConnectionContext:
    def __init__(self, raw):
        self.raw = raw

    async def __aenter__(self):
        return self.raw

    async def __aexit__(self, exc_type, exc, traceback):
        return False


class _Pool:
    def __init__(self):
        self.raw = _RawConnection()

    async def acquire(self):
        return _ConnectionContext(self.raw)


class _Cipher:
    key_id = 4

    def encrypt(self, value, **kwargs):
        return f"sealed:{value}".encode()


def _payload(account_id: str, access_token: str = "access-a"):
    return {
        "account_id": account_id,
        "access_token": access_token,
        "refresh_token": "refresh-a",
        "expires_at": 1_900_000_000,
        "scopes": ["read"],
        "cloud_id": "cloud-a",
        "site_url": "https://example.atlassian.net",
    }


@pytest.mark.asyncio
async def test_identity_vault_store_roundtrip_any_provider(monkeypatch):
    """A provider-neutral minted payload is encrypted and metadata stays bounded."""
    pool = _Pool()
    store = IdentityVaultCredentialStore(pool, cipher=_Cipher())
    await store.save("42", "o365", _payload("account-a"), minted=True, principal=None, state_payload=None)

    row = pool.raw.rows[0]
    assert row["auth_provider"] == "o365"
    assert row["access_token"] == b"sealed:access-a"
    assert json.loads(row["auth_data"]) == {
        "account_id": "account-a",
        "cloud_id": "cloud-a",
        "site_url": "https://example.atlassian.net",
    }
    assert "access-a" not in row["auth_data"]

    identity = SimpleNamespace(
        provider_user_id="account-a",
        auth_data={"account_id": "account-a", "cloud_id": "cloud-a"},
    )
    token = SimpleNamespace(
        access_token="access-a",
        refresh_token="refresh-a",
        id_token=None,
        expires_at=datetime.fromtimestamp(1_900_000_000, tz=timezone.utc),
        scopes=["read"],
    )
    fake_identity_store = SimpleNamespace(
        get_by_provider=lambda user_id, provider: _async_value(identity),
        decrypt_credential=lambda current: token,
    )
    monkeypatch.setattr(store, "_store", lambda: fake_identity_store)
    assert await store.load("42", "o365") == {
        "access_token": "access-a",
        "refresh_token": "refresh-a",
        "expires_at": 1_900_000_000.0,
        "scopes": ["read"],
        "account_id": "account-a",
        "cloud_id": "cloud-a",
    }


async def _async_value(value):
    return value


@pytest.mark.asyncio
async def test_refresh_updates_selected_row_only():
    """A refresh for a replaced account is a no-op, while the selected one updates."""
    pool = _Pool()
    store = IdentityVaultCredentialStore(pool, cipher=_Cipher())
    await store.save("42", "jira", _payload("account-a"), minted=True, principal=None, state_payload=None)

    await store.save(
        "42",
        "jira",
        {"account_id": "account-old", "access_token": "stale", "expires_at": 1_900_000_001},
        minted=False,
        principal=None,
        state_payload=None,
    )
    assert pool.raw.rows[0]["access_token"] == b"sealed:access-a"

    await store.save(
        "42",
        "jira",
        {"account_id": "account-a", "access_token": "access-b", "expires_at": 1_900_000_001},
        minted=False,
        principal=None,
        state_payload=None,
    )
    assert pool.raw.rows[0]["access_token"] == b"sealed:access-b"


@pytest.mark.asyncio
async def test_delete_removes_all_rows_for_provider():
    """Disconnect uses one transaction and leaves other providers untouched."""
    pool = _Pool()
    store = IdentityVaultCredentialStore(pool, cipher=_Cipher())
    await store.save("42", "jira", _payload("account-a"), minted=True, principal=None, state_payload=None)
    await store.save("42", "o365", _payload("account-b"), minted=True, principal=None, state_payload=None)
    await store.delete("42", "jira")
    assert pool.raw.rows[0]["auth_provider"] == "o365"
