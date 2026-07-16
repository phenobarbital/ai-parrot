---
type: Wiki Overview
title: 'TASK-1089: Concept Catalog Sync Worker'
id: doc:sdd-tasks-completed-task-1089-concept-catalog-sync-worker-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: The `ConceptCatalogSyncWorker` drains the `ontology_concept_outbox` table
  using `SELECT ... FOR UPDATE SKIP LOCKED`, upserts concepts/edges to ArangoDB via
  `OntologyGraphStore`, and publishes cache invalidation messages via Redis pub/sub.
  See spec §3 Module 5.
relates_to:
- concept: mod:parrot.knowledge.ontology.concept_catalog.models
  rel: mentions
- concept: mod:parrot.knowledge.ontology.concept_catalog.worker
  rel: mentions
- concept: mod:parrot.knowledge.ontology.graph_store
  rel: mentions
- concept: mod:parrot.knowledge.ontology.schema
  rel: mentions
- concept: mod:parrot.services.worker_pool
  rel: mentions
---

# TASK-1089: Concept Catalog Sync Worker

**Feature**: FEAT-159 — Topic-Authority Ontology Curation
**Spec**: `sdd/specs/topic-authority-ontology.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1087, TASK-1088
**Assigned-to**: unassigned

---

## Context

The `ConceptCatalogSyncWorker` drains the `ontology_concept_outbox` table using `SELECT ... FOR UPDATE SKIP LOCKED`, upserts concepts/edges to ArangoDB via `OntologyGraphStore`, and publishes cache invalidation messages via Redis pub/sub. See spec §3 Module 5.

---

## Scope

- Implement `ConceptCatalogSyncWorker` with `run_once(batch_size)`.
- Operation dispatch via the `OPERATIONS` class dict: `publish_to_graph`, `deprecate_in_graph`, `invalidate_cache`.
- `_op_publish`: upserts concept node to ArangoDB `concepts` collection with `pg_concept_id` attribute; for is_a edges, creates edge in `concept_isa` collection.
- `_op_deprecate`: soft-deletes node/edge in ArangoDB.
- `_op_invalidate`: publishes `ontology:invalidate:<tenant_id>` to Redis.
- DLQ after N retries (configurable, default 5): increment `attempts`, set `last_error`; on threshold, log error and skip.
- Mark processed rows with `processed_at` timestamp.
- Write unit tests.

**NOT in scope**: Service logic (TASK-1088), HTTP routes, reconciliation.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/ontology/concept_catalog/worker.py` | CREATE | ConceptCatalogSyncWorker |
| `tests/knowledge/ontology/concept_catalog/test_worker.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
from parrot.knowledge.ontology.concept_catalog.models import ConceptRow, IsaEdgeRow  # TASK-1087
from parrot.knowledge.ontology.graph_store import OntologyGraphStore  # graph_store.py:33
from parrot.knowledge.ontology.schema import TenantContext  # schema.py:261
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/knowledge/ontology/graph_store.py
class OntologyGraphStore:                                                       # line 33
    async def upsert_nodes(
        self, ctx: TenantContext, collection: str,
        nodes: list[dict[str, Any]], key_field: str,
    ) -> UpsertResult: ...                                                      # line 225
    async def create_edges(
        self, ctx: TenantContext, edge_collection: str,
        edges: list[dict[str, Any]],
    ) -> int: ...                                                               # line 312
    async def soft_delete_nodes(
        self, ctx: TenantContext, collection: str, keys: list[str],
    ) -> None: ...                                                              # line 413

# packages/ai-parrot/src/parrot/knowledge/ontology/graph_store.py
class UpsertResult:                                                             # line 19
    ...
```

### Does NOT Exist

- ~~`ConceptCatalogSyncWorker`~~ — does not exist; this task creates it.
- ~~qworker task class~~ — project uses asyncio `WorkerPool` from `parrot.services.worker_pool`, not Redis Queue. Implement as a standalone async class with `run_once()`.

---

## Implementation Notes

### Pattern to Follow

```python
class ConceptCatalogSyncWorker:
    """Drains ontology_concept_outbox, materializes to ArangoDB, publishes invalidation."""

    OPERATIONS: dict[str, str] = {
        "publish_to_graph":   "_op_publish",
        "deprecate_in_graph": "_op_deprecate",
        "invalidate_cache":   "_op_invalidate",
    }
    GRAPH_NODE_COLLECTION = "concepts"
    GRAPH_EDGE_COLLECTION = "concept_isa"
    MAX_RETRIES = 5

    def __init__(self, pg_pool, graph_store: OntologyGraphStore, redis_client) -> None:
        self.logger = logging.getLogger("Parrot.Ontology.ConceptCatalog.Worker")
        ...

    async def run_once(self, batch_size: int = 50) -> int:
        """Drain up to batch_size outbox rows. Returns count processed."""
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT * FROM ontology_concept_outbox "
                "WHERE processed_at IS NULL "
                "ORDER BY enqueued_at "
                "LIMIT $1 "
                "FOR UPDATE SKIP LOCKED",
                batch_size,
            )
            for row in rows:
                handler = getattr(self, self.OPERATIONS[row["operation"]])
                try:
                    await handler(conn, row)
                    await conn.execute(
                        "UPDATE ontology_concept_outbox SET processed_at = now() WHERE id = $1",
                        row["id"],
                    )
                except Exception as e:
                    attempts = row["attempts"] + 1
                    if attempts >= self.MAX_RETRIES:
                        self.logger.error("DLQ: outbox row %s after %d attempts: %s", row["id"], attempts, e)
                    await conn.execute(
                        "UPDATE ontology_concept_outbox SET attempts = $1, last_error = $2 WHERE id = $3",
                        attempts, str(e), row["id"],
                    )
            return len(rows)
```

### Key Constraints

- `SKIP LOCKED` ensures two parallel workers process disjoint rows.
- Every ArangoDB document must carry `pg_concept_id` (or `pg_isa_edge_id` for edges).
- After successful `_op_publish` or `_op_deprecate`, also run `_op_invalidate`.
- Redis publish channel: `ontology:invalidate:<tenant_id>`.
- DLQ: after `MAX_RETRIES`, log error but do NOT re-enqueue. Row stays with `processed_at IS NULL` and `attempts >= MAX_RETRIES` — a monitoring query surfaces these.

### References in Codebase

- `packages/ai-parrot/src/parrot/knowledge/ontology/graph_store.py` — `upsert_nodes`, `create_edges`, `soft_delete_nodes`.
- `packages/ai-parrot/src/parrot/services/worker_pool.py` — asyncio worker pattern reference.

---

## Acceptance Criteria

- [ ] `run_once()` drains outbox rows with `FOR UPDATE SKIP LOCKED`.
- [ ] `_op_publish` upserts ArangoDB doc with `pg_concept_id`.
- [ ] `_op_deprecate` soft-deletes ArangoDB doc.
- [ ] `_op_invalidate` publishes to Redis `ontology:invalidate:<tenant_id>`.
- [ ] Two parallel workers process disjoint rows (no double-processing).
- [ ] DLQ: after MAX_RETRIES, row is skipped with error logged.
- [ ] Processed rows have `processed_at` set.
- [ ] All tests pass: `pytest tests/knowledge/ontology/concept_catalog/test_worker.py -v`

---

## Test Specification

```python
# tests/knowledge/ontology/concept_catalog/test_worker.py
import pytest
from parrot.knowledge.ontology.concept_catalog.worker import ConceptCatalogSyncWorker


class TestConceptCatalogSyncWorker:
    async def test_drains_outbox_skip_locked(self, worker, outbox_with_rows):
        count = await worker.run_once(batch_size=10)
        assert count > 0

    async def test_upsert_carries_pg_concept_id(self, worker, outbox_with_publish_row):
        await worker.run_once()
        # verify ArangoDB doc has pg_concept_id

    async def test_publishes_invalidation(self, worker, outbox_with_row, redis_subscriber):
        await worker.run_once()
        msg = await redis_subscriber.get_message(timeout=1)
        assert msg is not None

    async def test_dlq_after_max_retries(self, worker, outbox_with_failing_row):
        for _ in range(6):
            await worker.run_once()
        # verify row still has processed_at IS NULL but attempts >= MAX_RETRIES
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** §3 Module 5 and §2 "ConceptCatalogSyncWorker" interface
2. **Verify** TASK-1087 (models) and TASK-1088 (service) are done
3. **Read** `packages/ai-parrot/src/parrot/knowledge/ontology/graph_store.py` for `upsert_nodes`/`create_edges`/`soft_delete_nodes` signatures
4. **Implement** worker with operation dispatch pattern
5. **Run tests**: `pytest tests/knowledge/ontology/concept_catalog/test_worker.py -v`

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: 
**Date**: 
**Notes**: 

**Deviations from spec**: none | describe if any
