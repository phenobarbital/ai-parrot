---
type: Wiki Summary
title: parrot.rerankers.models
id: mod:parrot.rerankers.models
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: Pydantic data models for the reranker subsystem.
relates_to:
- concept: class:parrot.rerankers.models.RerankedDocument
  rel: defines
- concept: class:parrot.rerankers.models.RerankerConfig
  rel: defines
- concept: mod:parrot.models.stores
  rel: references
---

# `parrot.rerankers.models`

Pydantic data models for the reranker subsystem.

This module defines the data structures used by all reranker implementations:
- ``RerankedDocument``: a ``SearchResult`` enriched with reranker scoring metadata.
- ``RerankerConfig``: construction configuration for ``LocalCrossEncoderReranker``.

## Classes

- **`RerankedDocument(BaseModel)`** — A SearchResult enriched with reranker scoring.
- **`RerankerConfig(BaseModel)`** — Construction configuration for LocalCrossEncoderReranker.
