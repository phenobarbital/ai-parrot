---
type: Wiki Summary
title: parrot.tools.databasequery.base
id: mod:parrot.tools.databasequery.base
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: DatabaseToolkit — Result Types & AbstractDatabaseSource.
relates_to:
- concept: class:parrot.tools.databasequery.base.AbstractDatabaseSource
  rel: defines
- concept: class:parrot.tools.databasequery.base.ColumnMeta
  rel: defines
- concept: class:parrot.tools.databasequery.base.MetadataResult
  rel: defines
- concept: class:parrot.tools.databasequery.base.QueryResult
  rel: defines
- concept: class:parrot.tools.databasequery.base.RowResult
  rel: defines
- concept: class:parrot.tools.databasequery.base.TableMeta
  rel: defines
- concept: class:parrot.tools.databasequery.base.ValidationResult
  rel: defines
- concept: func:parrot.tools.databasequery.base.add_row_limit
  rel: defines
---

# `parrot.tools.databasequery.base`

DatabaseToolkit — Result Types & AbstractDatabaseSource.

Defines all Pydantic v2 result models and the AbstractDatabaseSource ABC
that every database source must implement.

Part of FEAT-062 — DatabaseToolkit.
Part of FEAT-136 — database-toolkit-parity (add_row_limit, test_connection).

## Classes

- **`ValidationResult(BaseModel)`** — Result of a query validation operation.
- **`ColumnMeta(BaseModel)`** — Metadata for a single database column or field.
- **`TableMeta(BaseModel)`** — Metadata for a single database table, collection, or measurement.
- **`MetadataResult(BaseModel)`** — Result of a metadata discovery operation.
- **`QueryResult(BaseModel)`** — Result of a multi-row query execution.
- **`RowResult(BaseModel)`** — Result of a single-row fetch operation.
- **`AbstractDatabaseSource(ABC)`** — Abstract base class for all database source implementations.

## Functions

- `def add_row_limit(query: str, max_rows: int, driver: str) -> str` — Inject a dialect-specific row limit into a query string.
