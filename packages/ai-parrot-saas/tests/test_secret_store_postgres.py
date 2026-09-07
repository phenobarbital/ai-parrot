"""Integration tests for :class:`EncryptedPostgresSecretStore`.

These run against a real PostgreSQL instance (``SAAS_TEST_DSN``) because the
behaviour worth proving here is exactly the part a fake connection would fake:
that ciphertext really lands in the table, that rotation really rewrites rows,
and that nothing plaintext is ever persisted.
"""
from __future__ import annotations

import logging

import pytest
from asyncdb import AsyncDB

from parrot.security.audit_ledger import derive_key_fingerprint
from parrot.security.secrets.base import SecretDecryptionError
from parrot.security.secrets.envelope import EnvelopeCipher
from parrot.security.secrets.postgres import EncryptedPostgresSecretStore

pytestmark = pytest.mark.integration

SECRET = "sk-ant-api03-super-secret-value-never-log-me"


async def test_put_get_roundtrip(secret_store) -> None:
    """A stored secret decrypts back to the original value."""
    meta = await secret_store.put("bar-pepe", "anthropic:api_key", SECRET)

    assert meta.fingerprint == derive_key_fingerprint(SECRET)
    assert await secret_store.get("bar-pepe", "anthropic:api_key") == SECRET


async def test_get_missing_returns_none(secret_store) -> None:
    """An absent key is None rather than an error."""
    assert await secret_store.get("bar-pepe", "absent") is None


async def test_plaintext_is_never_persisted(
    secret_store, test_dsn: str, unique_schema: str
) -> None:
    """The secret must not appear anywhere in the stored row.

    Read back through raw SQL rather than the store, so the assertion cannot
    be satisfied by the store's own decryption path.
    """
    await secret_store.put("bar-pepe", "anthropic:api_key", SECRET)

    conn = AsyncDB("pg", dsn=test_dsn)
    async with await conn.connection():
        row = await conn.fetch_one(
            f"SELECT * FROM {unique_schema}.tenant_secrets "
            "WHERE tenant_id = $1 AND key = $2",
            "bar-pepe",
            "anthropic:api_key",
        )

    assert SECRET.encode() not in bytes(row["ciphertext"])
    assert SECRET not in str(dict(row))


async def test_secrets_are_tenant_scoped(secret_store) -> None:
    """The same key name under two tenants holds two different values."""
    await secret_store.put("bar-pepe", "anthropic:api_key", "value-a")
    await secret_store.put("hotel-x", "anthropic:api_key", "value-b")

    assert await secret_store.get("bar-pepe", "anthropic:api_key") == "value-a"
    assert await secret_store.get("hotel-x", "anthropic:api_key") == "value-b"


async def test_each_tenant_gets_its_own_data_key(
    secret_store, test_dsn: str, unique_schema: str
) -> None:
    """A per-tenant DEK means one compromised key is not a global compromise."""
    await secret_store.put("bar-pepe", "k", "a")
    await secret_store.put("hotel-x", "k", "b")

    conn = AsyncDB("pg", dsn=test_dsn)
    async with await conn.connection():
        rows = await conn.fetch_all(
            f"SELECT tenant_id, wrapped_dek FROM {unique_schema}.tenant_deks"
        )

    wrapped = {r["tenant_id"]: bytes(r["wrapped_dek"]) for r in rows}
    assert set(wrapped) == {"bar-pepe", "hotel-x"}
    assert wrapped["bar-pepe"] != wrapped["hotel-x"]


async def test_relocated_row_fails_to_decrypt(
    secret_store, test_dsn: str, unique_schema: str
) -> None:
    """Copying a ciphertext row to another tenant must not yield the secret.

    This is the AAD binding doing its job end-to-end, and it is the reason the
    store does not reuse the repository's ``encrypt_for_db`` helper.
    """
    await secret_store.put("bar-pepe", "anthropic:api_key", SECRET)
    await secret_store.put("hotel-x", "placeholder", "x")

    conn = AsyncDB("pg", dsn=test_dsn)
    async with await conn.connection():
        source = await conn.fetch_one(
            f"SELECT nonce, ciphertext FROM {unique_schema}.tenant_secrets "
            "WHERE tenant_id = 'bar-pepe' AND key = 'anthropic:api_key'"
        )
        victim_version = await conn.fetch_one(
            f"SELECT dek_version FROM {unique_schema}.tenant_deks "
            "WHERE tenant_id = 'hotel-x' AND active"
        )
        # Splice bar-pepe's ciphertext into hotel-x's row.
        await conn.execute(
            f"UPDATE {unique_schema}.tenant_secrets "
            "SET nonce = $1, ciphertext = $2, dek_version = $3 "
            "WHERE tenant_id = 'hotel-x' AND key = 'placeholder'",
            bytes(source["nonce"]),
            bytes(source["ciphertext"]),
            int(victim_version["dek_version"]),
        )

    with pytest.raises(SecretDecryptionError):
        await secret_store.get("hotel-x", "placeholder")


async def test_list_keys_is_scoped_and_valueless(secret_store) -> None:
    """A listing carries metadata for one tenant and no secret material."""
    await secret_store.put("bar-pepe", "google:api_key", "g")
    await secret_store.put("bar-pepe", "anthropic:api_key", SECRET)
    await secret_store.put("hotel-x", "google:api_key", "other")

    listing = await secret_store.list_keys("bar-pepe")

    assert [m.key for m in listing] == ["anthropic:api_key", "google:api_key"]
    assert SECRET not in repr(listing)


async def test_put_twice_updates_in_place(secret_store) -> None:
    """Re-uploading a key replaces the value and keeps created_at."""
    first = await secret_store.put("bar-pepe", "k", "one")
    second = await secret_store.put("bar-pepe", "k", "two")

    assert second.created_at == first.created_at
    assert second.updated_at >= first.updated_at
    assert await secret_store.get("bar-pepe", "k") == "two"


async def test_delete(secret_store) -> None:
    """delete() removes the row and reports whether it did."""
    await secret_store.put("bar-pepe", "k", SECRET)

    assert await secret_store.delete("bar-pepe", "k") is True
    assert await secret_store.delete("bar-pepe", "k") is False
    assert await secret_store.get("bar-pepe", "k") is None


# ---------------------------------------------------------------------------
# Rotation
# ---------------------------------------------------------------------------


async def test_rotate_dek_reencrypts_and_preserves_values(
    secret_store, test_dsn: str, unique_schema: str
) -> None:
    """A DEK rotation rewrites ciphertext while values stay readable."""
    await secret_store.put("bar-pepe", "anthropic:api_key", SECRET)
    await secret_store.put("bar-pepe", "google:api_key", "g-key")

    conn = AsyncDB("pg", dsn=test_dsn)
    async with await conn.connection():
        before = await conn.fetch_one(
            f"SELECT ciphertext, dek_version FROM {unique_schema}.tenant_secrets "
            "WHERE tenant_id = 'bar-pepe' AND key = 'anthropic:api_key'"
        )

    migrated = await secret_store.rotate_dek("bar-pepe")
    assert migrated == 2

    async with await conn.connection():
        after = await conn.fetch_one(
            f"SELECT ciphertext, dek_version FROM {unique_schema}.tenant_secrets "
            "WHERE tenant_id = 'bar-pepe' AND key = 'anthropic:api_key'"
        )

    assert int(after["dek_version"]) == int(before["dek_version"]) + 1
    assert bytes(after["ciphertext"]) != bytes(before["ciphertext"])
    assert await secret_store.get("bar-pepe", "anthropic:api_key") == SECRET
    assert await secret_store.get("bar-pepe", "google:api_key") == "g-key"


async def test_rotate_dek_leaves_exactly_one_active_key(
    secret_store, test_dsn: str, unique_schema: str
) -> None:
    """Only the newest data key stays active after a rotation."""
    await secret_store.put("bar-pepe", "k", SECRET)
    await secret_store.rotate_dek("bar-pepe")

    conn = AsyncDB("pg", dsn=test_dsn)
    async with await conn.connection():
        rows = await conn.fetch_all(
            f"SELECT dek_version, active FROM {unique_schema}.tenant_deks "
            "WHERE tenant_id = 'bar-pepe' ORDER BY dek_version"
        )

    assert [bool(r["active"]) for r in rows] == [False, True]


async def test_rotate_dek_does_not_touch_other_tenants(secret_store) -> None:
    """Rotation is tenant-scoped."""
    await secret_store.put("bar-pepe", "k", "a")
    await secret_store.put("hotel-x", "k", "b")

    await secret_store.rotate_dek("bar-pepe")

    assert await secret_store.get("hotel-x", "k") == "b"


async def test_rotate_kek_rewraps_deks_without_touching_ciphertext(
    test_dsn: str, unique_schema: str, master_keys: dict[int, bytes]
) -> None:
    """A master-key rotation re-wraps data keys and leaves values alone.

    That asymmetry is the whole reason for the envelope: rotating the master
    key is O(tenants), not O(secrets), and never rewrites customer data.
    """
    store_v1 = EncryptedPostgresSecretStore(
        test_dsn,
        schema=unique_schema,
        cipher=EnvelopeCipher(master_keys, active_key_id=1),
    )
    try:
        await store_v1.put("bar-pepe", "anthropic:api_key", SECRET)

        conn = AsyncDB("pg", dsn=test_dsn)
        async with await conn.connection():
            before = await conn.fetch_one(
                f"SELECT ciphertext FROM {unique_schema}.tenant_secrets "
                "WHERE tenant_id = 'bar-pepe' AND key = 'anthropic:api_key'"
            )
    finally:
        await store_v1.aclose()

    # Same data, new active master key.
    store_v2 = EncryptedPostgresSecretStore(
        test_dsn,
        schema=unique_schema,
        cipher=EnvelopeCipher(master_keys, active_key_id=2),
    )
    try:
        rewrapped = await store_v2.rotate_kek()
        assert rewrapped == 1

        conn = AsyncDB("pg", dsn=test_dsn)
        async with await conn.connection():
            dek_row = await conn.fetch_one(
                f"SELECT kek_id FROM {unique_schema}.tenant_deks "
                "WHERE tenant_id = 'bar-pepe'"
            )
            after = await conn.fetch_one(
                f"SELECT ciphertext FROM {unique_schema}.tenant_secrets "
                "WHERE tenant_id = 'bar-pepe' AND key = 'anthropic:api_key'"
            )

        assert int(dek_row["kek_id"]) == 2
        assert bytes(after["ciphertext"]) == bytes(before["ciphertext"])
        assert await store_v2.get("bar-pepe", "anthropic:api_key") == SECRET
    finally:
        await store_v2.aclose()


async def test_secret_never_appears_in_logs(
    secret_store, caplog: pytest.LogCaptureFixture
) -> None:
    """No code path may log secret material, at any level."""
    caplog.set_level(logging.DEBUG)

    await secret_store.put("bar-pepe", "anthropic:api_key", SECRET)
    await secret_store.get("bar-pepe", "anthropic:api_key")
    await secret_store.rotate_dek("bar-pepe")
    await secret_store.list_keys("bar-pepe")
    await secret_store.delete("bar-pepe", "anthropic:api_key")

    combined = "\n".join(r.getMessage() for r in caplog.records)
    assert SECRET not in combined
