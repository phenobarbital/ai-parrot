---
type: Wiki Entity
title: GraphIndexEmbedder
id: class:parrot.knowledge.graphindex.embed.GraphIndexEmbedder
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Batch-embed UniversalNode summaries and manage vector indices.
---

# GraphIndexEmbedder

Defined in [`parrot.knowledge.graphindex.embed`](../summaries/mod:parrot.knowledge.graphindex.embed.md).

```python
class GraphIndexEmbedder
```

Batch-embed UniversalNode summaries and manage vector indices.

Provides an in-memory FAISS index for fast similarity search and
pgvector persistence for durable storage.

Args:
    model_name: Name of the embedding model to use via
        ``EmbeddingRegistry``.
    dimension: Embedding vector dimension.  Must match the model output.
        Defaults to 384 (all-MiniLM-L6-v2 style).
    pgvector_dsn: Optional DSN for pgvector persistence.  If ``None``,
        only the in-memory FAISS index is populated.

## Methods

- `async def embed_nodes(self, nodes: list[UniversalNode], batch_size: int=64) -> list[UniversalNode]` — Batch-embed nodes and populate ``embedding_ref``.
- `async def search_similar(self, query_text: str, top_k: int=10) -> list[tuple[str, float]]` — Search for similar nodes by text query using FAISS.
- `def get_embedding(self, node_id: str) -> Optional[np.ndarray]` — Retrieve the embedding vector for a specific node.
