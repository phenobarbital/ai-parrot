---
type: Wiki Summary
title: parrot.tools.dataset_manager.sources.deltatable
id: mod:parrot.tools.dataset_manager.sources.deltatable
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: DeltaTableSource — DataSource subclass for Delta Lake tables.
relates_to:
- concept: class:parrot.tools.dataset_manager.sources.deltatable.DeltaTableSource
  rel: defines
- concept: mod:parrot._imports
  rel: references
- concept: mod:parrot.interfaces.aws
  rel: references
- concept: mod:parrot.tools.dataset_manager.sources.base
  rel: references
---

# `parrot.tools.dataset_manager.sources.deltatable`

DeltaTableSource — DataSource subclass for Delta Lake tables.

On registration, prefetch_schema() opens a connection via the asyncdb delta
driver and calls conn.schema() to retrieve column names and types from the
Delta table metadata without fetching any rows.

At fetch time, supports:
- DuckDB SQL queries (``sql`` param) via ``conn.query(sentence=sql, tablename=...)``
- Column selection (``columns`` param) via ``conn.to_df(columns=...)``
- Filter expressions (``filter`` param) via ``conn.query(sentence=filter_expr)``
- Full-table read (no params) via ``conn.to_df()``

Supports local paths, s3:// (with AWSInterface credential resolution), and gs://.
Row count estimation is available for LLM size warnings.

A static helper create_from_parquet() enables creating a new Delta table from
an existing Parquet file.

## Classes

- **`DeltaTableSource(DataSource)`** — DataSource for Delta Lake tables via asyncdb's delta driver.
