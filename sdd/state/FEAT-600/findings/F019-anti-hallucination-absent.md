---
id: F019
query_id: Q028
type: grep
intent: No schema plane exists: no knowledge/wiki/schema, no wiki_schema_* tools, no table:/schema:/source: page kinds
executed_at: 2026-09-24T20:41:46+00:00
duration_ms: 0
parent_id: null
depth: 0
---

# F019 — No schema plane exists: no knowledge/wiki/schema, no wiki_schema_* tools, no table:/schema:/source: page kinds

## Summary

grep over packages/*/src for 'knowledge/wiki/schema|wiki_schema_' → 0 files. The literal 'table:' appears only as the CachePartition Redis key prefix (cache.py L104/L321), as the 'table:read' permission string in auth/dataplane_guard.py L182/L261, and in a regex in bots/database/toolkits/_internal.py L272. No overlay declares 'table', 'schema' or 'source' prefixes, so the proposed kinds are free.

## Citations

- path: `packages/ai-parrot/src/parrot/auth/dataplane_guard.py`
  lines: 182,261
  excerpt: |
    "table:read"
- path: `packages/ai-parrot/src/parrot/bots/database/toolkits/_internal.py`
  lines: 272
  excerpt: |
    re.findall(r"table:\s+\w+\.(\w+)", metadata_context)
- path: `packages/ai-parrot/src/parrot/bots/database/cache.py`
  lines: 104,321
  excerpt: |
    f"table:{schema_name}:{table_name}"
