---
type: Wiki Entity
title: RecordsDataSource
id: class:parrot_loaders.extractors.records_source.RecordsDataSource
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Wrap an in-memory list[dict] as a data source.
relates_to:
- concept: class:parrot_loaders.extractors.base.ExtractDataSource
  rel: extends
---

# RecordsDataSource

Defined in [`parrot_loaders.extractors.records_source`](../summaries/mod:parrot_loaders.extractors.records_source.md).

```python
class RecordsDataSource(ExtractDataSource)
```

Wrap an in-memory list[dict] as a data source.

Useful for:
    - Unit testing (pass test data directly).
    - Programmatic ingestion (data already in memory).
    - Chaining with other extractors (transform then re-extract).

Args:
    name: Human-readable name for logging and reporting.
    records: The in-memory records to serve.
    config: Optional source-specific configuration.

## Methods

- `async def extract(self, fields: list[str] | None=None, filters: dict[str, Any] | None=None) -> ExtractionResult` — Return the in-memory records, optionally filtered/projected.
- `async def list_fields(self) -> list[str]` — Return keys from first record, or empty list.
