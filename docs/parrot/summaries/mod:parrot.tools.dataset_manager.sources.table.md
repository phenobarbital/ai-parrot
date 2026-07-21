---
type: Wiki Summary
title: parrot.tools.dataset_manager.sources.table
id: mod:parrot.tools.dataset_manager.sources.table
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: TableSource — schema-prefetch DataSource for database tables.
relates_to:
- concept: class:parrot.tools.dataset_manager.sources.table.TableSource
  rel: defines
- concept: func:parrot.tools.dataset_manager.sources.table.dialect_hint
  rel: defines
- concept: mod:parrot._imports
  rel: references
- concept: mod:parrot.tools.dataset_manager.sources.base
  rel: references
---

# `parrot.tools.dataset_manager.sources.table`

TableSource — schema-prefetch DataSource for database tables.

On registration, prefetch_schema() runs a driver-aware INFORMATION_SCHEMA query
to retrieve column names and types without materializing any rows. The LLM
receives full schema awareness before any data is fetched.

At fetch time, the LLM provides a SQL statement which is validated to reference
the registered table before execution.

## Classes

- **`TableSource(DataSource)`** — DataSource for a database table with INFORMATION_SCHEMA schema prefetch.

## Functions

- `def dialect_hint(driver: str) -> str` — Return concise SQL-dialect guidance for ``driver`` (empty if unknown).
