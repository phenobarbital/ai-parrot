---
type: Wiki Entity
title: JSONDataSource
id: class:parrot_loaders.extractors.json_source.JSONDataSource
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Extract structured records from JSON files or arrays.
relates_to:
- concept: class:parrot_loaders.extractors.base.ExtractDataSource
  rel: extends
---

# JSONDataSource

Defined in [`parrot_loaders.extractors.json_source`](../summaries/mod:parrot_loaders.extractors.json_source.md).

```python
class JSONDataSource(ExtractDataSource)
```

Extract structured records from JSON files or arrays.

Config:
    path: str — Path to JSON file.
    records_path: str | None — Dot-separated path to the array of records
        (e.g. "data.employees" for nested JSON). None means the root is
        the array.

Args:
    name: Human-readable name for logging and reporting.
    config: Source-specific configuration.

## Methods

- `async def extract(self, fields: list[str] | None=None, filters: dict[str, Any] | None=None) -> ExtractionResult` — Parse JSON and extract records from the configured path.
- `async def list_fields(self) -> list[str]` — Load first record and return its keys.
