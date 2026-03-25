"""MySQL database source for DatabaseToolkit.

Implements ``AbstractDatabaseSource`` for MySQL/MariaDB using the asyncdb ``mysql``
driver. Queries ``information_schema`` for metadata discovery.
Inherits SQL validation from the base class via ``sqlglot_dialect = "mysql"``.

Part of FEAT-062 — DatabaseToolkit.
"""
from __future__ import annotations

import logging
import time
from typing import Any

from asyncdb import AsyncDB

from parrot.tools.database.base import (
    AbstractDatabaseSource,
    ColumnMeta,
    MetadataResult,
    QueryResult,
    RowResult,
    TableMeta,
)
from parrot.tools.database.sources import register_source


@register_source("mysql")
class MySQLSource(AbstractDatabaseSource):
    """MySQL/MariaDB database source.

    Uses the asyncdb ``mysql`` driver. Validates queries with the
    ``mysql`` sqlglot dialect. Discovers schema via ``information_schema``.
    """

    driver = "mysql"
    sqlglot_dialect = "mysql"

    def __init__(self) -> None:
        """Initialize MySQLSource with a logger."""
        self.logger = logging.getLogger("Parrot.Toolkits.Database.MySQL")

    async def get_default_credentials(self) -> dict[str, Any]:
        """Return default MySQL credentials.

        Returns:
            Empty dict (no default MySQL credentials are configured).
        """
        from parrot.interfaces.database import get_default_credentials
        dsn = get_default_credentials("mysql")
        return {"dsn": dsn} if dsn else {}

    async def get_metadata(
        self,
        credentials: dict[str, Any],
        tables: list[str] | None = None,
    ) -> MetadataResult:
        """Discover MySQL schema via information_schema.

        Args:
            credentials: Connection credentials.
            tables: Optional list of specific table names to inspect.

        Returns:
            MetadataResult with table and column metadata.
        """
        self.logger.debug("get_metadata called, tables=%s", tables)
        dsn = credentials.get("dsn")
        params = credentials.get("params", credentials if "host" in credentials else None)
        database = credentials.get("database", "")

        db = AsyncDB("mysql", dsn=dsn, params=params)
        async with await db.connection() as conn:
            if tables:
                placeholders = ", ".join(["%s"] * len(tables))
                sql = f"""
                    SELECT
                        TABLE_SCHEMA AS table_schema,
                        TABLE_NAME AS table_name,
                        COLUMN_NAME AS column_name,
                        DATA_TYPE AS data_type,
                        IS_NULLABLE AS is_nullable,
                        COLUMN_DEFAULT AS column_default,
                        COLUMN_KEY AS column_key
                    FROM information_schema.COLUMNS
                    WHERE TABLE_SCHEMA = %s
                        AND TABLE_NAME IN ({placeholders})
                    ORDER BY TABLE_NAME, ORDINAL_POSITION
                """
                rows = await conn.fetch_all(sql, database, *tables)
            else:
                sql = """
                    SELECT
                        TABLE_SCHEMA AS table_schema,
                        TABLE_NAME AS table_name,
                        COLUMN_NAME AS column_name,
                        DATA_TYPE AS data_type,
                        IS_NULLABLE AS is_nullable,
                        COLUMN_DEFAULT AS column_default,
                        COLUMN_KEY AS column_key
                    FROM information_schema.COLUMNS
                    WHERE TABLE_SCHEMA = %s
                    ORDER BY TABLE_NAME, ORDINAL_POSITION
                """
                rows = await conn.fetch_all(sql, database)

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
                primary_key=row_dict.get("column_key", "") == "PRI",
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
        dsn = credentials.get("dsn")
        conn_params = credentials.get("params", credentials if "host" in credentials else None)

        db = AsyncDB("mysql", dsn=dsn, params=conn_params)
        async with await db.connection() as conn:
            if params:
                rows = await conn.fetch_all(sql, *params.values() if isinstance(params, dict) else params)
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

        db = AsyncDB("mysql", dsn=dsn, params=conn_params)
        async with await db.connection() as conn:
            if params:
                row = await conn.fetch_one(sql, *params.values() if isinstance(params, dict) else params)
            else:
                row = await conn.fetch_one(sql)

        elapsed_ms = (time.monotonic() - start) * 1000
        row_dict = dict(row) if row else None

        return RowResult(
            driver=self.driver,
            row=row_dict,
            found=row_dict is not None,
            execution_time_ms=round(elapsed_ms, 3),
        )
