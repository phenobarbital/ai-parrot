"""PostgreSQL database source for DatabaseToolkit.

Implements ``AbstractDatabaseSource`` for PostgreSQL using the asyncdb ``pg`` driver.
Queries ``information_schema`` for metadata discovery.
Inherits SQL validation from the base class via ``sqlglot_dialect = "postgres"``.

Part of FEAT-062 — DatabaseToolkit.
"""
from __future__ import annotations

import logging
import time
from typing import Any

from parrot.tools.database.base import (
    AbstractDatabaseSource,
    ColumnMeta,
    MetadataResult,
    QueryResult,
    RowResult,
    TableMeta,
)
from parrot.tools.database.sources import register_source


@register_source("pg")
class PostgresSource(AbstractDatabaseSource):
    """PostgreSQL database source.

    Uses the asyncdb ``pg`` driver. Validates queries with the
    ``postgres`` sqlglot dialect. Discovers schema via ``information_schema``.
    """

    driver = "pg"
    sqlglot_dialect = "postgres"

    def __init__(self) -> None:
        """Initialize PostgresSource with a logger."""
        self.logger = logging.getLogger("Parrot.Toolkits.Database.Postgres")

    async def get_default_credentials(self) -> dict[str, Any]:
        """Return default PostgreSQL credentials from querysource config.

        Returns:
            Dict with ``dsn`` key if a default DSN is configured, else empty dict.
        """
        from parrot.interfaces.database import get_default_credentials
        dsn = get_default_credentials("pg")
        return {"dsn": dsn} if dsn else {}

    async def get_metadata(
        self,
        credentials: dict[str, Any],
        tables: list[str] | None = None,
    ) -> MetadataResult:
        """Discover PostgreSQL schema via information_schema.

        Args:
            credentials: Connection credentials (``dsn`` or ``params``).
            tables: Optional list of specific table names to inspect.

        Returns:
            MetadataResult with table and column metadata.
        """
        self.logger.debug("get_metadata called, tables=%s", tables)
        dsn = credentials.get("dsn")
        params = credentials.get("params", credentials if "host" in credentials else None)

        db = self._get_db("pg", dsn, params)
        async with await db.connection() as conn:
            if tables:
                filter_clause = "AND t.table_name = ANY($1)"
                filter_args = [tables]
            else:
                filter_clause = ""
                filter_args = []

            sql = f"""
                SELECT
                    t.table_schema,
                    t.table_name,
                    c.column_name,
                    c.data_type,
                    c.is_nullable,
                    c.column_default,
                    CASE WHEN kcu.column_name IS NOT NULL THEN true ELSE false END AS is_pk
                FROM information_schema.tables t
                JOIN information_schema.columns c
                    ON c.table_schema = t.table_schema
                    AND c.table_name = t.table_name
                LEFT JOIN information_schema.table_constraints tc
                    ON tc.table_schema = t.table_schema
                    AND tc.table_name = t.table_name
                    AND tc.constraint_type = 'PRIMARY KEY'
                LEFT JOIN information_schema.key_column_usage kcu
                    ON kcu.constraint_name = tc.constraint_name
                    AND kcu.table_schema = tc.table_schema
                    AND kcu.column_name = c.column_name
                WHERE t.table_type = 'BASE TABLE'
                    AND t.table_schema NOT IN ('pg_catalog', 'information_schema')
                    {filter_clause}
                ORDER BY t.table_schema, t.table_name, c.ordinal_position
            """
            rows = await conn.fetch_all(sql, *filter_args)

        # Group by table
        tables_map: dict[str, TableMeta] = {}
        for row in (rows or []):
            row_dict = dict(row) if hasattr(row, '__iter__') and not isinstance(row, dict) else row
            key = f"{row_dict.get('table_schema', '')}.{row_dict.get('table_name', '')}"
            if key not in tables_map:
                tables_map[key] = TableMeta(
                    name=row_dict.get("table_name", ""),
                    schema_name=row_dict.get("table_schema"),
                )
            col = ColumnMeta(
                name=row_dict.get("column_name", ""),
                data_type=row_dict.get("data_type", "unknown"),
                nullable=row_dict.get("is_nullable", "YES") == "YES",
                primary_key=bool(row_dict.get("is_pk", False)),
                default=row_dict.get("column_default"),
            )
            tables_map[key].columns.append(col)

        return MetadataResult(driver=self.driver, tables=list(tables_map.values()))

    async def query(
        self,
        credentials: dict[str, Any],
        sql: str,
        params: dict[str, Any] | None = None,
    ) -> QueryResult:
        """Execute a SQL query and return all results.

        Args:
            credentials: Connection credentials.
            sql: SQL query string.
            params: Optional query parameters (positional or named).

        Returns:
            QueryResult with rows and execution metadata.
        """
        self.logger.debug("query called: %s", sql[:100])
        start = time.monotonic()
        dsn = credentials.get("dsn")
        conn_params = credentials.get("params", credentials if "host" in credentials else None)

        db = self._get_db("pg", dsn, conn_params)
        async with await db.connection() as conn:
            if params:
                if isinstance(params, dict):
                    rows = await conn.fetch_all(sql, **params)
                else:
                    rows = await conn.fetch_all(sql, *params)
            else:
                rows = await conn.fetch_all(sql)

        elapsed_ms = (time.monotonic() - start) * 1000
        rows_list = [dict(r) for r in (rows or [])]
        columns = list(rows_list[0].keys()) if rows_list else []

        return QueryResult(
            driver=self.driver,
            rows=rows_list,
            row_count=len(rows_list),
            columns=columns,
            execution_time_ms=round(elapsed_ms, 3),
        )

    async def query_row(
        self,
        credentials: dict[str, Any],
        sql: str,
        params: dict[str, Any] | None = None,
    ) -> RowResult:
        """Execute a SQL query and return the first row.

        Args:
            credentials: Connection credentials.
            sql: SQL query string.
            params: Optional query parameters.

        Returns:
            RowResult with a single row or found=False.
        """
        self.logger.debug("query_row called: %s", sql[:100])
        start = time.monotonic()
        dsn = credentials.get("dsn")
        conn_params = credentials.get("params", credentials if "host" in credentials else None)

        db = self._get_db("pg", dsn, conn_params)
        async with await db.connection() as conn:
            if params:
                if isinstance(params, dict):
                    row = await conn.fetch_one(sql, **params)
                else:
                    row = await conn.fetch_one(sql, *params)
            else:
                row = await conn.fetch_one(sql)

        elapsed_ms = (time.monotonic() - start) * 1000
        row_dict = dict(row) if row is not None else None

        return RowResult(
            driver=self.driver,
            row=row_dict,
            found=row_dict is not None,
            execution_time_ms=round(elapsed_ms, 3),
        )
