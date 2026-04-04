"""Query retry handling — generalized for multiple database types.

Provides ``RetryHandler`` base class and ``SQLRetryHandler`` for SQL-specific
error patterns.  Stubs for Flux and DSL handlers are included for future use.
"""
from __future__ import annotations

import re
from typing import Any, List, Optional, Tuple

from navconfig.logging import logging

#: Regex for safe SQL identifiers.
_SAFE_IDENTIFIER = re.compile(r'^[a-zA-Z_][a-zA-Z0-9_]*$')


class QueryRetryConfig:
    """Configuration for query retry mechanism."""

    def __init__(
        self,
        max_retries: int = 3,
        retry_on_errors: Optional[List[str]] = None,
        sample_data_on_error: bool = True,
        max_sample_rows: int = 3,
        database_type: str = "sql",
    ):
        self.max_retries = max_retries
        self.retry_on_errors = retry_on_errors or [
            "InvalidTextRepresentationError",
            "DataError",
            "ProgrammingError",
            "invalid input syntax",
            "column does not exist",
            "relation does not exist",
            "type",
            "cast",
            "convert",
        ]
        self.sample_data_on_error = sample_data_on_error
        self.max_sample_rows = max_sample_rows
        self.database_type = database_type


class RetryHandler:
    """Base retry handler for any database toolkit.

    Subclass and override ``_is_retryable_error`` and ``retry_query``
    for database-specific error patterns.
    """

    def __init__(
        self,
        toolkit: Any = None,
        config: Optional[QueryRetryConfig] = None,
    ):
        self.toolkit = toolkit
        self.config = config or QueryRetryConfig()
        self.logger = logging.getLogger(self.__class__.__name__)

    def _is_retryable_error(self, error: Exception) -> bool:
        """Determine if an error is worth retrying.

        Args:
            error: The exception that occurred.

        Returns:
            ``True`` if the error matches a retryable pattern.
        """
        error_str = str(error).lower()
        error_type = type(error).__name__

        for pattern in self.config.retry_on_errors:
            if pattern.lower() in error_str or pattern.lower() in error_type.lower():
                return True
        return False

    async def retry_query(
        self,
        query: str,
        error: Exception,
        attempt: int,
    ) -> Optional[str]:
        """Attempt to produce a corrected query after an error.

        Args:
            query: The query that failed.
            error: The exception from execution.
            attempt: Current retry attempt number.

        Returns:
            A corrected query string, or ``None`` if no correction possible.
        """
        if attempt >= self.config.max_retries:
            return None
        if not self._is_retryable_error(error):
            return None
        return None  # base class doesn't know how to fix queries


class SQLRetryHandler(RetryHandler):
    """SQL-specific retry handler with error learning."""

    def __init__(
        self,
        toolkit: Any = None,
        config: Optional[QueryRetryConfig] = None,
        # Backward-compat: accept 'agent' as alias for 'toolkit'
        agent: Any = None,
    ):
        super().__init__(toolkit=toolkit or agent, config=config)

    async def _get_sample_data_for_error(
        self,
        schema_name: str,
        table_name: str,
        column_name: str,
    ) -> str:
        """Get sample data from the problematic column.

        Args:
            schema_name: Schema containing the table.
            table_name: Table with the problematic column.
            column_name: Column to sample.

        Returns:
            A string describing sample values, or empty string.
        """
        if not self.config.sample_data_on_error:
            return ""
        if self.toolkit is None:
            return ""

        try:
            # Validate identifiers to prevent SQL injection
            for ident in (schema_name, table_name, column_name):
                if not _SAFE_IDENTIFIER.match(ident):
                    self.logger.debug("Unsafe identifier skipped: %s", ident)
                    return ""
            sample_query = f'''
            SELECT "{column_name}"
            FROM "{schema_name}"."{table_name}"
            WHERE "{column_name}" IS NOT NULL
            LIMIT {int(self.config.max_sample_rows)};
            '''
            # Try using toolkit's execute method
            if hasattr(self.toolkit, "execute_query"):
                result = await self.toolkit.execute_query(
                    sample_query, limit=self.config.max_sample_rows
                )
                if result.success and result.data:
                    samples = [row.get(column_name) for row in result.data]
                    return f"Sample values from {column_name}: {samples}"
            # Fallback for agents with engine attribute
            elif hasattr(self.toolkit, "engine") and self.toolkit.engine is not None:
                from sqlalchemy import text

                async with self.toolkit.engine.begin() as conn:
                    result = await conn.execute(text(sample_query))
                    samples = [row[0] for row in result]
                    if samples:
                        return f"Sample values from {column_name}: {samples}"
        except Exception as exc:
            self.logger.debug("Could not fetch sample data: %s", exc)
        return ""

    def _extract_table_column_from_error(
        self,
        sql_query: str,
        error: Exception,
    ) -> Tuple[Optional[str], Optional[str]]:
        """Extract problematic table and column from SQL and error.

        Args:
            sql_query: The SQL that failed.
            error: The exception.

        Returns:
            Tuple of (table_name, column_name), either may be None.
        """
        try:
            from_match = re.search(
                r'FROM\s+(?:"?(\w+)"?\.)?"?(\w+)"?', sql_query, re.IGNORECASE
            )
            table_name = from_match.group(2) if from_match else None

            order_match = re.search(
                r'ORDER BY\s+.*?(\w+)', sql_query, re.IGNORECASE
            )
            column_name = order_match.group(1) if order_match else None

            cast_match = re.search(
                r'CAST\([^,]+,\s*[\'"]([^\'"]+)[\'"]', sql_query, re.IGNORECASE
            )
            if cast_match:
                cast_col_match = re.search(
                    r'CAST\(\s*(?:REPLACE\([^,]+,\s*)?[\'"]?(\w+)[\'"]?',
                    sql_query,
                    re.IGNORECASE,
                )
                if cast_col_match:
                    column_name = cast_col_match.group(1)

            return table_name, column_name
        except Exception:
            return None, None

    async def retry_query(
        self,
        query: str,
        error: Exception,
        attempt: int,
    ) -> Optional[str]:
        """Attempt to produce a corrected SQL query.

        Extracts table/column info from the error, fetches sample data,
        and provides context for correction.
        """
        if attempt >= self.config.max_retries:
            return None
        if not self._is_retryable_error(error):
            return None

        table, column = self._extract_table_column_from_error(query, error)
        if table and column:
            sample_info = await self._get_sample_data_for_error(
                self.toolkit.primary_schema if self.toolkit else "public",
                table,
                column,
            )
            if sample_info:
                self.logger.info(
                    "Retry %d: error on %s.%s — %s",
                    attempt, table, column, sample_info,
                )
        return None  # actual correction is done by the LLM agent


class FluxRetryHandler(RetryHandler):
    """InfluxDB Flux-specific retry handler (stub for future use)."""

    def __init__(self, toolkit: Any = None, config: Optional[QueryRetryConfig] = None):
        super().__init__(
            toolkit=toolkit,
            config=config or QueryRetryConfig(
                retry_on_errors=["syntax error", "bucket not found", "measurement not found"],
                database_type="influxdb",
            ),
        )


class DSLRetryHandler(RetryHandler):
    """Elasticsearch DSL-specific retry handler (stub for future use)."""

    def __init__(self, toolkit: Any = None, config: Optional[QueryRetryConfig] = None):
        super().__init__(
            toolkit=toolkit,
            config=config or QueryRetryConfig(
                retry_on_errors=["parsing_exception", "index_not_found", "mapper_parsing_exception"],
                database_type="elasticsearch",
            ),
        )
