---
type: Wiki Entity
title: SchemaMetadataCache
id: class:parrot_tools.database.cache.SchemaMetadataCache
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: 'Two-tier caching: LRU (hot data) + Optional Vector Store (cold/searchable
  data).'
---

# SchemaMetadataCache

Defined in [`parrot_tools.database.cache`](../summaries/mod:parrot_tools.database.cache.md).

```python
class SchemaMetadataCache
```

Two-tier caching: LRU (hot data) + Optional Vector Store (cold/searchable data).

## Methods

- `async def get_table_metadata(self, schema_name: str, table_name: str) -> Optional[TableMetadata]` — Get table metadata with access tracking.
- `async def store_table_metadata(self, metadata: TableMetadata)` — Store table metadata in available cache tiers.
- `async def search_similar_tables(self, schema_names: List[str], query: str, limit: int=5) -> List[TableMetadata]` — Search for similar tables within allowed schemas.
- `def get_schema_overview(self, schema_name: str) -> Optional[SchemaMetadata]` — Get complete schema overview.
- `def get_hot_tables(self, schema_names: List[str], limit: int=10) -> List[tuple[str, str, int]]` — Get most frequently accessed tables across allowed schemas.
