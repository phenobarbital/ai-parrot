"""
TableSource — schema-prefetch DataSource for database tables.

On registration, prefetch_schema() runs a driver-aware INFORMATION_SCHEMA query
to retrieve column names and types without materializing any rows. The LLM
receives full schema awareness before any data is fetched.

At fetch time, the LLM provides a SQL statement which is validated to reference
the registered table before execution.
"""
from __future__ import annotations
import hashlib
import json
import logging
import re
from typing import Any, Dict, List, Optional, Tuple, Union, TYPE_CHECKING

import pandas as pd

from .base import DataSource
from parrot._imports import lazy_import

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
            _qs_conf = lazy_import("querysource.conf", package_name="querysource", extra="db")
            if _qs_conf.default_dsn:
                return None, _qs_conf.default_dsn
        except (ImportError, Exception):
            pass
        pg_password = config.get('PG_PWD') or config.get('PG_PASSWORD')
        return {
            'host': config.get('PG_HOST', fallback='localhost'),
            'port': config.get('PG_PORT', fallback='5432'),
            'database': config.get('PG_DATABASE', fallback='postgres'),
            'user': config.get('PG_USER', fallback='postgres'),
            'password': pg_password,
        }, None

    if driver == 'bigquery':
        bigquery_creds_path = config.get('BIGQUERY_CREDENTIALS') or config.get('BIGQUERY_CREDENTIALS_PATH')
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
        permanent_filter: Optional dict of equality conditions that are always
                          injected as a WHERE clause into every fetch() SQL.
                          Scalar values produce ``col = 'val'``; list/tuple values
                          produce ``col IN ('a', 'b')``. Column names are validated
                          against ``_SAFE_IDENTIFIER_RE``; values are safely escaped.
        allowed_columns: Optional list of column names to restrict access. When set,
                         only these columns appear in the schema, describe() output,
                         guide, and metadata. SQL queries referencing other columns
                         (or SELECT *) are rejected at fetch() time.
    """

    def __init__(
        self,
        table: str,
        driver: str,
        dsn: Optional[str] = None,
        credentials: Optional[Dict] = None,
        strict_schema: bool = True,
        permanent_filter: Optional[Dict[str, Any]] = None,
        allowed_columns: Optional[List[str]] = None,
    ) -> None:
        self.table = table
        self.driver = _normalize_driver(driver)
        self._dsn = dsn
        self._credentials = credentials
        self.strict_schema = strict_schema
        self._permanent_filter: Dict[str, Any] = permanent_filter or {}
        self._schema: Dict[str, str] = {}
        self._row_count_estimate: Optional[int] = None
        # Validate filter column names early
        for col_name in self._permanent_filter:
            _validate_identifier(col_name, 'permanent_filter column')
        # Validate and store allowed_columns
        self._allowed_columns: Optional[List[str]] = None
        if allowed_columns is not None:
            if len(allowed_columns) == 0:
                raise ValueError(
                    "allowed_columns must not be an empty list. "
                    "Pass None for no restriction, or a non-empty list."
                )
            for col_name in allowed_columns:
                _validate_identifier(col_name, 'allowed_columns entry')
            self._allowed_columns = list(allowed_columns)  # defensive copy

    # ─────────────────────────────────────────────────────────────
    # Public properties
    # ─────────────────────────────────────────────────────────────

    @property
    def allowed_columns(self) -> Optional[List[str]]:
        """Return the allowed columns list, or None if unrestricted.

        Returns:
            List of allowed column names, or None if no restriction is set.
        """
        return self._allowed_columns

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

    @staticmethod
    def _escape_value(value: Union[str, int, float]) -> str:
        """Escape a single scalar value for safe SQL interpolation.

        Strings are single-quoted with internal quotes doubled.
        Numbers are returned as-is.

        Args:
            value: The value to escape.

        Returns:
            Safe SQL literal string.
        """
        if isinstance(value, (int, float)):
            return str(value)
        # Escape single quotes by doubling them
        safe = str(value).replace("'", "''")
        return f"'{safe}'"

    def _build_filter_clause(self) -> str:
        """Build a SQL WHERE fragment from the permanent_filter dict.

        Scalar values produce ``column = 'value'``.
        List/tuple values produce ``column IN ('a', 'b')``.

        Returns:
            SQL fragment (without leading WHERE/AND), or empty string
            if no permanent filter is set.
        """
        if not self._permanent_filter:
            return ''

        parts: List[str] = []
        for col, val in self._permanent_filter.items():
            if isinstance(val, (list, tuple)):
                escaped = ', '.join(self._escape_value(v) for v in val)
                parts.append(f"{col} IN ({escaped})")
            else:
                parts.append(f"{col} = {self._escape_value(val)}")

        return ' AND '.join(parts)

    def _inject_permanent_filter(self, sql: str) -> str:
        """Inject the permanent filter clause into a SQL statement.

        If the SQL already contains a WHERE clause, the filter conditions are
        appended with AND. Otherwise, a WHERE clause is inserted before any
        trailing ORDER BY, GROUP BY, LIMIT, or at the end.

        Args:
            sql: The original SQL statement.

        Returns:
            SQL with permanent filter conditions injected.
        """
        clause = self._build_filter_clause()
        if not clause:
            return sql

        # Check if SQL already has a WHERE (case-insensitive)
        where_match = re.search(r'\bWHERE\b', sql, re.IGNORECASE)
        if where_match:
            # Insert AND <clause> right after the first WHERE ... before
            # ORDER BY / GROUP BY / LIMIT / HAVING / UNION or end
            tail_kw = re.search(
                r'\b(ORDER\s+BY|GROUP\s+BY|HAVING|LIMIT|UNION|OFFSET)\b',
                sql[where_match.end():],
                re.IGNORECASE,
            )
            if tail_kw:
                insert_pos = where_match.end() + tail_kw.start()
                return f"{sql[:insert_pos]}AND {clause} {sql[insert_pos:]}"
            return f"{sql} AND {clause}"

        # No WHERE — insert before trailing keywords or at end
        tail_kw = re.search(
            r'\b(ORDER\s+BY|GROUP\s+BY|HAVING|LIMIT|UNION|OFFSET)\b',
            sql,
            re.IGNORECASE,
        )
        if tail_kw:
            insert_pos = tail_kw.start()
            return f"{sql[:insert_pos]}WHERE {clause} {sql[insert_pos:]}"
        return f"{sql} WHERE {clause}"

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

        # Filter schema to allowed columns if restriction is set
        if self._allowed_columns is not None:
            full_schema = dict(self._schema)
            self._schema = {
                col: dtype for col, dtype in full_schema.items()
                if col in self._allowed_columns
            }
            missing = set(self._allowed_columns) - set(full_schema.keys())
            if missing:
                if self.strict_schema:
                    raise ValueError(
                        f"allowed_columns contains columns not found in table "
                        f"'{self.table}': {sorted(missing)}"
                    )
                else:
                    logger.warning(
                        "TableSource('%s'): allowed_columns not found in schema: %s",
                        self.table, sorted(missing),
                    )

        return self._schema

    async def prefetch_row_count(self) -> Optional[int]:
        """Estimate the row count for this table via COUNT(*).

        The result is stored in ``self._row_count_estimate`` and surfaced to
        the LLM so it can decide whether to use aggregation queries instead
        of SELECT *.

        When a permanent_filter is set the count reflects only the filtered
        subset, matching what the LLM would see at fetch time.

        Returns:
            Estimated row count, or None if the query fails.
        """
        count_sql = f"SELECT COUNT(*) AS cnt FROM {self.table}"
        if self._permanent_filter:
            count_sql = self._inject_permanent_filter(count_sql)

        try:
            df = await self._run_query(count_sql)
            if df is not None and not df.empty:
                self._row_count_estimate = int(df.iloc[0, 0])
            else:
                self._row_count_estimate = None
        except Exception as exc:
            logger.warning(
                "TableSource: row count prefetch failed for '%s': %s",
                self.table,
                exc,
            )
            self._row_count_estimate = None

        return self._row_count_estimate

    @staticmethod
    def _size_warning(row_count: Optional[int]) -> str:
        """Return a human-readable size warning for the LLM.

        Args:
            row_count: Estimated number of rows.

        Returns:
            Empty string if the table is small or count is unknown,
            otherwise a warning string.
        """
        if row_count is None:
            return ""
        if row_count > 100_000:
            return (
                f"⚠ LARGE TABLE ({row_count:,} rows). "
                "You MUST use GROUP BY / COUNT / SUM / AVG in your SQL. "
                "Do NOT fetch all rows with SELECT *."
            )
        if row_count > 10_000:
            return (
                f"⚠ Medium table ({row_count:,} rows). "
                "Prefer aggregation queries (GROUP BY) over SELECT *."
            )
        return ""

    async def fetch(self, sql: Optional[str] = None, **params) -> pd.DataFrame:
        """Execute a SQL query against the registered table.

        The SQL is validated to contain the table name as a whole word
        (case-insensitive, word-boundary check) to prevent the LLM from
        executing arbitrary queries outside the registered scope.

        When the registered table is schema-qualified (e.g. ``schema.table``),
        SQL that references just the table name is accepted and automatically
        rewritten to use the fully-qualified name before execution.

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

        # Word-boundary check: table name must appear as a whole token.
        # For schema-qualified tables (e.g. "pokemon.fso_daily_summary"),
        # also accept just the table part and auto-qualify it.
        full_pattern = re.escape(self.table)
        if re.search(rf'\b{full_pattern}\b', sql, re.IGNORECASE):
            # SQL already uses the fully-qualified name — pass through.
            pass
        elif '.' in self.table:
            # Registered table is schema-qualified; check for just the
            # table name and rewrite the SQL to use the full qualifier.
            _schema_name, table_name = self.table.rsplit('.', 1)
            short_pattern = re.escape(table_name)
            if re.search(rf'\b{short_pattern}\b', sql, re.IGNORECASE):
                # Replace the unqualified table name with the full reference
                sql = re.sub(
                    rf'\b{short_pattern}\b',
                    self.table,
                    sql,
                    count=0,
                    flags=re.IGNORECASE,
                )
                logger.debug(
                    "Auto-qualified table name '%s' → '%s' in SQL",
                    table_name, self.table,
                )
            else:
                raise ValueError(
                    f"SQL must reference the registered table '{self.table}' "
                    f"(or just '{table_name}'). "
                    f"The provided SQL does not mention this table."
                )
        else:
            raise ValueError(
                f"SQL must reference the registered table '{self.table}'. "
                f"The provided SQL does not mention this table."
            )

        # Inject permanent filter as WHERE/AND conditions
        if self._permanent_filter:
            sql = self._inject_permanent_filter(sql)

        logger.info("TableSource('%s') executing SQL: %s", self.table, sql)
        return await self._run_query(sql)

    def describe(self) -> str:
        """Return a human-readable description for the LLM guide.

        Returns:
            String describing the table, driver, number of known columns,
            and estimated row count with size warning if applicable.
        """
        n_cols = len(self._schema)
        desc = f"Table '{self.table}' via {self.driver} ({n_cols} columns known)"
        if self._row_count_estimate is not None:
            desc += f", ~{self._row_count_estimate:,} rows"
        if self._permanent_filter:
            desc += f" [permanent filter: {self._permanent_filter}]"
        if self._allowed_columns is not None:
            col_list = ', '.join(self._allowed_columns)
            desc += (
                f" [restricted to {len(self._allowed_columns)} columns: {col_list}]"
                f" Only these columns may be used in queries."
            )
        warning = self._size_warning(self._row_count_estimate)
        if warning:
            desc += f" {warning}"
        return desc

    @property
    def cache_key(self) -> str:
        """Stable Redis cache key for this table source.

        Format: ``table:{driver}:{table}`` or ``table:{driver}:{table}:f={hash}``
        when a permanent filter is set, with an optional ``:ac={hash}`` suffix
        when allowed_columns is set.
        """
        base = f"table:{self.driver}:{self.table}"
        if self._permanent_filter:
            suffix = hashlib.md5(
                json.dumps(self._permanent_filter, sort_keys=True).encode()
            ).hexdigest()[:8]
            base = f"{base}:f={suffix}"
        if self._allowed_columns is not None:
            ac_suffix = hashlib.md5(
                json.dumps(sorted(self._allowed_columns)).encode()
            ).hexdigest()[:8]
            base = f"{base}:ac={ac_suffix}"
        return base
