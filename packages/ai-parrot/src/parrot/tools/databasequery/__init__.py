"""parrot.tools.databasequery — Public exports for the database query tools package.

Provides a multi-tool database interface for AI agents with full driver parity
across PostgreSQL, MySQL, SQLite, BigQuery, MSSQL (with stored procedures),
Oracle, ClickHouse, DuckDB, MongoDB, Atlas, DocumentDB, InfluxDB, and
Elasticsearch/OpenSearch.

Example:
    >>> from parrot.tools.databasequery import DatabaseQueryToolkit
    >>> toolkit = DatabaseQueryToolkit()
    >>> agent = Agent(tools=toolkit.get_tools())

Part of FEAT-105 — databasetoolkit-clash.
"""
from __future__ import annotations

from parrot.tools.databasequery.base import (
    AbstractDatabaseSource,
    ColumnMeta,
    MetadataResult,
    QueryResult,
    RowResult,
    TableMeta,
    ValidationResult,
)
from parrot.tools.databasequery.toolkit import DatabaseQueryToolkit
from parrot.tools.databasequery.tool import DatabaseQueryTool

__all__ = [
    # Main toolkit entry point (FEAT-105 renamed class)
    "DatabaseQueryToolkit",
    # Legacy tool (moved from parrot_tools.databasequery)
    "DatabaseQueryTool",
    # Abstract base for custom sources
    "AbstractDatabaseSource",
    # Result types
    "ValidationResult",
    "ColumnMeta",
    "TableMeta",
    "MetadataResult",
    "QueryResult",
    "RowResult",
]
