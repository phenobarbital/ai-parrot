---
id: F017
query_id: Q023
type: read
intent: Determine whether ontology refresh/migration tooling exists for incremental source sync
executed_at: 2026-08-23T00:41:06Z
depth: 2
parent_id: F002
---

# F017 — A CRON-triggered delta-sync pipeline already exists and matches the BOE/EUR-Lex incremental sync the source planned to build

## Summary

`ontology/refresh.py` is a "CRON-triggered refresh pipeline for ontology graph delta sync"
with six documented stages: EXTRACT fresh source data, DIFF against existing graph nodes,
APPLY (upsert changed, soft-delete removed), REDISCOVER relations for changed nodes, SYNC
PgVector embeddings for changed vectorizable fields, and INVALIDATE the tenant's Redis cache.
It carries a `DiffResult` model with `to_add`/`to_update` and composes `RelationDiscovery`,
`OntologyGraphStore.UpsertResult`, `OntologyCache` and `TenantOntologyManager`. This is
substantially the machinery the source's §2.1 `boe_sync_consolidated(since)` and §7 Sprint 1
assume must be written from scratch.

## Citations

- path: `packages/ai-parrot/src/parrot/knowledge/ontology/refresh.py`
  lines: 1-24
  excerpt: |
    """CRON-triggered refresh pipeline for ontology graph delta sync.

    Keeps the ontology graph in sync with source data via:
        1. EXTRACT: Pull fresh data from configured sources.
        2. DIFF: Compare new data vs existing graph nodes.
        3. APPLY: Upsert changed nodes, soft-delete removed ones.
        4. REDISCOVER: Re-run relation discovery for changed nodes.
        5. SYNC: Update PgVector embeddings for changed vectorizable fields.
        6. INVALIDATE: Bust Redis cache for the affected tenant.
    """

- path: `packages/ai-parrot/src/parrot/knowledge/ontology/refresh.py`
  lines: 27-34
  symbol: `DiffResult`
  excerpt: |
    class DiffResult(BaseModel):
        Args:
            to_add: Records present in new data but not existing.
            to_update: Records present in both but with changed values.

## Notes

Pairs with F016: the incremental path exists at the ontology layer, and F020 shows a parallel
per-document incremental path at the GraphIndex layer.
