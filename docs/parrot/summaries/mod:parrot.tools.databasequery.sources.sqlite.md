---
type: Wiki Summary
title: parrot.tools.databasequery.sources.sqlite
id: mod:parrot.tools.databasequery.sources.sqlite
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: SQLite database source for DatabaseToolkit.
relates_to:
- concept: class:parrot.tools.databasequery.sources.sqlite.SQLiteSource
  rel: defines
- concept: mod:parrot.interfaces.database
  rel: references
- concept: mod:parrot.tools.databasequery.base
  rel: references
- concept: mod:parrot.tools.databasequery.sources
  rel: references
---

# `parrot.tools.databasequery.sources.sqlite`

SQLite database source for DatabaseToolkit.

Implements ``AbstractDatabaseSource`` for SQLite using the asyncdb ``sqlite``
driver. Uses ``PRAGMA table_info()`` and ``sqlite_master`` for metadata discovery
(SQLite does not have information_schema).
Inherits SQL validation from the base class via ``sqlglot_dialect = "sqlite"``.

Part of FEAT-062 — DatabaseToolkit.

## Classes

- **`SQLiteSource(AbstractDatabaseSource)`** — SQLite database source.
