---
type: Wiki Entity
title: AbstractDatabaseSource
id: class:parrot.tools.databasequery.base.AbstractDatabaseSource
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Abstract base class for all database source implementations.
---

# AbstractDatabaseSource

Defined in [`parrot.tools.databasequery.base`](../summaries/mod:parrot.tools.databasequery.base.md).

```python
class AbstractDatabaseSource(ABC)
```

Abstract base class for all database source implementations.

Each concrete subclass represents a specific database driver (e.g., PostgreSQL,
MongoDB, Elasticsearch) and provides driver-specific implementations of
metadata discovery, query validation, and query execution.

Class Attributes:
    driver: The canonical asyncdb driver name (e.g., ``'pg'``, ``'mongo'``).
    sqlglot_dialect: The sqlglot dialect for SQL validation, or ``None``
        for non-SQL databases.

## Methods

- `async def resolve_credentials(self, credentials: dict[str, Any] | None) -> dict[str, Any]` — Resolve credentials, using defaults if none provided.
- `async def get_default_credentials(self) -> dict[str, Any]` — Return default credentials for this database driver.
- `async def validate_query(self, query: str) -> ValidationResult` — Validate a query using sqlglot for the configured dialect.
- `async def test_connection(self, credentials: dict[str, Any]) -> bool` — Test database connectivity by executing a trivial query.
- `async def get_metadata(self, credentials: dict[str, Any], tables: list[str] | None=None) -> MetadataResult` — Discover database schema metadata.
- `async def query(self, credentials: dict[str, Any], sql: str, params: dict[str, Any] | None=None) -> QueryResult` — Execute a query and return all results.
- `async def query_row(self, credentials: dict[str, Any], sql: str, params: dict[str, Any] | None=None) -> RowResult` — Execute a query and return a single row.
- `async def close(self) -> None` — Release all cached AsyncDB pool instances.
