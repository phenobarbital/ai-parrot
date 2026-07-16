---
type: Wiki Summary
title: parrot.tools.databasequery.sources.bigquery
id: mod:parrot.tools.databasequery.sources.bigquery
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: BigQuery database source for DatabaseToolkit.
relates_to:
- concept: class:parrot.tools.databasequery.sources.bigquery.BigQuerySource
  rel: defines
- concept: mod:parrot.interfaces.database
  rel: references
- concept: mod:parrot.tools.databasequery.base
  rel: references
- concept: mod:parrot.tools.databasequery.sources
  rel: references
---

# `parrot.tools.databasequery.sources.bigquery`

BigQuery database source for DatabaseToolkit.

Implements ``AbstractDatabaseSource`` for Google BigQuery using the asyncdb
``bigquery`` driver. Queries ``INFORMATION_SCHEMA.COLUMNS`` for metadata.
Inherits SQL validation from the base class via ``sqlglot_dialect = "bigquery"``.

Part of FEAT-062 — DatabaseToolkit.

## Classes

- **`BigQuerySource(AbstractDatabaseSource)`** — Google BigQuery database source.
