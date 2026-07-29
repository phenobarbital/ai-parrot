---
type: Wiki Entity
title: ConceptCatalogSyncWorker
id: class:parrot.knowledge.ontology.concept_catalog.worker.ConceptCatalogSyncWorker
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Drain ``ontology_concept_outbox``, sync to ArangoDB, publish invalidation.
---

# ConceptCatalogSyncWorker

Defined in [`parrot.knowledge.ontology.concept_catalog.worker`](../summaries/mod:parrot.knowledge.ontology.concept_catalog.worker.md).

```python
class ConceptCatalogSyncWorker
```

Drain ``ontology_concept_outbox``, sync to ArangoDB, publish invalidation.

Operation dispatch table (class-level) maps outbox ``operation`` values to
private method names so new operations can be registered without branching.

DLQ policy: after ``MAX_RETRIES`` attempts the row is left with
``processed_at IS NULL`` and ``attempts >= MAX_RETRIES``; a monitoring
query can surface these rows. They are NOT re-enqueued.

Args:
    pg_pool: asyncpg connection pool.
    graph_store: OntologyGraphStore instance for ArangoDB I/O.
    redis_client: aioredis (or compatible) client for pub/sub publish.

## Methods

- `async def run_once(self, batch_size: int=50) -> int` — Drain up to *batch_size* outbox rows.
