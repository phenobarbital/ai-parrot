"""DatabaseQueryToolkit — Multi-database tools as an AbstractToolkit.

Exposes four LLM-callable tools via public async methods:

  - get_database_metadata
  - validate_database_query
  - execute_database_query
  - fetch_database_row

Every query method routes through ``parrot.security.QueryValidator``
to block DDL/DML before reaching the underlying source.

Part of FEAT-105 — databasetoolkit-clash.
"""
from __future__ import annotations

import contextlib
import logging
from typing import Any, Optional

from parrot.security import QueryLanguage, QueryValidator
from parrot.tools.databasequery.base import (
    AbstractDatabaseSource,
    MetadataResult,
    QueryResult,
    RowResult,
    ValidationResult,
)
from parrot.tools.databasequery.sources import get_source_class, normalize_driver
from parrot.tools.toolkit import AbstractToolkit


# ---------------------------------------------------------------------------
# Driver → QueryLanguage mapping
# ---------------------------------------------------------------------------

#: Maps canonical driver names to their ``QueryLanguage`` for safety checks.
_DRIVER_TO_QUERY_LANGUAGE: dict[str, QueryLanguage] = {
    # SQL family
    "pg": QueryLanguage.SQL,
    "mysql": QueryLanguage.SQL,
    "bigquery": QueryLanguage.SQL,
    "sqlite": QueryLanguage.SQL,
    "oracle": QueryLanguage.SQL,
    "mssql": QueryLanguage.SQL,
    "clickhouse": QueryLanguage.SQL,
    "duckdb": QueryLanguage.SQL,
    # Time-series
    "influx": QueryLanguage.FLUX,
    # Document DB
    "mongo": QueryLanguage.MQL,
    "atlas": QueryLanguage.MQL,
    "documentdb": QueryLanguage.MQL,
    # Search
    "elastic": QueryLanguage.JSON,
}


def _resolve_query_language(driver: str) -> QueryLanguage:
    """Return the QueryLanguage for a driver name.

    Args:
        driver: Raw driver name (may be an alias such as 'postgres').

    Returns:
        The corresponding ``QueryLanguage`` enum value.

    Raises:
        ValueError: If the driver is not supported for query validation.
    """
    canonical = normalize_driver(driver)
    if canonical not in _DRIVER_TO_QUERY_LANGUAGE:
        raise ValueError(
            f"Unsupported driver for query validation: {driver!r} "
            f"(resolved to {canonical!r})"
        )
    return _DRIVER_TO_QUERY_LANGUAGE[canonical]


def _validator_result_to_validation_result(
    check: dict[str, Any],
    language: QueryLanguage,
) -> ValidationResult:
    """Convert a QueryValidator result dict into a ValidationResult.

    Args:
        check: Raw dict returned by ``QueryValidator.validate_query``.
        language: The query language that was validated.

    Returns:
        A ``ValidationResult`` with ``valid`` set to the safety flag.
    """
    is_safe = bool(check.get("is_safe", True))
    return ValidationResult(
        valid=is_safe,
        error=None if is_safe else check.get("message"),
        dialect=language.value,
    )


# ---------------------------------------------------------------------------
# DatabaseQueryToolkit
# ---------------------------------------------------------------------------


class DatabaseQueryToolkit(AbstractToolkit):
    """Multi-database toolkit — discover schema, validate queries, execute.

    Inherits from ``AbstractToolkit`` so the four public async methods are
    automatically discovered and wrapped as ``AbstractTool`` instances.  Use
    ``get_tools()`` to retrieve them and attach them to an Agent or AgentCrew.

    Tool names (with ``tool_prefix="dq"``):
      - ``dq_get_database_metadata``
      - ``dq_validate_database_query``
      - ``dq_execute_database_query``
      - ``dq_fetch_database_row``

    DDL/DML guard:
        Every query-executing method calls
        ``parrot.security.QueryValidator.validate_query`` BEFORE contacting the
        underlying source, ensuring that dangerous statements (``DROP``,
        ``INSERT``, ``UPDATE``, …) are rejected even if the caller skips
        ``validate_database_query``.

    Supported drivers (canonical names):
        ``pg``, ``mysql``, ``bigquery``, ``sqlite``, ``oracle``, ``mssql``,
        ``clickhouse``, ``duckdb``, ``influx``, ``mongo``, ``atlas``,
        ``documentdb``, ``elastic`` — plus all aliases resolved by
        ``normalize_driver()``.
    """

    #: Prefix applied to every auto-generated tool name.
    #: Owner decision Q2: use "dq" to avoid clash with SQLToolkit prefix "sql".
    tool_prefix: Optional[str] = "dq"

    #: Internal helpers that must NOT become LLM-callable tools.
    #: ``cleanup``, ``start``, ``stop`` are also excluded by ``AbstractToolkit``
    #: but listed here for self-documentation clarity.
    exclude_tools: tuple[str, ...] = ("get_source", "cleanup", "start", "stop")

    def __init__(self, **kwargs: Any) -> None:
        """Initialise the toolkit.

        Args:
            **kwargs: Forwarded to ``AbstractToolkit.__init__``.
        """
        super().__init__(**kwargs)
        self._source_cache: dict[str, AbstractDatabaseSource] = {}

    # ── Non-tool helpers ────────────────────────────────────────────────────

    def get_source(self, driver: str) -> AbstractDatabaseSource:
        """Return a (cached) source instance for *driver*.

        Not a tool — listed in ``exclude_tools``.

        Args:
            driver: Raw driver name (alias or canonical).

        Returns:
            A concrete ``AbstractDatabaseSource`` instance.
        """
        canonical = normalize_driver(driver)
        if canonical not in self._source_cache:
            cls = get_source_class(canonical)
            self._source_cache[canonical] = cls()
            self.logger.debug("Instantiated source for driver '%s'", canonical)
        return self._source_cache[canonical]

    async def cleanup(self) -> None:
        """Close all cached source pools.

        Not a tool — listed in ``exclude_tools``.  Called automatically by
        ``AbstractToolkit.stop()`` lifecycle if hooked.
        """
        for source in self._source_cache.values():
            with contextlib.suppress(Exception):
                if hasattr(source, "close"):
                    await source.close()
        self._source_cache.clear()

    # ── Public tools ────────────────────────────────────────────────────────

    async def get_database_metadata(
        self,
        driver: str,
        credentials: Optional[dict[str, Any]] = None,
        tables: Optional[list[str]] = None,
    ) -> dict:
        """Discover database schema. Call this FIRST before writing queries.

        Returns table names, column names, and data types for the target
        database.  Use this to understand what data is available before
        attempting to run a query.

        Args:
            driver: Canonical driver name (e.g. ``'pg'``, ``'mysql'``,
                ``'mongo'``, ``'elastic'``) or a supported alias
                (e.g. ``'postgres'``, ``'postgresql'``).
            credentials: Optional connection credentials dictionary.
                When omitted, the source falls back to environment-variable
                defaults.
            tables: Optional list of table or collection names to inspect.
                When omitted, the source returns metadata for all objects.

        Returns:
            ``MetadataResult.model_dump()`` containing ``tables`` (list of
            ``TableMeta``) and optionally an ``error`` field on failure.
        """
        source = self.get_source(driver)
        creds = await source.resolve_credentials(credentials)
        result = await source.get_metadata(creds, tables)
        return result.model_dump()

    async def validate_database_query(
        self,
        driver: str,
        query: str,
        credentials: Optional[dict[str, Any]] = None,
    ) -> dict:
        """Validate a query for safety and syntax. Call BEFORE executing.

        Applies a two-layer guard:

        1. **DDL/DML safety check** (``parrot.security.QueryValidator``) —
           rejects ``CREATE``, ``DROP``, ``INSERT``, ``UPDATE``, ``DELETE``,
           ``TRUNCATE``, ``GRANT``, ``EXEC``, etc.  Returns immediately if
           the query is unsafe, *without* contacting the underlying database.
        2. **Syntactic check** (``source.validate_query`` via sqlglot) —
           only reached for safe queries; returns dialect-aware parse errors.

        Args:
            driver: Canonical driver name or alias (see ``get_database_metadata``).
            query: Query string to validate.
            credentials: Optional connection credentials (used by the syntactic
                layer; the safety layer never contacts the database).

        Returns:
            ``ValidationResult.model_dump()`` with ``valid`` (bool), optional
            ``error`` (str), and ``dialect`` (str).  ``valid=False`` means the
            query MUST NOT be executed.
        """
        language = _resolve_query_language(driver)
        check = QueryValidator.validate_query(query, language)
        if not check.get("is_safe", False):
            return _validator_result_to_validation_result(check, language).model_dump()
        # Second layer: source-level syntactic check (sqlglot for SQL drivers).
        source = self.get_source(driver)
        result = await source.validate_query(query)
        return result.model_dump()

    async def execute_database_query(
        self,
        driver: str,
        query: str,
        credentials: Optional[dict[str, Any]] = None,
        params: Optional[dict[str, Any]] = None,
    ) -> dict:
        """Execute a validated query and return all matching rows or documents.

        Re-applies the ``QueryValidator`` DDL/DML guard before contacting the
        source, so a malicious or mistaken caller cannot skip the validation
        step and run a destructive statement.

        Args:
            driver: Canonical driver name or alias.
            query: Query string to execute (must be a read-only query).
            credentials: Optional explicit connection credentials.
            params: Optional parameterised query values
                (``{":name": value, ...}`` or driver-specific format).

        Returns:
            ``QueryResult.model_dump()`` with a ``rows`` list and optional
            ``error``.  When the DDL guard blocks the query the return value is
            a ``ValidationResult.model_dump()`` with ``valid=False``.
        """
        language = _resolve_query_language(driver)
        check = QueryValidator.validate_query(query, language)
        if not check.get("is_safe", False):
            return _validator_result_to_validation_result(check, language).model_dump()
        source = self.get_source(driver)
        creds = await source.resolve_credentials(credentials)
        result = await source.query(creds, query, params)
        return result.model_dump()

    async def fetch_database_row(
        self,
        driver: str,
        query: str,
        credentials: Optional[dict[str, Any]] = None,
        params: Optional[dict[str, Any]] = None,
    ) -> dict:
        """Execute a query and return at most one matching row or document.

        Use this instead of ``execute_database_query`` when you expect a single
        result (e.g. lookup by primary key).  Applies the same DDL/DML guard.

        Args:
            driver: Canonical driver name or alias.
            query: Query string expected to return one row/document.
            credentials: Optional explicit connection credentials.
            params: Optional parameterised query values.

        Returns:
            ``RowResult.model_dump()`` with a single ``row`` dict (or ``None``)
            and optional ``error``.  When the DDL guard blocks the query the
            return value is a ``ValidationResult.model_dump()`` with
            ``valid=False``.
        """
        language = _resolve_query_language(driver)
        check = QueryValidator.validate_query(query, language)
        if not check.get("is_safe", False):
            return _validator_result_to_validation_result(check, language).model_dump()
        source = self.get_source(driver)
        creds = await source.resolve_credentials(credentials)
        result = await source.query_row(creds, query, params)
        return result.model_dump()
