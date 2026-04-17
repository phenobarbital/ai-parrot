"""SQLite database source for DatabaseToolkit.

Implements ``AbstractDatabaseSource`` for SQLite using the asyncdb ``sqlite``
driver. Uses ``PRAGMA table_info()`` and ``sqlite_master`` for metadata discovery
(SQLite does not have information_schema).
Inherits SQL validation from the base class via ``sqlglot_dialect = "sqlite"``.

Part of FEAT-062 — DatabaseToolkit.
"""
from __future__ import annotations

import logging
import time
from typing import Any

from parrot.tools.databasequery.base import (
    AbstractDatabaseSource,
    ColumnMeta,
    MetadataResult,
    QueryResult,
    RowResult,
    TableMeta,
    _validate_sql_identifier,
)
from parrot.tools.databasequery.sources import register_source


@register_source("sqlite")
class SQLiteSource(AbstractDatabaseSource):
    """SQLite database source.

    Uses the asyncdb ``sqlite`` driver. Validates queries with the
    ``sqlite`` sqlglot dialect. Discovers schema via PRAGMA and sqlite_master.
    """

    driver = "sqlite"
    sqlglot_dialect = "sqlite"

    def __init__(self) -> None:
        """Initialize SQLiteSource with a logger."""
        self.logger = logging.getLogger("Parrot.Toolkits.Database.SQLite")

    async def get_default_credentials(self) -> dict[str, Any]:
        """Return default SQLite credentials.

        Returns:
            Empty dict (SQLite uses file paths, no default configured).
        """
        return {}

    async def get_metadata(
        self,
        credentials: dict[str, Any],
        tables: list[str] | None = None,
    ) -> MetadataResult:
        """Discover SQLite schema via PRAGMA table_info() and sqlite_master.

        Args:
            credentials: Connection credentials (``database`` key for file path).
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

        database = credentials.get("database", credentials.get("dsn", ":memory:"))
        params = {"database": database} if isinstance(database, str) and not database.startswith("sqlite://") else None
        dsn = credentials.get("dsn") if not params else None

        db = self._get_db("sqlite", dsn, params)
        async with await db.connection() as conn:
            # Get all tables
            if validated_tables:
                placeholders = ", ".join([f"'{t}'" for t in validated_tables])
                table_list_sql = f"SELECT name FROM sqlite_master WHERE type='table' AND name IN ({placeholders})"
            else:
                table_list_sql = "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"

            table_rows = await conn.fetch_all(table_list_sql)
            table_names = [r[0] if isinstance(r, (list, tuple)) else r.get("name", "") for r in (table_rows or [])]

            tables_result = []
            for table_name in table_names:
                safe_name = table_name.replace('"', '""')
                pragma_rows = await conn.fetch_all(f'PRAGMA table_info("{safe_name}")')
                columns = []
                for row in (pragma_rows or []):
                    row_dict = dict(row) if not isinstance(row, dict) else row
                    # PRAGMA returns: cid, name, type, notnull, dflt_value, pk
                    col = ColumnMeta(
                        name=row_dict.get("name", row_dict.get(1, "")),
                        data_type=row_dict.get("type", row_dict.get(2, "TEXT")),
                        nullable=not bool(row_dict.get("notnull", row_dict.get(3, 0))),
                        primary_key=bool(row_dict.get("pk", row_dict.get(5, 0))),
                        default=row_dict.get("dflt_value", row_dict.get(4)),
                    )
                    columns.append(col)
                tables_result.append(TableMeta(name=table_name, columns=columns))

        return MetadataResult(driver=self.driver, tables=tables_result)

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
            params: Optional query parameters.

        Returns:
            QueryResult with rows and execution metadata.
        """
        self.logger.debug("query called: %s", sql[:100])
        start = time.monotonic()
        database = credentials.get("database", credentials.get("dsn", ":memory:"))
        conn_params = {"database": database} if not database.startswith("sqlite://") else None
        dsn = credentials.get("dsn") if not conn_params else None

        db = self._get_db("sqlite", dsn, conn_params)
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
        database = credentials.get("database", credentials.get("dsn", ":memory:"))
        conn_params = {"database": database} if not database.startswith("sqlite://") else None
        dsn = credentials.get("dsn") if not conn_params else None

        db = self._get_db("sqlite", dsn, conn_params)
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
