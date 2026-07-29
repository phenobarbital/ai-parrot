---
type: Wiki Entity
title: VectorStoreSearchTool
id: class:parrot.tools.vectorstoresearch.VectorStoreSearchTool
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: A tool for performing similarity search on vector stores.
relates_to:
- concept: class:parrot.tools.abstract.AbstractTool
  rel: extends
---

# VectorStoreSearchTool

Defined in [`parrot.tools.vectorstoresearch`](../summaries/mod:parrot.tools.vectorstoresearch.md).

```python
class VectorStoreSearchTool(AbstractTool)
```

A tool for performing similarity search on vector stores.

This tool creates a vector store instance based on the provided StoreConfig
and performs similarity searches to find documents relevant to user queries.

Example usage:
    config = StoreConfig(
        vector_store='postgres',
        table='products',
        schema='gorillashed',
        embedding_model={"model": "BAAI/bge-base-en-v1.5", "model_type": "huggingface"},
        dimension=768,
        dsn=asyncpg_sqlalchemy_url,
        auto_create=False
    )
    tool = VectorStoreSearchTool(store_config=config)
    result = await tool.execute(query="Find products similar to...")

## Methods

- `def store(self) -> AbstractStore` — Get or create the vector store instance.
- `async def search(self, query: str, limit: int=10, score_threshold: Optional[float]=None, metadata_filters: Optional[Dict[str, Any]]=None, use_mmr: bool=False, lambda_mult: float=0.5) -> ToolResult` — Convenience method for executing a search.
