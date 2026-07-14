---
type: Wiki Summary
title: parrot.bots.database.toolkits.sql
id: mod:parrot.bots.database.toolkits.sql
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: SQLToolkit — common SQL operations with overridable dialect hooks.
relates_to:
- concept: class:parrot.bots.database.toolkits.sql.SQLToolkit
  rel: defines
- concept: mod:parrot.bots.database.cache
  rel: references
- concept: mod:parrot.bots.database.models
  rel: references
- concept: mod:parrot.bots.database.retries
  rel: references
- concept: mod:parrot.bots.database.toolkits.base
  rel: references
- concept: mod:parrot.security
  rel: references
---

# `parrot.bots.database.toolkits.sql`

SQLToolkit — common SQL operations with overridable dialect hooks.

Inherits ``DatabaseToolkit`` and implements schema search, query generation,
execution, explain, and validation for SQL databases.  Dialect differences
(PostgreSQL vs BigQuery vs MySQL) are handled via overridable ``_get_*``
hook methods.

All execution goes through asyncdb — the asyncpg-native path is the only
supported backend. Query builders emit ``$1, $2, …`` positional placeholders.

## Classes

- **`SQLToolkit(DatabaseToolkit)`** — Common SQL operations with overridable dialect hooks.
