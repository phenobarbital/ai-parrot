---
type: Wiki Entity
title: CachePartition
id: class:parrot.bots.database.cache.CachePartition
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Namespaced cache partition with the same API as ``SchemaMetadataCache``.
---

# CachePartition

Defined in [`parrot.bots.database.cache`](../summaries/mod:parrot.bots.database.cache.md).

```python
class CachePartition
```

Namespaced cache partition with the same API as ``SchemaMetadataCache``.

Each partition owns:
* An independent ``TTLCache`` (LRU tier)
* A schema-level cache (``Dict[str, SchemaMetadata]``)
* Access statistics for hot-table tracking

Optionally uses a shared Redis pool and vector store passed by the
``CacheManager``.

## Methods

- `async def get(self, schema_name: str, table_name: str, *, required: Completeness=Completeness.NAME_ONLY, max_age: Optional[timedelta]=None) -> Optional[TableMetadata]` — Return metadata only when completeness and freshness requirements are met.
- `async def get_table_metadata(self, schema_name: str, table_name: str) -> Optional[TableMetadata]` — Deprecated — use get() instead.
- `async def store_table_metadata(self, metadata: TableMetadata) -> None` — Store table metadata across all available tiers.
- `async def list(self, schema_names: List[str], *, completeness_min: Completeness=Completeness.NAME_ONLY, max_age: Optional[timedelta]=None, limit: Optional[int]=None) -> List[TableMetadata]` — Return all cached tables in *schema_names* filtered by completeness and age.
- `async def search(self, schema_names: List[str], search_term: str, *, completeness_min: Completeness=Completeness.NAME_ONLY, max_age: Optional[timedelta]=None, limit: int=20) -> List[TableMetadata]` — Search for tables within *schema_names* filtered by completeness and age.
- `async def search_similar_tables(self, schema_names: List[str], query: str, limit: int=5) -> List[TableMetadata]` — Deprecated — use search() instead.
- `def get_schema_overview(self, schema_name: str) -> Optional[SchemaMetadata]` — Get complete schema overview.
- `def get_hot_tables(self, schema_names: List[str], limit: int=10) -> List[tuple[str, str, int]]` — Get most frequently accessed tables across allowed schemas.
