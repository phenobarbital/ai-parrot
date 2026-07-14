---
type: Wiki Summary
title: parrot.tools.dataset_manager.sources.iceberg
id: mod:parrot.tools.dataset_manager.sources.iceberg
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: IcebergSource — DataSource subclass for Apache Iceberg tables.
relates_to:
- concept: class:parrot.tools.dataset_manager.sources.iceberg.IcebergSource
  rel: defines
- concept: mod:parrot._imports
  rel: references
- concept: mod:parrot.tools.dataset_manager.sources.base
  rel: references
---

# `parrot.tools.dataset_manager.sources.iceberg`

IcebergSource — DataSource subclass for Apache Iceberg tables.

On registration, prefetch_schema() loads the table metadata via the asyncdb
iceberg driver and retrieves column names and types without fetching any rows.
Row count estimation is also available for LLM size warnings.

At fetch time, supports DuckDB SQL queries (via driver.query()) or full-table
reads (via driver.to_df()). A static helper create_table_from_df() enables
the register-as-dataset workflow: write a DataFrame to a new Iceberg table,
then register it as a source.

## Classes

- **`IcebergSource(DataSource)`** — DataSource for Apache Iceberg tables via asyncdb's iceberg driver.
