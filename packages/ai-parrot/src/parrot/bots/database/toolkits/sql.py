"""SQLToolkit — common SQL operations with overridable dialect hooks.

Inherits ``DatabaseToolkit`` and implements schema search, query generation,
execution, explain, and validation for SQL databases.  Dialect differences
(PostgreSQL vs BigQuery vs MySQL) are handled via overridable ``_get_*``
hook methods.

All execution goes through asyncdb — the asyncpg-native path is the only
supported backend. Query builders emit ``$1, $2, …`` positional placeholders.
"""
from __future__ import annotations

import time
from typing import Any, Dict, List, Optional, Union

from ..cache import CachePartition
from ..models import (
    QueryExecutionResponse,
    TableMetadata,
)
from ..retries import QueryRetryConfig, RetryContext, SQLRetryHandler
from .base import DatabaseToolkit


#: Map ``DatabaseToolkit.database_type`` values to sqlglot dialect names.
_SQLGLOT_DIALECT_MAP: Dict[str, str] = {
    "postgresql": "postgres",
    "postgres": "postgres",
    "bigquery": "bigquery",
    "mysql": "mysql",
    "mariadb": "mysql",
    "sqlite": "sqlite",
    "mssql": "tsql",
    "sqlserver": "tsql",
    "oracle": "oracle",
    "clickhouse": "clickhouse",
    "duckdb": "duckdb",
    "redshift": "redshift",
    "snowflake": "snowflake",
}


class SQLToolkit(DatabaseToolkit):
    """Common SQL operations with overridable dialect hooks.

    Subclass and override the ``_get_*`` methods to customize behaviour for
    specific SQL dialects (PostgreSQL, BigQuery, etc.).
    """

    # Extend parent exclude_tools — private _get_* hooks start with '_' and
    # are auto-excluded by AbstractToolkit, but we add extras here.
    exclude_tools: tuple[str, ...] = (
        "start",
        "stop",
        "cleanup",
        "get_table_metadata",
        "health_check",
    )

    def __init__(
        self,
        dsn: str,
        allowed_schemas: Optional[List[str]] = None,
        primary_schema: Optional[str] = None,
        tables: Optional[List[str]] = None,
        read_only: bool = True,
        cache_partition: Optional[CachePartition] = None,
        retry_config: Optional[QueryRetryConfig] = None,
        database_type: str = "postgresql",
        **kwargs: Any,
    ) -> None:
        super().__init__(
            dsn=dsn,
            allowed_schemas=allowed_schemas,
            primary_schema=primary_schema,
            tables=tables,
            read_only=read_only,
            cache_partition=cache_partition,
            retry_config=retry_config,
            database_type=database_type,
            **kwargs,
        )

    # ------------------------------------------------------------------
    # LLM-callable tool methods
    # ------------------------------------------------------------------

    async def search_schema(
        self,
        search_term: str,
        schema_name: Optional[str] = None,
        limit: int = 10,
    ) -> List[TableMetadata]:
        """Search for tables/columns matching *search_term*.

        Checks the cache first; on miss, queries the database's
        information_schema and populates the cache.

        Args:
            search_term: Keyword or pattern to match.
            schema_name: Restrict to a specific schema.
            limit: Maximum results.

        Returns:
            Matching ``TableMetadata`` list.
        """
        # 1. Cache-first
        if self.cache_partition is not None:
            target_schemas = [schema_name] if schema_name else self.allowed_schemas
            cached = await self.cache_partition.search_similar_tables(
                target_schemas, search_term, limit=limit
            )
            if cached:
                return cached

        # 2. Query information_schema
        return await self._search_in_database(search_term, schema_name, limit)

    async def generate_query(
        self,
        natural_language: str,
        target_tables: Optional[List[str]] = None,
        query_type: str = "SELECT",
    ) -> str:
        """Prepare context for SQL generation from natural language.

        This method gathers schema context for the relevant tables so the
        LLM can generate SQL.  The actual SQL generation happens in the
        agent's tool-call loop.

        Args:
            natural_language: User's question in plain English.
            target_tables: Optional list of specific table names.
            query_type: Hint for query type (SELECT, INSERT, etc.).

        Returns:
            Schema context string for the LLM to generate SQL from.
        """
        context_parts: list[str] = []

        if target_tables and self.cache_partition:
            for table_name in target_tables:
                for schema in self.allowed_schemas:
                    meta = await self.cache_partition.get_table_metadata(schema, table_name)
                    if meta:
                        context_parts.append(meta.to_yaml_context())
                        break

        if not context_parts:
            # Search for relevant tables
            results = await self.search_schema(natural_language, limit=5)
            for meta in results:
                context_parts.append(meta.to_yaml_context())

        schema_context = "\n---\n".join(context_parts) if context_parts else "No schema context available."
        return (
            f"Generate a {query_type} SQL query for: {natural_language}\n\n"
            f"Available schema context:\n{schema_context}"
        )

    async def execute_query(
        self,
        query: str,
        limit: int = 1000,
        timeout: int = 30,
    ) -> Union[QueryExecutionResponse, RetryContext]:
        """Execute a SQL query and return results or a retry context.

        Applies the configured safety policy first.  When ``retry_config`` is
        set and the query fails with a retryable error, returns a
        ``RetryContext`` instead of ``QueryExecutionResponse`` so that
        ``DatabaseAgent.ask()`` can re-ask the LLM with error context.

        Non-retryable exceptions are re-raised when ``retry_config`` is set,
        and wrapped in ``QueryExecutionResponse(success=False)`` otherwise
        (legacy behaviour for callers that don't check the return type).

        Args:
            query: SQL query string.
            limit: Maximum rows to return.
            timeout: Query timeout in seconds.

        Returns:
            ``QueryExecutionResponse`` on success or when retrying is not
            configured; ``RetryContext`` when a retryable error occurs and
            ``retry_config`` is set.

        Raises:
            Exception: For non-retryable errors when ``retry_config`` is set.
        """
        safety_error = self._check_query_safety(query)
        if safety_error is not None:
            self.logger.warning("Query rejected by safety policy: %s", safety_error)
            return QueryExecutionResponse(
                success=False,
                row_count=0,
                execution_time_ms=0.0,
                schema_used=self.primary_schema,
                error_message=f"Query blocked by safety policy: {safety_error}",
            )

        retry_cfg: Optional[QueryRetryConfig] = getattr(self, "retry_config", None)
        start = time.monotonic()
        try:
            data = await self._run_query(query, limit=limit, timeout=timeout)
            elapsed = (time.monotonic() - start) * 1000
            return QueryExecutionResponse(
                success=True,
                row_count=len(data),
                columns=list(data[0].keys()) if data else [],
                data=data,
                execution_time_ms=elapsed,
                schema_used=self.primary_schema,
            )
        except Exception as err:
            elapsed = (time.monotonic() - start) * 1000
            if retry_cfg is None:
                # Legacy path: no retry config → swallow and return failure response.
                self.logger.error("Query execution failed: %s", err)
                return QueryExecutionResponse(
                    success=False,
                    row_count=0,
                    execution_time_ms=elapsed,
                    schema_used=self.primary_schema,
                    error_message=str(err),
                )
            handler = SQLRetryHandler(toolkit=self, config=retry_cfg)
            if not handler._is_retryable_error(err):
                raise
            # Retryable error — collect sample data and return RetryContext.
            table, column = handler._extract_table_column_from_error(query, err)
            sample_data = ""
            if table and column:
                try:
                    sample_data = await handler._get_sample_data_for_error(
                        self.primary_schema, table, column
                    )
                except Exception:
                    pass
            correction = await handler.retry_query(query, err, attempt=1)
            return RetryContext(
                query=query,
                error=str(err),
                attempt=1,
                sample_data=sample_data,
                suggested_correction=correction,
            )

    async def explain_query(self, query: str) -> str:
        """Run an EXPLAIN on the given query and return the plan.

        Args:
            query: SQL query to explain.

        Returns:
            Execution plan text.
        """
        prefix = self._get_explain_prefix()
        explain_sql = f"{prefix} {query}"
        try:
            data, error = await self._execute_asyncdb(explain_sql, limit=0, timeout=60)
            if error:
                return f"EXPLAIN failed: {error}"
            if data:
                return "\n".join(str(row) for row in data)
            return "No plan returned."
        except Exception as exc:
            return f"EXPLAIN failed: {exc}"

    async def validate_query(self, sql: str) -> Dict[str, Any]:
        """Validate SQL syntax and referenced objects.

        Args:
            sql: SQL query to validate.

        Returns:
            Dict with ``valid``, ``errors``, and ``referenced_tables`` keys.
        """
        import re

        errors: list[str] = []
        referenced: list[str] = []

        # Extract table references from FROM / JOIN clauses
        from_pattern = r'(?:FROM|JOIN)\s+(?:"?(\w+)"?\.)?"?(\w+)"?'
        matches = re.findall(from_pattern, sql, re.IGNORECASE)
        for schema_part, table_part in matches:
            schema = schema_part or self.primary_schema
            referenced.append(f"{schema}.{table_part}")

            # Verify table exists in cache
            if self.cache_partition:
                meta = await self.cache_partition.get_table_metadata(schema, table_part)
                if meta is None:
                    errors.append(f"Table '{schema}.{table_part}' not found in cache.")

        return {
            "valid": len(errors) == 0,
            "errors": errors,
            "referenced_tables": referenced,
            "sql": sql,
        }

    # ------------------------------------------------------------------
    # Safety policy (called by execute_query before running)
    # ------------------------------------------------------------------

    def _check_query_safety(self, sql: str) -> Optional[str]:
        """Return an error message if *sql* must be rejected, ``None`` otherwise.

        Uses :meth:`parrot.security.QueryValidator.validate_sql_ast` (sqlglot
        AST parse) when sqlglot is available — this reliably catches DDL,
        multi-statement, and missing-WHERE cases even when keywords appear
        inside string literals. Falls back to the regex validator when
        sqlglot cannot be imported.

        Policy:
          * ``read_only=True`` (default) — only SELECT/WITH/EXPLAIN/SHOW/
            DESCRIBE permitted.
          * ``read_only=False`` — DML permitted; DDL and multi-statement
            always blocked; UPDATE/DELETE must include a WHERE clause.
        """
        from ....security import QueryValidator

        dialect = _SQLGLOT_DIALECT_MAP.get(self.database_type)
        result = QueryValidator.validate_sql_ast(
            sql, dialect=dialect, read_only=self.read_only
        )
        if not result.get("is_safe", False):
            return result.get("message", "Query rejected by validator")
        return None

    # ------------------------------------------------------------------
    # Cache warm-up (called by DatabaseToolkit.start when tables is set)
    # ------------------------------------------------------------------

    async def _warm_table_cache(self) -> None:
        """Pre-populate ``cache_partition`` for each entry in ``self.tables``.

        Entries use ``"schema.table"`` format; bare ``"table"`` falls back to
        ``self.primary_schema``. Missing or introspection-failed tables log a
        warning and are skipped rather than raising.
        """
        if not self.tables:
            return
        if self.cache_partition is None:
            self.logger.debug(
                "No cache_partition on %s; skipping warm-up of %d tables",
                self.__class__.__name__,
                len(self.tables),
            )
            return

        warmed = 0
        for entry in self.tables:
            parsed = self._parse_table_entry(entry)
            if parsed is None:
                self.logger.warning(
                    "Skipping malformed 'tables' entry: %r", entry
                )
                continue
            schema, table = parsed
            try:
                metadata = await self._build_table_metadata(
                    schema, table, "BASE TABLE", None
                )
            except Exception as exc:
                self.logger.warning(
                    "Warm-up failed for %s.%s: %s", schema, table, exc
                )
                continue
            if metadata is None or not metadata.columns:
                self.logger.warning(
                    "Warm-up skipped %s.%s (table not found or no columns)",
                    schema,
                    table,
                )
                continue
            await self.cache_partition.store_table_metadata(metadata)
            warmed += 1

        self.logger.info(
            "%s warmed metadata cache for %d/%d tables",
            self.__class__.__name__,
            warmed,
            len(self.tables),
        )

    # ------------------------------------------------------------------
    # Overridable dialect hooks (private — not exposed as tools)
    # ------------------------------------------------------------------

    def _get_explain_prefix(self) -> str:
        """Return the EXPLAIN statement prefix for this SQL dialect."""
        return "EXPLAIN ANALYZE"

    def _get_information_schema_query(
        self,
        search_term: str,
        schemas: List[str],
    ) -> tuple[str, tuple]:
        """Return ``(sql, params)`` for table discovery via information_schema.

        Emits ``$1, $2, …`` asyncpg positional placeholders.
        Override in subclasses for dialect-specific introspection.

        Args:
            search_term: Term to match against table names.
            schemas: List of schema names to search.

        Returns:
            ``(sql, params_tuple)`` ready for :meth:`_execute_asyncdb`.
        """
        sql = """
            SELECT DISTINCT
                table_schema,
                table_name,
                table_type
            FROM information_schema.tables
            WHERE table_schema = ANY($1)
            AND (
                table_name ILIKE $2
                OR (table_schema || '.' || table_name) ILIKE $2
            )
            AND table_type IN ('BASE TABLE', 'VIEW')
            ORDER BY table_name
            LIMIT $3
        """
        return sql, (schemas, f"%{search_term}%", 20)

    def _get_columns_query(self, schema: str, table: str) -> tuple[str, tuple]:
        """Return ``(sql, params)`` for column metadata.

        Args:
            schema: Schema name.
            table: Table name.

        Returns:
            ``(sql, params_tuple)`` with ``$1=schema, $2=table``.
        """
        sql = """
            SELECT column_name, data_type, is_nullable, column_default,
                   ordinal_position
            FROM information_schema.columns
            WHERE table_schema = $1 AND table_name = $2
            ORDER BY ordinal_position
        """
        return sql, (schema, table)

    def _get_primary_keys_query(self, schema: str, table: str) -> tuple[str, tuple]:
        """Return ``(sql, params)`` for primary key columns.

        Args:
            schema: Schema name.
            table: Table name.

        Returns:
            ``(sql, params_tuple)`` with ``$1=schema, $2=table``.
        """
        sql = """
            SELECT kcu.column_name
            FROM information_schema.table_constraints tc
            JOIN information_schema.key_column_usage kcu
                ON tc.constraint_name = kcu.constraint_name
                AND tc.table_schema = kcu.table_schema
            WHERE tc.constraint_type = 'PRIMARY KEY'
            AND tc.table_schema = $1
            AND tc.table_name = $2
            ORDER BY kcu.ordinal_position
        """
        return sql, (schema, table)

    def _get_unique_constraints_query(
        self, schema: str, table: str
    ) -> tuple[str, tuple]:
        """Return ``(sql, params)`` for UNIQUE constraint columns of (schema, table).

        Queries ``information_schema.table_constraints`` joined with
        ``information_schema.key_column_usage`` to list each UNIQUE
        constraint and its member columns in ordinal order.

        Subclasses (e.g. ``PostgresToolkit``) may override this to also
        capture UNIQUE indexes not backed by named constraints.

        Args:
            schema: Schema name.
            table: Table name.

        Returns:
            Tuple of ``(sql, params)`` ready for :meth:`_execute_asyncdb`.
        """
        sql = """
            SELECT
                tc.constraint_name,
                kcu.column_name,
                kcu.ordinal_position
            FROM information_schema.table_constraints tc
            JOIN information_schema.key_column_usage kcu
                ON kcu.constraint_name = tc.constraint_name
               AND kcu.table_schema   = tc.table_schema
               AND kcu.table_name     = tc.table_name
            WHERE tc.table_schema   = $1
              AND tc.table_name     = $2
              AND tc.constraint_type = 'UNIQUE'
            ORDER BY tc.constraint_name, kcu.ordinal_position
        """
        return sql, (schema, table)

    def _get_sample_data_query(
        self, schema: str, table: str, limit: int = 3
    ) -> str:
        """Return SQL for fetching sample rows."""
        safe_schema = self._validate_identifier(schema)
        safe_table = self._validate_identifier(table)
        return f'SELECT * FROM "{safe_schema}"."{safe_table}" LIMIT {int(limit)}'

    # ------------------------------------------------------------------
    # Internal execution helpers
    # ------------------------------------------------------------------

    async def _run_query(
        self,
        query: str,
        limit: int = 1000,
        timeout: int = 30,
    ) -> List[Dict[str, Any]]:
        """Execute SQL and return raw row data, raising on any error.

        Args:
            query: SQL to execute.
            limit: Maximum rows to return.
            timeout: Query timeout in seconds.

        Returns:
            List of row dicts (may be empty).

        Raises:
            Exception: With the database error message if execution fails.
        """
        data, error = await self._execute_asyncdb(query, limit=limit, timeout=timeout)
        if error:
            raise Exception(error)
        return data or []

    async def _execute_asyncdb(
        self,
        sql: str,
        params: tuple = (),
        limit: int = 1000,
        timeout: int = 30,
    ) -> tuple[Optional[List[Dict[str, Any]]], Optional[str]]:
        """Execute SQL via asyncdb and return ``(data, error)``.

        Uses the raw ``asyncpg.Connection`` obtained from
        :meth:`_acquire_asyncdb_connection` (boundary-unwrapped).

        Args:
            sql: SQL query with ``$N`` positional placeholders.
            params: Positional parameters tuple (default: empty).
            limit: Maximum rows to return (0 = no limit).
            timeout: Query timeout in seconds (unused by asyncpg fetch,
                kept for interface compatibility).

        Returns:
            ``(data, None)`` on success or ``(None, error_str)`` on failure.
        """
        if self._connection is None:
            return None, "Not connected (call start() first)"
        try:
            async with self._acquire_asyncdb_connection() as conn:
                # conn.fetch(sql, *()) is identical to conn.fetch(sql) in asyncpg.
                rows = await conn.fetch(sql, *params)
                if rows is None:
                    return [], None
                data = [dict(row) for row in rows]
                if limit and len(data) > limit:
                    data = data[:limit]
                return data, None
        except Exception as exc:
            return None, str(exc)

    async def _search_in_database(
        self,
        search_term: str,
        schema_name: Optional[str] = None,
        limit: int = 10,
    ) -> List[TableMetadata]:
        """Query information_schema for matching tables and build metadata."""
        target_schemas = [schema_name] if schema_name else self.allowed_schemas
        info_sql, params = self._get_information_schema_query(search_term, target_schemas)

        results: List[TableMetadata] = []
        try:
            data, error = await self._execute_asyncdb(info_sql, params=params, limit=limit, timeout=30)
            if error or not data:
                return results

            for row in data:
                schema = row.get("table_schema", self.primary_schema)
                table = row.get("table_name", "")
                table_type = row.get("table_type", "BASE TABLE")
                comment = row.get("comment")

                metadata = await self._build_table_metadata(
                    schema, table, table_type, comment
                )
                if metadata:
                    # Cache the result
                    if self.cache_partition:
                        await self.cache_partition.store_table_metadata(metadata)
                    results.append(metadata)

        except Exception as exc:
            self.logger.warning("Schema search failed: %s", exc)

        return results[:limit]

    async def _build_table_metadata(
        self,
        schema: str,
        table: str,
        table_type: str,
        comment: Optional[str] = None,
    ) -> Optional[TableMetadata]:
        """Build a ``TableMetadata`` object by querying column and key info."""
        try:
            # Columns
            col_sql, col_params = self._get_columns_query(schema, table)
            col_data, _ = await self._execute_asyncdb(col_sql, params=col_params, limit=0, timeout=15)

            columns = []
            if col_data:
                for col in col_data:
                    columns.append({
                        "name": col.get("column_name", ""),
                        "type": col.get("data_type", "unknown"),
                        "nullable": col.get("is_nullable", "YES") == "YES",
                        "default": col.get("column_default"),
                    })

            # Primary keys
            pk_sql, pk_params = self._get_primary_keys_query(schema, table)
            pk_data, _ = await self._execute_asyncdb(pk_sql, params=pk_params, limit=0, timeout=15)

            primary_keys = [
                row.get("column_name", "") for row in (pk_data or [])
            ]

            # Unique constraints
            unique_constraints: List[List[str]] = []
            try:
                uq_sql, uq_params = self._get_unique_constraints_query(schema, table)
                uq_data, uq_error = await self._execute_asyncdb(uq_sql, params=uq_params, limit=0, timeout=15)
                if uq_data:
                    grouped: Dict[str, List[str]] = {}
                    for row in uq_data:
                        constraint_name = row.get("constraint_name", "")
                        column_name = row.get("column_name", "")
                        if constraint_name and column_name:
                            grouped.setdefault(constraint_name, []).append(column_name)
                    # Sort for deterministic ordering
                    unique_constraints = sorted(
                        grouped.values(),
                        key=lambda cols: (cols[0] if cols else ""),
                    )
                else:
                    self.logger.debug(
                        "No UNIQUE constraints found for %s.%s", schema, table
                    )
            except Exception as uq_exc:
                self.logger.debug(
                    "Failed to fetch UNIQUE constraints for %s.%s: %s",
                    schema, table, uq_exc,
                )

            return TableMetadata(
                schema=schema,
                tablename=table,
                table_type=table_type,
                full_name=f'"{schema}"."{table}"',
                columns=columns,
                primary_keys=primary_keys,
                foreign_keys=[],
                indexes=[],
                comment=comment,
                unique_constraints=unique_constraints,
            )
        except Exception as exc:
            self.logger.warning("Failed to build metadata for %s.%s: %s", schema, table, exc)
            return None
