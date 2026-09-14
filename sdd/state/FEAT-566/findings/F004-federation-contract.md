---
id: F004
query_id: Q006
type: read
executed_at: 2026-09-14T00:05:00Z
duration_ms: 100
parent_id: null
depth: 0
---

# F004 — Federation can expose a separate ledger plane with qualified identifiers

## Summary

The federation layer opens namespace stores read-only by default, fans out reads across the local plane and namespaces, and sends writes only to the local plane unless a caller explicitly targets one namespace. Its neighbor implementation retains and hydrates qualified foreign ids, providing a viable read integration pattern for a separate ledger plane.

## Citations

- path: `packages/ai-parrot/src/parrot/knowledge/wiki/federation.py`
  lines: 337-365
  symbol: `open_namespace_store`
  excerpt: |
    read_only: bool = True
    ...
    the `--ns <name>` write path ... opens that store directly
- path: `packages/ai-parrot/src/parrot/knowledge/wiki/federation.py`
  lines: 599-606
  symbol: `FederatedWikiStore`
  excerpt: |
    Reads fan out concurrently, are normalised per namespace, weighted,
    qualified ... and merged. Writes go to the local plane.
- path: `packages/ai-parrot/src/parrot/knowledge/wiki/federation.py`
  lines: 872-880
  symbol: `FederatedWikiStore.search_fts`
  excerpt: |
    groups = await self._fan_out("search_fts", query, category=category, limit=limit)
    return self._merge(groups, limit)
- path: `packages/ai-parrot/src/parrot/knowledge/wiki/federation.py`
  lines: 913-938
  symbol: `FederatedWikiStore.neighbors`
  excerpt: |
    Outgoing hydration ... qualified foreign reference ...
    Incoming references ... live query against the true local plane's edges.

## Notes

The ledger should decide explicitly whether its mutable write API targets the ledger plane directly or runs through a local-plane facade; generic federation writes are intentionally not a substitute.
