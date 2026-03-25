"""DuckDB database source for DatabaseToolkit.

Implements ``AbstractDatabaseSource`` for DuckDB embedded analytical database
using the asyncdb ``duckdb`` driver. Queries ``information_schema.columns``
for metadata discovery. Supports both in-process (file) and in-memory modes.
Inherits SQL validation from the base class via ``sqlglot_dialect = "duckdb"``.

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
    _validate_sql_identifier,
)
from parrot.tools.database.sources import register_source


@register_source("duckdb")
class DuckDBSource(AbstractDatabaseSource):
    """DuckDB embedded analytical database source.

    Uses the asyncdb ``duckdb`` driver. Validates queries with the
    ``duckdb`` sqlglot dialect. Supports file-based and in-memory operation.
    Discovers schema via information_schema.columns.
    """

    driver = "duckdb"
    sqlglot_dialect = "duckdb"

    def __init__(self) -> None:
        """Initialize DuckDBSource with a logger."""
        self.logger = logging.getLogger("Parrot.Toolkits.Database.DuckDB")

    async def get_default_credentials(self) -> dict[str, Any]:
        """Return default DuckDB credentials.

        Returns:
            Empty dict (DuckDB defaults to in-memory database).
        """
        return {}

    def _get_connection(self, credentials: dict[str, Any]) -> Any:
        """Create a DuckDB connection from credentials.

        Args:
            credentials: Credentials dict. Supports:
                - ``database``: file path for persistent DB (default ``":memory:"``)
                - ``dsn``: full connection string

        Returns:
            DB instance configured for DuckDB.
        """
        database = credentials.get("database", credentials.get("dsn", ":memory:"))
        params = {"database": database}
        return self._get_db("duckdb", None, params)

    async def get_metadata(
        self,
        credentials: dict[str, Any],
        tables: list[str] | None = None,
    ) -> MetadataResult:
        """Discover DuckDB schema via information_schema.columns.

        Args:
            credentials: Connection credentials (``database`` for file path).
            tables: Optional list of specific table names to inspect.

        Returns:
            MetadataResult with table and column metadata.
        """
        self.logger.debug("get_metadata called, tables=%s", tables)
        # Validate table names before acquiring a connection (fail-fast on injection)
        if tables:
            validated_tables = [_validate_sql_identifier(t, "table name") for t in tables]
        else:
            validated_tables = None

        db = self._get_connection(credentials)

        async with await db.connection() as conn:
            if validated_tables:
                placeholders = ", ".join([f"'{t}'" for t in validated_tables])
                sql = f"""
                    SELECT table_schema, table_name, column_name, data_type,
                           is_nullable, column_default
                    FROM information_schema.columns
                    WHERE table_schema NOT IN ('pg_catalog', 'information_schema')
                      AND table_name IN ({placeholders})
                    ORDER BY table_name, ordinal_position
                """
            else:
                sql = """
                    SELECT table_schema, table_name, column_name, data_type,
                           is_nullable, column_default
                    FROM information_schema.columns
                    WHERE table_schema NOT IN ('pg_catalog', 'information_schema')
                    ORDER BY table_name, ordinal_position
                """
            rows = await conn.fetch_all(sql)

        tables_map: dict[str, TableMeta] = {}
        for row in (rows or []):
            row_dict = dict(row) if not isinstance(row, dict) else row
            table_name = row_dict.get("table_name", "")
            if table_name not in tables_map:
                tables_map[table_name] = TableMeta(
                    name=table_name,
                    schema_name=row_dict.get("table_schema"),
                )
            col = ColumnMeta(
                name=row_dict.get("column_name", ""),
                data_type=row_dict.get("data_type", "unknown"),
                nullable=row_dict.get("is_nullable", "YES") == "YES",
                default=row_dict.get("column_default"),
            )
            tables_map[table_name].columns.append(col)

        return MetadataResult(driver=self.driver, tables=list(tables_map.values()))

    async def query(
        self,
        credentials: dict[str, Any],
        sql: str,
        params: dict[str, Any] | None = None,
    ) -> QueryResult:
        """Execute a DuckDB SQL query and return all results.

        Args:
            credentials: Connection credentials.
            sql: DuckDB SQL query string.
            params: Optional query parameters.

        Returns:
            QueryResult with rows and execution metadata.
        """
        self.logger.debug("query called: %s", sql[:100])
        start = time.monotonic()
        db = self._get_connection(credentials)

        async with await db.connection() as conn:
            if params:
                if isinstance(params, dict):
                    rows = await conn.fetch_all(sql, **params)
                else:
                    rows = await conn.fetch_all(sql, *params)
            else:
                rows = await conn.fetch_all(sql)

        elapsed_ms = (time.monotonic() - start) * 1000
        rows_list = [dict(r) if not isinstance(r, dict) else r for r in (rows or [])]
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
        """Execute a DuckDB SQL query and return the first row.

        Args:
            credentials: Connection credentials.
            sql: DuckDB SQL query string.
            params: Optional query parameters.

        Returns:
            RowResult with a single row or found=False.
        """
        self.logger.debug("query_row called: %s", sql[:100])
        start = time.monotonic()
        db = self._get_connection(credentials)

        async with await db.connection() as conn:
            if params:
                if isinstance(params, dict):
                    row = await conn.fetch_one(sql, **params)
                else:
                    row = await conn.fetch_one(sql, *params)
            else:
                row = await conn.fetch_one(sql)

        elapsed_ms = (time.monotonic() - start) * 1000
        row_dict = dict(row) if row and not isinstance(row, dict) else row

        return RowResult(
            driver=self.driver,
            row=row_dict,
            found=row_dict is not None,
            execution_time_ms=round(elapsed_ms, 3),
        )
