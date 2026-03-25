"""DatabaseToolkit — Tool Argument Schemas, Tool Implementations, and Toolkit.

This module provides:
- Pydantic v2 argument schemas for all four database tools
- Four ``AbstractTool`` subclasses exposing database operations to LLMs
- ``DatabaseToolkit`` class that ties everything together

The toolkit exposes a three-step agentic flow for LLMs:
  1. ``get_database_metadata`` — discover schema first
  2. ``validate_database_query`` — validate your query before running it
  3. ``execute_database_query`` or ``fetch_database_row`` — execute after validation

Part of FEAT-062 — DatabaseToolkit.
"""
from __future__ import annotations

import contextlib
import logging
from typing import Any

from pydantic import Field

from parrot.tools.abstract import AbstractTool, AbstractToolArgsSchema, ToolResult
from parrot.tools.database.base import (
    AbstractDatabaseSource,
    MetadataResult,
    QueryResult,
    RowResult,
    ValidationResult,
)
from parrot.tools.database.sources import get_source_class, normalize_driver


# ---------------------------------------------------------------------------
# Argument Schemas
# ---------------------------------------------------------------------------


class DatabaseBaseArgs(AbstractToolArgsSchema):
    """Base arguments shared by all database tools.

    Attributes:
        driver: The database driver to use.
        credentials: Optional connection credentials.
    """

    driver: str = Field(
        description=(
            "Database driver to use. Supported canonical names: "
            "'pg' (PostgreSQL), 'mysql' (MySQL/MariaDB), 'sqlite', "
            "'bigquery', 'mssql' (SQL Server), 'oracle', 'clickhouse', 'duckdb', "
            "'mongo' (MongoDB), 'atlas' (MongoDB Atlas), 'documentdb' (AWS DocumentDB), "
            "'influx' (InfluxDB — Flux queries), "
            "'elastic' (Elasticsearch/OpenSearch — JSON DSL). "
            "Aliases accepted: 'postgresql' → 'pg', 'mariadb' → 'mysql', "
            "'bq' → 'bigquery', 'sqlserver' → 'mssql', 'influxdb' → 'influx', "
            "'mongodb' → 'mongo', 'elasticsearch'/'opensearch' → 'elastic'."
        )
    )
    credentials: dict[str, Any] | None = Field(
        default=None,
        description=(
            "Optional connection credentials. If omitted, the source's default "
            "credentials will be used (configured via environment/navconfig). "
            "For SQL databases: {'dsn': 'postgresql://...', 'params': {...}}. "
            "For MongoDB: {'dsn': 'mongodb://...', 'database': 'mydb'}. "
            "For InfluxDB: {'url': '...', 'token': '...', 'org': '...'}. "
            "For Elasticsearch: {'hosts': [...], 'http_auth': ['user', 'pass']}."
        ),
    )


class GetMetadataArgs(DatabaseBaseArgs):
    """Arguments for the database metadata discovery tool.

    Attributes:
        tables: Optional list of specific tables/collections to inspect.
    """

    tables: list[str] | None = Field(
        default=None,
        description=(
            "Optional list of specific table names, collection names, bucket names, "
            "or index names to inspect. If omitted, metadata for all accessible "
            "objects is returned."
        ),
    )


class ValidateQueryArgs(DatabaseBaseArgs):
    """Arguments for the query validation tool.

    Attributes:
        query: The query string to validate.
    """

    query: str = Field(
        description=(
            "The query to validate. For SQL databases: a SQL SELECT statement. "
            "For MSSQL: also accepts EXEC/EXECUTE for stored procedures. "
            "For MongoDB: a JSON filter document or aggregation pipeline array. "
            "For InfluxDB: a Flux query string starting with from(bucket:...). "
            "For Elasticsearch: a JSON DSL query body object."
        )
    )


class ExecuteQueryArgs(DatabaseBaseArgs):
    """Arguments for the multi-row query execution tool.

    Attributes:
        query: The query string to execute.
        params: Optional query parameters.
    """

    query: str = Field(
        description=(
            "The validated query to execute. Must have been validated first with "
            "validate_database_query. For SQL: a SELECT statement. "
            "For MongoDB: a JSON filter or pipeline. For InfluxDB: a Flux query. "
            "For Elasticsearch: a JSON DSL query body."
        )
    )
    params: dict[str, Any] | None = Field(
        default=None,
        description=(
            "Optional query parameters for parameterized SQL queries "
            "(e.g., {'user_id': 42}). Not used for NoSQL queries."
        ),
    )


class FetchRowArgs(DatabaseBaseArgs):
    """Arguments for the single-row fetch tool.

    Attributes:
        query: The query string to execute.
        params: Optional query parameters.
    """

    query: str = Field(
        description=(
            "The query to execute, expecting a single result row/document. "
            "For SQL: a SELECT statement (LIMIT 1 is applied automatically). "
            "For MongoDB: a JSON filter document."
        )
    )
    params: dict[str, Any] | None = Field(
        default=None,
        description="Optional query parameters for parameterized SQL queries.",
    )


# ---------------------------------------------------------------------------
# Tool Implementations
# ---------------------------------------------------------------------------


class GetDatabaseMetadataTool(AbstractTool):
    """Discover a database's schema: tables, columns, and their types.

    Call this tool BEFORE writing any query to understand what tables,
    collections, indices, or measurements exist and what fields/columns
    they contain. This is the first step in the three-step database flow.
    """

    name = "get_database_metadata"
    description = (
        "Discover the schema of a database: list tables, collections, indices, "
        "or measurements and their column/field definitions with data types. "
        "ALWAYS call this tool FIRST, before writing any query, to understand "
        "the available data structures."
    )
    args_schema = GetMetadataArgs

    def __init__(self, toolkit_ref: "DatabaseToolkit") -> None:
        """Initialize with a reference to the parent toolkit.

        Args:
            toolkit_ref: The DatabaseToolkit instance that owns this tool.
        """
        super().__init__()
        self._toolkit = toolkit_ref

    async def _execute(self, **kwargs: Any) -> ToolResult:
        """Execute metadata discovery.

        Args:
            **kwargs: Validated GetMetadataArgs fields.

        Returns:
            ToolResult containing MetadataResult.model_dump() on success.
        """
        try:
            driver = normalize_driver(kwargs["driver"])
            source = self._toolkit.get_source(driver)
            creds = await source.resolve_credentials(kwargs.get("credentials"))
            result: MetadataResult = await source.get_metadata(creds, kwargs.get("tables"))
            return ToolResult(success=True, result=result.model_dump())
        except Exception as exc:
            self.logger.error("get_database_metadata error: %s", exc)
            return ToolResult(success=False, result=None, error=str(exc))


class ValidateDatabaseQueryTool(AbstractTool):
    """Validate a database query before executing it.

    Call this tool AFTER discovering the schema and BEFORE executing any
    query. For SQL databases, validates syntax using sqlglot. For MongoDB,
    validates JSON format. For InfluxDB, validates Flux syntax. For
    Elasticsearch, validates JSON DSL structure.

    This is the second step in the three-step database flow.
    """

    name = "validate_database_query"
    description = (
        "Validate a database query for syntax and structural correctness "
        "without executing it. Call this tool AFTER discovering schema "
        "(get_database_metadata) and BEFORE executing (execute_database_query "
        "or fetch_database_row). Returns valid=True if the query is safe to run."
    )
    args_schema = ValidateQueryArgs

    def __init__(self, toolkit_ref: "DatabaseToolkit") -> None:
        """Initialize with a reference to the parent toolkit.

        Args:
            toolkit_ref: The DatabaseToolkit instance that owns this tool.
        """
        super().__init__()
        self._toolkit = toolkit_ref

    async def _execute(self, **kwargs: Any) -> ToolResult:
        """Execute query validation.

        Args:
            **kwargs: Validated ValidateQueryArgs fields.

        Returns:
            ToolResult containing ValidationResult.model_dump() on success.
        """
        try:
            driver = normalize_driver(kwargs["driver"])
            source = self._toolkit.get_source(driver)
            result: ValidationResult = await source.validate_query(kwargs["query"])
            return ToolResult(success=True, result=result.model_dump())
        except Exception as exc:
            self.logger.error("validate_database_query error: %s", exc)
            return ToolResult(success=False, result=None, error=str(exc))


class ExecuteDatabaseQueryTool(AbstractTool):
    """Execute a database query and return all matching rows/documents.

    Call this tool AFTER validating the query with validate_database_query.
    Returns all rows for SQL queries, all matching documents for MongoDB,
    all records for InfluxDB, all hits for Elasticsearch.

    This is the third step in the three-step database flow.
    """

    name = "execute_database_query"
    description = (
        "Execute a database query and return all matching rows, documents, "
        "or records. Call this tool ONLY AFTER validate_database_query returns "
        "valid=True. For large result sets, add LIMIT/size to your query. "
        "Returns row data with column names and execution time."
    )
    args_schema = ExecuteQueryArgs

    def __init__(self, toolkit_ref: "DatabaseToolkit") -> None:
        """Initialize with a reference to the parent toolkit.

        Args:
            toolkit_ref: The DatabaseToolkit instance that owns this tool.
        """
        super().__init__()
        self._toolkit = toolkit_ref

    async def _execute(self, **kwargs: Any) -> ToolResult:
        """Execute the query and return all results.

        Args:
            **kwargs: Validated ExecuteQueryArgs fields.

        Returns:
            ToolResult containing QueryResult.model_dump() on success.
        """
        try:
            driver = normalize_driver(kwargs["driver"])
            source = self._toolkit.get_source(driver)
            creds = await source.resolve_credentials(kwargs.get("credentials"))
            result: QueryResult = await source.query(
                creds, kwargs["query"], kwargs.get("params")
            )
            return ToolResult(success=True, result=result.model_dump())
        except Exception as exc:
            self.logger.error("execute_database_query error: %s", exc)
            return ToolResult(success=False, result=None, error=str(exc))


class FetchDatabaseRowTool(AbstractTool):
    """Execute a database query and return a single row or document.

    Use this tool when you need exactly one record from the database —
    for example, to look up a specific user by ID, fetch a configuration
    value, or retrieve the most recent record. Returns found=False if
    no matching record exists.
    """

    name = "fetch_database_row"
    description = (
        "Execute a database query and return a single row or document. "
        "Use when you need exactly one record (e.g., lookup by primary key, "
        "latest record). Returns found=True with the row data, or "
        "found=False if no record matches. More efficient than "
        "execute_database_query for single-record lookups."
    )
    args_schema = FetchRowArgs

    def __init__(self, toolkit_ref: "DatabaseToolkit") -> None:
        """Initialize with a reference to the parent toolkit.

        Args:
            toolkit_ref: The DatabaseToolkit instance that owns this tool.
        """
        super().__init__()
        self._toolkit = toolkit_ref

    async def _execute(self, **kwargs: Any) -> ToolResult:
        """Execute the query and return a single row.

        Args:
            **kwargs: Validated FetchRowArgs fields.

        Returns:
            ToolResult containing RowResult.model_dump() on success.
        """
        try:
            driver = normalize_driver(kwargs["driver"])
            source = self._toolkit.get_source(driver)
            creds = await source.resolve_credentials(kwargs.get("credentials"))
            result: RowResult = await source.query_row(
                creds, kwargs["query"], kwargs.get("params")
            )
            return ToolResult(success=True, result=result.model_dump())
        except Exception as exc:
            self.logger.error("fetch_database_row error: %s", exc)
            return ToolResult(success=False, result=None, error=str(exc))


# ---------------------------------------------------------------------------
# DatabaseToolkit
# ---------------------------------------------------------------------------


class DatabaseToolkit:
    """Multi-database toolkit providing four focused tools for LLM agents.

    Exposes four ``AbstractTool`` instances that guide agents through the
    three-step database interaction flow:
      1. **get_database_metadata** — discover schema before writing queries
      2. **validate_database_query** — check syntax before execution
      3. **execute_database_query** — run validated multi-row queries
      4. **fetch_database_row** — run validated single-row lookups

    Supports all major database systems via a pluggable source registry:
    PostgreSQL, MySQL, SQLite, BigQuery, MSSQL, Oracle, ClickHouse, DuckDB,
    MongoDB, Atlas, DocumentDB, InfluxDB, and Elasticsearch/OpenSearch.

    Example:
        >>> toolkit = DatabaseToolkit()
        >>> agent = Agent(tools=toolkit.get_tools())
    """

    def __init__(self) -> None:
        """Initialize the toolkit with four database tools and an empty source cache."""
        self.logger = logging.getLogger("Parrot.Toolkits.Database")
        self._source_cache: dict[str, AbstractDatabaseSource] = {}
        self._tools: list[AbstractTool] = []
        self._initialize_tools()

    def _initialize_tools(self) -> None:
        """Create the four tool instances with references to this toolkit."""
        self._tools = [
            GetDatabaseMetadataTool(toolkit_ref=self),
            ValidateDatabaseQueryTool(toolkit_ref=self),
            ExecuteDatabaseQueryTool(toolkit_ref=self),
            FetchDatabaseRowTool(toolkit_ref=self),
        ]

    def get_source(self, driver: str) -> AbstractDatabaseSource:
        """Get or create a cached database source instance.

        Source instances are cached per canonical driver name to avoid
        repeated instantiation within a single toolkit lifetime.

        Args:
            driver: Driver name or alias (normalized automatically).

        Returns:
            Cached or newly created ``AbstractDatabaseSource`` instance.

        Raises:
            ValueError: If no source is registered for the driver.
        """
        canonical = normalize_driver(driver)
        if canonical not in self._source_cache:
            source_cls = get_source_class(canonical)
            self._source_cache[canonical] = source_cls()
            self.logger.debug("Instantiated source for driver '%s'", canonical)
        return self._source_cache[canonical]

    def get_tools(self) -> list[AbstractTool]:
        """Return all four database tools.

        Returns:
            List of the four ``AbstractTool`` instances:
            GetDatabaseMetadataTool, ValidateDatabaseQueryTool,
            ExecuteDatabaseQueryTool, FetchDatabaseRowTool.
        """
        return self._tools

    def get_tool_by_name(self, name: str) -> AbstractTool | None:
        """Look up a tool by its name.

        Args:
            name: Tool name (e.g., ``"get_database_metadata"``).

        Returns:
            The matching tool, or None if not found.
        """
        return next((t for t in self._tools if t.name == name), None)

    async def cleanup(self) -> None:
        """Release resources and clear the source instance cache.

        Should be called when the toolkit is no longer needed to allow
        garbage collection of any source-level resources.
        """
        for tool in self._tools:
            with contextlib.suppress(Exception):
                if hasattr(tool, "cleanup"):
                    await tool.cleanup()
        self._source_cache.clear()
        self.logger.debug("DatabaseToolkit cleanup complete")
