---
type: Wiki Entity
title: DeltaTableSource
id: class:parrot.tools.dataset_manager.sources.deltatable.DeltaTableSource
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: DataSource for Delta Lake tables via asyncdb's delta driver.
relates_to:
- concept: class:parrot.tools.dataset_manager.sources.base.DataSource
  rel: extends
---

# DeltaTableSource

Defined in [`parrot.tools.dataset_manager.sources.deltatable`](../summaries/mod:parrot.tools.dataset_manager.sources.deltatable.md).

```python
class DeltaTableSource(DataSource)
```

DataSource for Delta Lake tables via asyncdb's delta driver.

Supports local paths, S3 (s3://), and GCS (gs://) via asyncdb's built-in
storage support. For S3 paths, credentials are resolved via AWSInterface
from parrot/interfaces/aws.py.

Args:
    path: Path to the Delta table. Can be a local filesystem path,
        an S3 URI (``s3://bucket/path``), or a GCS URI
        (``gs://bucket/path``).
    name: Dataset name/identifier for this source.
    table_name: DuckDB alias used for SQL queries (e.g. in
        ``SELECT * FROM {table_name} WHERE ...``). Defaults to the
        uppercased ``name``.
    mode: Write mode for creation operations: ``overwrite``, ``append``,
        ``error``, ``ignore``. Defaults to ``"error"``.
    credentials: Optional credentials dict for cloud storage access.
        For S3, AWSInterface is used automatically when this is None.

## Methods

- `def cache_key(self) -> str` — Stable Redis cache key for this Delta table source.
- `async def prefetch_schema(self) -> Dict[str, str]` — Retrieve column→type mapping from Delta table metadata.
- `async def prefetch_row_count(self) -> Optional[int]` — Estimate the row count for this Delta table.
- `async def fetch(self, **params) -> pd.DataFrame` — Query the Delta table and return a DataFrame.
- `def describe(self) -> str` — Return a human-readable description for the LLM guide.
- `async def create_from_parquet(delta_path: str, parquet_path: str, table_name: Optional[str]=None, mode: str='overwrite', credentials: Optional[Dict[str, Any]]=None) -> None` — Create a Delta table from a Parquet file.
