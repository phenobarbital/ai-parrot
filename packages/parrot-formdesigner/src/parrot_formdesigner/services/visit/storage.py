"""EventStorage ABC and concrete implementations for FEAT-303.

Mirrors the ``FormStorage`` / ``PostgresFormStorage`` pattern from
``services/registry.py`` and ``services/storage.py``:

- ``EventStorage`` — abstract base class (save / load / delete / list / close).
- ``InMemoryEventStorage`` — in-memory backend for unit tests.
- ``PostgresEventStorage`` — JSONB document in ``navigator.events`` using the
  same DDL and identifier-safety helpers (``_identifiers.py``) as
  ``PostgresFormStorage``.
"""

from __future__ import annotations

import json
import logging
from abc import ABC, abstractmethod
from typing import Any

from .models import Event
from .._identifiers import qualified_table, validate_identifier

logger = logging.getLogger(__name__)

DEFAULT_SCHEMA = "navigator"
DEFAULT_TABLE = "events"


# ---------------------------------------------------------------------------
# Abstract base
# ---------------------------------------------------------------------------


class EventStorage(ABC):
    """Abstract persistence backend for ``Event`` objects.

    Mirrors ``FormStorage`` (``services/registry.py:50``).
    All operations accept a ``tenant`` kwarg for multi-tenancy.
    """

    @abstractmethod
    async def save(self, event: Event, *, tenant: str | None = None) -> str:
        """Persist an event and return its ``event_id``.

        Args:
            event: The ``Event`` to persist.
            tenant: Optional per-call tenant override.

        Returns:
            The ``event_id`` of the saved event.
        """
        ...

    @abstractmethod
    async def load(
        self, event_id: str, *, tenant: str | None = None
    ) -> Event | None:
        """Load an event by ID.

        Args:
            event_id: Identifier of the event to load.
            tenant: Optional per-call tenant override.

        Returns:
            ``Event`` if found, ``None`` otherwise.
        """
        ...

    @abstractmethod
    async def delete(self, event_id: str, *, tenant: str | None = None) -> bool:
        """Delete an event.

        Args:
            event_id: Identifier of the event to delete.
            tenant: Optional per-call tenant override.

        Returns:
            ``True`` if the event was deleted, ``False`` if not found.
        """
        ...

    @abstractmethod
    async def list_events(
        self, *, tenant: str | None = None, **filters: Any
    ) -> list[dict[str, Any]]:
        """List persisted events.

        Each dict in the returned list MUST include ``event_id`` and
        ``status`` at minimum.

        Args:
            tenant: Optional per-call tenant override.
            **filters: Optional additional filter kwargs (e.g. ``org_node_id``).

        Returns:
            List of dicts with at minimum ``event_id`` and ``status``.
        """
        ...

    async def close(self) -> None:
        """Release any resources held by this storage backend.

        Default is a no-op. Subclasses with pools should override.
        """


# ---------------------------------------------------------------------------
# In-memory implementation (tests / local dev)
# ---------------------------------------------------------------------------


class InMemoryEventStorage(EventStorage):
    """Non-persistent, thread-safe-enough in-memory ``EventStorage``.

    Stores events in a nested dict ``{tenant: {event_id: Event}}``.
    ``tenant=None`` is treated as the literal key ``None``.

    Suitable for unit tests — no I/O dependencies.
    """

    def __init__(self) -> None:
        self._store: dict[str | None, dict[str, Event]] = {}
        self.logger = logging.getLogger(__name__)

    def _bucket(self, tenant: str | None) -> dict[str, Event]:
        if tenant not in self._store:
            self._store[tenant] = {}
        return self._store[tenant]

    async def save(self, event: Event, *, tenant: str | None = None) -> str:
        """Store the event under its ``event_id``.

        Uses the per-call ``tenant`` if provided, otherwise falls back to
        ``event.tenant``.
        """
        effective = tenant if tenant is not None else event.tenant
        self._bucket(effective)[event.event_id] = event
        self.logger.debug("InMemory: saved event %s (tenant=%r)", event.event_id, effective)
        return event.event_id

    async def load(
        self, event_id: str, *, tenant: str | None = None
    ) -> Event | None:
        return self._bucket(tenant).get(event_id)

    async def delete(self, event_id: str, *, tenant: str | None = None) -> bool:
        bucket = self._bucket(tenant)
        if event_id in bucket:
            del bucket[event_id]
            return True
        return False

    async def list_events(
        self, *, tenant: str | None = None, **filters: Any
    ) -> list[dict[str, Any]]:
        events = list(self._bucket(tenant).values())
        result = []
        for ev in events:
            d = ev.model_dump()
            # Apply simple equality filters
            if all(
                str(d.get(k)) == str(v) or d.get(k) == v
                for k, v in filters.items()
            ):
                result.append(d)
        return result


# ---------------------------------------------------------------------------
# Postgres implementation (JSONB document — mirrors PostgresFormStorage)
# ---------------------------------------------------------------------------


class PostgresEventStorage(EventStorage):
    """Persist ``Event`` objects as JSONB documents in ``navigator.events``.

    Mirrors ``PostgresFormStorage`` (``services/storage.py``) with the same
    identifier-safety helpers and asyncpg pool management.

    Schema, table, and tenant are configurable.  The target schema MUST
    already exist — ``initialize()`` only creates the table.

    Args:
        pool: An existing ``asyncpg`` connection pool. When provided,
            ``_owns_pool`` is ``False`` and ``close()`` will not close it.
        dsn: asyncpg DSN string. Used by ``initialize()`` when pool is ``None``.
        schema: Postgres schema for the events table. Default ``"navigator"``.
        table_name: Table name. Default ``"events"``.
        tenant: Optional default tenant slug.
        min_size: Minimum asyncpg pool size (default 2).
        max_size: Maximum asyncpg pool size (default 10).
    """

    def __init__(
        self,
        *,
        pool: Any | None = None,
        dsn: str | None = None,
        schema: str = DEFAULT_SCHEMA,
        table_name: str = DEFAULT_TABLE,
        tenant: str | None = None,
        min_size: int = 2,
        max_size: int = 10,
        **pool_kwargs: Any,
    ) -> None:
        validate_identifier(schema, kind="schema")
        validate_identifier(table_name, kind="table")
        if tenant is not None:
            validate_identifier(tenant, kind="tenant")

        self._pool: Any | None = pool
        self._dsn: str | None = dsn
        self._schema = schema
        self._table = table_name
        self._tenant = tenant
        self._min_size = min_size
        self._max_size = max_size
        self._pool_kwargs = pool_kwargs
        self._owns_pool: bool = pool is None
        self.logger = logging.getLogger(__name__)

    # ------------------------------------------------------------------
    # Identifier resolution (mirrors PostgresFormStorage)
    # ------------------------------------------------------------------

    def _resolve_schema(self, tenant: str | None) -> str:
        if tenant is not None:
            return validate_identifier(tenant, kind="tenant")
        if self._tenant is not None:
            return self._tenant
        return self._schema

    def _qualified(self, tenant: str | None) -> str:
        return qualified_table(self._resolve_schema(tenant), self._table)

    # ------------------------------------------------------------------
    # DDL (idempotent CREATE TABLE IF NOT EXISTS — mirrors form_schemas)
    # ------------------------------------------------------------------

    def _create_table_sql(self, tenant: str | None) -> str:
        qt = self._qualified(tenant)
        return f"""
        CREATE TABLE IF NOT EXISTS {qt} (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            event_id VARCHAR(255) NOT NULL UNIQUE,
            event_json JSONB NOT NULL,
            tenant VARCHAR(63),
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
        """

    def _upsert_sql(self, tenant: str | None) -> str:
        qt = self._qualified(tenant)
        return f"""
        INSERT INTO {qt} (event_id, event_json, tenant)
        VALUES ($1, $2::jsonb, $3)
        ON CONFLICT (event_id)
        DO UPDATE SET
            event_json = EXCLUDED.event_json,
            tenant = EXCLUDED.tenant,
            updated_at = NOW()
        """

    def _load_sql(self, tenant: str | None) -> str:
        qt = self._qualified(tenant)
        return f"SELECT event_json FROM {qt} WHERE event_id = $1"

    def _delete_sql(self, tenant: str | None) -> str:
        return f"DELETE FROM {self._qualified(tenant)} WHERE event_id = $1"

    def _list_sql(self, tenant: str | None) -> str:
        qt = self._qualified(tenant)
        return f"SELECT event_json FROM {qt} ORDER BY updated_at DESC"

    # ------------------------------------------------------------------
    # Pool helpers
    # ------------------------------------------------------------------

    def _require_pool(self) -> None:
        if self._pool is None:
            raise RuntimeError(
                "PostgresEventStorage is not initialized. "
                "Call initialize() before performing storage operations."
            )

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def initialize(self, *, tenant: str | None = None) -> None:
        """Create the ``events`` table if it does not exist.

        Idempotent. The target schema must already exist.

        Args:
            tenant: Optional per-call tenant override.
        """
        if self._pool is None:
            import asyncpg  # lazy runtime import

            self._pool = await asyncpg.create_pool(
                dsn=self._dsn,
                min_size=self._min_size,
                max_size=self._max_size,
                **self._pool_kwargs,
            )
            self.logger.info("PostgresEventStorage: created asyncpg pool")

        sql = self._create_table_sql(tenant)
        async with self._pool.acquire() as conn:
            await conn.execute(sql)
        self.logger.info("PostgresEventStorage: %s ensured", self._qualified(tenant))

    async def close(self) -> None:
        """Close the asyncpg pool if this storage owns it."""
        if self._owns_pool and self._pool is not None:
            await self._pool.close()
            self.logger.info("PostgresEventStorage: pool closed")
        self._pool = None
        self._owns_pool = False

    # ------------------------------------------------------------------
    # EventStorage implementation
    # ------------------------------------------------------------------

    async def save(self, event: Event, *, tenant: str | None = None) -> str:
        """Persist an Event as a JSONB document (UPSERT by event_id).

        Args:
            event: The ``Event`` to persist.
            tenant: Optional per-call tenant override. Falls back to
                ``event.tenant``, then the storage default, then ``schema``.

        Returns:
            The ``event_id`` of the saved event.
        """
        self._require_pool()
        effective = tenant if tenant is not None else event.tenant
        event_json = event.model_dump_json()

        async with self._pool.acquire() as conn:
            await conn.execute(
                self._upsert_sql(effective),
                event.event_id,
                event_json,
                effective,
            )
        self.logger.debug(
            "Saved event %s (tenant=%r)", event.event_id, effective
        )
        return event.event_id

    async def load(
        self, event_id: str, *, tenant: str | None = None
    ) -> Event | None:
        """Load an Event by its ``event_id``.

        Args:
            event_id: The identifier to look up.
            tenant: Optional per-call tenant override.

        Returns:
            ``Event`` if found, ``None`` otherwise.
        """
        self._require_pool()
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(self._load_sql(tenant), event_id)
        if row is None:
            return None
        data = json.loads(row["event_json"])
        return Event.model_validate(data)

    async def delete(self, event_id: str, *, tenant: str | None = None) -> bool:
        """Delete an Event by ``event_id``.

        Args:
            event_id: Identifier of the event to delete.
            tenant: Optional per-call tenant override.

        Returns:
            ``True`` if a row was deleted, ``False`` if not found.
        """
        self._require_pool()
        async with self._pool.acquire() as conn:
            result = await conn.execute(self._delete_sql(tenant), event_id)
        # asyncpg returns "DELETE N" — extract count
        deleted = int(result.split()[-1]) if result else 0
        return deleted > 0

    async def list_events(
        self, *, tenant: str | None = None, **filters: Any
    ) -> list[dict[str, Any]]:
        """List all events (optionally filtered).

        Args:
            tenant: Optional per-call tenant override.
            **filters: Not applied at the DB level in this implementation;
                filtering happens in Python (consistent with InMemoryEventStorage).

        Returns:
            List of event dicts with at minimum ``event_id`` and ``status``.
        """
        self._require_pool()
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(self._list_sql(tenant))

        result = []
        for row in rows:
            d = json.loads(row["event_json"])
            if all(
                str(d.get(k)) == str(v) or d.get(k) == v
                for k, v in filters.items()
            ):
                result.append(d)
        return result
