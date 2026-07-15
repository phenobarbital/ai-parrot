---
type: Wiki Summary
title: parrot.knowledge.ontology.cache
id: mod:parrot.knowledge.ontology.cache
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: Redis cache helpers for ontology pipeline results.
relates_to:
- concept: class:parrot.knowledge.ontology.cache.OntologyCache
  rel: defines
- concept: mod:parrot
  rel: references
- concept: mod:parrot.conf
  rel: references
- concept: mod:parrot.knowledge.ontology.schema
  rel: references
- concept: mod:parrot.knowledge.ontology.tenant
  rel: references
---

# `parrot.knowledge.ontology.cache`

Redis cache helpers for ontology pipeline results.

Provides key building, serialization, TTL management, and pattern-based
invalidation for the full ontology RAG pipeline cache.

FEAT-159 (TASK-1099): Extended with ``subscribe_invalidation()`` — a long-running
async coroutine that listens to the Redis ``ontology:invalidate:*`` pub/sub channel
and triggers both in-memory manager invalidation and Redis key deletion on receipt.

## Classes

- **`OntologyCache`** — Redis cache for ontology pipeline results.
