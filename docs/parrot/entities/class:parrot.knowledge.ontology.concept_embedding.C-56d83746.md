---
type: Wiki Entity
title: ConceptEmbeddingPipeline
id: class:parrot.knowledge.ontology.concept_embedding.ConceptEmbeddingPipeline
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Idempotent, hash-based embedding sync for ontology Concept instances.
---

# ConceptEmbeddingPipeline

Defined in [`parrot.knowledge.ontology.concept_embedding`](../summaries/mod:parrot.knowledge.ontology.concept_embedding.md).

```python
class ConceptEmbeddingPipeline
```

Idempotent, hash-based embedding sync for ontology Concept instances.

On each ``sync()`` call the pipeline:

1. Computes a content hash (sha256) for every concept in the supplied list.
2. Loads the on-disk hash cache for the tenant.
3. Diffs new hashes against cached hashes to determine added / updated /
   removed / unchanged sets.
4. Embeds *only* changed/new concepts via ``vector_store.add_documents()``.
5. Deletes removed concepts via ``vector_store.delete_documents_by_filter()``.
6. Atomically writes the updated hash cache to disk.

The ``concepts`` table is shared across tenants; isolation is enforced by
the ``tenant_id`` metadata field stored alongside each embedding row.

Args:
    vector_store: PgVectorStore instance used for embedding storage.
    embedder: Callable or embedding client; passed to the vector store's
        ``add_documents`` for embedding.  If the vector store handles its
        own embedding, this can be the same object as ``vector_store``.
    ontology_dir: Base directory for ontology files.  The hash-cache
        subdirectory ``.concept_hashes/`` is created here.
    schema: PostgreSQL schema name for the concepts table.
    table: PostgreSQL table name for concept embeddings.

## Methods

- `async def sync(self, tenant_id: str, concepts: list[Any]) -> ConceptSyncResult` — Synchronise concept embeddings for a tenant with the vector store.
