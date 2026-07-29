---
type: Wiki Summary
title: parrot.tools.databasequery.sources.oracle
id: mod:parrot.tools.databasequery.sources.oracle
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: Oracle database source for DatabaseToolkit.
relates_to:
- concept: class:parrot.tools.databasequery.sources.oracle.OracleSource
  rel: defines
- concept: mod:parrot.interfaces.database
  rel: references
- concept: mod:parrot.tools.databasequery.base
  rel: references
- concept: mod:parrot.tools.databasequery.sources
  rel: references
---

# `parrot.tools.databasequery.sources.oracle`

Oracle database source for DatabaseToolkit.

Implements ``AbstractDatabaseSource`` for Oracle Database using the asyncdb
``oracle`` driver. Queries ``ALL_TAB_COLUMNS`` for metadata discovery.
Inherits SQL validation from the base class via ``sqlglot_dialect = "oracle"``.

Part of FEAT-062 — DatabaseToolkit.

## Classes

- **`OracleSource(AbstractDatabaseSource)`** — Oracle Database source.
