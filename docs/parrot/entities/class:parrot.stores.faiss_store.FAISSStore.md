---
type: Wiki Entity
title: FAISSStore
id: class:parrot.stores.faiss_store.FAISSStore
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: An in-memory FAISS vector store implementation, completely independent of
  Langchain.
relates_to:
- concept: class:parrot.stores.abstract.AbstractStore
  rel: extends
---

# FAISSStore

Defined in [`parrot.stores.faiss_store`](../summaries/mod:parrot.stores.faiss_store.md).

```python
class FAISSStore(AbstractStore)
```

An in-memory FAISS vector store implementation, completely independent of Langchain.

This store provides high-performance vector similarity search using FAISS indexes
with support for multiple distance metrics and metadata filtering.

Features:
- Multiple FAISS index types (Flat, IVF, HNSW)
- CPU-only execution
- Cosine, L2, and Inner Product distance metrics
- MMR (Maximal Marginal Relevance) search
- Metadata filtering
- Persistent storage via save/load

## Methods

- `def define_collection_table(self, collection_name: str, dimension: int=384, **kwargs) -> Dict[str, Any]` — Define an in-memory collection table for saving vector + metadata information.
- `async def connection(self) -> bool` — Establish connection (for compatibility with AbstractStore).
- `async def disconnect(self) -> None` — Disconnect and cleanup resources.
- `async def prepare_embedding_table(self, collection: str=None, dimension: int=None, **kwargs) -> bool` — Prepare the embedding table/collection for storing vectors.
- `async def create_embedding_table(self, collection: str=None, dimension: int=None, **kwargs) -> None` — Create an embedding table/collection (alias for prepare_embedding_table).
- `async def create_collection(self, collection: str, **kwargs) -> None` — Create a new collection.
- `async def add_documents(self, documents: List[Document], collection: str=None, embedding_column: str=None, content_column: str=None, metadata_column: str=None, **kwargs) -> None` — Add documents to the FAISS store.
- `def get_distance_strategy(self, query_embedding: np.ndarray, metric: str=None) -> str` — Return the appropriate distance strategy based on the metric or configured strategy.
- `async def similarity_search(self, query: str, collection: str=None, k: Optional[int]=None, limit: int=None, metadata_filters: Optional[Dict[str, Any]]=None, score_threshold: Optional[float]=None, metric: str=None, embedding_column: str=None, content_column: str=None, metadata_column: str=None, id_column: str=None, **kwargs) -> List[SearchResult]` — Perform similarity search with optional threshold filtering.
- `async def asearch(self, query: str, collection: Optional[str]=None, k: Optional[int]=None, limit: Optional[int]=None, metadata_filters: Optional[Dict[str, Any]]=None, score_threshold: Optional[float]=None, metric: Optional[str]=None, embedding_column: Optional[str]=None, content_column: Optional[str]=None, metadata_column: Optional[str]=None, id_column: Optional[str]=None, **kwargs) -> List[SearchResult]` — Async alias for :meth:`similarity_search` to match store interface expectations.
- `async def mmr_search(self, query: str, collection: str=None, k: int=4, fetch_k: Optional[int]=None, lambda_mult: float=0.5, metadata_filters: Optional[Dict[str, Any]]=None, score_threshold: Optional[float]=None, metric: str=None, embedding_column: str=None, content_column: str=None, metadata_column: str=None, id_column: str=None, **kwargs) -> List[SearchResult]` — Perform MMR (Maximal Marginal Relevance) search for diversity.
- `def get_vector(self, metric_type: str=None, **kwargs)` — Get the FAISS vector store (for compatibility).
- `async def from_documents(self, documents: List[Document], collection: Union[str, None]=None, **kwargs) -> 'FAISSStore'` — Create Vector Store from Documents.
- `def save(self, file_path: Union[str, Path]) -> None` — Save the FAISS store to disk.
- `def load(self, file_path: Union[str, Path]) -> None` — Load the FAISS store from disk.
- `async def delete_documents(self, document_ids: List[str], collection: str=None, **kwargs) -> None` — Delete documents by their IDs from the FAISS store.
- `async def delete_documents_by_filter(self, filter_func, collection: str=None, **kwargs) -> None` — Delete documents that match a filter function from the FAISS store.
- `async def dump_to_s3(self, key: str, file_manager) -> str` — Serialize the FAISS index to a temp file and upload to S3.
- `async def load_from_s3(cls, key: str, file_manager, **kwargs) -> 'FAISSStore'` — Download a FAISS store tarball from S3 and hydrate a new instance.
