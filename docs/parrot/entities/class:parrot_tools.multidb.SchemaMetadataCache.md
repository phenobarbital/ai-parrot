---
type: Wiki Entity
title: SchemaMetadataCache
id: class:parrot_tools.multidb.SchemaMetadataCache
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Multi-tier caching system for database schema metadata.
---

# SchemaMetadataCache

Defined in [`parrot_tools.multidb`](../summaries/mod:parrot_tools.multidb.md).

```python
class SchemaMetadataCache
```

Multi-tier caching system for database schema metadata.

This class orchestrates the three-tier caching strategy:
Tier 1: In-memory LRU cache for hot tables
Tier 2: Vector store for semantic discovery
Tier 3: Direct database extraction

The cache learns from usage patterns and optimizes for common access patterns.

## Methods

- `async def get_table_metadata(self, schema_name: str, table_name: str, database_type: str, database_extractor_func: Optional[callable]=None) -> Optional[TableMetadata]` — Get table metadata using the three-tier caching strategy.
- `async def get_context_for_query(self, table_names: List[str], schema_name: str='public', database_type: str='postgresql', format_type: MetadataFormat=MetadataFormat.YAML_OPTIMIZED, database_extractor_func: Optional[callable]=None) -> str` — Build comprehensive LLM context for a set of tables.
- `async def cleanup(self)` — Clean up background tasks and resources.
- `def get_cache_stats(self) -> Dict[str, Any]` — Get caching statistics for monitoring and debugging.
