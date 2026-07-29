---
type: Wiki Summary
title: parrot.bots.database.toolkits._crud
id: mod:parrot.bots.database.toolkits._crud
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: Pure-function CRUD helpers for PostgresToolkit (FEAT-106).
relates_to:
- concept: mod:parrot.bots.database.models
  rel: references
- concept: mod:parrot.bots.database.toolkits.base
  rel: references
---

# `parrot.bots.database.toolkits._crud`

Pure-function CRUD helpers for PostgresToolkit (FEAT-106).

This module provides:

* :data:`ColumnsKey` — hashable cache-key type for ``_build_pydantic_model``.
* :func:`_columns_key_from_metadata` — converts ``TableMetadata.columns``
  into a ``ColumnsKey`` suitable for use as an ``lru_cache`` argument.
* :func:`_build_pydantic_model` — ``lru_cache``-backed dynamic
  ``pydantic.BaseModel`` builder.  ``extra="forbid"`` ensures unknown
  fields surface as ``ValidationError`` rather than silently ignored.
* Five SQL template builders (pure functions, no I/O):
  - :func:`_build_insert_sql`
  - :func:`_build_upsert_sql`
  - :func:`_build_update_sql`
  - :func:`_build_delete_sql`
  - :func:`_build_select_sql`

All builders return ``(sql: str, param_order: list[str])`` where
``param_order`` matches the ``$N`` positional placeholder order used by
asyncpg.
