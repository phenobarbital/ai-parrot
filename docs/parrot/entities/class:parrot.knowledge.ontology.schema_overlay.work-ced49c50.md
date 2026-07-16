---
type: Wiki Entity
title: SchemaOverlaySyncWorker
id: class:parrot.knowledge.ontology.schema_overlay.worker.SchemaOverlaySyncWorker
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Drain ``ontology_schema_outbox`` and publish cache invalidation.
---

# SchemaOverlaySyncWorker

Defined in [`parrot.knowledge.ontology.schema_overlay.worker`](../summaries/mod:parrot.knowledge.ontology.schema_overlay.worker.md).

```python
class SchemaOverlaySyncWorker
```

Drain ``ontology_schema_outbox`` and publish cache invalidation.

Operation dispatch table:

* ``invalidate_cache`` → ``_op_invalidate``
* ``deprecate_invalidate`` → ``_op_invalidate``

DLQ policy: after ``MAX_RETRIES`` attempts the row is left unprocessed.

Args:
    pg_pool: asyncpg connection pool.
    redis_client: aioredis (or compatible) client.

## Methods

- `async def run_once(self, batch_size: int=50) -> int` — Drain up to *batch_size* outbox rows.
