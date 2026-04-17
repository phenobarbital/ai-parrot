"""DatabaseToolkit — Result Types & AbstractDatabaseSource.

Defines all Pydantic v2 result models and the AbstractDatabaseSource ABC
that every database source must implement.

Part of FEAT-062 — DatabaseToolkit.
"""
from __future__ import annotations

import contextlib
import json
import re
from abc import ABC, abstractmethod
from typing import Any

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# SQL identifier validation (SQL injection guard)
# ---------------------------------------------------------------------------

_SQL_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9_\$#\.]+$")


def _validate_sql_identifier(name: str, context: str = "identifier") -> str:
    """Validate a SQL identifier to prevent injection attacks.

    Accepts identifiers containing only letters, digits, underscores, ``$``,
    ``#``, and dots (for ``schema.table`` qualified names). Rejects anything
    with quotes, semicolons, spaces, or other special characters.

    Args:
        name: The identifier to validate (table name, column name, etc.).
        context: Human-readable label used in error messages.

    Returns:
        The validated name, unchanged.

    Raises:
        ValueError: If the name contains characters that could enable SQL
            injection (quotes, semicolons, spaces, etc.).

    Examples:
        >>> _validate_sql_identifier("users")
        'users'
        >>> _validate_sql_identifier("public.orders")
        'public.orders'
        >>> _validate_sql_identifier("a'; DROP TABLE users--")
        # raises ValueError: Invalid SQL identifier ... possible SQL injection
    """
    if not name or not _SQL_IDENTIFIER_RE.match(name):
        raise ValueError(
            f"Invalid SQL {context} {name!r}: must contain only letters, digits, "
            "underscores, $, #, or dots. Possible SQL injection attempt."
        )
    return name


# ---------------------------------------------------------------------------
# Connection pool cache key helper
# ---------------------------------------------------------------------------


def _make_cred_key(dsn: str | None, params: dict[str, Any] | None) -> str:
    """Create a stable string key from connection credentials for pool caching.

    Args:
        dsn: Connection string, or None.
        params: Connection parameter dict, or None.

    Returns:
        A deterministic JSON string suitable as a dict key. Parameters are
        sorted so that ``{"host": "a", "port": 5}`` and
        ``{"port": 5, "host": "a"}`` produce the same key.
    """
    return json.dumps({"dsn": dsn, "params": params}, sort_keys=True, default=str)


# ---------------------------------------------------------------------------
# Result Models (Pydantic v2)
# ---------------------------------------------------------------------------


class ValidationResult(BaseModel):
    """Result of a query validation operation.

    Attributes:
        valid: Whether the query is syntactically valid.
        error: Error message if validation failed.
        dialect: The query dialect that was validated against.
    """

    valid: bool
    error: str | None = None
    dialect: str | None = None


class ColumnMeta(BaseModel):
    """Metadata for a single database column or field.

    Attributes:
        name: Column name.
        data_type: Column data type.
        nullable: Whether the column allows null values.
        primary_key: Whether this column is part of the primary key.
        default: Default value for the column.
    """

    name: str
    data_type: str
    nullable: bool = True
    primary_key: bool = False
    default: Any = None


class TableMeta(BaseModel):
    """Metadata for a single database table, collection, or measurement.

    Attributes:
        name: Table or collection name.
        schema_name: Schema or namespace (optional).
        columns: List of column/field metadata.
        row_count: Approximate row count (optional).
    """

    name: str
    schema_name: str | None = None
    columns: list[ColumnMeta] = Field(default_factory=list)
    row_count: int | None = None


class MetadataResult(BaseModel):
    """Result of a metadata discovery operation.

    Attributes:
        driver: The database driver used.
        tables: List of table/collection metadata.
        raw: Raw metadata from the database (driver-specific).
    """

    driver: str
    tables: list[TableMeta]
    raw: dict[str, Any] = Field(default_factory=dict)


class QueryResult(BaseModel):
    """Result of a multi-row query execution.

    Attributes:
        driver: The database driver used.
        rows: List of rows as dictionaries.
        row_count: Number of rows returned.
        columns: List of column names.
        execution_time_ms: Query execution time in milliseconds.
    """

    driver: str
    rows: list[dict[str, Any]]
    row_count: int
    columns: list[str]
    execution_time_ms: float


class RowResult(BaseModel):
    """Result of a single-row fetch operation.

    Attributes:
        driver: The database driver used.
        row: The fetched row as a dictionary, or None if not found.
        found: Whether a row was found.
        execution_time_ms: Query execution time in milliseconds.
    """

    driver: str
    row: dict[str, Any] | None
    found: bool
    execution_time_ms: float


# ---------------------------------------------------------------------------
# AbstractDatabaseSource
# ---------------------------------------------------------------------------


class AbstractDatabaseSource(ABC):
    """Abstract base class for all database source implementations.

    Each concrete subclass represents a specific database driver (e.g., PostgreSQL,
    MongoDB, Elasticsearch) and provides driver-specific implementations of
    metadata discovery, query validation, and query execution.

    Class Attributes:
        driver: The canonical asyncdb driver name (e.g., ``'pg'``, ``'mongo'``).
        sqlglot_dialect: The sqlglot dialect for SQL validation, or ``None``
            for non-SQL databases.
    """

    driver: str
    sqlglot_dialect: str | None = None

    async def resolve_credentials(
        self, credentials: dict[str, Any] | None
    ) -> dict[str, Any]:
        """Resolve credentials, using defaults if none provided.

        Args:
            credentials: Explicit credentials dictionary or None.

        Returns:
            Resolved credentials dictionary. Falls back to
            ``get_default_credentials()`` if credentials is None.
        """
        return credentials if credentials is not None else await self.get_default_credentials()

    @abstractmethod
    async def get_default_credentials(self) -> dict[str, Any]:
        """Return default credentials for this database driver.

        Returns:
            Default credentials dictionary. May be empty if no defaults
            are configured.
        """

    async def validate_query(self, query: str) -> ValidationResult:
        """Validate a query using sqlglot for the configured dialect.

        SQL sources (where ``sqlglot_dialect`` is set) use sqlglot for
        validation. Non-SQL sources must override this method.

        Args:
            query: Query string to validate.

        Returns:
            ValidationResult indicating whether the query is valid.

        Raises:
            NotImplementedError: If ``sqlglot_dialect`` is None (non-SQL sources
                must override this method).
        """
        if self.sqlglot_dialect is None:
            raise NotImplementedError(
                f"{self.__class__.__name__} is a non-SQL source and must override "
                "validate_query() to implement custom validation logic."
            )
        import sqlglot
        import sqlglot.errors

        try:
            statements = sqlglot.parse(query, dialect=self.sqlglot_dialect, error_level=sqlglot.errors.ErrorLevel.RAISE)
            if not statements or all(s is None for s in statements):
                return ValidationResult(
                    valid=False,
                    error="Query produced no parseable statements.",
                    dialect=self.sqlglot_dialect,
                )
            return ValidationResult(valid=True, dialect=self.sqlglot_dialect)
        except sqlglot.errors.ParseError as exc:
            return ValidationResult(
                valid=False,
                error=str(exc),
                dialect=self.sqlglot_dialect,
            )
        except Exception as exc:  # noqa: BLE001
            return ValidationResult(
                valid=False,
                error=f"Validation error: {exc}",
                dialect=self.sqlglot_dialect,
            )

    @abstractmethod
    async def get_metadata(
        self,
        credentials: dict[str, Any],
        tables: list[str] | None = None,
    ) -> MetadataResult:
        """Discover database schema metadata.

        Args:
            credentials: Connection credentials.
            tables: Optional list of specific tables to inspect.
                If None, returns metadata for all accessible tables.

        Returns:
            MetadataResult with table and column definitions.
        """

    @abstractmethod
    async def query(
        self,
        credentials: dict[str, Any],
        sql: str,
        params: dict[str, Any] | None = None,
    ) -> QueryResult:
        """Execute a query and return all results.

        Args:
            credentials: Connection credentials.
            sql: Query string (SQL for relational, JSON for NoSQL, etc.).
            params: Optional query parameters.

        Returns:
            QueryResult with rows and execution metadata.
        """

    @abstractmethod
    async def query_row(
        self,
        credentials: dict[str, Any],
        sql: str,
        params: dict[str, Any] | None = None,
    ) -> RowResult:
        """Execute a query and return a single row.

        Args:
            credentials: Connection credentials.
            sql: Query string.
            params: Optional query parameters.

        Returns:
            RowResult with a single row or found=False if no rows.
        """

    # ------------------------------------------------------------------
    # Connection pool management
    # ------------------------------------------------------------------

    def _get_db(
        self,
        asyncdb_driver: str,
        dsn: str | None,
        params: dict[str, Any] | None,
    ) -> Any:
        """Get or create a cached AsyncDB pool instance for the given credentials.

        Source instances are cached by ``DatabaseToolkit``, so this method
        provides connection-pool reuse across multiple calls that use the same
        credentials. Each unique (dsn, params) combination gets its own pool.

        Args:
            asyncdb_driver: The asyncdb driver name (e.g., ``'pg'``, ``'mysql'``).
            dsn: Optional connection string.
            params: Optional connection parameter dict.

        Returns:
            A cached or newly created ``AsyncDB`` pool instance. Callers should
            use ``async with await db.connection() as conn:`` to borrow a
            connection from the pool.
        """
        if not hasattr(self, "_db_pool"):
            self._db_pool: dict[str, Any] = {}
        key = _make_cred_key(dsn, params)
        if key not in self._db_pool:
            from asyncdb import AsyncDB  # lazy import — asyncdb is an optional dep
            self._db_pool[key] = AsyncDB(asyncdb_driver, dsn=dsn, params=params)
        return self._db_pool[key]

    async def close(self) -> None:
        """Release all cached AsyncDB pool instances.

        Called automatically by ``DatabaseToolkit.cleanup()``. Override if the
        source holds additional resources beyond the AsyncDB pool.

        Does nothing if no pool has been created yet (safe to call on a fresh
        instance).
        """
        pool: dict[str, Any] = getattr(self, "_db_pool", {})
        for db in list(pool.values()):
            with contextlib.suppress(Exception):
                if hasattr(db, "close"):
                    await db.close()
        pool.clear()
