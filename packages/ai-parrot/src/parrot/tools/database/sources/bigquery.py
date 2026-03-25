"""BigQuery database source for DatabaseToolkit.

Implements ``AbstractDatabaseSource`` for Google BigQuery using the asyncdb
``bigquery`` driver. Queries ``INFORMATION_SCHEMA.COLUMNS`` for metadata.
Inherits SQL validation from the base class via ``sqlglot_dialect = "bigquery"``.

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


@register_source("bigquery")
class BigQuerySource(AbstractDatabaseSource):
    """Google BigQuery database source.

    Uses the asyncdb ``bigquery`` driver. Validates queries with the
    ``bigquery`` sqlglot dialect. Discovers schema via INFORMATION_SCHEMA.
    """

    driver = "bigquery"
    sqlglot_dialect = "bigquery"

    def __init__(self) -> None:
        """Initialize BigQuerySource with a logger."""
        self.logger = logging.getLogger("Parrot.Toolkits.Database.BigQuery")

    async def get_default_credentials(self) -> dict[str, Any]:
        """Return default BigQuery credentials.

        Returns:
            Empty dict (BigQuery credentials from environment/service account).
        """
        from parrot.interfaces.database import get_default_credentials
        dsn = get_default_credentials("bigquery")
        return {"dsn": dsn} if dsn else {}

    async def get_metadata(
        self,
        credentials: dict[str, Any],
        tables: list[str] | None = None,
    ) -> MetadataResult:
        """Discover BigQuery schema via INFORMATION_SCHEMA.COLUMNS.

        Args:
            credentials: Connection credentials (project, dataset, etc.).
            tables: Optional list of specific table names to inspect.

        Returns:
            MetadataResult with table and column metadata.
        """
        self.logger.debug("get_metadata called, tables=%s", tables)
        dataset = credentials.get("dataset", credentials.get("schema", ""))
        project = credentials.get("project", credentials.get("project_id", ""))
        params = {k: v for k, v in credentials.items() if k not in ("dsn",)}
        dsn = credentials.get("dsn")

        db = AsyncDB("bigquery", dsn=dsn, params=params or None)
        async with await db.connection() as conn:
            dataset_ref = f"`{project}.{dataset}`" if project else f"`{dataset}`"
            if tables:
                table_filter = "AND table_name IN UNNEST(@tables)"
                sql = f"""
                    SELECT table_name, column_name, data_type, is_nullable
                    FROM {dataset_ref}.INFORMATION_SCHEMA.COLUMNS
                    WHERE {table_filter}
                    ORDER BY table_name, ordinal_position
                """
                rows = await conn.fetch_all(sql, tables=tables)
            else:
                sql = f"""
                    SELECT table_name, column_name, data_type, is_nullable
                    FROM {dataset_ref}.INFORMATION_SCHEMA.COLUMNS
                    ORDER BY table_name, ordinal_position
                """
                rows = await conn.fetch_all(sql)

        tables_map: dict[str, TableMeta] = {}
        for row in (rows or []):
            row_dict = dict(row) if not isinstance(row, dict) else row
            table_name = row_dict.get("table_name", "")
            if table_name not in tables_map:
                tables_map[table_name] = TableMeta(name=table_name, schema_name=dataset)
            col = ColumnMeta(
                name=row_dict.get("column_name", ""),
                data_type=row_dict.get("data_type", "unknown"),
                nullable=row_dict.get("is_nullable", "YES") == "YES",
            )
            tables_map[table_name].columns.append(col)

        return MetadataResult(driver=self.driver, tables=list(tables_map.values()))

    async def query(
        self,
        credentials: dict[str, Any],
        sql: str,
        params: dict[str, Any] | None = None,
    ) -> QueryResult:
        """Execute a BigQuery SQL query and return all results.

        Args:
            credentials: Connection credentials.
            sql: BigQuery SQL query string.
            params: Optional query parameters.

        Returns:
            QueryResult with rows and execution metadata.
        """
        self.logger.debug("query called: %s", sql[:100])
        start = time.monotonic()
        conn_params = {k: v for k, v in credentials.items() if k != "dsn"}
        dsn = credentials.get("dsn")

        db = AsyncDB("bigquery", dsn=dsn, params=conn_params or None)
        async with await db.connection() as conn:
            rows = await conn.fetch_all(sql, **(params or {}))

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
        """Execute a BigQuery SQL query and return the first row.

        Args:
            credentials: Connection credentials.
            sql: BigQuery SQL query string.
            params: Optional query parameters.

        Returns:
            RowResult with a single row or found=False.
        """
        self.logger.debug("query_row called: %s", sql[:100])
        start = time.monotonic()
        conn_params = {k: v for k, v in credentials.items() if k != "dsn"}
        dsn = credentials.get("dsn")

        db = AsyncDB("bigquery", dsn=dsn, params=conn_params or None)
        async with await db.connection() as conn:
            row = await conn.fetch_one(sql, **(params or {}))

        elapsed_ms = (time.monotonic() - start) * 1000
        row_dict = dict(row) if row and not isinstance(row, dict) else row

        return RowResult(
            driver=self.driver,
            row=row_dict,
            found=row_dict is not None,
            execution_time_ms=round(elapsed_ms, 3),
        )
