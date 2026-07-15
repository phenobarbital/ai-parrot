---
type: Wiki Entity
title: DataSourceFactory
id: class:parrot_loaders.extractors.factory.DataSourceFactory
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Resolve source names to ExtractDataSource implementations.
---

# DataSourceFactory

Defined in [`parrot_loaders.extractors.factory`](../summaries/mod:parrot_loaders.extractors.factory.md).

```python
class DataSourceFactory
```

Resolve source names to ExtractDataSource implementations.

Resolution order:
    1. Check ``type`` key in source_config against built-in types.
    2. Check registered custom API sources.
    3. Raise UnknownDataSourceError.

Built-in types: csv, json, sql, records.
Custom API sources can be registered via ``register_api_source()``.

## Methods

- `def register_api_source(cls, name: str, source_cls: type[ExtractDataSource]) -> None` — Register a custom API data source implementation.
- `def get(self, source_name: str, source_config: dict[str, Any] | None=None) -> ExtractDataSource` — Resolve a source name to an ExtractDataSource instance.
