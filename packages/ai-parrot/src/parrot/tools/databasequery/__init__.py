"""DatabaseToolkit — Public exports for the database tools package.

Provides a multi-tool database interface for AI agents with full driver parity
across PostgreSQL, MySQL, SQLite, BigQuery, MSSQL (with stored procedures),
Oracle, ClickHouse, DuckDB, MongoDB, Atlas, DocumentDB, InfluxDB, and
Elasticsearch/OpenSearch.

Example:
    >>> from parrot.tools.databasequery import DatabaseToolkit
    >>> toolkit = DatabaseToolkit()
    >>> agent = Agent(tools=toolkit.get_tools())

Part of FEAT-062 — DatabaseToolkit.
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
from parrot.tools.databasequery.toolkit import DatabaseToolkit

__all__ = [
    # Main toolkit entry point
    "DatabaseToolkit",
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
