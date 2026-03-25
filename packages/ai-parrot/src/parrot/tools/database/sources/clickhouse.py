"""ClickHouse database source for DatabaseToolkit.

Implements ``AbstractDatabaseSource`` for ClickHouse OLAP database using the
asyncdb ``clickhouse`` driver. Queries ``system.columns`` for metadata discovery.
Inherits SQL validation from the base class via ``sqlglot_dialect = "clickhouse"``.

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


@register_source("clickhouse")
class ClickHouseSource(AbstractDatabaseSource):
    """ClickHouse OLAP database source.

    Uses the asyncdb ``clickhouse`` driver. Validates queries with the
    ``clickhouse`` sqlglot dialect. Discovers schema via system.columns.
    """

    driver = "clickhouse"
    sqlglot_dialect = "clickhouse"

    def __init__(self) -> None:
        """Initialize ClickHouseSource with a logger."""
        self.logger = logging.getLogger("Parrot.Toolkits.Database.ClickHouse")

    async def get_default_credentials(self) -> dict[str, Any]:
        """Return default ClickHouse credentials.

        Returns:
            Empty dict (no default ClickHouse credentials configured).
        """
        from parrot.interfaces.database import get_default_credentials
        dsn = get_default_credentials("clickhouse")
        return {"dsn": dsn} if dsn else {}

    async def get_metadata(
        self,
        credentials: dict[str, Any],
        tables: list[str] | None = None,
    ) -> MetadataResult:
        """Discover ClickHouse schema via system.columns.

        Args:
            credentials: Connection credentials (``database`` key for DB name).
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

        database = credentials.get("database", credentials.get("db", "default"))
        dsn = credentials.get("dsn")
        params = credentials.get("params", credentials if "host" in credentials else None)

        db = self._get_db("clickhouse", dsn, params)
        async with await db.connection() as conn:
            if validated_tables:
                placeholders = ", ".join([f"'{t}'" for t in validated_tables])
                sql = f"""
                    SELECT database, table, name AS column_name, type AS data_type,
                           default_expression AS column_default,
                           is_in_primary_key
                    FROM system.columns
                    WHERE database = %(db)s AND table IN ({placeholders})
                    ORDER BY table, position
                """
            else:
                sql = """
                    SELECT database, table, name AS column_name, type AS data_type,
                           default_expression AS column_default,
                           is_in_primary_key
                    FROM system.columns
                    WHERE database = %(db)s
                    ORDER BY table, position
                """
            rows = await conn.fetch_all(sql, db=database)

        tables_map: dict[str, TableMeta] = {}
        for row in (rows or []):
            row_dict = dict(row) if not isinstance(row, dict) else row
            table_name = row_dict.get("table", "")
            if table_name not in tables_map:
                tables_map[table_name] = TableMeta(
                    name=table_name,
                    schema_name=row_dict.get("database", database),
                )
            col = ColumnMeta(
                name=row_dict.get("column_name", ""),
                data_type=row_dict.get("data_type", "unknown"),
                nullable="Nullable" in row_dict.get("data_type", ""),
                primary_key=bool(row_dict.get("is_in_primary_key", 0)),
                default=row_dict.get("column_default") or None,
            )
            tables_map[table_name].columns.append(col)

        return MetadataResult(driver=self.driver, tables=list(tables_map.values()))

    async def query(
        self,
        credentials: dict[str, Any],
        sql: str,
        params: dict[str, Any] | None = None,
    ) -> QueryResult:
        """Execute a ClickHouse SQL query and return all results.

        Args:
            credentials: Connection credentials.
            sql: ClickHouse SQL query string.
            params: Optional query parameters.

        Returns:
            QueryResult with rows and execution metadata.
        """
        self.logger.debug("query called: %s", sql[:100])
        start = time.monotonic()
        dsn = credentials.get("dsn")
        conn_params = credentials.get("params", credentials if "host" in credentials else None)

        db = self._get_db("clickhouse", dsn, conn_params)
        async with await db.connection() as conn:
            if params:
                rows = await conn.fetch_all(sql, **params)
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
        """Execute a ClickHouse SQL query and return the first row.

        Args:
            credentials: Connection credentials.
            sql: ClickHouse SQL query string.
            params: Optional query parameters.

        Returns:
            RowResult with a single row or found=False.
        """
        self.logger.debug("query_row called: %s", sql[:100])
        start = time.monotonic()
        dsn = credentials.get("dsn")
        conn_params = credentials.get("params", credentials if "host" in credentials else None)

        db = self._get_db("clickhouse", dsn, conn_params)
        async with await db.connection() as conn:
            if params:
                row = await conn.fetch_one(sql, **params)
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
