---
type: Wiki Entity
title: TableSource
id: class:parrot.tools.dataset_manager.sources.table.TableSource
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: DataSource for a database table with INFORMATION_SCHEMA schema prefetch.
relates_to:
- concept: class:parrot.tools.dataset_manager.sources.base.DataSource
  rel: extends
---

# TableSource

Defined in [`parrot.tools.dataset_manager.sources.table`](../summaries/mod:parrot.tools.dataset_manager.sources.table.md).

```python
class TableSource(DataSource)
```

DataSource for a database table with INFORMATION_SCHEMA schema prefetch.

Registers a table reference (e.g. "troc.finance_visits_details") for a given
AsyncDB driver. On registration (via add_table_source), prefetch_schema() is
called to retrieve column names and data types from INFORMATION_SCHEMA — no
rows are fetched.

The LLM can then build a SQL query using the schema and call fetch(sql=...) to
materialize actual data. The SQL is validated to reference self.table before
execution.

Args:
    table: Fully-qualified table name, e.g. "public.orders" or
           "troc.finance_visits_details". For BigQuery use "dataset.table".
    driver: AsyncDB driver name, e.g. "pg", "bigquery", "mysql".
    dsn: Optional DSN string. If None, credentials are resolved from navconfig.
    credentials: Optional credentials dict. Takes priority over navconfig defaults
                 when dsn is also None.
    strict_schema: If True (default), prefetch_schema() failures raise and
                   registration fails. If False, failures log a warning and
                   register with empty schema.
    permanent_filter: Optional dict of equality conditions that are always
                      injected as a WHERE clause into every fetch() SQL.
                      Scalar values produce ``col = 'val'``; list/tuple values
                      produce ``col IN ('a', 'b')``. Column names are validated
                      against ``_SAFE_IDENTIFIER_RE``; values are safely escaped.
    allowed_columns: Optional list of column names to restrict access. When set,
                     only these columns appear in the schema, describe() output,
                     guide, and metadata. SQL queries referencing other columns
                     (or SELECT *) are rejected at fetch() time.

## Methods

- `def schema_name(self) -> Optional[str]` — Return the schema/dataset prefix, or None if unqualified.
- `def short_table_name(self) -> str` — Return the unqualified table name (part after the last dot).
- `def allowed_columns(self) -> Optional[List[str]]` — Return the allowed columns list, or None if unrestricted.
- `async def prefetch_schema(self) -> Dict[str, str]` — Fetch column names and types from INFORMATION_SCHEMA.
- `async def prefetch_row_count(self) -> Optional[int]` — Estimate the row count for this table via COUNT(*).
- `async def fetch(self, sql: Optional[str]=None, **params) -> pd.DataFrame` — Execute a SQL query against the registered table.
- `def describe(self) -> str` — Return a human-readable description for the LLM guide.
- `def cache_key(self) -> str` — Stable Redis cache key for this table source.
