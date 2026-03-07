"""
SQLQuerySource — user-provided SQL with {param} interpolation.

Executes an arbitrary SQL template against any AsyncDB-supported driver.
All {param} placeholders are validated and safely escaped at fetch() time.
"""
import hashlib
import logging
import re
from datetime import date, datetime
from typing import Any, Dict, List, Optional, Set

import pandas as pd
from asyncdb import AsyncDB

from parrot.tools.databasequery import get_default_credentials
from .base import DataSource

# Regex for safe SQL identifier names (param placeholders)
_SAFE_IDENTIFIER_RE = re.compile(r'^[a-zA-Z_][a-zA-Z0-9_]*$')


class SQLQuerySource(DataSource):
    """DataSource backed by a user-provided SQL template with {param} interpolation.

    SQL can contain placeholders like ``{start_date}``, ``{ticker}`` etc.
    All placeholders are validated and escaped at ``fetch()`` time before execution.

    Args:
        sql: SQL template string with optional ``{param}`` placeholders.
        driver: AsyncDB driver name (``pg``, ``mysql``, ``bigquery``, etc.).
        dsn: Optional DSN string. Resolved via ``get_default_credentials(driver)``
            when ``None``.
        cache_ttl: Cache TTL in seconds. Defaults to 3600.
    """

    def __init__(
        self,
        sql: str,
        driver: str,
        dsn: Optional[str] = None,
        cache_ttl: int = 3600,
    ) -> None:
        self.sql = sql
        self.driver = driver
        self.cache_ttl = cache_ttl
        self.logger = logging.getLogger(__name__)

        if dsn is None:
            dsn = get_default_credentials(driver)

        self.dsn = dsn

    @property
    def cache_key(self) -> str:
        """Stable Redis cache key for this source.

        Returns:
            Cache key in the format ``sql:{driver}:{md5[:8]}``.
        """
        md5 = hashlib.md5(self.sql.encode(), usedforsecurity=False).hexdigest()[:8]
        return f"sql:{self.driver}:{md5}"

    def describe(self) -> str:
        """Human-readable description for the LLM.

        Returns:
            Description string showing the driver and a truncated SQL preview.
        """
        truncated = self.sql[:80] + ('...' if len(self.sql) > 80 else '')
        return f"SQL query via {self.driver}: {truncated}"

    async def prefetch_schema(self) -> Dict[str, str]:
        """Return empty dict — schema only available after first fetch.

        Returns:
            Empty dict.
        """
        return {}

    def _extract_params(self) -> List[str]:
        """Extract ``{param_name}`` placeholder names from the SQL template.

        Returns:
            List of placeholder names found in the SQL.

        Raises:
            ValueError: If any placeholder name contains unsafe characters.
        """
        params = re.findall(r'\{(\w+)\}', self.sql)
        for p in params:
            if not _SAFE_IDENTIFIER_RE.match(p):
                raise ValueError(
                    f"Unsafe SQL placeholder name: '{p}'. "
                    f"Only [a-zA-Z_][a-zA-Z0-9_]* is allowed."
                )
        return params

    # Characters forbidden inside string values to mitigate injection attempts.
    _DANGEROUS_PATTERNS: Set[str] = {';', '--', '/*', '*/', 'xp_', 'EXEC ', 'exec '}

    @staticmethod
    def _escape_value(value: Any) -> str:
        """Escape a value for safe SQL string interpolation.

        - ``bool``: ``TRUE`` / ``FALSE`` (checked before int, since bool ⊂ int).
        - ``int`` / ``float``: cast to string directly (no quoting).
        - ``date`` / ``datetime``: ISO-format string, wrapped in single quotes.
        - ``None``: literal ``NULL``.
        - All other types (str, etc.): wrap in single quotes, escape internal
          single quotes by doubling (``'`` → ``''``), and reject strings
          containing obvious injection patterns.

        .. warning::
            This is *not* equivalent to a parameterized query. It is a
            best-effort defence for cross-driver SQL templates where native
            bind-variables are unavailable. Prefer parameterized queries
            when the driver supports them.

        Args:
            value: The value to escape.

        Returns:
            Escaped string representation safe for SQL interpolation.

        Raises:
            ValueError: If the string value contains dangerous SQL patterns.
        """
        if value is None:
            return 'NULL'
        if isinstance(value, bool):
            # bool must come before int because bool is a subclass of int
            return str(value).upper()
        if isinstance(value, (int, float)):
            return str(value)
        if isinstance(value, (datetime, date)):
            return f"'{value.isoformat()}'"
        str_val = str(value)
        # Reject strings with obvious injection patterns
        for pattern in SQLQuerySource._DANGEROUS_PATTERNS:
            if pattern in str_val:
                raise ValueError(
                    f"Potentially dangerous SQL value rejected (contains '{pattern}'): "
                    f"{str_val[:50]}..."
                )
        escaped = str_val.replace("'", "''")
        return f"'{escaped}'"

    async def fetch(self, **params) -> pd.DataFrame:
        """Execute the SQL template and return a DataFrame.

        Validates that all ``{param}`` placeholders are present in ``params``,
        escapes values to prevent SQL injection, interpolates the SQL, and
        executes it via AsyncDB.

        Args:
            **params: Values for each ``{param}`` placeholder in the SQL template.

        Returns:
            DataFrame with the query results.

        Raises:
            ValueError: If required params are missing.
            RuntimeError: If the query fails or does not return a DataFrame.
        """
        required = self._extract_params()
        missing = [p for p in required if p not in params]
        if missing:
            raise ValueError(f"SQLQuerySource missing required params: {missing}")

        escaped_params = {k: self._escape_value(v) for k, v in params.items() if k in required}
        final_sql = self.sql.format(**escaped_params)

        self.logger.info("Executing SQL via %s: %s...", self.driver, final_sql[:100])

        try:
            db = AsyncDB(self.driver, dsn=self.dsn) if self.dsn else AsyncDB(self.driver)
            async with await db.connection() as conn:
                conn.output_format('pandas')
                result, errors = await conn.query(final_sql)

            if errors:
                raise RuntimeError(f"SQLQuerySource query failed: {errors}")

            if not isinstance(result, pd.DataFrame):
                raise RuntimeError(
                    f"SQLQuerySource did not return a DataFrame (got {type(result).__name__})"
                )

            return result

        except (RuntimeError, ValueError):
            raise
        except Exception as e:
            raise RuntimeError(f"SQLQuerySource execution failed: {e}") from e
