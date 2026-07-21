---
type: Wiki Entity
title: ExtractDataSource
id: class:parrot_loaders.extractors.base.ExtractDataSource
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Abstract base class for structured data extraction.
---

# ExtractDataSource

Defined in [`parrot_loaders.extractors.base`](../summaries/mod:parrot_loaders.extractors.base.md).

```python
class ExtractDataSource(ABC)
```

Abstract base class for structured data extraction.

Subclasses implement extract() and list_fields() for a specific data
source type (CSV, JSON, SQL, API, etc.). All implementations must be
async-first.

Args:
    name: Human-readable name for logging and reporting.
    config: Source-specific configuration (paths, credentials, etc.).

## Methods

- `async def extract(self, fields: list[str] | None=None, filters: dict[str, Any] | None=None) -> ExtractionResult` — Extract structured records from the data source.
- `async def list_fields(self) -> list[str]` — Return the available field names from this data source.
- `async def validate(self, expected_fields: list[str] | None=None) -> bool` — Validate that the source is accessible and has the expected schema.
