---
type: Wiki Summary
title: parrot.tools.dataset_manager.sources.sql
id: mod:parrot.tools.dataset_manager.sources.sql
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: SQLQuerySource — user-provided SQL with {param} interpolation.
relates_to:
- concept: class:parrot.tools.dataset_manager.sources.sql.SQLQuerySource
  rel: defines
- concept: mod:parrot._imports
  rel: references
- concept: mod:parrot.interfaces.database
  rel: references
- concept: mod:parrot.tools.dataset_manager.sources.base
  rel: references
- concept: mod:parrot.tools.dataset_manager.sources.table
  rel: references
---

# `parrot.tools.dataset_manager.sources.sql`

SQLQuerySource — user-provided SQL with {param} interpolation.

Executes an arbitrary SQL template against any AsyncDB-supported driver.
All {param} placeholders are validated and safely escaped at fetch() time.

## Classes

- **`SQLQuerySource(DataSource)`** — DataSource backed by a user-provided SQL template with {param} interpolation.
