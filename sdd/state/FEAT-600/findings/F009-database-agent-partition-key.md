---
id: F009
query_id: Q008
type: read
intent: DatabaseAgent keys partitions and the router by tk_id = f'{database_type}_{primary_schema}'
executed_at: 2026-09-24T20:41:46+00:00
duration_ms: 0
parent_id: null
depth: 0
---

# F009 — DatabaseAgent keys partitions and the router by tk_id = f'{database_type}_{primary_schema}'

## Summary

agent.py L206 builds tk_id from database_type and primary_schema, stores the toolkit in _toolkit_map L207, passes namespace=tk_id into CachePartitionConfig (L215/L221) and registers the router with (database_type, tk_id) L224. The plane's `origin` alias is a different key; a tk_id→origin map (or an explicit origin= on DatabaseToolkitConfig) is needed.

## Citations

- path: `packages/ai-parrot/src/parrot/bots/database/agent.py`
  lines: 206-224
  symbol: `DatabaseAgent (toolkit start loop)`
  excerpt: |
    tk_id = f"{tk.database_type}_{tk.primary_schema}" … self.cache_manager.create_partition(CachePartitionConfig(**config_kwargs)) … self.query_router.register_database(tk.database_type, tk_id)
