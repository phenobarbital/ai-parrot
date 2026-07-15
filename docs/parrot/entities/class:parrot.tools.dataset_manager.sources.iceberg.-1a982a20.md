---
type: Wiki Entity
title: IcebergSource
id: class:parrot.tools.dataset_manager.sources.iceberg.IcebergSource
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: DataSource for Apache Iceberg tables via asyncdb's iceberg driver.
relates_to:
- concept: class:parrot.tools.dataset_manager.sources.base.DataSource
  rel: extends
---

# IcebergSource

Defined in [`parrot.tools.dataset_manager.sources.iceberg`](../summaries/mod:parrot.tools.dataset_manager.sources.iceberg.md).

```python
class IcebergSource(DataSource)
```

DataSource for Apache Iceberg tables via asyncdb's iceberg driver.

On registration (via DatasetManager.add_iceberg_source), prefetch_schema()
loads the table metadata to retrieve column names and types without
fetching any rows.

At fetch time, the LLM can provide a DuckDB SQL query (sql=) or omit it
to read the full table.

Args:
    table_id: Fully-qualified Iceberg table identifier, e.g. "demo.cities".
    name: Dataset name/identifier for this source.
    catalog_params: asyncdb iceberg driver connection params
        (uri, warehouse, catalog type, etc.). Always required.
    factory: Output factory for asyncdb queries (default "pandas").
    credentials: Optional credentials dict (passed to asyncdb driver).
    dsn: Optional DSN string (not typically used for Iceberg).

## Methods

- `async def prefetch_schema(self) -> Dict[str, str]` — Load Iceberg table metadata and retrieve column→type mapping.
- `async def prefetch_row_count(self) -> Optional[int]` — Estimate the row count for this Iceberg table.
- `async def fetch(self, **params) -> pd.DataFrame` — Execute a query against the Iceberg table and return a DataFrame.
- `def describe(self) -> str` — Return a human-readable description for the LLM guide.
- `def cache_key(self) -> str` — Stable Redis cache key for this Iceberg source.
- `async def create_table_from_df(driver: Any, df: pd.DataFrame, table_id: str, namespace: str='default', mode: str='append') -> None` — Create a new Iceberg table from a DataFrame and write the data.
