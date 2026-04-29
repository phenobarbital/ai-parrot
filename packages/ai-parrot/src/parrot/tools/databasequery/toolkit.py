"""DatabaseQueryToolkit — Multi-database tools as an AbstractToolkit.

Exposes LLM-callable tools via public async methods:

  - get_database_metadata
  - validate_query
  - execute_database_query
  - fetch_database_row
  - get_table_metadata
  - test_connection
  - save_result

Every query method routes through ``parrot.security.QueryValidator``
to block DDL/DML before reaching the underlying source.

Part of FEAT-105 — databasetoolkit-clash.
Part of FEAT-136 — database-toolkit-parity.
"""
from __future__ import annotations

import contextlib
import os
from pathlib import Path
from typing import Any, Optional

from pydantic import BaseModel

from parrot.security import QueryLanguage, QueryValidator
from parrot.tools.databasequery.base import (
    AbstractDatabaseSource,
    MetadataResult,
    QueryResult,
    RowResult,
    ValidationResult,
    add_row_limit,
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

    Inherits from ``AbstractToolkit`` so public async methods are
    automatically discovered and wrapped as ``AbstractTool`` instances.  Use
    ``get_tools()`` to retrieve them and attach them to an Agent or AgentCrew.

    Tool names (with ``tool_prefix="dq"``):
      - ``dq_get_database_metadata``
      - ``dq_validate_query``
      - ``dq_execute_database_query``
      - ``dq_fetch_database_row``
      - ``dq_get_table_metadata``
      - ``dq_test_connection``
      - ``dq_save_result`` (only when ``output_dir`` is configured)

    DDL/DML guard:
        Every query-executing method calls
        ``parrot.security.QueryValidator.validate_query`` BEFORE contacting the
        underlying source, ensuring that dangerous statements (``DROP``,
        ``INSERT``, ``UPDATE``, …) are rejected even if the caller skips
        ``validate_query``.

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
            **kwargs: Supported keyword arguments:
                - ``output_dir`` (str | Path | None): Directory for ``save_result``
                  output files. When not set, ``save_result`` is excluded from the
                  tool list and returns an error dict if called directly.
                - ``static_dir`` (str | Path | None): Optional public URL root for
                  generating ``file_url`` values in ``save_result`` responses.
                - All other kwargs are forwarded to ``AbstractToolkit.__init__``.
        """
        output_dir = kwargs.pop("output_dir", None)
        static_dir = kwargs.pop("static_dir", None)
        super().__init__(**kwargs)
        self._source_cache: dict[str, AbstractDatabaseSource] = {}

        self._output_dir: Optional[Path] = Path(output_dir) if output_dir else None
        self._static_dir: Optional[str] = str(static_dir) if static_dir else None

        # Exclude save_result if output_dir is not configured
        if self._output_dir is None:
            self.exclude_tools = self.exclude_tools + ("save_result",)

    # ── Lifecycle hook ───────────────────────────────────────────────────────

    async def _post_execute(self, tool_name: str, result: Any, **kwargs: Any) -> Any:
        """Serialize Pydantic BaseModel results to dicts for the LLM.

        Called automatically after every tool execution by ``AbstractToolkit``.
        Converts any ``pydantic.BaseModel`` instance into a plain dict so the
        LLM receives JSON-serializable data.

        Args:
            tool_name: Name of the tool that just executed.
            result: Raw result returned by the bound method.
            **kwargs: Arguments forwarded to the bound method.

        Returns:
            ``result.model_dump()`` if result is a BaseModel, otherwise
            the result unchanged.
        """
        if isinstance(result, BaseModel):
            return result.model_dump()
        return result

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
    ) -> MetadataResult:
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
            ``MetadataResult`` containing ``tables`` (list of
            ``TableMeta``) and optionally an ``error`` field on failure.
            Serialized to dict via ``_post_execute``.
        """
        source = self.get_source(driver)
        creds = await source.resolve_credentials(credentials)
        return await source.get_metadata(creds, tables)

    async def validate_query(
        self,
        driver: str,
        query: str,
    ) -> ValidationResult:
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

        Returns:
            ``ValidationResult`` with ``valid`` (bool), optional
            ``error`` (str), and ``dialect`` (str).  ``valid=False`` means the
            query MUST NOT be executed. Serialized to dict via ``_post_execute``.
        """
        language = _resolve_query_language(driver)
        check = QueryValidator.validate_query(query, language)
        if not check.get("is_safe", False):
            return _validator_result_to_validation_result(check, language)
        # Second layer: source-level syntactic check (sqlglot for SQL drivers).
        source = self.get_source(driver)
        return await source.validate_query(query)

    async def get_table_metadata(
        self,
        driver: str,
        table: str,
        credentials: Optional[dict[str, Any]] = None,
    ) -> MetadataResult:
        """Get detailed metadata for a specific table or collection.

        Fetches schema information (column names, types, constraints) for a
        single named table, view, or collection.  Useful when you already
        know which table to query and want to inspect its structure.

        Args:
            driver: Canonical driver name or alias (see ``get_database_metadata``).
            table: The exact table, view, or collection name to inspect.
            credentials: Optional connection credentials dictionary.
                When omitted, the source falls back to environment-variable
                defaults.

        Returns:
            ``MetadataResult`` scoped to the single requested table.
            Serialized to dict via ``_post_execute``.
        """
        source = self.get_source(driver)
        creds = await source.resolve_credentials(credentials)
        return await source.get_metadata(creds, tables=[table])

    async def test_connection(
        self,
        driver: str,
        credentials: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        """Test connectivity to the target database.

        Attempts a lightweight connection check appropriate for the driver
        (e.g. ``SELECT 1`` for SQL, ``ping`` for MongoDB, ``info()`` for
        Elasticsearch, ``buckets()`` for InfluxDB).

        Args:
            driver: Canonical driver name or alias.
            credentials: Optional explicit connection credentials. When omitted,
                the source falls back to environment-variable defaults.

        Returns:
            ``{"status": "success"}`` on success, or
            ``{"status": "error", "message": "<description>"}`` on failure.
        """
        try:
            source = self.get_source(driver)
            creds = await source.resolve_credentials(credentials)
            ok = await source.test_connection(creds)
            if ok:
                return {"status": "success"}
            return {"status": "error", "message": f"Connection test failed for driver {driver!r}"}
        except Exception as exc:  # noqa: BLE001
            return {"status": "error", "message": str(exc)}

    async def execute_database_query(
        self,
        driver: str,
        query: str,
        credentials: Optional[dict[str, Any]] = None,
        params: Optional[dict[str, Any]] = None,
        max_rows: int = 10000,
    ) -> QueryResult:
        """Execute a validated query and return all matching rows or documents.

        Re-applies the ``QueryValidator`` DDL/DML guard before contacting the
        source, so a malicious or mistaken caller cannot skip the validation
        step and run a destructive statement.

        Injects a row limit into the query (via ``add_row_limit()``) when
        ``max_rows`` is positive, to prevent runaway result sets.

        Args:
            driver: Canonical driver name or alias.
            query: Query string to execute (must be a read-only query).
            credentials: Optional explicit connection credentials.
            params: Optional parameterised query values
                (``{":name": value, ...}`` or driver-specific format).
            max_rows: Maximum number of rows to return.  Defaults to 10000.
                Pass ``0`` to disable the limit.

        Returns:
            ``QueryResult`` with a ``rows`` list and optional ``error``.
            When the DDL guard blocks the query the return value is a
            ``ValidationResult`` with ``valid=False``.
            Serialized to dict via ``_post_execute``.
        """
        language = _resolve_query_language(driver)
        check = QueryValidator.validate_query(query, language)
        if not check.get("is_safe", False):
            return _validator_result_to_validation_result(check, language)
        source = self.get_source(driver)
        creds = await source.resolve_credentials(credentials)
        limited_query = add_row_limit(query, max_rows, driver)
        return await source.query(creds, limited_query, params)

    async def fetch_database_row(
        self,
        driver: str,
        query: str,
        credentials: Optional[dict[str, Any]] = None,
        params: Optional[dict[str, Any]] = None,
        max_rows: int = 1,
    ) -> RowResult:
        """Execute a query and return at most one matching row or document.

        Use this instead of ``execute_database_query`` when you expect a single
        result (e.g. lookup by primary key).  Applies the same DDL/DML guard.

        Args:
            driver: Canonical driver name or alias.
            query: Query string expected to return one row/document.
            credentials: Optional explicit connection credentials.
            params: Optional parameterised query values.
            max_rows: Maximum number of rows to consider (default 1). Passed
                to ``add_row_limit()`` before delegating to the source.

        Returns:
            ``RowResult`` with a single ``row`` dict (or ``None``) and optional
            ``error``.  When the DDL guard blocks the query the return value is a
            ``ValidationResult`` with ``valid=False``.
            Serialized to dict via ``_post_execute``.
        """
        language = _resolve_query_language(driver)
        check = QueryValidator.validate_query(query, language)
        if not check.get("is_safe", False):
            return _validator_result_to_validation_result(check, language)
        source = self.get_source(driver)
        creds = await source.resolve_credentials(credentials)
        limited_query = add_row_limit(query, max_rows, driver)
        return await source.query_row(creds, limited_query, params)

    async def save_result(
        self,
        result: dict[str, Any],
        filename: Optional[str] = None,
        file_format: str = "csv",
    ) -> dict[str, Any]:
        """Save a prior query result to a file on disk.

        Converts the ``rows`` list in *result* to a DataFrame and writes it to
        the configured ``output_dir`` in the requested format.  Only available
        when the toolkit was constructed with a valid ``output_dir``.

        Supported formats:
          - ``"csv"``  — comma-separated values
          - ``"json"`` — JSON array (``orient="records"``)
          - ``"excel"`` — XLSX (requires ``openpyxl``)

        Args:
            result: A dict with at least a ``"rows"`` key (list of dicts),
                as returned by ``execute_database_query`` or ``get_database_metadata``.
            filename: Base filename (without extension).  When omitted, a
                timestamp-based name is generated.
            file_format: One of ``"csv"``, ``"json"``, or ``"excel"``.
                Defaults to ``"csv"``.

        Returns:
            ``{"file_path": ..., "file_url": ..., "row_count": ..., "file_format": ...}``
            on success, or ``{"error": "..."}`` on failure.
        """
        if self._output_dir is None:
            return {"error": "output_dir not configured"}

        import pandas as pd

        rows = result.get("rows", [])
        df = pd.DataFrame(rows if rows else [])

        # Generate filename if not provided
        if not filename:
            import time as _time
            filename = f"result_{int(_time.time())}"

        fmt = file_format.lower().strip()
        ext_map = {"csv": ".csv", "json": ".json", "excel": ".xlsx"}
        if fmt not in ext_map:
            return {"error": f"Unsupported file_format {file_format!r}. Use 'csv', 'json', or 'excel'."}

        ext = ext_map[fmt]
        out_path = self._output_dir / f"{filename}{ext}"
        try:
            self._output_dir.mkdir(parents=True, exist_ok=True)
            if fmt == "csv":
                df.to_csv(out_path, index=False)
            elif fmt == "json":
                df.to_json(out_path, orient="records", indent=2)
            elif fmt == "excel":
                df.to_excel(out_path, index=False)
        except Exception as exc:  # noqa: BLE001
            return {"error": f"Failed to write file: {exc}"}

        # Build optional static URL
        file_url: Optional[str] = None
        if self._static_dir:
            rel = os.path.relpath(str(out_path), self._static_dir)
            file_url = f"/static/{rel}"

        return {
            "file_path": str(out_path),
            "file_url": file_url,
            "row_count": len(df),
            "file_format": fmt,
        }
