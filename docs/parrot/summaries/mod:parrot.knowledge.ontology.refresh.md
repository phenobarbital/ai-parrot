---
type: Wiki Summary
title: parrot.knowledge.ontology.refresh
id: mod:parrot.knowledge.ontology.refresh
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: CRON-triggered refresh pipeline for ontology graph delta sync.
relates_to:
- concept: class:parrot.knowledge.ontology.refresh.DiffResult
  rel: defines
- concept: class:parrot.knowledge.ontology.refresh.OntologyRefreshPipeline
  rel: defines
- concept: class:parrot.knowledge.ontology.refresh.RefreshReport
  rel: defines
- concept: mod:parrot.knowledge.ontology.cache
  rel: references
- concept: mod:parrot.knowledge.ontology.discovery
  rel: references
- concept: mod:parrot.knowledge.ontology.graph_store
  rel: references
- concept: mod:parrot.knowledge.ontology.tenant
  rel: references
---

# `parrot.knowledge.ontology.refresh`

CRON-triggered refresh pipeline for ontology graph delta sync.

Keeps the ontology graph in sync with source data via:
    1. EXTRACT: Pull fresh data from configured sources.
    2. DIFF: Compare new data vs existing graph nodes.
    3. APPLY: Upsert changed nodes, soft-delete removed ones.
    4. REDISCOVER: Re-run relation discovery for changed nodes.
    5. SYNC: Update PgVector embeddings for changed vectorizable fields.
    6. INVALIDATE: Bust Redis cache for the affected tenant.

## Classes

- **`DiffResult(BaseModel)`** — Result of computing delta between new and existing data.
- **`RefreshReport(BaseModel)`** — Report from a full refresh pipeline run.
- **`OntologyRefreshPipeline`** — CRON-triggered pipeline that keeps the ontology graph in sync.
