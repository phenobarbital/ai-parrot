---
type: Wiki Summary
title: parrot.tools.databasequery.sources.duckdb
id: mod:parrot.tools.databasequery.sources.duckdb
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: DuckDB database source for DatabaseToolkit.
relates_to:
- concept: class:parrot.tools.databasequery.sources.duckdb.DuckDBSource
  rel: defines
- concept: mod:parrot.tools.databasequery.base
  rel: references
- concept: mod:parrot.tools.databasequery.sources
  rel: references
---

# `parrot.tools.databasequery.sources.duckdb`

DuckDB database source for DatabaseToolkit.

Implements ``AbstractDatabaseSource`` for DuckDB embedded analytical database
using the asyncdb ``duckdb`` driver. Queries ``information_schema.columns``
for metadata discovery. Supports both in-process (file) and in-memory modes.
Inherits SQL validation from the base class via ``sqlglot_dialect = "duckdb"``.

Part of FEAT-062 — DatabaseToolkit.

## Classes

- **`DuckDBSource(AbstractDatabaseSource)`** — DuckDB embedded analytical database source.
