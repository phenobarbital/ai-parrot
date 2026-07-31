---
type: Wiki Summary
title: parrot.bots.database.toolkits.bigquery
id: mod:parrot.bots.database.toolkits.bigquery
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: BigQueryToolkit — BigQuery-specific overrides of ``SQLToolkit``.
relates_to:
- concept: class:parrot.bots.database.toolkits.bigquery.BigQueryToolkit
  rel: defines
- concept: mod:parrot.bots.database.toolkits.sql
  rel: references
---

# `parrot.bots.database.toolkits.bigquery`

BigQueryToolkit — BigQuery-specific overrides of ``SQLToolkit``.

Provides BigQuery-specific schema introspection via
``INFORMATION_SCHEMA.TABLES``/``COLUMNS``, dry-run cost estimation for
EXPLAIN, and support for project/dataset-based DSNs.

BigQuery uses the asyncdb ``bigquery`` driver natively. No SQLAlchemy path.
Parameter style: values are safely inlined into queries using Python
f-strings with SQL-escaped values; builders return ``(sql, ())`` (empty
tuple) since BigQuery's asyncdb driver does not support positional ``$N``
parameters via ``conn.fetch()``.

## Classes

- **`BigQueryToolkit(SQLToolkit)`** — BigQuery-specific toolkit.
