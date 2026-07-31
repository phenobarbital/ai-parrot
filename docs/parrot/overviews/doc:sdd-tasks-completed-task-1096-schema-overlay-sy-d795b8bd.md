---
type: Wiki Overview
title: 'TASK-1096: Schema Overlay Sync Worker'
id: doc:sdd-tasks-completed-task-1096-schema-overlay-sync-worker-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: The `SchemaOverlaySyncWorker` drains `ontology_schema_outbox` with `SELECT
  ... FOR UPDATE SKIP LOCKED` and publishes cache invalidation messages via Redis
  pub/sub. Unlike the concept worker, it does NOT materialize to ArangoDB — schema
  overlays are composed at resolve-time. See s
relates_to:
- concept: mod:parrot.knowledge.ontology.schema_overlay.models
  rel: mentions
- concept: mod:parrot.knowledge.ontology.schema_overlay.worker
  rel: mentions
---

# TASK-1096: Schema Overlay Sync Worker

**Feature**: FEAT-159 — Topic-Authority Ontology Curation
**Spec**: `sdd/specs/topic-authority-ontology.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1093, TASK-1095
**Assigned-to**: unassigned

---

## Context

The `SchemaOverlaySyncWorker` drains `ontology_schema_outbox` with `SELECT ... FOR UPDATE SKIP LOCKED` and publishes cache invalidation messages via Redis pub/sub. Unlike the concept worker, it does NOT materialize to ArangoDB — schema overlays are composed at resolve-time. See spec §3 Module 12.

---

## Scope

- Implement `SchemaOverlaySyncWorker` with `run_once(batch_size)`.
- Operation dispatch: `invalidate_cache` and `deprecate_invalidate` both call `_op_invalidate`.
- `_op_invalidate`: publishes `ontology:invalidate:<tenant_id>` to Redis.
- DLQ after N retries.
- Mark processed rows with `processed_at` timestamp.
- Write unit tests.

**NOT in scope**: Service logic (TASK-1095), HTTP routes (TASK-1097), ArangoDB materialization.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/ontology/schema_overlay/worker.py` | CREATE | SchemaOverlaySyncWorker |
| `tests/knowledge/ontology/schema_overlay/test_worker.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
from parrot.knowledge.ontology.schema_overlay.models import SchemaOverlayRow  # TASK-1093
# redis.asyncio for pub/sub — already a dependency
```

### Existing Signatures to Use

```python
# No ArangoDB calls — this worker only publishes to Redis.
```

### Does NOT Exist

- ~~`SchemaOverlaySyncWorker`~~ — does not exist; this task creates it.
- ~~ArangoDB materialization for schema overlays~~ — by design, overlays are composed at resolve-time, not materialized.

---

## Implementation Notes

### Pattern to Follow

```python
class SchemaOverlaySyncWorker:
    """Drains ontology_schema_outbox, publishes cache invalidation."""

    OPERATIONS: dict[str, str] = {
        "invalidate_cache":     "_op_invalidate",
        "deprecate_invalidate": "_op_invalidate",
    }
    INVALIDATE_CHANNEL_TEMPLATE = "ontology:invalidate:{tenant_id}"
    MAX_RETRIES = 5

    def __init__(self, pg_pool, redis_client) -> None:
        self.logger = logging.getLogger("Parrot.Ontology.SchemaOverlay.Worker")
        ...

    async def run_once(self, batch_size: int = 50) -> int:
        """Drain up to batch_size outbox rows. Returns count processed."""
        # Same SKIP LOCKED pattern as ConceptCatalogSyncWorker
        ...

    async def _op_invalidate(self, conn, row) -> None:
        tenant_id = row["payload"].get("tenant_id") or ...
        channel = self.INVALIDATE_CHANNEL_TEMPLATE.format(tenant_id=tenant_id)
        await self._redis.publish(channel, "invalidate")
```

### Key Constraints

- Simpler than the concept worker — only publishes Redis messages.
- Same `SKIP LOCKED` + DLQ pattern as TASK-1089.
- `tenant_id` must be extracted from the outbox row's `payload` JSONB.

### References in Codebase

- TASK-1089 (concept worker) — identical outbox drain pattern.
- Spec §3 Module 12.

---

## Acceptance Criteria

- [ ] `run_once()` drains schema outbox with `FOR UPDATE SKIP LOCKED`.
- [ ] `_op_invalidate` publishes to Redis `ontology:invalidate:<tenant_id>`.
- [ ] DLQ after MAX_RETRIES.
- [ ] Processed rows have `processed_at` set.
- [ ] All tests pass: `pytest tests/knowledge/ontology/schema_overlay/test_worker.py -v`

---

## Test Specification

```python
# tests/knowledge/ontology/schema_overlay/test_worker.py
import pytest
from parrot.knowledge.ontology.schema_overlay.worker import SchemaOverlaySyncWorker


class TestSchemaOverlaySyncWorker:
    async def test_drains_outbox(self, worker, schema_outbox_with_rows):
        count = await worker.run_once(batch_size=10)
        assert count > 0

    async def test_publishes_invalidation(self, worker, schema_outbox_with_row, redis_subscriber):
        await worker.run_once()
        msg = await redis_subscriber.get_message(timeout=1)
        assert msg is not None

    async def test_dlq_after_max_retries(self, worker, failing_outbox_row):
        for _ in range(6):
            await worker.run_once()
        # verify row skipped after MAX_RETRIES
```

---

## Agent Instructions

When you pick up this task:

1. **Read** TASK-1089 (concept worker) for the identical outbox drain pattern
2. **Verify** TASK-1093 (models) and TASK-1095 (service) are done
3. **Implement** worker — much simpler than concept worker (Redis only, no Arango)
4. **Run tests**: `pytest tests/knowledge/ontology/schema_overlay/test_worker.py -v`

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: 
**Date**: 
**Notes**: 

**Deviations from spec**: none | describe if any
