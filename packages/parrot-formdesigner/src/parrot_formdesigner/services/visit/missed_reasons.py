"""MissedReasonService — per-tenant Missed Reasons catalogue (FEAT-303).

Decision (spec §8): the catalogue is **per-tenant** with hard isolation
(consistent with FEAT-302). No global (cross-tenant) rows are allowed.

Two concrete implementations:

- ``InMemoryMissedReasonStorage`` — for unit tests; no DB required.
- ``PostgresMissedReasonStorage`` — idempotent DDL in the ``fieldsync``
  schema, mirroring the identifier-safety pattern of ``PostgresFormStorage``.

``MissedReasonService`` orchestrates CRUD; all methods are async and
tenant-scoped.
"""

from __future__ import annotations

import logging
import uuid
from abc import ABC, abstractmethod
from typing import Any

from .models import MissedReason
from .._identifiers import qualified_table, validate_identifier

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Storage ABC
# ---------------------------------------------------------------------------

MISSED_REASONS_SCHEMA = "fieldsync"
MISSED_REASONS_TABLE = "missed_reasons"


class MissedReasonStorage(ABC):
    """Abstract persistence backend for ``MissedReason`` catalogue entries."""

    @abstractmethod
    async def save(
        self, reason: MissedReason, *, tenant: str
    ) -> str:
        """Persist a reason and return its ``reason_id``."""
        ...

    @abstractmethod
    async def load(
        self, reason_id: str, *, tenant: str
    ) -> MissedReason | None:
        """Load a reason by ID for the given tenant."""
        ...

    @abstractmethod
    async def list_reasons(self, *, tenant: str) -> list[MissedReason]:
        """List all active reasons for the given tenant."""
        ...

    @abstractmethod
    async def delete(self, reason_id: str, *, tenant: str) -> bool:
        """Soft-delete (deactivate) a reason. Returns ``True`` if found."""
        ...

    async def close(self) -> None:
        """Release resources. Default is a no-op."""


# ---------------------------------------------------------------------------
# In-memory (tests)
# ---------------------------------------------------------------------------


class InMemoryMissedReasonStorage(MissedReasonStorage):
    """Non-persistent in-memory backend for unit tests.

    Each tenant has its own isolated bucket — no cross-tenant access.
    """

    def __init__(self) -> None:
        # {tenant: {reason_id: MissedReason}}
        self._store: dict[str, dict[str, MissedReason]] = {}

    def _bucket(self, tenant: str) -> dict[str, MissedReason]:
        if tenant not in self._store:
            self._store[tenant] = {}
        return self._store[tenant]

    async def save(self, reason: MissedReason, *, tenant: str) -> str:
        self._bucket(tenant)[reason.reason_id] = reason
        return reason.reason_id

    async def load(self, reason_id: str, *, tenant: str) -> MissedReason | None:
        return self._bucket(tenant).get(reason_id)

    async def list_reasons(self, *, tenant: str) -> list[MissedReason]:
        return [r for r in self._bucket(tenant).values() if r.active]

    async def delete(self, reason_id: str, *, tenant: str) -> bool:
        bucket = self._bucket(tenant)
        if reason_id not in bucket:
            return False
        reason = bucket[reason_id]
        bucket[reason_id] = reason.model_copy(update={"active": False})
        return True


# ---------------------------------------------------------------------------
# Postgres (fieldsync schema)
# ---------------------------------------------------------------------------


class PostgresMissedReasonStorage(MissedReasonStorage):
    """Persist ``MissedReason`` objects in ``fieldsync.missed_reasons``.

    DDL is idempotent (``CREATE TABLE IF NOT EXISTS``). The table lives in
    the ``fieldsync`` schema, consistent with per-tenant FieldSync tables
    introduced by FEAT-302.

    Args:
        pool: An active asyncpg connection pool.
        schema: Postgres schema. Default ``"fieldsync"``.
        table_name: Table name. Default ``"missed_reasons"``.
    """

    def __init__(
        self,
        pool: Any,
        *,
        schema: str = MISSED_REASONS_SCHEMA,
        table_name: str = MISSED_REASONS_TABLE,
    ) -> None:
        validate_identifier(schema, kind="schema")
        validate_identifier(table_name, kind="table")
        self._pool = pool
        self._schema = schema
        self._table = table_name
        self.logger = logging.getLogger(__name__)

    def _qualified(self) -> str:
        return qualified_table(self._schema, self._table)

    def _create_table_sql(self) -> str:
        qt = self._qualified()
        return f"""
        CREATE TABLE IF NOT EXISTS {qt} (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            reason_id VARCHAR(255) NOT NULL,
            label TEXT NOT NULL,
            tenant VARCHAR(63) NOT NULL,
            active BOOLEAN NOT NULL DEFAULT TRUE,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            UNIQUE(reason_id, tenant)
        );
        """

    def _upsert_sql(self) -> str:
        qt = self._qualified()
        return f"""
        INSERT INTO {qt} (reason_id, label, tenant, active)
        VALUES ($1, $2, $3, $4)
        ON CONFLICT (reason_id, tenant)
        DO UPDATE SET label = EXCLUDED.label, active = EXCLUDED.active
        """

    def _load_sql(self) -> str:
        qt = self._qualified()
        return f"SELECT reason_id, label, tenant, active FROM {qt} WHERE reason_id = $1 AND tenant = $2"

    def _list_sql(self) -> str:
        qt = self._qualified()
        return f"SELECT reason_id, label, tenant, active FROM {qt} WHERE tenant = $1 AND active = TRUE"

    def _deactivate_sql(self) -> str:
        qt = self._qualified()
        return f"UPDATE {qt} SET active = FALSE WHERE reason_id = $1 AND tenant = $2"

    async def initialize(self) -> None:
        """Create the table if it does not exist (idempotent)."""
        async with self._pool.acquire() as conn:
            await conn.execute(self._create_table_sql())
        self.logger.info("PostgresMissedReasonStorage: %s ensured", self._qualified())

    async def save(self, reason: MissedReason, *, tenant: str) -> str:
        async with self._pool.acquire() as conn:
            await conn.execute(
                self._upsert_sql(),
                reason.reason_id,
                reason.label,
                tenant,
                reason.active,
            )
        return reason.reason_id

    async def load(self, reason_id: str, *, tenant: str) -> MissedReason | None:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(self._load_sql(), reason_id, tenant)
        if row is None:
            return None
        return MissedReason(
            reason_id=row["reason_id"],
            label=row["label"],
            tenant=row["tenant"],
            active=row["active"],
        )

    async def list_reasons(self, *, tenant: str) -> list[MissedReason]:
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(self._list_sql(), tenant)
        return [
            MissedReason(
                reason_id=r["reason_id"],
                label=r["label"],
                tenant=r["tenant"],
                active=r["active"],
            )
            for r in rows
        ]

    async def delete(self, reason_id: str, *, tenant: str) -> bool:
        async with self._pool.acquire() as conn:
            result = await conn.execute(
                self._deactivate_sql(), reason_id, tenant
            )
        updated = int(result.split()[-1]) if result else 0
        return updated > 0


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------


class MissedReasonService:
    """CRUD service for tenant-scoped ``MissedReason`` catalogue entries.

    Every method requires an explicit ``tenant`` argument — no cross-tenant
    access is possible.

    Args:
        storage: Persistence backend (``InMemoryMissedReasonStorage`` or
            ``PostgresMissedReasonStorage``).
    """

    def __init__(self, storage: MissedReasonStorage) -> None:
        self._storage = storage
        self.logger = logging.getLogger(__name__)

    async def create_reason(
        self, label: str, *, tenant: str
    ) -> MissedReason:
        """Create a new Missed Reason for the given tenant.

        Args:
            label: Human-readable label shown in the UI.
            tenant: Tenant slug (hard isolation — required).

        Returns:
            The persisted ``MissedReason`` instance.
        """
        reason = MissedReason(
            reason_id=str(uuid.uuid4()),
            label=label,
            tenant=tenant,
            active=True,
        )
        await self._storage.save(reason, tenant=tenant)
        self.logger.info(
            "Created missed reason %r (tenant=%r)", reason.reason_id, tenant
        )
        return reason

    async def get_reason(
        self, reason_id: str, *, tenant: str
    ) -> MissedReason | None:
        """Load a Missed Reason by ID for the given tenant.

        Args:
            reason_id: The identifier to look up.
            tenant: Tenant slug (only returns reasons belonging to this tenant).

        Returns:
            ``MissedReason`` if found, ``None`` otherwise.
        """
        return await self._storage.load(reason_id, tenant=tenant)

    async def list_reasons(self, *, tenant: str) -> list[MissedReason]:
        """List all active Missed Reasons for the given tenant.

        Args:
            tenant: Tenant slug.

        Returns:
            List of active ``MissedReason`` objects for this tenant only.
        """
        return await self._storage.list_reasons(tenant=tenant)

    async def deactivate_reason(
        self, reason_id: str, *, tenant: str
    ) -> bool:
        """Deactivate (soft-delete) a Missed Reason.

        Args:
            reason_id: The reason to deactivate.
            tenant: Tenant slug.

        Returns:
            ``True`` if the reason was found and deactivated, ``False`` otherwise.
        """
        return await self._storage.delete(reason_id, tenant=tenant)
