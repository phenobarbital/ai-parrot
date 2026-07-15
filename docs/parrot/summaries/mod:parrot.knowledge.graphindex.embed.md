---
type: Wiki Summary
title: parrot.knowledge.graphindex.embed
id: mod:parrot.knowledge.graphindex.embed
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: Embedding stage for GraphIndex.
relates_to:
- concept: class:parrot.knowledge.graphindex.embed.GraphIndexEmbedder
  rel: defines
- concept: mod:parrot.embeddings.registry
  rel: references
- concept: mod:parrot.knowledge.graphindex.schema
  rel: references
- concept: mod:parrot.utils.faiss_logging
  rel: references
---

# `parrot.knowledge.graphindex.embed`

Embedding stage for GraphIndex.

Batch-embeds ``UniversalNode`` summaries and titles via
``EmbeddingModel.encode()``, builds an in-memory FAISS index for fast
similarity search, and persists embeddings to pgvector for durable storage.

## Classes

- **`GraphIndexEmbedder`** — Batch-embed UniversalNode summaries and manage vector indices.
