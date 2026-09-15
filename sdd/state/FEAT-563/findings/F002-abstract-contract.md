---
id: F002
query_id: Q002
type: read
intent: Store contract includes lifecycle, ingestion and deletion
executed_at: 2026-09-09T23:24:11.921Z
parent_id: null
depth: 1
---

# F002 — Store contract includes lifecycle, ingestion and deletion

## Summary

AbstractStore requires connection/disconnect, get_vector, similarity_search, from_documents, create_collection, add_documents, prepare_embedding_table, delete_documents and delete_documents_by_filter. Search accepts metadata_filters, similarity_threshold and include_parents; parent rows are excluded by default. Embeddings remain owned by the existing abstraction.

## Citations

- path: `packages/ai-parrot/src/parrot/stores/abstract.py`
  lines: 117-174,201-325,383-454,454-542
  symbol: `AbstractStore`
  excerpt: |
    async def similarity_search(

- path: `packages/ai-parrot/src/parrot/stores/abstract.py`
  lines: 383-451
  symbol: `generate_embedding / _apply_contextual_augmentation`
  excerpt: |
    return await self._embed_.embed_documents(documents)

- path: `packages/ai-parrot/src/parrot/stores/models.py`
  lines: 19-36
  symbol: `Document / DistanceStrategy`
  excerpt: |
    page_content: str

## Notes

The base accepts PostgreSQL-shaped compatibility parameters. The implementation must define supported mappings or explicit rejection; silently ignoring them would be unsafe. Embedding configuration can cause model loading; local storage alone does not prove offline inference.
