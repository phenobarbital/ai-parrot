---
type: Wiki Summary
title: parrot.knowledge.ontology.concept_catalog.worker
id: mod:parrot.knowledge.ontology.concept_catalog.worker
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: Concept Catalog Sync Worker (FEAT-159 TASK-1089).
relates_to:
- concept: class:parrot.knowledge.ontology.concept_catalog.worker.ConceptCatalogSyncWorker
  rel: defines
- concept: mod:parrot.knowledge.ontology.concept_catalog
  rel: references
- concept: mod:parrot.knowledge.ontology.graph_store
  rel: references
- concept: mod:parrot.knowledge.ontology.schema
  rel: references
---

# `parrot.knowledge.ontology.concept_catalog.worker`

Concept Catalog Sync Worker (FEAT-159 TASK-1089).

Drains ``ontology_concept_outbox`` rows using ``SELECT … FOR UPDATE SKIP LOCKED``,
materialises concept/is_a data to ArangoDB via ``OntologyGraphStore``, and
publishes cache-invalidation messages to Redis pub/sub.

## Classes

- **`ConceptCatalogSyncWorker`** — Drain ``ontology_concept_outbox``, sync to ArangoDB, publish invalidation.
