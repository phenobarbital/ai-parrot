---
type: Wiki Entity
title: ConceptCatalogReconciler
id: class:parrot.knowledge.ontology.concept_catalog.reconcile.ConceptCatalogReconciler
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Detect drift between Postgres and ArangoDB for a tenant's concept catalog.
---

# ConceptCatalogReconciler

Defined in [`parrot.knowledge.ontology.concept_catalog.reconcile`](../summaries/mod:parrot.knowledge.ontology.concept_catalog.reconcile.md).

```python
class ConceptCatalogReconciler
```

Detect drift between Postgres and ArangoDB for a tenant's concept catalog.

The reconciler performs two scans per collection:

1. **Forward scan** — for each approved PG row, verify an ArangoDB document
   with matching ``pg_concept_id`` / ``pg_isa_edge_id`` exists.
2. **Reverse scan** — for each ArangoDB document, verify a corresponding
   approved PG row exists.

Only discrepancies are logged (at WARNING level).  No writes are made.

Args:
    pg_pool: asyncpg connection pool.
    graph_store: OntologyGraphStore instance.
    outbox_drain_interval: Seconds to wait before flagging an in-flight row.
        Rows updated within ``outbox_drain_interval × 10`` seconds are
        excluded from forward-scan results.

## Methods

- `async def reconcile(self, tenant_id: str) -> ReconciliationReport` — Run a full reconciliation for *tenant_id*.
