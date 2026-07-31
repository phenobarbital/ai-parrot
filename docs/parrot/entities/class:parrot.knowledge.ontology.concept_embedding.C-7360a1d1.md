---
type: Wiki Entity
title: ConceptSyncResult
id: class:parrot.knowledge.ontology.concept_embedding.ConceptSyncResult
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Summary of a single ``ConceptEmbeddingPipeline.sync()`` run.
---

# ConceptSyncResult

Defined in [`parrot.knowledge.ontology.concept_embedding`](../summaries/mod:parrot.knowledge.ontology.concept_embedding.md).

```python
class ConceptSyncResult
```

Summary of a single ``ConceptEmbeddingPipeline.sync()`` run.

Attributes:
    added: Number of new concepts embedded for the first time.
    updated: Number of existing concepts that were re-embedded (content changed).
    removed: Number of concepts deleted from the vector store.
    unchanged: Number of concepts whose content hash matched the cache
        (no embedding call made).
    duration_ms: Wall-clock time for the sync operation in milliseconds.
