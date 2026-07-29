---
type: Wiki Summary
title: parrot_tools.multistoresearch
id: mod:parrot_tools.multistoresearch
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: Multi-store search tool with BM25 reranking.
relates_to:
- concept: class:parrot_tools.multistoresearch.MultiStoreSearchSchema
  rel: defines
- concept: class:parrot_tools.multistoresearch.MultiStoreSearchTool
  rel: defines
- concept: mod:parrot.models
  rel: references
- concept: mod:parrot.models.stores
  rel: references
- concept: mod:parrot.stores.arango
  rel: references
- concept: mod:parrot.stores.faiss_store
  rel: references
- concept: mod:parrot.stores.postgres
  rel: references
- concept: mod:parrot.tools.abstract
  rel: references
---

# `parrot_tools.multistoresearch`

Multi-store search tool with BM25 reranking.

Performs parallel searches across pgVector, FAISS, and ArangoDB, then
applies BM25S (or rank_bm25 fallback) for intelligent reranking and
priority selection.

The concrete vector/graph store classes now ship from
``ai-parrot-embeddings`` (``parrot.stores.*``). They are accepted as
duck-typed instances here — any object exposing an async
``similarity_search(query, limit=...)`` works — so this module never
imports a concrete store at load time. ``StoreType`` is the core
source-of-truth enum from ``parrot.models``.

## Classes

- **`MultiStoreSearchSchema(BaseModel)`** — Input schema for multi-store search tool
- **`MultiStoreSearchTool(AbstractTool)`** — Multi-store search tool with BM25 reranking.
