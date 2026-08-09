"""Encrypted Postgres implementation of :class:`SecretStore`.

Stores each secret as AES-GCM ciphertext under a per-tenant data key, itself
wrapped by the deployment's vault master key. See
:mod:`parrot.security.secrets.envelope` for the cryptography and for why the
AAD binding matters in a multi-tenant system.

Rotation is crash-safe without an explicit transaction because **every secret
row records the data-key version that encrypted it**. A rotation interrupted
half-way leaves some rows on the old version and some on the new, and both
remain readable; the only lost work is the re-encryption that had not run yet,
which a re-run completes.
"""
from __future__ import annotations

import re
import time
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Tuple

from asyncdb import AsyncDB
from navconfig.logging import logging

from ..audit_ledger import derive_key_fingerprint
from .base import SecretMeta, SecretStore, SecretStoreError
from .envelope import (
    EncryptedValue,
    EnvelopeCipher,
    WrappedDEK,
    generate_dek,
)

#: Schema and table names are interpolated into SQL (they cannot be bound as
#: parameters), so they are validated before any statement is issued.
_IDENT_RE = re.compile(r"^[a-z_][a-z0-9_]*$")


def _check_identifier(value: str, what: str) -> str:
    """Validate a SQL identifier.

    Args:
        value: Candidate schema or table name.
        what: Human-readable role, used in the error message.

    Returns:
        ``value`` unchanged.

    Raises:
        ValueError: If it does not match :data:`_IDENT_RE`.
    """
    if not _IDENT_RE.match(value):
        raise ValueError(f"unsafe {what} name: {value!r}")
    return value


class EncryptedPostgresSecretStore(SecretStore):
    """Per-tenant encrypted secret storage backed by PostgreSQL.

    Args:
        dsn: PostgreSQL DSN.
        schema: Schema owning the tables.
        dek_table: Table holding wrapped per-tenant data keys.
        secrets_table: Table holding encrypted values.
        cipher: Envelope cipher. Defaults to one built from the environment's
            ``VAULT_MASTER_KEY_v{N}`` / ``VAULT_ACTIVE_KEY_ID``.
        dek_cache_ttl: Seconds an unwrapped data key may stay in memory.
        audit_ledger: Optional :class:`~parrot.security.audit_ledger.AuditLedger`.
            When supplied, every mutation is recorded; only the fingerprint is
            stored, never the material.

    Raises:
        MasterKeyUnavailable: If no usable master key material is configured.
            Constructed eagerly and deliberately: a store that cannot encrypt
            must fail at start-up, not at the first customer write.
    """

    def __init__(
        self,
        dsn: str,
        *,
        schema: str = "saas",
        dek_table: str = "tenant_deks",
        secrets_table: str = "tenant_secrets",
        cipher: Optional[EnvelopeCipher] = None,
        dek_cache_ttl: int = 300,
        audit_ledger: Optional[Any] = None,
    ) -> None:
        self._dsn = dsn
        self._schema = _check_identifier(schema, "schema")
        self._dek_table = (
            f"{self._schema}.{_check_identifier(dek_table, 'table')}"
        )
        self._secrets_table = (
            f"{self._schema}.{_check_identifier(secrets_table, 'table')}"
        )
        self._cipher = cipher or EnvelopeCipher.from_environment()
        self._dek_cache_ttl = dek_cache_ttl
        self._audit = audit_ledger
        self._conn: Optional[AsyncDB] = None
        self._initialised = False
        # (tenant_id, dek_version) -> (dek, expires_at monotonic)
        self._dek_cache: Dict[Tuple[str, int], Tuple[bytes, float]] = {}
        self.logger = logging.getLogger("parrot.security.secrets.postgres")

    # -- connection / DDL --------------------------------------------------

    async def _ensure(self) -> AsyncDB:
        """Return an open connection, creating the schema on first use."""
        if self._conn is None:
            self._conn = AsyncDB("pg", dsn=self._dsn)
        if not self._conn.is_connected():
            await self._conn.connection()
        if not self._initialised:
            await self._create_schema(self._conn)
            self._initialised = True
        return self._conn

    async def _create_schema(self, conn: AsyncDB) -> None:
        """Issue idempotent DDL for the two tables."""
        await conn.execute(f"CREATE SCHEMA IF NOT EXISTS {self._schema}")
        await conn.execute(
            f"CREATE TABLE IF NOT EXISTS {self._dek_table} ("
            "  tenant_id   text        NOT NULL,"
            "  dek_version integer     NOT NULL,"
            "  kek_id      integer     NOT NULL,"
            "  nonce       bytea       NOT NULL,"
            "  wrapped_dek bytea       NOT NULL,"
            "  active      boolean     NOT NULL DEFAULT true,"
            "  created_at  timestamptz NOT NULL DEFAULT now(),"
            "  PRIMARY KEY (tenant_id, dek_version)"
            ")"
        )
        await conn.execute(
            f"CREATE TABLE IF NOT EXISTS {self._secrets_table} ("
            "  tenant_id   text        NOT NULL,"
            "  key         text        NOT NULL,"
            "  dek_version integer     NOT NULL,"
            "  nonce       bytea       NOT NULL,"
            "  ciphertext  bytea       NOT NULL,"
            "  fingerprint text        NOT NULL,"
            "  created_at  timestamptz NOT NULL DEFAULT now(),"
            "  updated_at  timestamptz NOT NULL DEFAULT now(),"
            "  PRIMARY KEY (tenant_id, key),"
            f" FOREIGN KEY (tenant_id, dek_version) REFERENCES {self._dek_table}"
            "   (tenant_id, dek_version)"
            ")"
        )

    # -- DEK handling ------------------------------------------------------

    async def _active_dek(self, tenant_id: str) -> Tuple[bytes, int]:
        """Return the tenant's active data key, creating one on first use.

        Args:
            tenant_id: Owning tenant.

        Returns:
            Tuple of ``(dek, dek_version)``.
        """
        conn = await self._ensure()
        row = await conn.fetch_one(
            f"SELECT dek_version, kek_id, nonce, wrapped_dek FROM {self._dek_table} "
            "WHERE tenant_id = $1 AND active ORDER BY dek_version DESC LIMIT 1",
            tenant_id,
        )
        if row is None:
            return await self._create_dek(tenant_id, version=1)
        version = int(row["dek_version"])
        cached = self._cached_dek(tenant_id, version)
        if cached is not None:
            return cached, version
        dek = self._cipher.unwrap_dek(
            WrappedDEK(
                tenant_id=tenant_id,
                dek_version=version,
                kek_id=int(row["kek_id"]),
                nonce=bytes(row["nonce"]),
                ciphertext=bytes(row["wrapped_dek"]),
            )
        )
        self._cache_dek(tenant_id, version, dek)
        return dek, version

    async def _dek_for_version(self, tenant_id: str, version: int) -> bytes:
        """Return a specific data-key version for a tenant.

        Args:
            tenant_id: Owning tenant.
            version: Data-key version recorded on the secret row.

        Returns:
            The raw data key.

        Raises:
            SecretStoreError: If that version is not stored.
        """
        cached = self._cached_dek(tenant_id, version)
        if cached is not None:
            return cached
        conn = await self._ensure()
        row = await conn.fetch_one(
            f"SELECT kek_id, nonce, wrapped_dek FROM {self._dek_table} "
            "WHERE tenant_id = $1 AND dek_version = $2",
            tenant_id,
            version,
        )
        if row is None:
            raise SecretStoreError(
                f"data key version {version} for tenant {tenant_id!r} is "
                "missing; its secrets cannot be decrypted"
            )
        dek = self._cipher.unwrap_dek(
            WrappedDEK(
                tenant_id=tenant_id,
                dek_version=version,
                kek_id=int(row["kek_id"]),
                nonce=bytes(row["nonce"]),
                ciphertext=bytes(row["wrapped_dek"]),
            )
        )
        self._cache_dek(tenant_id, version, dek)
        return dek

    async def _create_dek(
        self, tenant_id: str, *, version: int, active: bool = True
    ) -> Tuple[bytes, int]:
        """Generate, wrap and persist a new data key.

        Args:
            tenant_id: Owning tenant.
            version: Version number to assign.
            active: Whether the new key immediately becomes the active one.

        Returns:
            Tuple of ``(dek, version)``.
        """
        conn = await self._ensure()
        dek = generate_dek()
        wrapped = self._cipher.wrap_dek(
            dek, tenant_id=tenant_id, dek_version=version
        )
        await conn.execute(
            f"INSERT INTO {self._dek_table} "
            "(tenant_id, dek_version, kek_id, nonce, wrapped_dek, active) "
            "VALUES ($1, $2, $3, $4, $5, $6) "
            "ON CONFLICT (tenant_id, dek_version) DO NOTHING",
            tenant_id,
            version,
            wrapped.kek_id,
            wrapped.nonce,
            wrapped.ciphertext,
            active,
        )
        self._cache_dek(tenant_id, version, dek)
        return dek, version

    def _cached_dek(self, tenant_id: str, version: int) -> Optional[bytes]:
        """Return a cached data key if present and unexpired."""
        entry = self._dek_cache.get((tenant_id, version))
        if entry is None:
            return None
        dek, expires_at = entry
        if expires_at < time.monotonic():
            self._dek_cache.pop((tenant_id, version), None)
            return None
        return dek

    def _cache_dek(self, tenant_id: str, version: int, dek: bytes) -> None:
        """Cache an unwrapped data key for a bounded time."""
        self._dek_cache[(tenant_id, version)] = (
            dek,
            time.monotonic() + self._dek_cache_ttl,
        )

    # -- SecretStore -------------------------------------------------------

    async def get(self, tenant_id: str, key: str) -> Optional[str]:
        """Return a secret value, or ``None`` when absent."""
        conn = await self._ensure()
        row = await conn.fetch_one(
            f"SELECT dek_version, nonce, ciphertext FROM {self._secrets_table} "
            "WHERE tenant_id = $1 AND key = $2",
            tenant_id,
            key,
        )
        if row is None:
            return None
        version = int(row["dek_version"])
        dek = await self._dek_for_version(tenant_id, version)
        return self._cipher.decrypt_value(
            dek,
            EncryptedValue(
                dek_version=version,
                nonce=bytes(row["nonce"]),
                ciphertext=bytes(row["ciphertext"]),
            ),
            tenant_id=tenant_id,
            key=key,
        )

    async def put(self, tenant_id: str, key: str, value: str) -> SecretMeta:
        """Create or replace a secret value and return its metadata."""
        conn = await self._ensure()
        dek, version = await self._active_dek(tenant_id)
        encrypted = self._cipher.encrypt_value(
            dek, value, tenant_id=tenant_id, key=key, dek_version=version
        )
        fingerprint = derive_key_fingerprint(value)
        row = await conn.fetch_one(
            f"INSERT INTO {self._secrets_table} "
            "(tenant_id, key, dek_version, nonce, ciphertext, fingerprint) "
            "VALUES ($1, $2, $3, $4, $5, $6) "
            "ON CONFLICT (tenant_id, key) DO UPDATE SET "
            "  dek_version = EXCLUDED.dek_version,"
            "  nonce       = EXCLUDED.nonce,"
            "  ciphertext  = EXCLUDED.ciphertext,"
            "  fingerprint = EXCLUDED.fingerprint,"
            "  updated_at  = now() "
            "RETURNING created_at, updated_at",
            tenant_id,
            key,
            version,
            encrypted.nonce,
            encrypted.ciphertext,
            fingerprint,
        )
        await self._record_audit(tenant_id, key, value)
        now = datetime.now(timezone.utc)
        return SecretMeta(
            tenant_id=tenant_id,
            key=key,
            fingerprint=fingerprint,
            created_at=row["created_at"] if row else now,
            updated_at=row["updated_at"] if row else now,
        )

    async def delete(self, tenant_id: str, key: str) -> bool:
        """Remove a secret; return whether one existed."""
        conn = await self._ensure()
        row = await conn.fetch_one(
            f"DELETE FROM {self._secrets_table} "
            "WHERE tenant_id = $1 AND key = $2 RETURNING key",
            tenant_id,
            key,
        )
        return row is not None

    async def list_keys(self, tenant_id: str) -> list[SecretMeta]:
        """Return metadata for every secret owned by ``tenant_id``."""
        conn = await self._ensure()
        rows = await conn.fetch_all(
            f"SELECT key, fingerprint, created_at, updated_at "
            f"FROM {self._secrets_table} WHERE tenant_id = $1 ORDER BY key",
            tenant_id,
        )
        return [
            SecretMeta(
                tenant_id=tenant_id,
                key=row["key"],
                fingerprint=row["fingerprint"],
                created_at=row["created_at"],
                updated_at=row["updated_at"],
            )
            for row in (rows or [])
        ]

    # -- rotation ----------------------------------------------------------

    async def rotate_dek(self, tenant_id: str) -> int:
        """Re-encrypt every secret of ``tenant_id`` under a fresh data key.

        Ordering is chosen so an interruption is harmless: the new key is
        written first (inactive), rows migrate one at a time, and the active
        flag flips last. Each row records its own key version, so a partially
        migrated tenant is fully readable.

        Args:
            tenant_id: Tenant whose secrets should be re-encrypted.

        Returns:
            Number of secrets re-encrypted.
        """
        conn = await self._ensure()
        current = await conn.fetch_one(
            f"SELECT COALESCE(MAX(dek_version), 0) AS v FROM {self._dek_table} "
            "WHERE tenant_id = $1",
            tenant_id,
        )
        next_version = int(current["v"] if current else 0) + 1
        new_dek, _ = await self._create_dek(
            tenant_id, version=next_version, active=False
        )

        rows = await conn.fetch_all(
            f"SELECT key, dek_version, nonce, ciphertext "
            f"FROM {self._secrets_table} WHERE tenant_id = $1",
            tenant_id,
        )
        migrated = 0
        for row in rows or []:
            old_version = int(row["dek_version"])
            if old_version == next_version:
                continue
            old_dek = await self._dek_for_version(tenant_id, old_version)
            plaintext = self._cipher.decrypt_value(
                old_dek,
                EncryptedValue(
                    dek_version=old_version,
                    nonce=bytes(row["nonce"]),
                    ciphertext=bytes(row["ciphertext"]),
                ),
                tenant_id=tenant_id,
                key=row["key"],
            )
            encrypted = self._cipher.encrypt_value(
                new_dek,
                plaintext,
                tenant_id=tenant_id,
                key=row["key"],
                dek_version=next_version,
            )
            await conn.execute(
                f"UPDATE {self._secrets_table} SET dek_version = $1, "
                "nonce = $2, ciphertext = $3, updated_at = now() "
                "WHERE tenant_id = $4 AND key = $5",
                next_version,
                encrypted.nonce,
                encrypted.ciphertext,
                tenant_id,
                row["key"],
            )
            migrated += 1

        await conn.execute(
            f"UPDATE {self._dek_table} SET active = (dek_version = $2) "
            "WHERE tenant_id = $1",
            tenant_id,
            next_version,
        )
        self._evict_tenant(tenant_id)
        self.logger.info(
            "rotated data key for tenant %s to version %d (%d secrets)",
            tenant_id,
            next_version,
            migrated,
        )
        return migrated

    async def rotate_kek(self) -> int:
        """Re-wrap every data key under the active master key.

        Secret ciphertexts are never touched — re-wrapping only the data keys
        is what an envelope buys.

        Returns:
            Number of data keys re-wrapped.
        """
        conn = await self._ensure()
        rows = await conn.fetch_all(
            f"SELECT tenant_id, dek_version, kek_id, nonce, wrapped_dek "
            f"FROM {self._dek_table}"
        )
        rewrapped = 0
        for row in rows or []:
            if int(row["kek_id"]) == self._cipher.active_key_id:
                continue
            tenant_id = row["tenant_id"]
            version = int(row["dek_version"])
            dek = self._cipher.unwrap_dek(
                WrappedDEK(
                    tenant_id=tenant_id,
                    dek_version=version,
                    kek_id=int(row["kek_id"]),
                    nonce=bytes(row["nonce"]),
                    ciphertext=bytes(row["wrapped_dek"]),
                )
            )
            wrapped = self._cipher.wrap_dek(
                dek, tenant_id=tenant_id, dek_version=version
            )
            await conn.execute(
                f"UPDATE {self._dek_table} SET kek_id = $1, nonce = $2, "
                "wrapped_dek = $3 WHERE tenant_id = $4 AND dek_version = $5",
                wrapped.kek_id,
                wrapped.nonce,
                wrapped.ciphertext,
                tenant_id,
                version,
            )
            rewrapped += 1
        self.logger.info("re-wrapped %d data key(s) under the active master key", rewrapped)
        return rewrapped

    # -- housekeeping ------------------------------------------------------

    async def _record_audit(self, tenant_id: str, key: str, value: str) -> None:
        """Append a mutation to the audit ledger, when one is configured.

        The ledger derives and stores only a fingerprint; ``value`` is passed
        so it can do that and is never persisted. An audit failure must not
        fail the write that already succeeded, so it is logged and swallowed.
        """
        if self._audit is None:
            return
        try:
            await self._audit.append(
                user_id=tenant_id,
                channel="saas:secret-store",
                tool="secret_store.put",
                provider=key.split(":", 1)[0],
                credential_material=value,
            )
        except Exception as exc:  # noqa: BLE001 - audit must not break writes
            self.logger.warning("secret-store audit append failed: %s", exc)

    def _evict_tenant(self, tenant_id: str) -> None:
        """Drop every cached data key belonging to a tenant."""
        for cache_key in [k for k in self._dek_cache if k[0] == tenant_id]:
            self._dek_cache.pop(cache_key, None)

    async def aclose(self) -> None:
        """Clear cached key material and close the connection."""
        self._dek_cache.clear()
        if self._conn is not None and self._conn.is_connected():
            await self._conn.close()
        self._conn = None


__all__ = ("EncryptedPostgresSecretStore",)
