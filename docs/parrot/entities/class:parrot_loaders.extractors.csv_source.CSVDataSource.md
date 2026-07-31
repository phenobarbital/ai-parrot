---
type: Wiki Entity
title: CSVDataSource
id: class:parrot_loaders.extractors.csv_source.CSVDataSource
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Extract structured records from CSV files.
relates_to:
- concept: class:parrot_loaders.extractors.base.ExtractDataSource
  rel: extends
---

# CSVDataSource

Defined in [`parrot_loaders.extractors.csv_source`](../summaries/mod:parrot_loaders.extractors.csv_source.md).

```python
class CSVDataSource(ExtractDataSource)
```

Extract structured records from CSV files.

Config:
    path: str — Path to the CSV file.
    delimiter: str — Column delimiter (default: ',').
    encoding: str — File encoding (default: 'utf-8').
    skip_rows: int — Number of initial rows to skip (default: 0).

Args:
    name: Human-readable name for logging and reporting.
    config: Source-specific configuration.

## Methods

- `async def extract(self, fields: list[str] | None=None, filters: dict[str, Any] | None=None) -> ExtractionResult` — Read CSV and return each row as an ExtractedRecord.
- `async def list_fields(self) -> list[str]` — Read only the header row to get column names.
