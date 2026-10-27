"""Postgres store for FEAT-756 metric definitions (``navigator.metric_definitions``).

Mirrors ``PgUISurfaceStore`` (handlers/models/ui_surfaces.py:457): fresh AsyncDB per call,
idempotent DDL with race tolerance, JSONB params passed as native objects.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from typing import Any

from asyncdb import AsyncDB
from parrot.conf import default_dsn
from parrot.handlers.scope import RequestScope, scope_grants
from parrot.metrics import MetricDefinition

logger = logging.getLogger("Parrot.MetricDefinitions.Store")

_DDL_STATEMENTS: list[str] = [
    "CREATE SCHEMA IF NOT EXISTS navigator",
    """CREATE TABLE IF NOT EXISTS navigator.metric_definitions (
        metric_id VARCHAR(63) NOT NULL,
        tenant VARCHAR(63) NULL,
        name TEXT NOT NULL,
        owner VARCHAR NULL,
        visibility VARCHAR(16) NOT NULL DEFAULT 'tenant',
        allowed_groups JSONB NOT NULL DEFAULT '[]'::jsonb,
        global_only BOOLEAN NOT NULL DEFAULT FALSE,
        program VARCHAR NULL,
        definition JSONB NOT NULL,
        version INTEGER NOT NULL DEFAULT 1,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        UNIQUE (tenant, metric_id),
        CHECK (tenant IS NOT NULL OR visibility <> 'tenant')
    )""",
    "CREATE UNIQUE INDEX IF NOT EXISTS metric_definitions_global_uq "
    "ON navigator.metric_definitions (metric_id) WHERE tenant IS NULL",
    "CREATE INDEX IF NOT EXISTS metric_definitions_tenant_vis_idx ON navigator.metric_definitions (tenant, visibility)",
    "CREATE INDEX IF NOT EXISTS metric_definitions_program_idx ON navigator.metric_definitions (program)",
]

_COLUMNS = (
    "metric_id, tenant, name, owner, visibility, allowed_groups, global_only, "
    "program, definition, version, created_at, updated_at"
)
_VALUES = "$1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12"
_UPDATE_SET = (
    "name = EXCLUDED.name, owner = EXCLUDED.owner, visibility = EXCLUDED.visibility, "
    "allowed_groups = EXCLUDED.allowed_groups, global_only = EXCLUDED.global_only, "
    "program = EXCLUDED.program, definition = EXCLUDED.definition, version = EXCLUDED.version, "
    "updated_at = EXCLUDED.updated_at"
)

_INSERT_TENANT_SQL = (
    f"INSERT INTO navigator.metric_definitions ({_COLUMNS}) VALUES ({_VALUES}) "
    "ON CONFLICT (tenant, metric_id) DO NOTHING RETURNING metric_id"
)
_UPSERT_TENANT_SQL = (
    f"INSERT INTO navigator.metric_definitions ({_COLUMNS}) VALUES ({_VALUES}) "
    f"ON CONFLICT (tenant, metric_id) DO UPDATE SET {_UPDATE_SET} RETURNING metric_id"
)
_INSERT_GLOBAL_SQL = (
    f"INSERT INTO navigator.metric_definitions ({_COLUMNS}) VALUES ({_VALUES}) "
    "ON CONFLICT (metric_id) WHERE tenant IS NULL DO NOTHING RETURNING metric_id"
)
_UPSERT_GLOBAL_SQL = (
    f"INSERT INTO navigator.metric_definitions ({_COLUMNS}) VALUES ({_VALUES}) "
    f"ON CONFLICT (metric_id) WHERE tenant IS NULL DO UPDATE SET {_UPDATE_SET} RETURNING metric_id"
)

_SELECT = f"SELECT {_COLUMNS} FROM navigator.metric_definitions"

_GET_TENANT_SQL = f"{_SELECT} WHERE metric_id = $1 AND tenant = $2"
_GET_GLOBAL_SQL = f"{_SELECT} WHERE metric_id = $1 AND tenant IS NULL"

_LIST_TENANT_SQL = f"{_SELECT} WHERE tenant = $1 ORDER BY metric_id"
_LIST_TENANT_PROGRAM_SQL = f"{_SELECT} WHERE tenant = $1 AND program = $2 ORDER BY metric_id"
_LIST_GLOBAL_SQL = f"{_SELECT} WHERE tenant IS NULL ORDER BY metric_id"
_LIST_GLOBAL_PROGRAM_SQL = f"{_SELECT} WHERE tenant IS NULL AND program = $1 ORDER BY metric_id"

_DELETE_TENANT_SQL = "DELETE FROM navigator.metric_definitions WHERE metric_id = $1 AND tenant = $2 RETURNING metric_id"
_DELETE_GLOBAL_SQL = (
    "DELETE FROM navigator.metric_definitions WHERE metric_id = $1 AND tenant IS NULL RETURNING metric_id"
)

_LIST_VISIBLE_SQL = (
    f"{_SELECT} WHERE ((tenant IS NULL AND visibility = 'public') OR tenant = $1) "
    "AND ($2::varchar IS NULL OR program = $2) ORDER BY metric_id, tenant NULLS FIRST"
)
_LIST_VISIBLE_GLOBAL_SQL = (
    f"{_SELECT} WHERE tenant IS NULL AND visibility = 'public' "
    "AND ($1::varchar IS NULL OR program = $1) ORDER BY metric_id"
)


async def _exec(conn: Any, sql: str, *args: Any) -> None:
    """``conn.execute`` that raises on error instead of returning it (ui_surfaces.py:438 idiom)."""
    result = await conn.execute(sql, *args)
    if isinstance(result, (list, tuple)) and len(result) == 2 and result[1]:
        error = result[1]
        raise error if isinstance(error, Exception) else RuntimeError(str(error))


async def _fetch_rows(conn: Any, sql: str, *args: Any) -> list[Any]:
    """``conn.fetch_all`` with ``None`` normalised to ``[]``."""
    rows = await conn.fetch_all(sql, *args)
    return list(rows) if rows else []


def _row_to_definition(row: Any) -> MetricDefinition:
    """Rebuild a definition from the JSONB ``definition`` column (tolerates a legacy JSON string)."""
    payload = row["definition"]
    if isinstance(payload, str):
        payload = json.loads(payload)
    return MetricDefinition.model_validate(payload)


def _row_groups(row: Any) -> list[str]:
    """Decode the ``allowed_groups`` column (native list or legacy JSON string)."""
    raw = row["allowed_groups"]
    if isinstance(raw, str):
        raw = json.loads(raw)
    return list(raw or [])


class PgMetricDefinitionStore:
    """Postgres ``MetricStore`` (PgUISurfaceStore idiom — handlers/models/ui_surfaces.py:457)."""

    def __init__(self, dsn: str | None = None) -> None:
        """Create the store.

        Args:
            dsn: Postgres DSN; defaults to ``parrot.conf.default_dsn``.
        """
        self.dsn = dsn or default_dsn
        self.logger = logger
        self._schema_ensured = False

    def _get_db(self) -> AsyncDB:
        """Fresh ``AsyncDB("pg", dsn=self.dsn)`` per call (ui_surfaces.py:474)."""
        return AsyncDB("pg", dsn=self.dsn)

    async def _ensure_ready(self) -> None:
        """Run ``ensure_schema`` once per store instance."""
        if not self._schema_ensured:
            await self.ensure_schema()

    async def ensure_schema(self) -> None:
        """Idempotent DDL; tolerates "already exists" races (ui_surfaces.py:483-501)."""
        db = self._get_db()
        async with await db.connection() as conn:
            for stmt in _DDL_STATEMENTS:
                try:
                    await _exec(conn, stmt)
                except Exception as exc:  # noqa: BLE001
                    if "already exists" in str(exc).lower():
                        self.logger.debug("metric_definitions DDL race tolerated: %s", exc)
                        continue
                    raise
        self._schema_ensured = True

    async def get(self, metric_id: str, *, tenant: str | None) -> MetricDefinition | None:
        """Return one definition in exactly that namespace, or ``None``.

        Args:
            metric_id: Metric identifier.
            tenant: Namespace tenant; ``None`` selects the global namespace.
        """
        await self._ensure_ready()
        db = self._get_db()
        async with await db.connection() as conn:
            if tenant is None:
                row = await conn.fetch_one(_GET_GLOBAL_SQL, metric_id)
            else:
                row = await conn.fetch_one(_GET_TENANT_SQL, metric_id, tenant)
        return _row_to_definition(row) if row else None

    async def list(self, *, tenant: str | None, program: str | None = None) -> list[MetricDefinition]:
        """Every definition of one namespace (no visibility filtering), ordered by metric_id.

        Args:
            tenant: Namespace tenant; ``None`` selects the global namespace.
            program: Optional program filter.
        """
        await self._ensure_ready()
        db = self._get_db()
        async with await db.connection() as conn:
            if tenant is None:
                if program is None:
                    rows = await _fetch_rows(conn, _LIST_GLOBAL_SQL)
                else:
                    rows = await _fetch_rows(conn, _LIST_GLOBAL_PROGRAM_SQL, program)
            elif program is None:
                rows = await _fetch_rows(conn, _LIST_TENANT_SQL, tenant)
            else:
                rows = await _fetch_rows(conn, _LIST_TENANT_PROGRAM_SQL, tenant, program)
        return [_row_to_definition(row) for row in rows]

    async def save(self, definition: MetricDefinition, *, overwrite: bool = False) -> str:
        """INSERT … ON CONFLICT DO NOTHING / DO UPDATE; returns ``definition.id``.

        Raises:
            ValueError: the definition already exists and ``overwrite`` is ``False``.
        """
        await self._ensure_ready()
        payload = definition.model_dump(mode="json")  # native dict — NEVER json.dumps (ui_surfaces.py:524-534)
        if definition.tenant is None:
            sql = _UPSERT_GLOBAL_SQL if overwrite else _INSERT_GLOBAL_SQL
        else:
            sql = _UPSERT_TENANT_SQL if overwrite else _INSERT_TENANT_SQL
        now = datetime.now(UTC)
        created_at = definition.created_at or now
        updated_at = now if overwrite else (definition.updated_at or now)
        db = self._get_db()
        async with await db.connection() as conn:
            result = await conn.fetchval(
                sql,
                definition.id,
                definition.tenant,
                definition.name,
                definition.owner,
                definition.visibility,
                list(definition.allowed_groups),
                definition.global_only,
                definition.program,
                payload,
                definition.version,
                created_at,
                updated_at,
            )
        if result is None:
            raise ValueError(f"Metric definition {definition.id!r} already exists for tenant {definition.tenant!r}")
        return definition.id

    async def delete(self, metric_id: str, *, tenant: str | None) -> bool:
        """Remove one definition; ``True`` when a row was removed."""
        await self._ensure_ready()
        db = self._get_db()
        async with await db.connection() as conn:
            if tenant is None:
                result = await conn.fetchval(_DELETE_GLOBAL_SQL, metric_id)
            else:
                result = await conn.fetchval(_DELETE_TENANT_SQL, metric_id, tenant)
        return bool(result)

    async def list_visible(self, scope: RequestScope, *, program: str | None = None) -> list[MetricDefinition]:
        """Global ``public`` rows plus ``scope.tenant`` rows the scope grants.

        Tenant rows are kept when the scope owns them or ``scope_grants`` allows them;
        other tenants' rows are never selected.
        """
        await self._ensure_ready()
        db = self._get_db()
        async with await db.connection() as conn:
            if scope.tenant is None:
                rows = await _fetch_rows(conn, _LIST_VISIBLE_GLOBAL_SQL, program)
            else:
                rows = await _fetch_rows(conn, _LIST_VISIBLE_SQL, scope.tenant, program)
        visible: list[MetricDefinition] = []
        for row in rows:
            row_tenant = row["tenant"]
            if row_tenant is None:
                if row["visibility"] == "public":
                    visible.append(_row_to_definition(row))
                continue
            if row_tenant != scope.tenant:
                continue
            owned = row["owner"] is not None and row["owner"] == scope.user_id
            if owned or scope_grants(
                tenant=row_tenant,
                visibility=row["visibility"],
                allowed_groups=_row_groups(row),
                scope=scope,
            ):
                visible.append(_row_to_definition(row))
        return visible
