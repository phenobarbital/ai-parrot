"""Oracle database source for DatabaseToolkit.

Implements ``AbstractDatabaseSource`` for Oracle Database using the asyncdb
``oracle`` driver. Queries ``ALL_TAB_COLUMNS`` for metadata discovery.
Inherits SQL validation from the base class via ``sqlglot_dialect = "oracle"``.

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


@register_source("oracle")
class OracleSource(AbstractDatabaseSource):
    """Oracle Database source.

    Uses the asyncdb ``oracle`` driver. Validates queries with the
    ``oracle`` sqlglot dialect. Discovers schema via ALL_TAB_COLUMNS.
    """

    driver = "oracle"
    sqlglot_dialect = "oracle"

    def __init__(self) -> None:
        """Initialize OracleSource with a logger."""
        self.logger = logging.getLogger("Parrot.Toolkits.Database.Oracle")

    async def get_default_credentials(self) -> dict[str, Any]:
        """Return default Oracle credentials.

        Returns:
            Empty dict (no default Oracle credentials configured).
        """
        from parrot.interfaces.database import get_default_credentials
        dsn = get_default_credentials("oracle")
        return {"dsn": dsn} if dsn else {}

    async def get_metadata(
        self,
        credentials: dict[str, Any],
        tables: list[str] | None = None,
    ) -> MetadataResult:
        """Discover Oracle schema via ALL_TAB_COLUMNS.

        Args:
            credentials: Connection credentials (``schema`` key for owner).
            tables: Optional list of specific table names to inspect.

        Returns:
            MetadataResult with table and column metadata.
        """
        self.logger.debug("get_metadata called, tables=%s", tables)
        schema = credentials.get("schema", credentials.get("user", "")).upper()
        dsn = credentials.get("dsn")
        params = credentials.get("params", credentials if "host" in credentials else None)

        db = AsyncDB("oracle", dsn=dsn, params=params)
        async with await db.connection() as conn:
            if tables:
                upper_tables = [t.upper() for t in tables]
                placeholders = ", ".join([f":t{i}" for i in range(len(upper_tables))])
                sql = f"""
                    SELECT OWNER, TABLE_NAME, COLUMN_NAME, DATA_TYPE,
                           NULLABLE, DATA_DEFAULT,
                           CASE WHEN cc.COLUMN_NAME IS NOT NULL THEN 'Y' ELSE 'N' END AS is_pk
                    FROM ALL_TAB_COLUMNS atc
                    LEFT JOIN (
                        SELECT acc.TABLE_NAME, acc.COLUMN_NAME
                        FROM ALL_CONS_COLUMNS acc
                        JOIN ALL_CONSTRAINTS ac ON acc.CONSTRAINT_NAME = ac.CONSTRAINT_NAME
                        WHERE ac.CONSTRAINT_TYPE = 'P' AND ac.OWNER = :owner
                    ) cc ON cc.TABLE_NAME = atc.TABLE_NAME AND cc.COLUMN_NAME = atc.COLUMN_NAME
                    WHERE atc.OWNER = :owner AND atc.TABLE_NAME IN ({placeholders})
                    ORDER BY atc.TABLE_NAME, atc.COLUMN_ID
                """
                bind_params = {"owner": schema}
                bind_params.update({f"t{i}": t for i, t in enumerate(upper_tables)})
                rows = await conn.fetch_all(sql, **bind_params)
            else:
                sql = """
                    SELECT OWNER, TABLE_NAME, COLUMN_NAME, DATA_TYPE,
                           NULLABLE, DATA_DEFAULT,
                           CASE WHEN cc.COLUMN_NAME IS NOT NULL THEN 'Y' ELSE 'N' END AS is_pk
                    FROM ALL_TAB_COLUMNS atc
                    LEFT JOIN (
                        SELECT acc.TABLE_NAME, acc.COLUMN_NAME
                        FROM ALL_CONS_COLUMNS acc
                        JOIN ALL_CONSTRAINTS ac ON acc.CONSTRAINT_NAME = ac.CONSTRAINT_NAME
                        WHERE ac.CONSTRAINT_TYPE = 'P' AND ac.OWNER = :owner
                    ) cc ON cc.TABLE_NAME = atc.TABLE_NAME AND cc.COLUMN_NAME = atc.COLUMN_NAME
                    WHERE atc.OWNER = :owner
                    ORDER BY atc.TABLE_NAME, atc.COLUMN_ID
                """
                rows = await conn.fetch_all(sql, owner=schema)

        tables_map: dict[str, TableMeta] = {}
        for row in (rows or []):
            row_dict = dict(row) if not isinstance(row, dict) else row
            table_name = row_dict.get("TABLE_NAME", row_dict.get("table_name", ""))
            if table_name not in tables_map:
                tables_map[table_name] = TableMeta(
                    name=table_name,
                    schema_name=row_dict.get("OWNER", row_dict.get("owner", schema)),
                )
            col = ColumnMeta(
                name=row_dict.get("COLUMN_NAME", row_dict.get("column_name", "")),
                data_type=row_dict.get("DATA_TYPE", row_dict.get("data_type", "unknown")),
                nullable=row_dict.get("NULLABLE", row_dict.get("nullable", "Y")) == "Y",
                primary_key=row_dict.get("IS_PK", row_dict.get("is_pk", "N")) == "Y",
                default=row_dict.get("DATA_DEFAULT", row_dict.get("data_default")),
            )
            tables_map[table_name].columns.append(col)

        return MetadataResult(driver=self.driver, tables=list(tables_map.values()))

    async def query(
        self,
        credentials: dict[str, Any],
        sql: str,
        params: dict[str, Any] | None = None,
    ) -> QueryResult:
        """Execute an Oracle SQL query and return all results.

        Args:
            credentials: Connection credentials.
            sql: Oracle SQL query string.
            params: Optional query parameters (named bind variables).

        Returns:
            QueryResult with rows and execution metadata.
        """
        self.logger.debug("query called: %s", sql[:100])
        start = time.monotonic()
        dsn = credentials.get("dsn")
        conn_params = credentials.get("params", credentials if "host" in credentials else None)

        db = AsyncDB("oracle", dsn=dsn, params=conn_params)
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
        """Execute an Oracle SQL query and return the first row.

        Args:
            credentials: Connection credentials.
            sql: Oracle SQL query string.
            params: Optional query parameters.

        Returns:
            RowResult with a single row or found=False.
        """
        self.logger.debug("query_row called: %s", sql[:100])
        start = time.monotonic()
        dsn = credentials.get("dsn")
        conn_params = credentials.get("params", credentials if "host" in credentials else None)

        db = AsyncDB("oracle", dsn=dsn, params=conn_params)
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
