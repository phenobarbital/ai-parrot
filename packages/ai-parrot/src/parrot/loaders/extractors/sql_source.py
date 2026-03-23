"""SQL data source for structured record extraction."""
from __future__ import annotations

import re
from typing import Any

from .base import ExtractDataSource, ExtractionResult


class SQLDataSource(ExtractDataSource):
    """Extract structured records from SQL queries.

    Config:
        dsn: str — Database connection string.
        query: str — SQL SELECT query to execute.
        params: dict — Query parameters (for parameterized queries).

    Uses asyncpg for PostgreSQL. The query MUST be read-only (SELECT only).

    Args:
        name: Human-readable name for logging and reporting.
        config: Source-specific configuration.
    """

    # Patterns that indicate a non-read-only query
    _MUTATION_PATTERN = re.compile(
        r"\b(INSERT|UPDATE|DELETE|DROP|CREATE|ALTER|TRUNCATE|GRANT|REVOKE)\b",
        re.IGNORECASE,
    )

    async def extract(
        self,
        fields: list[str] | None = None,
        filters: dict[str, Any] | None = None,
    ) -> ExtractionResult:
        """Execute SQL query and return rows as records.

        Args:
            fields: Optional field projection (applied post-query).
            filters: Optional key-value filters (applied post-query in-memory).

        Returns:
            ExtractionResult with query rows as records.

        Raises:
            DataSourceValidationError: If query contains mutation statements.
        """
        from parrot.knowledge.ontology.exceptions import DataSourceValidationError

        query = self.config.get("query", "")
        dsn = self.config.get("dsn", "")
        params = self.config.get("params", {})

        if not query:
            return self._build_result(
                [], fields=fields, errors=["No 'query' configured for SQL source"],
            )

        if not dsn:
            return self._build_result(
                [], fields=fields, errors=["No 'dsn' configured for SQL source"],
            )

        # Validate read-only
        if self._MUTATION_PATTERN.search(query):
            raise DataSourceValidationError(
                f"SQL query for source '{self.name}' contains mutation statements. "
                f"Only SELECT queries are allowed."
            )

        try:
            import asyncpg  # noqa: F811
        except ImportError:
            return self._build_result(
                [], fields=fields,
                errors=["asyncpg is required for SQLDataSource but not installed"],
            )

        try:
            conn = await asyncpg.connect(dsn)
            try:
                rows = await conn.fetch(query, *params.values() if params else [])
                records = [dict(row) for row in rows]
            finally:
                await conn.close()
        except Exception as e:
            self.logger.error("SQL extraction failed: %s", e)
            return self._build_result(
                [], fields=fields, errors=[f"SQL execution error: {e}"],
            )

        self.logger.debug("Extracted %d records from SQL", len(records))
        return self._build_result(records, fields=fields, filters=filters)

    async def list_fields(self) -> list[str]:
        """Execute query with LIMIT 0 to get column names.

        Returns:
            List of column names from the query result.
        """
        query = self.config.get("query", "")
        dsn = self.config.get("dsn", "")

        if not query or not dsn:
            return []

        # Wrap query with LIMIT 0 to get schema without data
        limited_query = f"SELECT * FROM ({query}) _sq LIMIT 0"

        try:
            import asyncpg

            conn = await asyncpg.connect(dsn)
            try:
                stmt = await conn.prepare(limited_query)
                return [attr.name for attr in stmt.get_attributes()]
            finally:
                await conn.close()
        except Exception as e:
            self.logger.warning("Failed to list SQL fields: %s", e)
            return []
