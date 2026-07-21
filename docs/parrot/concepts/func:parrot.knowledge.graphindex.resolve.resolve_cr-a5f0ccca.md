---
type: Concept
title: resolve_cross_domain()
id: func:parrot.knowledge.graphindex.resolve.resolve_cross_domain
tags:
- concept
timestamp: '2026-07-16T08:34:12+00:00'
summary: Discover implicit cross-domain edges via embedding similarity.
---

# resolve_cross_domain

```python
async def resolve_cross_domain(nodes: list[UniversalNode], embedder: object, config: Optional[ResolutionConfig]=None) -> list[UniversalEdge]
```

Discover implicit cross-domain edges via embedding similarity.

For each pair of nodes from different extractors (different domain
strings), checks cosine similarity via the FAISS index.  Emits
``mentions`` edges where similarity exceeds the configured threshold.

Args:
    nodes: All nodes from all extractors.
    embedder: A ``GraphIndexEmbedder`` instance with the FAISS index
        already populated (i.e., after the embed stage).
    config: Resolution configuration.  Uses ``ResolutionConfig()``
        defaults if not provided.

Returns:
    List of new ``UniversalEdge`` objects with
    ``provenance=Provenance.INFERRED``.
