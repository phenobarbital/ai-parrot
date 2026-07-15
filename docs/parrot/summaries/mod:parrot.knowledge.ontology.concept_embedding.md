---
type: Wiki Summary
title: parrot.knowledge.ontology.concept_embedding
id: mod:parrot.knowledge.ontology.concept_embedding
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: Concept embedding pipeline for the ontology knowledge layer (FEAT-159).
relates_to:
- concept: class:parrot.knowledge.ontology.concept_embedding.ConceptEmbeddingPipeline
  rel: defines
- concept: class:parrot.knowledge.ontology.concept_embedding.ConceptSyncResult
  rel: defines
- concept: mod:parrot.stores.models
  rel: references
---

# `parrot.knowledge.ontology.concept_embedding`

Concept embedding pipeline for the ontology knowledge layer (FEAT-159).

Provides ``ConceptEmbeddingPipeline``, an idempotent content-hash-based sync
that writes Concept embeddings into a shared PgVector ``concepts`` table scoped
by ``tenant_id`` metadata.  Only changed or new concepts are re-embedded on
each call, and removed concepts are deleted from the store.

The hash cache is persisted as JSON at::

    {ontology_dir}/.concept_hashes/{tenant_id}.json

Writes to the cache file are atomic (tmpfile + rename) to prevent corruption
from partial writes or process interruption.

## Classes

- **`ConceptSyncResult`** — Summary of a single ``ConceptEmbeddingPipeline.sync()`` run.
- **`ConceptEmbeddingPipeline`** — Idempotent, hash-based embedding sync for ontology Concept instances.
