---
type: Wiki Entity
title: GraphIndexLoader
id: class:parrot.knowledge.graphindex.loader.GraphIndexLoader
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Build a GraphIndex graph from a list of files.
relates_to:
- concept: class:parrot.loaders.abstract.AbstractLoader
  rel: extends
---

# GraphIndexLoader

Defined in [`parrot.knowledge.graphindex.loader`](../summaries/mod:parrot.knowledge.graphindex.loader.md).

```python
class GraphIndexLoader(AbstractLoader)
```

Build a GraphIndex graph from a list of files.

Args:
    source: Path, directory, or list of paths to index.
    tenant_id: Tenant identifier used for graph isolation and the default
        ArangoDB database / pgvector schema names.
    client: An ``AbstractClient`` for the optional PageIndex adapter used
        when ``storage_dir`` is set (hierarchical content → sidecars). When
        ``None`` and an adapter is needed, a default client is created.
    model: Model id for that adapter.
    adapter: A pre-built ``PageIndexLLMAdapter`` (overrides ``client``).
    output_dir: Directory for the generated ``GRAPH_REPORT.md``. A temp
        directory is used when omitted.
    embedding_model: Embedding model name (via ``EmbeddingRegistry``).
    embedding_dim: Embedding dimension (must match the model output).
    pgvector_dsn: Optional DSN for durable pgvector embedding storage. When
        ``None`` only the in-memory FAISS index is built.
    detect_communities: Enable Louvain community detection.
    arango: ArangoDB connection dict (alternative to discrete kwargs).
    arango_host / arango_port / arango_protocol / arango_user /
    arango_password / arango_database: Discrete ArangoDB credentials.
        Supplying ``arango`` or **any** of these enables persistence; the
        rest are filled from ``ARANGODB_*`` env vars.
    storage_dir: When set (and an adapter is available), a
        :class:`PageIndexToolkit` is attached so hierarchical documents are
        persisted as PageIndex trees with per-node sidecars.
    **kwargs: Forwarded to :class:`AbstractLoader`.

## Methods

- `async def load(self, source: Optional[Any]=None, split_documents: bool=False, **kwargs: Any) -> List[Document]` — Run the pipeline and return one Document per graph node.
- `async def build_graph(self, source: Optional[Any]=None) -> BuildResult` — Run the full GraphIndex pipeline and return the :class:`BuildResult`.
