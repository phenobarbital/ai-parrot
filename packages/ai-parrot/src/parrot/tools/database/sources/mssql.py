"""Microsoft SQL Server database source for DatabaseToolkit.

Implements ``AbstractDatabaseSource`` for MSSQL using the asyncdb ``mssql`` driver.
Overrides ``validate_query()`` to allow EXEC/EXECUTE statements (stored procedures)
in addition to standard T-SQL. Includes stored procedures in metadata discovery.

Part of FEAT-062 — DatabaseToolkit.
"""
from __future__ import annotations

import logging
import re
import time
from typing import Any

from parrot.tools.database.base import (
    AbstractDatabaseSource,
    ColumnMeta,
    MetadataResult,
    QueryResult,
    RowResult,
    TableMeta,
    ValidationResult,
    _validate_sql_identifier,
)
from parrot.tools.database.sources import register_source

# Pattern to detect stored procedure execution statements
_EXEC_PATTERN = re.compile(r"^\s*(EXEC|EXECUTE)\s+", re.IGNORECASE)


@register_source("mssql")
class MSSQLSource(AbstractDatabaseSource):
    """Microsoft SQL Server database source with stored procedure support.

    Uses the asyncdb ``mssql`` driver. Validates queries with the ``tsql``
    sqlglot dialect, with special handling for EXEC/EXECUTE stored procedure calls.
    Exposes stored procedures alongside tables in metadata discovery.
    """

    driver = "mssql"
    sqlglot_dialect = "tsql"

    def __init__(self) -> None:
        """Initialize MSSQLSource with a logger."""
        self.logger = logging.getLogger("Parrot.Toolkits.Database.MSSQL")

    async def get_default_credentials(self) -> dict[str, Any]:
        """Return default MSSQL credentials.

        Returns:
            Empty dict (no default MSSQL credentials configured).
        """
        from parrot.interfaces.database import get_default_credentials
        dsn = get_default_credentials("mssql")
        return {"dsn": dsn} if dsn else {}

    async def validate_query(self, query: str) -> ValidationResult:
        """Validate a T-SQL query, including EXEC/EXECUTE statements.

        EXEC and EXECUTE are valid MSSQL stored procedure calls. The base
        sqlglot validation may reject them, so we pre-check for this pattern
        and return valid=True immediately for SP invocations.

        Standard SELECT/INSERT/UPDATE/DELETE queries are validated via the
        base class using the ``tsql`` sqlglot dialect.

        Args:
            query: T-SQL query string or EXEC/EXECUTE statement.

        Returns:
            ValidationResult indicating whether the query is valid.
        """
        if _EXEC_PATTERN.match(query):
            self.logger.debug("EXEC/EXECUTE statement detected — validated as valid")
            return ValidationResult(valid=True, dialect="tsql")
        # Delegate to base sqlglot validation with tsql dialect
        return await super().validate_query(query)

    async def get_metadata(
        self,
        credentials: dict[str, Any],
        tables: list[str] | None = None,
    ) -> MetadataResult:
        """Discover MSSQL schema, including tables and stored procedures.

        Queries both ``INFORMATION_SCHEMA.COLUMNS`` for table metadata and
        ``sys.procedures``/``sys.parameters`` for stored procedure metadata.
        Stored procedures are returned as TableMeta entries with
        ``schema_name="stored_procedures"``.

        Args:
            credentials: Connection credentials.
            tables: Optional list of specific table names to inspect.

        Returns:
            MetadataResult with table, column, and stored procedure metadata.
        """
        self.logger.debug("get_metadata called, tables=%s", tables)
        # Validate table names before acquiring a connection (fail-fast on injection)
        if tables:
            validated_tables = [_validate_sql_identifier(t, "table name") for t in tables]
        else:
            validated_tables = None

        dsn = credentials.get("dsn")
        params = credentials.get("params", credentials if "host" in credentials else None)

        db = self._get_db("mssql", dsn, params)
        async with await db.connection() as conn:
            # Query table columns
            if validated_tables:
                placeholders = ", ".join([f"'{t}'" for t in validated_tables])
                col_sql = f"""
                    SELECT
                        c.TABLE_SCHEMA, c.TABLE_NAME, c.COLUMN_NAME,
                        c.DATA_TYPE, c.IS_NULLABLE, c.COLUMN_DEFAULT,
                        CASE WHEN kcu.COLUMN_NAME IS NOT NULL THEN 1 ELSE 0 END AS is_pk
                    FROM INFORMATION_SCHEMA.COLUMNS c
                    LEFT JOIN INFORMATION_SCHEMA.TABLE_CONSTRAINTS tc
                        ON tc.TABLE_SCHEMA = c.TABLE_SCHEMA
                        AND tc.TABLE_NAME = c.TABLE_NAME
                        AND tc.CONSTRAINT_TYPE = 'PRIMARY KEY'
                    LEFT JOIN INFORMATION_SCHEMA.KEY_COLUMN_USAGE kcu
                        ON kcu.CONSTRAINT_NAME = tc.CONSTRAINT_NAME
                        AND kcu.COLUMN_NAME = c.COLUMN_NAME
                    WHERE c.TABLE_NAME IN ({placeholders})
                    ORDER BY c.TABLE_NAME, c.ORDINAL_POSITION
                """
            else:
                col_sql = """
                    SELECT
                        c.TABLE_SCHEMA, c.TABLE_NAME, c.COLUMN_NAME,
                        c.DATA_TYPE, c.IS_NULLABLE, c.COLUMN_DEFAULT,
                        CASE WHEN kcu.COLUMN_NAME IS NOT NULL THEN 1 ELSE 0 END AS is_pk
                    FROM INFORMATION_SCHEMA.COLUMNS c
                    LEFT JOIN INFORMATION_SCHEMA.TABLE_CONSTRAINTS tc
                        ON tc.TABLE_SCHEMA = c.TABLE_SCHEMA
                        AND tc.TABLE_NAME = c.TABLE_NAME
                        AND tc.CONSTRAINT_TYPE = 'PRIMARY KEY'
                    LEFT JOIN INFORMATION_SCHEMA.KEY_COLUMN_USAGE kcu
                        ON kcu.CONSTRAINT_NAME = tc.CONSTRAINT_NAME
                        AND kcu.COLUMN_NAME = c.COLUMN_NAME
                    ORDER BY c.TABLE_NAME, c.ORDINAL_POSITION
                """
            col_rows = await conn.fetch_all(col_sql)

            # Query stored procedures and their parameters
            sproc_sql = """
                SELECT
                    p.name AS proc_name,
                    SCHEMA_NAME(p.schema_id) AS schema_name,
                    sp.name AS param_name,
                    TYPE_NAME(sp.user_type_id) AS param_type,
                    sp.is_output
                FROM sys.procedures p
                LEFT JOIN sys.parameters sp ON sp.object_id = p.object_id
                ORDER BY p.name, sp.parameter_id
            """
            try:
                sproc_rows = await conn.fetch_all(sproc_sql)
            except Exception:  # noqa: BLE001
                sproc_rows = []

        # Build table metadata
        tables_map: dict[str, TableMeta] = {}
        for row in (col_rows or []):
            row_dict = dict(row) if not isinstance(row, dict) else row
            table_name = row_dict.get("TABLE_NAME", row_dict.get("table_name", ""))
            if table_name not in tables_map:
                tables_map[table_name] = TableMeta(
                    name=table_name,
                    schema_name=row_dict.get("TABLE_SCHEMA", row_dict.get("table_schema")),
                )
            col = ColumnMeta(
                name=row_dict.get("COLUMN_NAME", row_dict.get("column_name", "")),
                data_type=row_dict.get("DATA_TYPE", row_dict.get("data_type", "unknown")),
                nullable=row_dict.get("IS_NULLABLE", row_dict.get("is_nullable", "YES")) == "YES",
                primary_key=bool(row_dict.get("is_pk", 0)),
                default=row_dict.get("COLUMN_DEFAULT", row_dict.get("column_default")),
            )
            tables_map[table_name].columns.append(col)

        # Build stored procedure metadata
        sproc_map: dict[str, TableMeta] = {}
        for row in (sproc_rows or []):
            row_dict = dict(row) if not isinstance(row, dict) else row
            proc_name = row_dict.get("proc_name", "")
            if not proc_name:
                continue
            if proc_name not in sproc_map:
                sproc_map[proc_name] = TableMeta(
                    name=proc_name,
                    schema_name="stored_procedures",
                )
            param_name = row_dict.get("param_name", "")
            if param_name:
                col = ColumnMeta(
                    name=param_name,
                    data_type=row_dict.get("param_type", "unknown"),
                    nullable=True,
                    primary_key=False,
                )
                sproc_map[proc_name].columns.append(col)

        all_tables = list(tables_map.values()) + list(sproc_map.values())
        return MetadataResult(driver=self.driver, tables=all_tables)

    async def query(
        self,
        credentials: dict[str, Any],
        sql: str,
        params: dict[str, Any] | None = None,
    ) -> QueryResult:
        """Execute a T-SQL query or stored procedure call.

        Supports both standard SELECT statements and EXEC/EXECUTE calls.

        Args:
            credentials: Connection credentials.
            sql: T-SQL query or EXEC statement.
            params: Optional query parameters.

        Returns:
            QueryResult with rows and execution metadata.
        """
        self.logger.debug("query called: %s", sql[:100])
        start = time.monotonic()
        dsn = credentials.get("dsn")
        conn_params = credentials.get("params", credentials if "host" in credentials else None)

        db = self._get_db("mssql", dsn, conn_params)
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
        """Execute a T-SQL query and return the first row.

        Args:
            credentials: Connection credentials.
            sql: T-SQL query string.
            params: Optional query parameters.

        Returns:
            RowResult with a single row or found=False.
        """
        self.logger.debug("query_row called: %s", sql[:100])
        start = time.monotonic()
        dsn = credentials.get("dsn")
        conn_params = credentials.get("params", credentials if "host" in credentials else None)

        db = self._get_db("mssql", dsn, conn_params)
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
