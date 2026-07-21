---
type: Wiki Entity
title: MilvusStore
id: class:parrot.stores.milvus.MilvusStore
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: A Milvus vector store implementation using pymilvus MilvusClient.
relates_to:
- concept: class:parrot.stores.abstract.AbstractStore
  rel: extends
---

# MilvusStore

Defined in [`parrot.stores.milvus`](../summaries/mod:parrot.stores.milvus.md).

```python
class MilvusStore(AbstractStore)
```

A Milvus vector store implementation using pymilvus MilvusClient.

This store interacts with a Milvus instance for vector similarity search,
document management, and collection operations.

## Methods

- `async def connection(self) -> None` — Establish connection to the Milvus server.
- `async def disconnect(self) -> None` — Close the Milvus connection.
- `async def initialize_database(self) -> None` — Initialize database-level resources.
- `def get_distance_strategy(self, metric: Optional[str]=None, **kwargs) -> str` — Return the Milvus metric type string for the current strategy.
- `def get_vector(self, metric_type: str=None, **kwargs)` — Return the underlying MilvusClient instance.
- `async def collection_exists(self, collection: str=None) -> bool` — Check whether a collection exists in Milvus.
- `async def create_collection(self, collection: str=None, dimension: int=None, metric_type: str=None, index_type: str=None, **kwargs) -> None` — Create a new collection in Milvus with a vector index.
- `async def drop_collection(self, collection: str=None) -> None` — Drop a collection from Milvus.
- `async def create_embedding_table(self, collection: str=None, dimension: int=None, metric_type: str=None, index_type: str=None, **kwargs) -> None` — Alias for ``create_collection`` to match PgVectorStore interface.
- `async def prepare_embedding_table(self, tablename: str, conn: Any=None, embedding_column: str='embedding', document_column: str='document', metadata_column: str='metadata', dimension: int=None, id_column: str='id', use_jsonb: bool=True, drop_columns: bool=False, create_all_indexes: bool=True, **kwargs) -> None` — Prepare a collection as an embedding table.
- `async def add_documents(self, documents: List[Document], collection: str=None, **kwargs) -> None` — Add documents to a Milvus collection.
- `async def from_documents(self, documents: List[Any], collection: str=None, **kwargs) -> 'MilvusStore'` — Create the collection (if needed) and add documents.
- `async def update_documents_by_filter(self, updates: Dict[str, Any], filter_dict: Dict[str, Any], collection: str=None, **kwargs) -> int` — Update documents matching a metadata filter.
- `async def delete_documents(self, documents: Optional[List[Document]]=None, pk: str='source_type', values: Optional[Union[str, List[str]]]=None, table: Optional[str]=None, schema: Optional[str]=None, collection: Optional[str]=None, **kwargs) -> int` — Delete documents by metadata field values.
- `async def delete_documents_by_filter(self, search_filter: Dict[str, Union[str, List[str]]], table: Optional[str]=None, schema: Optional[str]=None, collection: Optional[str]=None, **kwargs) -> int` — Delete documents matching multiple metadata conditions.
- `async def delete_documents_by_ids(self, document_ids: List[str], collection: Optional[str]=None, **kwargs) -> int` — Delete documents by their primary key IDs.
- `async def similarity_search(self, query: str, collection: str=None, limit: int=10, similarity_threshold: float=0.0, search_strategy: str='auto', metadata_filters: Optional[Dict[str, Any]]=None, metric: str=None, additional_columns: Optional[List[str]]=None, **kwargs) -> List[SearchResult]` — Perform vector similarity search against a Milvus collection.
- `async def document_search(self, query: str, collection: str=None, limit: int=10, search_chunks: bool=True, search_full_docs: bool=False, **kwargs) -> List[SearchResult]` — Search with chunk-awareness support.
