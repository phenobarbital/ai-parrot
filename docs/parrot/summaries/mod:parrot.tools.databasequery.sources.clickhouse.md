---
type: Wiki Summary
title: parrot.tools.databasequery.sources.clickhouse
id: mod:parrot.tools.databasequery.sources.clickhouse
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: ClickHouse database source for DatabaseToolkit.
relates_to:
- concept: class:parrot.tools.databasequery.sources.clickhouse.ClickHouseSource
  rel: defines
- concept: mod:parrot.interfaces.database
  rel: references
- concept: mod:parrot.tools.databasequery.base
  rel: references
- concept: mod:parrot.tools.databasequery.sources
  rel: references
---

# `parrot.tools.databasequery.sources.clickhouse`

ClickHouse database source for DatabaseToolkit.

Implements ``AbstractDatabaseSource`` for ClickHouse OLAP database using the
asyncdb ``clickhouse`` driver. Queries ``system.columns`` for metadata discovery.
Inherits SQL validation from the base class via ``sqlglot_dialect = "clickhouse"``.

Part of FEAT-062 — DatabaseToolkit.

## Classes

- **`ClickHouseSource(AbstractDatabaseSource)`** — ClickHouse OLAP database source.
