---
type: Wiki Summary
title: parrot.tools.databasequery.sources.postgres
id: mod:parrot.tools.databasequery.sources.postgres
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: PostgreSQL database source for DatabaseToolkit.
relates_to:
- concept: class:parrot.tools.databasequery.sources.postgres.PostgresSource
  rel: defines
- concept: mod:parrot.interfaces.database
  rel: references
- concept: mod:parrot.tools.databasequery.base
  rel: references
- concept: mod:parrot.tools.databasequery.sources
  rel: references
---

# `parrot.tools.databasequery.sources.postgres`

PostgreSQL database source for DatabaseToolkit.

Implements ``AbstractDatabaseSource`` for PostgreSQL using the asyncdb ``pg`` driver.
Queries ``information_schema`` for metadata discovery.
Inherits SQL validation from the base class via ``sqlglot_dialect = "postgres"``.

Part of FEAT-062 — DatabaseToolkit.

## Classes

- **`PostgresSource(AbstractDatabaseSource)`** — PostgreSQL database source.
