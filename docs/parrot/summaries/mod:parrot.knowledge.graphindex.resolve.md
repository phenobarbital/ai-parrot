---
type: Wiki Summary
title: parrot.knowledge.graphindex.resolve
id: mod:parrot.knowledge.graphindex.resolve
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: Cross-domain resolution stage for GraphIndex.
relates_to:
- concept: class:parrot.knowledge.graphindex.resolve.ResolutionConfig
  rel: defines
- concept: func:parrot.knowledge.graphindex.resolve.resolve_cross_domain
  rel: defines
- concept: mod:parrot.knowledge.graphindex.schema
  rel: references
---

# `parrot.knowledge.graphindex.resolve`

Cross-domain resolution stage for GraphIndex.

Level 1 embedding-threshold pass: for each pair of nodes from DIFFERENT
extractors (identified by different source domains), computes cosine
similarity from the FAISS index.  If ``sim > threshold``, emits a
``mentions`` edge with ``provenance=Provenance.INFERRED`` and
``confidence=sim``.

Level 2 LLM verification is deferred to v2.

## Classes

- **`ResolutionConfig`** — Configuration for cross-domain resolution.

## Functions

- `async def resolve_cross_domain(nodes: list[UniversalNode], embedder: object, config: Optional[ResolutionConfig]=None) -> list[UniversalEdge]` — Discover implicit cross-domain edges via embedding similarity.
