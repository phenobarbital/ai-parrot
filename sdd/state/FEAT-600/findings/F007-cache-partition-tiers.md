---
id: F007
query_id: Q006/Q024
type: read
intent: CachePartition tiers are LRU → schema cache → Redis → vector store; nothing durable; Redis keys already use a `table:` prefix
executed_at: 2026-09-24T20:41:46+00:00
duration_ms: 0
parent_id: null
depth: 0
---

# F007 — CachePartition tiers are LRU → schema cache → Redis → vector store; nothing durable; Redis keys already use a `table:` prefix

## Summary

CachePartitionConfig (L33) has lru_ttl=1800, redis_ttl=3600, ttl_by_completeness (L40). CachePartition.__init__ takes vector_store (L73) and builds a TTLCache (L85). get() docstring L122 states the resolution order; vector fallback at L151; Redis TTL chosen by completeness L164; store_table_metadata L185. Redis key helper L104 returns f'table:{schema_name}:{table_name}' and L321 scans f'table:{schema_name}:' — a string-prefix overlap with the proposed `table:` page kind (different store, but grep-visible).

## Citations

- path: `packages/ai-parrot/src/parrot/bots/database/cache.py`
  lines: 33-40
  symbol: `CachePartitionConfig`
  excerpt: |
    lru_ttl: int = Field(default=1800 …) redis_ttl: int = Field(default=3600 …) ttl_by_completeness
- path: `packages/ai-parrot/src/parrot/bots/database/cache.py`
  lines: 54-92
  symbol: `CachePartition.__init__`
  excerpt: |
    vector_store: Optional["AbstractStore"] = None … self.hot_cache: TTLCache = TTLCache(maxsize=lru_maxsize, ttl=lru_ttl)
- path: `packages/ai-parrot/src/parrot/bots/database/cache.py`
  lines: 104
  symbol: `CachePartition._table_key`
  excerpt: |
    return f"table:{schema_name}:{table_name}"
- path: `packages/ai-parrot/src/parrot/bots/database/cache.py`
  lines: 112-164
  symbol: `CachePartition.get`
  excerpt: |
    Resolution order: LRU → schema cache → Redis → vector store.
- path: `packages/ai-parrot/src/parrot/bots/database/cache.py`
  lines: 185
  symbol: `CachePartition.store_table_metadata`
- path: `packages/ai-parrot/src/parrot/bots/database/cache.py`
  lines: 321
  symbol: `CachePartition.list/search`
  excerpt: |
    schema_prefix = f"table:{schema_name}:"
