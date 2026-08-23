---
id: F011
query_id: Q020,Q028
type: read
intent: What status reports today (to extend per namespace)
executed_at: 2026-08-23T02:20:00Z
depth: 0
---
# F011 — status is single-plane: store.stats() + SourceCollectionManager staleness

## Summary
`status` (cli.py:1241-1288) resolves one project, calls `store.stats()` (1260), lists sources
and stale entries via `SourceCollectionManager.is_stale` (1262), prints wiki/root/storage/plane/
categories/languages/sources. `WikiStatusTool` (tools.py:272-286) returns `store.stats()`.
`stats()` is implemented per backend (store.py:1152, file_store.py:631, arango_store.py:856).
A federated `stats()` can return `{"namespaces": {name: stats}}`; per-namespace staleness
needs one `SourceCollectionManager` per sqlite namespace (`_open_sources`, cli.py:138).

## Citations
- path: `packages/ai-parrot/src/parrot/knowledge/wiki/cli.py`
  lines: 1241-1288
  symbol: `status`
  excerpt: |
    stats = _run(store.stats())                                           # 1260
    stale = [e.source_id for e in entries if sources.is_stale(e.source_id)] # 1262
    click.echo(f"Wiki      : {config.wiki_name} ({config.backend})")        # 1276
- path: `packages/ai-parrot/src/parrot/knowledge/wiki/tools.py`
  lines: 272-286
  symbol: `WikiStatusTool`
- path: `packages/ai-parrot/src/parrot/knowledge/wiki/store.py`
  lines: 1152-1181
  symbol: `SQLiteWikiStore.stats`
- path: `packages/ai-parrot/src/parrot/knowledge/wiki/file_store.py`
  lines: 631
  symbol: `InMemoryWikiStore.stats`
- path: `packages/ai-parrot/src/parrot/knowledge/wiki/arango_store.py`
  lines: 856
  symbol: `ArangoDBWikiStore.stats`
