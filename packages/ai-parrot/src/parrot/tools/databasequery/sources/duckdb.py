"""DuckDB database source for DatabaseToolkit.

Implements ``AbstractDatabaseSource`` for DuckDB embedded analytical database
using the ``duckdb`` Python API in a worker thread. Queries
``information_schema.columns`` for metadata discovery. Supports both in-process
(file) and in-memory modes. Inherits SQL validation from the base class via
``sqlglot_dialect = "duckdb"``.

Part of FEAT-062 — DatabaseToolkit.
"""

from __future__ import annotations

import asyncio
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


@register_source("duckdb")
class DuckDBSource(AbstractDatabaseSource):
    """DuckDB embedded analytical database source.

    Runs the synchronous ``duckdb`` Python API in a worker thread. Validates
    queries with the ``duckdb`` sqlglot dialect. Supports file-based and
    in-memory operation. Discovers schema via information_schema.columns.
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
                - ``read_only``: open a file database read-only (used by ``query``)

        Returns:
            DB instance configured for DuckDB.
        """
        database = credentials.get("database", credentials.get("dsn", ":memory:"))
        params = {"database": database}
        return self._get_db("duckdb", None, params)

    @staticmethod
    def _database(credentials: dict[str, Any]) -> str:
        """Return the configured DuckDB database path."""
        return str(credentials.get("database", credentials.get("dsn", ":memory:")))

    @staticmethod
    def _read_only(credentials: dict[str, Any]) -> bool:
        """Return whether the ``read_only`` credential requests a read-only file connection.

        In-memory databases cannot be opened read-only, so the flag only applies
        to file databases. String values (from environment overlays) are parsed.
        """
        value = credentials.get("read_only", False)
        if isinstance(value, str):
            value = value.strip().lower() in {"1", "true", "yes", "on"}
        return bool(value) and DuckDBSource._database(credentials) != ":memory:"

    @staticmethod
    def _unique_columns(columns: list[str]) -> list[str]:
        """Disambiguate duplicate result column names instead of collapsing them.

        The first occurrence keeps its name; later ones get ``_1``, ``_2`` ...
        suffixes that never collide with another column of the result.
        """
        taken = set(columns)
        seen: set[str] = set()
        unique: list[str] = []
        for column in columns:
            name = column
            if name in seen:
                index = 1
                while f"{column}_{index}" in taken:
                    index += 1
                name = f"{column}_{index}"
                taken.add(name)
            seen.add(name)
            unique.append(name)
        return unique

    @staticmethod
    def _execute_sync(
        database: str,
        sql: str,
        params: Any,
        *,
        one: bool,
        read_only: bool = False,
    ) -> tuple[list[dict[str, Any]], list[str]]:
        """Execute a query on a short-lived synchronous DuckDB connection.

        Args:
            database: DuckDB database path or ``":memory:"``.
            sql: SQL statement to execute.
            params: Named or positional query parameters.
            one: Whether to fetch at most one row.
            read_only: Open the file database read-only (a second barrier for
                governed SQL behind the positive guard).

        Returns:
            A pair containing dictionary rows and cursor column names.

        Raises:
            ImportError: If the optional DuckDB dependency is unavailable.
        """
        try:
            import duckdb
        except ModuleNotFoundError as exc:
            if exc.name != "duckdb":
                raise
            raise ImportError(
                "DuckDB support requires the optional 'duckdb' package; install the 'duckdb' extra."
            ) from exc

        connection = duckdb.connect(database=database, read_only=read_only)
        try:
            cursor = connection.execute(sql, params) if params is not None else connection.execute(sql)
            columns = DuckDBSource._unique_columns([column[0] for column in (cursor.description or [])])
            if one:
                row = cursor.fetchone()
                raw_rows = [] if row is None else [row]
            else:
                raw_rows = cursor.fetchall()
            rows = [dict(zip(columns, row, strict=True)) for row in raw_rows]
            return rows, columns
        finally:
            connection.close()

    async def _execute(
        self,
        credentials: dict[str, Any],
        sql: str,
        params: Any = None,
        *,
        one: bool = False,
    ) -> tuple[list[dict[str, Any]], list[str]]:
        """Execute blocking DuckDB work outside the event loop."""
        return await asyncio.to_thread(
            self._execute_sync,
            self._database(credentials),
            sql,
            params,
            one=one,
            read_only=self._read_only(credentials),
        )

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

        if validated_tables:
            placeholders = ", ".join([f"'{table}'" for table in validated_tables])
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
        rows, _ = await self._execute(credentials, sql)

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
        rows, columns = await self._execute(credentials, sql, params)

        elapsed_ms = (time.monotonic() - start) * 1000
        rows_list = [dict(r) if not isinstance(r, dict) else r for r in (rows or [])]

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
        rows, _ = await self._execute(credentials, sql, params, one=True)
        row = rows[0] if rows else None

        elapsed_ms = (time.monotonic() - start) * 1000
        row_dict = dict(row) if row and not isinstance(row, dict) else row

        return RowResult(
            driver=self.driver,
            row=row_dict,
            found=row_dict is not None,
            execution_time_ms=round(elapsed_ms, 3),
        )
