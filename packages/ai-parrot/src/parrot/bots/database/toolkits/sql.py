"""SQLToolkit — common SQL operations with overridable dialect hooks.

Inherits ``DatabaseToolkit`` and implements schema search, query generation,
execution, explain, and validation for SQL databases.  Dialect differences
(PostgreSQL vs BigQuery vs MySQL) are handled via overridable ``_get_*``
hook methods.
"""
from __future__ import annotations

import time
from typing import Any, Dict, List, Optional

from ..cache import CachePartition
from ..models import (
    QueryExecutionResponse,
    SchemaMetadata,
    TableMetadata,
)
from ..retries import QueryRetryConfig
from .base import DatabaseToolkit


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
        backend: str = "asyncdb",
        cache_partition: Optional[CachePartition] = None,
        retry_config: Optional[QueryRetryConfig] = None,
        database_type: str = "postgresql",
        **kwargs: Any,
    ) -> None:
        super().__init__(
            dsn=dsn,
            allowed_schemas=allowed_schemas,
            primary_schema=primary_schema,
            backend=backend,
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
    ) -> QueryExecutionResponse:
        """Execute a SQL query and return results.

        Args:
            query: SQL query string.
            limit: Maximum rows to return.
            timeout: Query timeout in seconds.

        Returns:
            ``QueryExecutionResponse`` with data, row count, and timing.
        """
        start = time.monotonic()
        try:
            if self.backend == "asyncdb":
                data, error = await self._execute_asyncdb(query, limit, timeout)
            else:
                data, error = await self._execute_sqlalchemy(query, limit, timeout)

            elapsed = (time.monotonic() - start) * 1000

            if error:
                return QueryExecutionResponse(
                    success=False,
                    row_count=0,
                    execution_time_ms=elapsed,
                    schema_used=self.primary_schema,
                    error_message=str(error),
                )

            return QueryExecutionResponse(
                success=True,
                row_count=len(data) if data else 0,
                columns=list(data[0].keys()) if data else [],
                data=data,
                execution_time_ms=elapsed,
                schema_used=self.primary_schema,
            )
        except Exception as exc:
            elapsed = (time.monotonic() - start) * 1000
            self.logger.error("Query execution failed: %s", exc)
            return QueryExecutionResponse(
                success=False,
                row_count=0,
                execution_time_ms=elapsed,
                schema_used=self.primary_schema,
                error_message=str(exc),
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
            if self.backend == "asyncdb":
                data, error = await self._execute_asyncdb(explain_sql, limit=0, timeout=60)
            else:
                data, error = await self._execute_sqlalchemy(explain_sql, limit=0, timeout=60)

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
    # Overridable dialect hooks (private �� not exposed as tools)
    # ------------------------------------------------------------------

    def _get_explain_prefix(self) -> str:
        """Return the EXPLAIN statement prefix for this SQL dialect."""
        return "EXPLAIN ANALYZE"

    def _get_information_schema_query(
        self,
        search_term: str,
        schemas: List[str],
    ) -> tuple[str, Dict[str, Any]]:
        """Return (SQL, params) for table discovery via information_schema.

        Override in subclasses for dialect-specific introspection.
        """
        sql = """
            SELECT DISTINCT
                table_schema,
                table_name,
                table_type
            FROM information_schema.tables
            WHERE table_schema = ANY(:schemas)
            AND (
                table_name ILIKE :term
                OR (table_schema || '.' || table_name) ILIKE :term
            )
            AND table_type IN ('BASE TABLE', 'VIEW')
            ORDER BY table_name
            LIMIT :limit
        """
        params = {
            "schemas": schemas,
            "term": f"%{search_term}%",
            "limit": 20,
        }
        return sql, params

    def _get_columns_query(self, schema: str, table: str) -> tuple[str, Dict[str, Any]]:
        """Return (SQL, params) for column metadata."""
        sql = """
            SELECT column_name, data_type, is_nullable, column_default,
                   ordinal_position
            FROM information_schema.columns
            WHERE table_schema = :schema AND table_name = :table
            ORDER BY ordinal_position
        """
        return sql, {"schema": schema, "table": table}

    def _get_primary_keys_query(self, schema: str, table: str) -> tuple[str, Dict[str, Any]]:
        """Return (SQL, params) for primary key columns."""
        sql = """
            SELECT kcu.column_name
            FROM information_schema.table_constraints tc
            JOIN information_schema.key_column_usage kcu
                ON tc.constraint_name = kcu.constraint_name
                AND tc.table_schema = kcu.table_schema
            WHERE tc.constraint_type = 'PRIMARY KEY'
            AND tc.table_schema = :schema
            AND tc.table_name = :table
            ORDER BY kcu.ordinal_position
        """
        return sql, {"schema": schema, "table": table}

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

    async def _execute_asyncdb(
        self,
        sql: str,
        limit: int = 1000,
        timeout: int = 30,
    ) -> tuple[Optional[List[Dict[str, Any]]], Optional[str]]:
        """Execute SQL via asyncdb and return (data, error)."""
        if self._connection is None:
            return None, "Not connected (call start() first)"
        try:
            async with await self._connection.connection() as conn:
                result, error = await conn.query(sql)
                if error:
                    return None, str(error)
                if result is None:
                    return [], None
                data = [dict(row) for row in result] if result else []
                if limit and len(data) > limit:
                    data = data[:limit]
                return data, None
        except Exception as exc:
            return None, str(exc)

    async def _execute_sqlalchemy(
        self,
        sql: str,
        limit: int = 1000,
        timeout: int = 30,
    ) -> tuple[Optional[List[Dict[str, Any]]], Optional[str]]:
        """Execute SQL via sqlalchemy-async and return (data, error)."""
        if self._engine is None:
            return None, "Not connected (call start() first)"
        try:
            from sqlalchemy import text
            from sqlalchemy.ext.asyncio import AsyncSession
            from sqlalchemy.orm import sessionmaker

            async_session = sessionmaker(
                self._engine, class_=AsyncSession, expire_on_commit=False
            )
            async with async_session() as session:
                result = await session.execute(text(sql))
                rows = result.fetchall()
                columns = list(result.keys())
                data = [dict(zip(columns, row)) for row in rows]
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
            if self.backend == "asyncdb":
                data, error = await self._execute_asyncdb(info_sql, limit=limit, timeout=30)
                if error or not data:
                    return results
                rows = data
            else:
                data, error = await self._execute_sqlalchemy(info_sql, limit=limit, timeout=30)
                if error or not data:
                    return results
                rows = data

            for row in rows:
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
            if self.backend == "asyncdb":
                col_data, _ = await self._execute_asyncdb(col_sql, limit=0, timeout=15)
            else:
                col_data, _ = await self._execute_sqlalchemy(col_sql, limit=0, timeout=15)

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
            if self.backend == "asyncdb":
                pk_data, _ = await self._execute_asyncdb(pk_sql, limit=0, timeout=15)
            else:
                pk_data, _ = await self._execute_sqlalchemy(pk_sql, limit=0, timeout=15)

            primary_keys = [
                row.get("column_name", "") for row in (pk_data or [])
            ]

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
            )
        except Exception as exc:
            self.logger.warning("Failed to build metadata for %s.%s: %s", schema, table, exc)
            return None
