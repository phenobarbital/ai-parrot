---
type: Wiki Summary
title: parrot.tools.databasequery.sources.mysql
id: mod:parrot.tools.databasequery.sources.mysql
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: MySQL database source for DatabaseToolkit.
relates_to:
- concept: class:parrot.tools.databasequery.sources.mysql.MySQLSource
  rel: defines
- concept: mod:parrot.interfaces.database
  rel: references
- concept: mod:parrot.tools.databasequery.base
  rel: references
- concept: mod:parrot.tools.databasequery.sources
  rel: references
---

# `parrot.tools.databasequery.sources.mysql`

MySQL database source for DatabaseToolkit.

Implements ``AbstractDatabaseSource`` for MySQL/MariaDB using the asyncdb ``mysql``
driver. Queries ``information_schema`` for metadata discovery.
Inherits SQL validation from the base class via ``sqlglot_dialect = "mysql"``.

Part of FEAT-062 — DatabaseToolkit.

## Classes

- **`MySQLSource(AbstractDatabaseSource)`** — MySQL/MariaDB database source.
