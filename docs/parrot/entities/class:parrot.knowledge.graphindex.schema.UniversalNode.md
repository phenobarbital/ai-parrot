---
type: Wiki Entity
title: UniversalNode
id: class:parrot.knowledge.graphindex.schema.UniversalNode
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: A node in the GraphIndex knowledge graph.
---

# UniversalNode

Defined in [`parrot.knowledge.graphindex.schema`](../summaries/mod:parrot.knowledge.graphindex.schema.md).

```python
class UniversalNode(BaseModel)
```

A node in the GraphIndex knowledge graph.

Args:
    node_id: Globally unique identifier within the tenant graph.
    kind: Semantic category of this node.
    title: Human-readable display name.
    source_uri: URI of the source artefact (file path, URL, etc.).
    content_ref: Optional reference to the full source body (not stored
        inline to keep the graph lightweight).
    summary: Optional short textual summary suitable for embedding.
    embedding_ref: Reference into the FAISS/pgvector index after the
        embedding stage has run (e.g. ``"faiss:42"``).
    domain_tags: Arbitrary key-value metadata from the extractor
        (e.g. ``{"symbol_type": "function"}``, ``{"flat": true}``).
    parent_id: Optional ``node_id`` of the logical parent node.
    provenance: How this node was created.
