---
type: Wiki Entity
title: MongoSource
id: class:parrot.tools.databasequery.sources.mongodb.MongoSource
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: MongoDB database source.
relates_to:
- concept: class:parrot.tools.databasequery.base.AbstractDatabaseSource
  rel: extends
---

# MongoSource

Defined in [`parrot.tools.databasequery.sources.mongodb`](../summaries/mod:parrot.tools.databasequery.sources.mongodb.md).

```python
class MongoSource(AbstractDatabaseSource)
```

MongoDB database source.

Uses the asyncdb ``mongo`` driver with JSON-based query validation.
Supports both filter-only queries and command-style queries.

## Methods

- `async def get_default_credentials(self) -> dict[str, Any]` — Return default MongoDB credentials from environment variables.
- `async def validate_query(self, query: str) -> ValidationResult` — Validate a MongoDB query string (JSON format).
- `async def test_connection(self, credentials: dict[str, Any]) -> bool` — Test MongoDB connectivity using the ``ping`` command.
- `async def get_metadata(self, credentials: dict[str, Any], tables: list[str] | None=None) -> MetadataResult` — Discover MongoDB schema: collections and inferred field types.
- `async def query(self, credentials: dict[str, Any], sql: str, params: dict[str, Any] | None=None) -> QueryResult` — Execute a MongoDB query (JSON filter or command).
- `async def query_row(self, credentials: dict[str, Any], sql: str, params: dict[str, Any] | None=None) -> RowResult` — Execute a MongoDB query and return a single document.
