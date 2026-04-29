"""BigQueryToolkit — BigQuery-specific overrides of ``SQLToolkit``.

Provides BigQuery-specific schema introspection via
``INFORMATION_SCHEMA.TABLES``/``COLUMNS``, dry-run cost estimation for
EXPLAIN, and support for project/dataset-based DSNs.

BigQuery uses the asyncdb ``bigquery`` driver natively. No SQLAlchemy path.
Parameter style: values are safely inlined into queries using Python
f-strings with SQL-escaped values; builders return ``(sql, ())`` (empty
tuple) since BigQuery's asyncdb driver does not support positional ``$N``
parameters via ``conn.fetch()``.
"""
from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any, AsyncIterator, Dict, List, Optional

from .sql import SQLToolkit


class BigQueryToolkit(SQLToolkit):
    """BigQuery-specific toolkit.

    Overrides dialect hooks for BigQuery's introspection, dry-run cost
    estimation, and project/dataset DSN format.  Uses asyncdb's BigQuery
    driver natively — no SQLAlchemy path.
    """

    def __init__(
        self,
        dsn: Optional[str] = None,
        project_id: Optional[str] = None,
        credentials_file: Optional[str] = None,
        allowed_schemas: Optional[List[str]] = None,
        primary_schema: Optional[str] = None,
        tables: Optional[List[str]] = None,
        read_only: bool = True,
        **kwargs: Any,
    ) -> None:
        # BigQuery uses project_id + dataset instead of traditional DSN
        self.project_id = project_id
        self.credentials_file = credentials_file
        effective_dsn = dsn or f"bigquery://{project_id or 'default'}"
        super().__init__(
            dsn=effective_dsn,
            allowed_schemas=allowed_schemas or ["default"],
            primary_schema=primary_schema,
            tables=tables,
            read_only=read_only,
            database_type="bigquery",
            **kwargs,
        )

    # ------------------------------------------------------------------
    # Dialect hooks
    # ------------------------------------------------------------------

    def _get_explain_prefix(self) -> str:
        """BigQuery uses dry-run for cost estimation (no EXPLAIN ANALYZE)."""
        return "-- DRY RUN COST ESTIMATION"

    def _get_information_schema_query(
        self,
        search_term: str,
        schemas: List[str],
    ) -> tuple[str, tuple]:
        """BigQuery uses dataset.INFORMATION_SCHEMA.TABLES.

        BigQuery does not support asyncpg-style positional parameters.
        Values are inlined with SQL-safe escaping; the params tuple is
        empty. The schema/dataset name is validated via
        :meth:`_validate_identifier`.

        Args:
            search_term: Term to match against table names.
            schemas: List of dataset names (uses first entry).

        Returns:
            ``(sql, ())`` — empty params tuple; values are inlined.
        """
        dataset = schemas[0] if schemas else "default"
        safe_dataset = self._validate_identifier(dataset)
        # Escape the search term for safe inline use.  Single-quote
        # doubling prevents string-termination injection.  LIKE wildcards
        # (% and _) are intentionally left unescaped: searching for % or _
        # is permissive matching that is consistent with the search_schema
        # "show all available tables" semantics.
        safe_term = search_term.replace("'", "''")
        sql = f"""
            SELECT
                table_schema,
                table_name,
                table_type
            FROM `{safe_dataset}`.INFORMATION_SCHEMA.TABLES
            WHERE table_name LIKE '%{safe_term}%'
            ORDER BY table_name
            LIMIT 20
        """
        return sql, ()

    def _get_columns_query(
        self, schema: str, table: str
    ) -> tuple[str, tuple]:
        """BigQuery column introspection.

        Values are inlined with SQL-safe escaping; the params tuple is
        empty. Schema name is validated; table name is single-quote escaped.

        Args:
            schema: Dataset name.
            table: Table name.

        Returns:
            ``(sql, ())`` — empty params tuple; values are inlined.
        """
        safe_schema = self._validate_identifier(schema)
        safe_table = table.replace("'", "''")
        sql = f"""
            SELECT
                column_name,
                data_type,
                is_nullable,
                column_default,
                ordinal_position
            FROM `{safe_schema}`.INFORMATION_SCHEMA.COLUMNS
            WHERE table_name = '{safe_table}'
            ORDER BY ordinal_position
        """
        return sql, ()

    def _get_primary_keys_query(
        self, schema: str, table: str
    ) -> tuple[str, tuple]:
        """BigQuery doesn't have traditional primary keys.

        Returns an empty query that will produce no results.
        """
        return "SELECT '' AS column_name WHERE FALSE", ()

    def _get_unique_constraints_query(
        self, schema: str, table: str
    ) -> tuple[str, tuple]:
        """BigQuery doesn't support ANSI UNIQUE constraints.

        Returns an empty query that will produce no results.
        """
        return "SELECT '' AS constraint_name, '' AS column_name, 0 AS ordinal_position WHERE FALSE", ()

    def _get_sample_data_query(
        self, schema: str, table: str, limit: int = 3
    ) -> str:
        safe_schema = self._validate_identifier(schema)
        safe_table = self._validate_identifier(table)
        return f"SELECT * FROM `{safe_schema}`.`{safe_table}` LIMIT {int(limit)}"

    def _get_asyncdb_driver(self) -> str:
        return "bigquery"

    # ------------------------------------------------------------------
    # Connection boundary — BigQuery-specific override
    # ------------------------------------------------------------------

    @asynccontextmanager
    async def _acquire_asyncdb_connection(self) -> AsyncIterator[Any]:
        """Yield the asyncdb BigQuery driver wrapper, not the raw BQ client.

        The base-class implementation calls ``wrapper.engine()`` to unwrap
        to the native connection object.  For the ``pg`` driver that is a
        raw ``asyncpg.Connection`` — correct.  For the ``bigquery`` driver,
        ``engine()`` exposes ``google.cloud.bigquery.Client``, which has no
        ``.fetch()`` method and cannot be used as a query executor.

        BigQuery's asyncdb driver wrapper IS the query executor, so we
        yield it directly without calling ``engine()``.
        """
        if self._connection is None:
            raise RuntimeError("Not connected (call start() first)")
        # BigQuery asyncdb driver does not support pooling; always single.
        async with await self._connection.connection() as wrapper:
            yield wrapper  # asyncdb bigquery driver object, not wrapper.engine()
