---
type: Wiki Summary
title: parrot.knowledge.ontology.schema_overlay.worker
id: mod:parrot.knowledge.ontology.schema_overlay.worker
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: Schema Overlay Sync Worker (FEAT-159 TASK-1096).
relates_to:
- concept: class:parrot.knowledge.ontology.schema_overlay.worker.SchemaOverlaySyncWorker
  rel: defines
---

# `parrot.knowledge.ontology.schema_overlay.worker`

Schema Overlay Sync Worker (FEAT-159 TASK-1096).

Drains ``ontology_schema_outbox`` using ``SELECT … FOR UPDATE SKIP LOCKED``
and publishes cache-invalidation messages to Redis pub/sub.

Unlike the concept catalog worker, the schema overlay worker does **not**
materialise data to ArangoDB — overlays are composed at resolve-time by
``TenantOntologyManager`` + ``OntologyMerger``.

## Classes

- **`SchemaOverlaySyncWorker`** — Drain ``ontology_schema_outbox`` and publish cache invalidation.
