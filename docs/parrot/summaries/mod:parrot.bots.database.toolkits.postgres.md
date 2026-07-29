---
type: Wiki Summary
title: parrot.bots.database.toolkits.postgres
id: mod:parrot.bots.database.toolkits.postgres
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: PostgresToolkit — PostgreSQL-specific overrides of ``SQLToolkit``.
relates_to:
- concept: class:parrot.bots.database.toolkits.postgres.PostgresToolkit
  rel: defines
- concept: mod:parrot.bots.database.models
  rel: references
- concept: mod:parrot.bots.database.toolkits
  rel: references
- concept: mod:parrot.bots.database.toolkits._crud
  rel: references
- concept: mod:parrot.bots.database.toolkits.sql
  rel: references
- concept: mod:parrot.security
  rel: references
---

# `parrot.bots.database.toolkits.postgres`

PostgresToolkit — PostgreSQL-specific overrides of ``SQLToolkit``.

Provides PG-specific EXPLAIN format, ``pg_class``/``pg_namespace``
introspection, column comments via ``col_description()``,
``postgresql+asyncpg://`` DSN mapping, and full first-class CRUD tools:
``insert_row``, ``upsert_row``, ``update_row``, ``delete_row``,
``select_rows``.

Write tools are hidden from the LLM when ``read_only=True`` (the default)
by extending ``exclude_tools`` before ``AbstractToolkit._generate_tools()``
runs.

## Classes

- **`PostgresToolkit(SQLToolkit)`** — PostgreSQL-specific toolkit with first-class CRUD tools.
