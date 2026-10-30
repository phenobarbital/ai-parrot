"""Unit tests for the metadata-preserving Identity Vault re-seal helpers."""

from __future__ import annotations

import pytest
from navigator_auth.identity.crypto import IdentityCipher
from navigator_auth.identity.store import IdentityCredentialError
from navigator_session.vault import KeyRing

from parrot.services.identity_credential_sink import (
    list_credential_rows,
    reseal_identity_row,
    verify_active_only,
)

KEYS = {1: b"1" * 32, 2: b"2" * 32}
CTX = {"user_id": 7, "auth_provider": "atlassian", "provider_user_id": "acct-1"}


class _Tx:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


class _Raw:
    def __init__(self, rows):
        self.rows = rows
        self.updates = []

    def transaction(self):
        return _Tx()

    async def fetch(self, query, *args):
        rows = self.rows
        if args:
            rows = [r for r in rows if r["auth_provider"] in args[0]]
        return list(rows)

    async def fetchrow(self, query, *args):
        return next((r for r in self.rows if r["identity_id"] == args[0]), None)

    async def execute(self, query, *args):
        self.updates.append((query, args))
        row = next(r for r in self.rows if r["identity_id"] == args[0])
        assignments = query.split(" SET ", 1)[1].split(" WHERE ", 1)[0].split(", ")
        for assignment, value in zip(assignments, args[1:], strict=True):
            row[assignment.split(" = ", 1)[0]] = value


class _Ctx:
    def __init__(self, raw):
        self.raw = raw

    async def __aenter__(self):
        return self.raw

    async def __aexit__(self, *exc):
        return False


class _Pool:
    def __init__(self, rows):
        self.raw = _Raw(rows)

    async def acquire(self):
        return _Ctx(self.raw)


def _cipher(ids, active):
    return IdentityCipher(keyring=KeyRing({i: KEYS[i] for i in ids}, active))


def _row(old, new, enabled=True, tokens=("access_token", "refresh_token", "id_token")):
    row = {"identity_id": "id-1", **CTX, "enabled": enabled, "key_version": 2}
    for field in ("access_token", "refresh_token", "id_token"):
        if field in tokens:
            cipher = old if field == "id_token" else new
            row[field] = cipher.encrypt(f"{field}-value", field=field, **CTX)
        else:
            row[field] = None
    return row


@pytest.mark.asyncio
async def test_reseal_mixed_key_row_then_active_only_verifies():
    old, new = _cipher([1], 1), _cipher([2], 2)
    ring = _cipher([1, 2], 2)
    row = _row(old, new)
    assert not verify_active_only(row, active_cipher=new)
    pool = _Pool([row])
    await reseal_identity_row(pool, row, cipher=ring)
    assert verify_active_only(pool.raw.rows[0], active_cipher=new)
    assert new.decrypt(pool.raw.rows[0]["id_token"], field="id_token", **CTX) == "id_token-value"


@pytest.mark.asyncio
async def test_reencrypt_preserves_disabled_metadata():
    old, new = _cipher([1], 1), _cipher([2], 2)
    row = _row(old, new, enabled=False, tokens=("access_token", "id_token"))
    pool = _Pool([row])
    await reseal_identity_row(pool, row, cipher=_cipher([1, 2], 2))
    stored = pool.raw.rows[0]
    assert stored["enabled"] is False
    assert stored["refresh_token"] is None
    assert stored["key_version"] == 2
    query = pool.raw.updates[0][0]
    assert "enabled" not in query and "auth_data" not in query and "scopes" not in query
    assert "refresh_token" not in query


@pytest.mark.asyncio
async def test_undecryptable_row_untouched():
    old, new = _cipher([1], 1), _cipher([2], 2)
    row = _row(old, new)
    before = dict(row)
    pool = _Pool([row])
    with pytest.raises(IdentityCredentialError):
        await reseal_identity_row(pool, row, cipher=new)  # ring lacks key 1
    assert pool.raw.updates == []
    assert pool.raw.rows[0] == before


@pytest.mark.asyncio
async def test_list_credential_rows_filters_providers():
    old, new = _cipher([1], 1), _cipher([2], 2)
    other = {**_row(old, new), "identity_id": "id-2", "auth_provider": "github"}
    pool = _Pool([_row(old, new), other])
    assert len(await list_credential_rows(pool, [])) == 2
    assert [r["identity_id"] for r in await list_credential_rows(pool, ["github"])] == ["id-2"]
