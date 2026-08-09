"""In-memory :class:`SecretStore` — tests, local development, and defaults.

Holds plaintext in process memory. That is appropriate for unit tests (the
whole point is not to need Postgres) and unacceptable for anything holding a
real customer key, so :class:`InMemorySecretStore` says so loudly in its own
docstring rather than relying on callers to know.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Dict, Optional, Tuple

from ..audit_ledger import derive_key_fingerprint
from .base import SecretMeta, SecretStore


class InMemorySecretStore(SecretStore):
    """Process-local secret store with no persistence and no encryption.

    **Not for production.** Values are held as plaintext in a dict and vanish
    with the process. Use :class:`~parrot.security.secrets.postgres.EncryptedPostgresSecretStore`
    for anything holding real credentials.

    Safe for concurrent use: mutations are serialised by an
    :class:`asyncio.Lock`.
    """

    def __init__(self) -> None:
        """Initialise an empty store."""
        self._values: Dict[Tuple[str, str], str] = {}
        self._meta: Dict[Tuple[str, str], SecretMeta] = {}
        self._lock = asyncio.Lock()

    async def get(self, tenant_id: str, key: str) -> Optional[str]:
        """Return a secret value, or ``None`` when absent."""
        return self._values.get((tenant_id, key))

    async def put(self, tenant_id: str, key: str, value: str) -> SecretMeta:
        """Create or replace a secret value and return its metadata."""
        now = datetime.now(timezone.utc)
        async with self._lock:
            existing = self._meta.get((tenant_id, key))
            meta = SecretMeta(
                tenant_id=tenant_id,
                key=key,
                fingerprint=derive_key_fingerprint(value),
                created_at=existing.created_at if existing else now,
                updated_at=now,
            )
            self._values[(tenant_id, key)] = value
            self._meta[(tenant_id, key)] = meta
        return meta

    async def delete(self, tenant_id: str, key: str) -> bool:
        """Remove a secret; return whether one existed."""
        async with self._lock:
            existed = self._values.pop((tenant_id, key), None) is not None
            self._meta.pop((tenant_id, key), None)
        return existed

    async def list_keys(self, tenant_id: str) -> list[SecretMeta]:
        """Return metadata for every secret owned by ``tenant_id``."""
        return sorted(
            (m for (t, _), m in self._meta.items() if t == tenant_id),
            key=lambda m: m.key,
        )

    async def aclose(self) -> None:
        """Drop every held value.

        Called on shutdown and by tests between cases; clearing rather than
        leaving plaintext resident is the cheap, correct default.
        """
        async with self._lock:
            self._values.clear()
            self._meta.clear()


__all__ = ("InMemorySecretStore",)
