"""
TableSource — schema-prefetch DataSource for database tables.

On registration, prefetch_schema() runs a driver-aware INFORMATION_SCHEMA query
to retrieve column names and types without materializing any rows. The LLM
receives full schema awareness before any data is fetched.

At fetch time, the LLM provides a SQL statement which is validated to reference
the registered table before execution.
"""
import logging
import re
from typing import Dict, Optional, Tuple

import pandas as pd

from .base import DataSource

logger = logging.getLogger(__name__)

# Canonical driver aliases map
_DRIVER_ALIASES: Dict[str, str] = {
    'postgresql': 'pg',
    'postgres': 'pg',
    'mariadb': 'mysql',
    'bq': 'bigquery',
}

# Valid SQL identifier: letters, digits, underscores (no leading digit)
_SAFE_IDENTIFIER_RE = re.compile(r'^[a-zA-Z_][a-zA-Z0-9_]*$')


def _validate_identifier(name: str, label: str = 'identifier') -> None:
    """Validate that a name is a safe SQL identifier.

    Raises:
        ValueError: If the name contains unsafe characters.
    """
    if not _SAFE_IDENTIFIER_RE.match(name):
        raise ValueError(
            f"Unsafe SQL {label}: '{name}'. "
            f"Only [a-zA-Z_][a-zA-Z0-9_]* is allowed."
        )


def _normalize_driver(driver: str) -> str:
    """Normalize driver name to the canonical asyncdb driver string."""
    return _DRIVER_ALIASES.get(driver.lower(), driver.lower())


def _resolve_credentials(driver: str) -> Tuple[Optional[Dict], Optional[str]]:
    """Resolve default credentials for a driver from navconfig.

    Returns (credentials_dict, dsn_string). The caller should use dsn if set,
    otherwise use the credentials dict to construct the AsyncDB instance.

    Args:
        driver: Canonical asyncdb driver name (already normalized).

    Returns:
        Tuple of (credentials dict or None, DSN string or None).
    """
    from pathlib import Path
    from navconfig import config

    if driver == 'pg':
        # Prefer DSN from querysource if available
        try:
            from querysource.conf import default_dsn  # type: ignore[import]
            if default_dsn:
                return None, default_dsn
        except (ImportError, Exception):
            pass
        return {
            'host': config.get('POSTGRES_HOST', fallback='localhost'),
            'port': config.get('POSTGRES_PORT', fallback='5432'),
            'database': config.get('POSTGRES_DB', fallback='postgres'),
            'user': config.get('POSTGRES_USER', fallback='postgres'),
            'password': config.get('POSTGRES_PASSWORD'),
        }, None

    if driver == 'bigquery':
        bigquery_creds_path = config.get('BIGQUERY_CREDENTIALS_PATH')
        return {
            'credentials': (
                Path(bigquery_creds_path).resolve() if bigquery_creds_path else None
            ),
            'project_id': config.get('BIGQUERY_PROJECT_ID'),
        }, None

    if driver in ('mysql', 'mariadb'):
        return {
            'host': config.get('MYSQL_HOST', fallback='localhost'),
            'port': config.get('MYSQL_PORT', fallback='3306'),
            'database': config.get('MYSQL_DATABASE', fallback='mysql'),
            'user': config.get('MYSQL_USER', fallback='root'),
            'password': config.get('MYSQL_PASSWORD'),
        }, None

    # Unknown driver — return empty credentials; caller will likely fail at connect
    return {}, None


class TableSource(DataSource):
    """DataSource for a database table with INFORMATION_SCHEMA schema prefetch.

    Registers a table reference (e.g. "troc.finance_visits_details") for a given
    AsyncDB driver. On registration (via add_table_source), prefetch_schema() is
    called to retrieve column names and data types from INFORMATION_SCHEMA — no
    rows are fetched.

    The LLM can then build a SQL query using the schema and call fetch(sql=...) to
    materialize actual data. The SQL is validated to reference self.table before
    execution.

    Args:
        table: Fully-qualified table name, e.g. "public.orders" or
               "troc.finance_visits_details". For BigQuery use "dataset.table".
        driver: AsyncDB driver name, e.g. "pg", "bigquery", "mysql".
        dsn: Optional DSN string. If None, credentials are resolved from navconfig.
        credentials: Optional credentials dict. Takes priority over navconfig defaults
                     when dsn is also None.
        strict_schema: If True (default), prefetch_schema() failures raise and
                       registration fails. If False, failures log a warning and
                       register with empty schema.
    """

    def __init__(
        self,
        table: str,
        driver: str,
        dsn: Optional[str] = None,
        credentials: Optional[Dict] = None,
        strict_schema: bool = True,
    ) -> None:
        self.table = table
        self.driver = _normalize_driver(driver)
        self._dsn = dsn
        self._credentials = credentials
        self.strict_schema = strict_schema
        self._schema: Dict[str, str] = {}

    # ─────────────────────────────────────────────────────────────
    # Internal helpers
    # ─────────────────────────────────────────────────────────────

    def _parse_table(self) -> Tuple[str, str]:
        """Return (schema_name, table_name) by splitting on '.'.

        For BigQuery, schema_name is the dataset name.
        For PostgreSQL, schema_name defaults to 'public' when not specified.
        """
        parts = self.table.split('.')
        if len(parts) >= 2:
            return parts[0], parts[1]
        return 'public', parts[0]

    def _get_connection_args(self) -> Tuple[Optional[Dict], Optional[str]]:
        """Return (credentials, dsn) for AsyncDB construction.

        Priority:
          1. Explicit DSN passed at construction
          2. Explicit credentials dict passed at construction
          3. Navconfig defaults for the driver
        """
        if self._dsn:
            return None, self._dsn
        if self._credentials:
            return self._credentials, None
        return _resolve_credentials(self.driver)

    def _build_schema_query(self) -> Tuple[str, bool]:
        """Build the INFORMATION_SCHEMA query for this driver.

        All identifier values are validated against ``_SAFE_IDENTIFIER_RE``
        before interpolation to prevent SQL injection.

        Returns:
            Tuple of (sql_string, is_fallback). is_fallback=True means the
            LIMIT 0 fallback is used and dtype inference applies.

        Raises:
            ValueError: If schema or table name contains unsafe characters.
        """
        schema_name, table_name = self._parse_table()
        _validate_identifier(schema_name, 'schema name')
        _validate_identifier(table_name, 'table name')

        if self.driver == 'bigquery':
            dataset = schema_name
            sql = (
                f"SELECT column_name, data_type "
                f"FROM `{dataset}.INFORMATION_SCHEMA.COLUMNS` "
                f"WHERE table_name = '{table_name}'"
            )
            return sql, False

        if self.driver == 'pg':
            sql = (
                "SELECT column_name, data_type "
                "FROM information_schema.columns "
                f"WHERE table_schema = '{schema_name}' "
                f"AND table_name = '{table_name}'"
            )
            return sql, False

        if self.driver == 'mysql':
            sql = (
                "SELECT column_name, data_type "
                "FROM information_schema.columns "
                f"WHERE table_schema = DATABASE() "
                f"AND table_name = '{table_name}'"
            )
            return sql, False

        # Fallback for unknown drivers: zero-row fetch
        return f"SELECT * FROM {self.table} LIMIT 0", True

    async def _run_query(self, sql: str) -> pd.DataFrame:
        """Execute SQL via AsyncDB and return a pandas DataFrame.

        Opens a connection, executes, closes. Does not hold connections open.

        Args:
            sql: The SQL statement to execute.

        Returns:
            A pandas DataFrame with the query results.

        Raises:
            RuntimeError: If the query fails or returns unexpected data.
        """
        from asyncdb import AsyncDB  # type: ignore[import]

        credentials, dsn = self._get_connection_args()

        if dsn:
            db = AsyncDB(self.driver, dsn=dsn)
        else:
            db = AsyncDB(self.driver, params=credentials)

        async with await db.connection() as conn:
            conn.output_format('pandas')
            result, errors = await conn.query(sql)

            if errors:
                raise RuntimeError(
                    f"TableSource query failed on '{self.table}': {errors}"
                )

            if result is None:
                return pd.DataFrame()

            if not isinstance(result, pd.DataFrame):
                raise RuntimeError(
                    f"Expected pandas DataFrame but got {type(result).__name__}"
                )

            return result

    # ─────────────────────────────────────────────────────────────
    # DataSource interface
    # ─────────────────────────────────────────────────────────────

    async def prefetch_schema(self) -> Dict[str, str]:
        """Fetch column names and types from INFORMATION_SCHEMA.

        Runs a driver-specific metadata query that returns no data rows.
        Result is stored in self._schema and returned.

        On error:
          - strict_schema=True (default): re-raises the exception.
          - strict_schema=False: logs a warning, sets self._schema = {}.

        Returns:
            Dict mapping column_name → data_type string.
        """
        sql, is_fallback = self._build_schema_query()

        try:
            df = await self._run_query(sql)

            if is_fallback:
                # Zero-row fetch: infer schema from DataFrame dtypes
                self._schema = {col: str(dtype) for col, dtype in df.dtypes.items()}
            else:
                # INFORMATION_SCHEMA result has column_name and data_type columns
                if df.empty:
                    self._schema = {}
                else:
                    self._schema = {
                        str(row['column_name']): str(row['data_type'])
                        for _, row in df.iterrows()
                    }

        except Exception as exc:
            if self.strict_schema:
                raise
            logger.warning(
                "TableSource: schema prefetch failed for table '%s' via %s "
                "(strict_schema=False): %s",
                self.table,
                self.driver,
                exc,
            )
            self._schema = {}

        return self._schema

    async def fetch(self, sql: Optional[str] = None, **params) -> pd.DataFrame:
        """Execute a SQL query against the registered table.

        The SQL is validated to contain the table name as a whole word
        (case-insensitive, word-boundary check) to prevent the LLM from
        executing arbitrary queries outside the registered scope.

        .. note::
            This is an allowlist heuristic, not a full SQL parser.
            It prevents most accidental misuse but is not a security boundary.
            Agent-level permissions control which sources are accessible.

        Args:
            sql: The SQL statement to execute. Required for TableSource.
                 Build it using the columns from prefetch_schema() / describe().
            **params: Additional params (ignored; SQL must be fully formed).

        Returns:
            DataFrame with the query results.

        Raises:
            ValueError: If sql is not provided or does not reference self.table.
            RuntimeError: If the query fails at the database level.
        """
        if not sql:
            raise ValueError(
                f"TableSource.fetch() requires a 'sql' argument. "
                f"Build a SQL query using the schema for '{self.table}' "
                f"(call describe() or get_source_schema()) and pass it as sql=..."
            )

        # Word-boundary check: table name must appear as a whole token
        table_pattern = re.escape(self.table)
        if not re.search(rf'\b{table_pattern}\b', sql, re.IGNORECASE):
            raise ValueError(
                f"SQL must reference the registered table '{self.table}'. "
                f"The provided SQL does not mention this table."
            )

        return await self._run_query(sql)

    def describe(self) -> str:
        """Return a human-readable description for the LLM guide.

        Returns:
            String describing the table, driver, and number of known columns.
        """
        n_cols = len(self._schema)
        return f"Table '{self.table}' via {self.driver} ({n_cols} columns known)"

    @property
    def cache_key(self) -> str:
        """Stable Redis cache key for this table source.

        Format: 'table:{driver}:{table}'
        """
        return f"table:{self.driver}:{self.table}"
