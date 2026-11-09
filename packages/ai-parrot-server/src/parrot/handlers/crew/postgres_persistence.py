"""Durable crew definition rows and deletion tombstones."""

from __future__ import annotations

import json
import logging
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any, AsyncIterator

from asyncdb import AsyncDB
from parrot.conf import CREW_DEFINITION_PG_DSN
from pydantic import BaseModel

from .definition_codec import crew_definition_from_dict, crew_definition_to_document
from .models import CrewDefinition

TABLE = "navigator.crew_definitions"
MIGRATION_LOCK_KEY = "parrot:crew_definitions:migration"

_DDL_STATEMENTS: list[str] = [
    "CREATE SCHEMA IF NOT EXISTS navigator",
    """CREATE TABLE IF NOT EXISTS navigator.crew_definitions (
        tenant TEXT NOT NULL DEFAULT 'global',
        name TEXT NOT NULL,
        crew_id TEXT NOT NULL,
        description TEXT,
        execution_mode VARCHAR(32),
        definition JSONB NOT NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        deleted_at TIMESTAMPTZ,
        PRIMARY KEY (tenant, name),
        CONSTRAINT uq_crew_definitions_tenant_crew_id UNIQUE (tenant, crew_id)
    )""",
]

_SAVE_SQL = f"""
INSERT INTO {TABLE} (
    tenant, name, crew_id, description, execution_mode, definition,
    created_at, updated_at, deleted_at
) VALUES ($1, $2, $3, $4, $5, $6::jsonb, $7, $8, NULL)
ON CONFLICT (tenant, name) DO UPDATE SET
    crew_id = EXCLUDED.crew_id,
    description = EXCLUDED.description,
    execution_mode = EXCLUDED.execution_mode,
    definition = EXCLUDED.definition,
    updated_at = EXCLUDED.updated_at,
    deleted_at = NULL
RETURNING crew_id
"""

_INSERT_IF_ABSENT_SQL = f"""
INSERT INTO {TABLE} (
    tenant, name, crew_id, description, execution_mode, definition,
    created_at, updated_at, deleted_at
) VALUES ($1, $2, $3, $4, $5, $6::jsonb, $7, $8, NULL)
ON CONFLICT (tenant, name) DO NOTHING
RETURNING crew_id
"""

_DELETE_SQL = f"""
INSERT INTO {TABLE} (
    tenant, name, crew_id, description, execution_mode, definition,
    created_at, updated_at, deleted_at
) VALUES ($1, $2, $3, $4, $5, $6::jsonb, $7, $8, $8)
ON CONFLICT (tenant, name) DO UPDATE SET
    description = EXCLUDED.description,
    execution_mode = EXCLUDED.execution_mode,
    definition = EXCLUDED.definition,
    updated_at = EXCLUDED.updated_at,
    deleted_at = EXCLUDED.deleted_at
WHERE {TABLE}.crew_id = EXCLUDED.crew_id
RETURNING crew_id
"""

_ROW_COLUMNS = "tenant, name, crew_id, definition, deleted_at"
_LOAD_BY_NAME_SQL = f"SELECT {_ROW_COLUMNS} FROM {TABLE} WHERE tenant = $1 AND name = $2"
_LOAD_BY_ID_SQL = f"SELECT {_ROW_COLUMNS} FROM {TABLE} WHERE tenant = $1 AND crew_id = $2"
_LIST_ALL_ROWS_SQL = f"SELECT {_ROW_COLUMNS} FROM {TABLE} ORDER BY tenant, name"
_LIST_TENANT_ROWS_SQL = f"SELECT {_ROW_COLUMNS} FROM {TABLE} WHERE tenant = $1 ORDER BY name"


async def _execute(conn: Any, statement: str, *args: Any) -> None:
    """Execute a statement and raise errors returned as adapter values."""
    result = await conn.execute(statement, *args)
    if isinstance(result, (list, tuple)) and len(result) == 2 and result[1]:
        error = result[1]
        raise error if isinstance(error, Exception) else RuntimeError(str(error))


def _stored_row(row: Any) -> "CrewStoredRow":
    """Convert an AsyncDB row without deserializing its definition."""
    data = dict(row)
    return CrewStoredRow(
        tenant=str(data["tenant"]),
        name=str(data["name"]),
        crew_id=str(data["crew_id"]),
        definition=data["definition"],
        deleted_at=data.get("deleted_at"),
    )


class CrewStoredRow(BaseModel):
    """Authoritative identity survives malformed definition deserialization."""

    tenant: str
    name: str
    crew_id: str
    definition: dict[str, Any] | str
    deleted_at: datetime | None = None


class CrewPostgres:
    """AsyncDB-backed definitions; errors propagate, None means confirmed absence."""

    def __init__(self, dsn: str | None = None) -> None:
        """Initialize the Postgres crew definition store.

        Args:
            dsn: Optional Postgres DSN, defaulting to application configuration.
        """
        self.dsn = dsn or CREW_DEFINITION_PG_DSN
        self.logger = logging.getLogger(__name__)
        self._schema_ensured = False

    @property
    def configured(self) -> bool:
        """Return whether a Postgres DSN is configured."""
        return bool(self.dsn)

    def _get_db(self) -> AsyncDB:
        """Construct a fresh AsyncDB wrapper for one operation."""
        return AsyncDB("pg", dsn=self.dsn)

    async def _ensure_ready(self) -> None:
        """Ensure the fixed schema before a data operation."""
        if not self._schema_ensured:
            await self.ensure_schema()

    async def ensure_schema(self) -> None:
        """Apply fixed DDL idempotently; retry on later calls after failure."""
        if not self.configured:
            raise RuntimeError("Postgres crew definition storage is not configured")

        db = self._get_db()
        async with await db.connection() as conn:
            for statement in _DDL_STATEMENTS:
                try:
                    await _execute(conn, statement)
                except Exception as exc:
                    if "already exists" in str(exc).lower():
                        self.logger.debug("crew_definitions DDL race tolerated: %s", exc)
                        continue
                    raise
        self._schema_ensured = True

    async def ping(self) -> bool:
        """Ensure schema then SELECT 1; False on unavailable or missing DSN."""
        if not self.configured:
            return False
        try:
            await self._ensure_ready()
            db = self._get_db()
            async with await db.connection() as conn:
                return await conn.fetchval("SELECT 1") == 1
        except Exception as exc:
            self.logger.warning("Postgres crew definition storage is unavailable: %s", exc)
            return False

    @staticmethod
    def _write_args(crew: CrewDefinition, timestamp: datetime) -> tuple[Any, ...]:
        """Build ordered SQL parameters with a timestamp-consistent document."""
        persisted = crew.model_copy(update={"tenant": crew.tenant or "global", "updated_at": timestamp})
        return (
            persisted.tenant,
            persisted.name,
            persisted.crew_id,
            persisted.description,
            persisted.execution_mode.value,
            crew_definition_to_document(persisted),
            persisted.created_at,
            timestamp,
        )

    async def save_crew(self, crew: CrewDefinition) -> bool:
        """Upsert by name; explicit saves clear tombstones and update UTC time."""
        await self._ensure_ready()
        updated_at = datetime.now(timezone.utc)
        db = self._get_db()
        async with await db.connection() as conn:
            saved_id = await conn.fetchval(_SAVE_SQL, *self._write_args(crew, updated_at))
        if saved_id is None:
            raise RuntimeError("Postgres did not confirm the crew definition save")
        crew.updated_at = updated_at
        return True

    async def insert_if_absent(self, crew: CrewDefinition) -> bool:
        """Target name conflict only; preserve timestamps and raise on ID collision."""
        await self._ensure_ready()
        db = self._get_db()
        async with await db.connection() as conn:
            inserted_id = await conn.fetchval(_INSERT_IF_ABSENT_SQL, *self._write_args(crew, crew.updated_at))
        return inserted_id is not None

    async def delete_crew(self, crew: CrewDefinition) -> bool:
        """Atomically create/retain a tombstone, refusing conflicting identities."""
        await self._ensure_ready()
        deleted_at = datetime.now(timezone.utc)
        db = self._get_db()
        async with await db.connection() as conn:
            deleted_id = await conn.fetchval(_DELETE_SQL, *self._write_args(crew, deleted_at))
        if deleted_id is None:
            raise ValueError(f"Crew {crew.tenant or 'global'}:{crew.name!s} no longer has identity {crew.crew_id!r}")
        return True

    async def _load_row(self, name: str, tenant: str | None = None) -> CrewStoredRow | None:
        """Include deleted rows and malformed payload identities."""
        await self._ensure_ready()
        db = self._get_db()
        async with await db.connection() as conn:
            row = await conn.fetch_one(_LOAD_BY_NAME_SQL, tenant or "global", name)
        return _stored_row(row) if row is not None else None

    async def _load_row_by_id(self, crew_id: str, tenant: str | None = None) -> CrewStoredRow | None:
        """Look up tenant/ID including deleted or malformed rows."""
        await self._ensure_ready()
        db = self._get_db()
        async with await db.connection() as conn:
            row = await conn.fetch_one(_LOAD_BY_ID_SQL, tenant or "global", crew_id)
        return _stored_row(row) if row is not None else None

    async def _list_rows(self, tenant: str | None = None) -> list[CrewStoredRow]:
        """List identities and payloads, retaining tombstones."""
        await self._ensure_ready()
        db = self._get_db()
        async with await db.connection() as conn:
            if tenant is None:
                rows = await conn.fetch_all(_LIST_ALL_ROWS_SQL)
            else:
                rows = await conn.fetch_all(_LIST_TENANT_ROWS_SQL, tenant or "global")
        return [_stored_row(row) for row in rows or []]

    def _decode_row(self, row: CrewStoredRow) -> CrewDefinition:
        """Decode and validate a stored row payload."""
        definition = row.definition
        if isinstance(definition, str):
            definition = json.loads(definition)
        if not isinstance(definition, dict):
            raise ValueError("Crew definition JSONB payload is not an object")
        return crew_definition_from_dict(dict(definition), self.logger)

    async def load_crew(self, name: str, tenant: str | None = None) -> CrewDefinition | None:
        """Return an active validated model, otherwise None."""
        row = await self._load_row(name, tenant)
        return self._decode_active_row(row)

    async def load_crew_by_id(self, crew_id: str, tenant: str | None = None) -> CrewDefinition | None:
        """Return an active validated model for a tenant/ID lookup."""
        row = await self._load_row_by_id(crew_id, tenant)
        return self._decode_active_row(row)

    def _decode_active_row(self, row: CrewStoredRow | None) -> CrewDefinition | None:
        """Decode one active row, logging malformed payloads as unavailable."""
        if row is None or row.deleted_at is not None:
            return None
        try:
            return self._decode_row(row)
        except (TypeError, ValueError) as exc:
            self.logger.warning(
                "Skipping malformed Postgres crew definition %s:%s (%s): %s",
                row.tenant,
                row.name,
                row.crew_id,
                exc,
            )
            return None

    async def list_all_crews(self) -> list[dict[str, str]]:
        """List active tenant/name entries across tenants."""
        rows = await self._list_rows()
        return [{"tenant": row.tenant, "name": row.name} for row in rows if row.deleted_at is None]

    async def get_all_crews(self, tenant: str | None = None) -> list[CrewDefinition]:
        """Decode active models; log malformed rows and skip them."""
        crews: list[CrewDefinition] = []
        for row in await self._list_rows(tenant):
            crew = self._decode_active_row(row)
            if crew is not None:
                crews.append(crew)
        return crews

    @asynccontextmanager
    async def migration_lock(self) -> AsyncIterator[bool]:
        """Try and release the session advisory lock on the same dedicated connection."""
        if not self.configured:
            yield False
            return

        db = self._get_db()
        async with await db.connection() as conn:
            acquired = bool(
                await conn.fetchval(
                    "SELECT pg_try_advisory_lock(hashtextextended($1, 0))",
                    MIGRATION_LOCK_KEY,
                )
            )
            try:
                yield acquired
            finally:
                if acquired:
                    await conn.fetchval(
                        "SELECT pg_advisory_unlock(hashtextextended($1, 0))",
                        MIGRATION_LOCK_KEY,
                    )

    async def close(self) -> None:
        """Per-call connections require no persistent close operation."""
