---
type: Wiki Entity
title: PgVectorStore
id: class:parrot.stores.postgres.PgVectorStore
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: A PostgreSQL vector store implementation using pgvector, completely independent
  of Langchain.
relates_to:
- concept: class:parrot.stores.abstract.AbstractStore
  rel: extends
---

# PgVectorStore

Defined in [`parrot.stores.postgres`](../summaries/mod:parrot.stores.postgres.md).

```python
class PgVectorStore(AbstractStore)
```

A PostgreSQL vector store implementation using pgvector, completely independent of Langchain.
This store interacts directly with a specified schema and table for robust data isolation.

## Methods

- `def get_id_column(self, use_uuid: bool) -> sqlalchemy.Column` — Return the ID column definition based on whether to use UUID or not.
- `def define_collection_table(self, table: str, schema: str, dimension: int=384, metadata: Optional[MetaData]=None, use_uuid: bool=False, id_column: str='id', embedding_column: str='embedding') -> sqlalchemy.Table` — Dynamically define a SQLAlchemy Table for pgvector storage.
- `async def connection(self, dsn: str=None) -> AsyncEngine` — Establishes and returns an async database connection.
- `async def get_session(self) -> AsyncSession` — Get a session from the pool. This is the main method for getting connections.
- `async def session(self)` — Context manager for handling database sessions with proper cleanup.
- `async def initialize_database(self)` — Initialize pgvector extension and detect index tuning.
- `async def disconnect(self) -> None` — Completely dispose of the engine and close all connections.
- `async def add_documents(self, documents: List[Document], table: str=None, schema: str=None, embedding_column: str='embedding', content_column: str='document', metadata_column: str='cmetadata', metadata_filters: Optional[Dict[str, Any]]=None, **kwargs) -> None` — Embeds and adds documents to the specified table.
- `def get_distance_strategy(self, embedding_column_obj, query_embedding, metric: str=None) -> Any` — Return the appropriate distance expression based on the metric or configured strategy.
- `async def similarity_search(self, query: str, table: str=None, schema: str=None, k: Optional[int]=None, limit: int=None, metadata_filters: Optional[Dict[str, Any]]=None, score_threshold: Optional[float]=None, metric: str=None, embedding_column: str='embedding', content_column: str='document', metadata_column: str='cmetadata', id_column: str='id', additional_columns: Optional[List[str]]=None, include_parents: bool=False) -> List[SearchResult]` — Perform similarity search with optional threshold filtering.
- `def get_vector(self, metric_type: str=None, **kwargs)`
- `async def drop_collection(self, table: str, schema: str='public') -> None` — Drops the specified table in the given schema.
- `async def prepare_embedding_table(self, table: str, schema: str='public', conn: AsyncEngine=None, id_column: str='id', embedding_column: str='embedding', document_column: str='document', metadata_column: str='cmetadata', dimension: int=768, colbert_dimension: int=128, use_jsonb: bool=True, drop_columns: bool=False, create_all_indexes: bool=True, **kwargs)` — Prepare a Postgres Table as an embedding table in PostgreSQL with advanced features.
- `async def create_embedding_table(self, table: str, columns: List[str], schema: str='public', embedding_column: str='embedding', document_column: str='document', metadata_column: str='cmetadata', dimension: int=None, id_column: str='id', use_jsonb: bool=False, drop_columns: bool=True, create_all_indexes: bool=True, **kwargs)` — Create an embedding table in PostgreSQL with advanced features.
- `async def add_colbert_document(self, document_id: str, content: str, token_embeddings: np.ndarray, table: str, schema: str='public', metadata: Optional[Dict[str, Any]]=None, document_column: str='document', metadata_column: str='cmetadata', id_column: str='id', **kwargs) -> None` — Add a document with ColBERT token embeddings to the specified table.
- `async def colbert_search(self, query_tokens: np.ndarray, table: str, schema: str='public', top_k: int=10, metadata_filters: Optional[Dict[str, Any]]=None, min_tokens: Optional[int]=None, max_tokens: Optional[int]=None, id_column: str='id', document_column: str='document', metadata_column: str='cmetadata', additional_columns: Optional[List[str]]=None) -> List[SearchResult]` — Perform ColBERT search with late interaction using MaxSim scoring.
- `async def hybrid_search(self, query: str, query_tokens: Optional[np.ndarray]=None, table: str=None, schema: str=None, top_k: int=10, dense_weight: float=0.7, colbert_weight: float=0.3, metadata_filters: Optional[Dict[str, Any]]=None, **kwargs) -> List[SearchResult]` — Perform hybrid search combining dense embeddings and ColBERT token matching.
- `async def mmr_search(self, query: str, table: str=None, schema: str=None, k: int=10, fetch_k: int=None, lambda_mult: float=0.5, metadata_filters: Optional[Dict[str, Any]]=None, score_threshold: Optional[float]=None, metric: str=None, embedding_column: str='embedding', content_column: str='document', metadata_column: str='cmetadata', id_column: str='id', additional_columns: Optional[List[str]]=None, include_parents: bool=False) -> List[SearchResult]` — Perform Maximal Marginal Relevance (MMR) search to balance relevance and diversity.
- `async def delete_documents(self, documents: Optional[List[Document]]=None, pk: str='source_type', values: Optional[Union[str, List[str]]]=None, table: Optional[str]=None, schema: Optional[str]=None, metadata_column: Optional[str]=None, **kwargs) -> int` — Delete documents from the vector store based on metadata field values.
- `async def delete_documents_by_filter(self, filter_dict: Dict[str, Union[str, List[str]]], table: Optional[str]=None, schema: Optional[str]=None, metadata_column: Optional[str]=None, **kwargs) -> int` — Delete documents based on multiple metadata field conditions.
- `async def delete_all_documents(self, table: Optional[str]=None, schema: Optional[str]=None, confirm: bool=False, **kwargs) -> int` — Delete ALL documents from the vector store table.
- `async def delete_documents_by_ids(self, document_ids: List[str], table: Optional[str]=None, schema: Optional[str]=None, id_column: Optional[str]=None, **kwargs) -> int` — Delete documents by their IDs.
- `async def count_documents_by_filter(self, filter_dict: Dict[str, Union[str, List[str]]], table: Optional[str]=None, schema: Optional[str]=None, metadata_column: Optional[str]=None, **kwargs) -> int` — Count documents that would be affected by a filter (useful before deletion).
- `async def from_documents(self, documents: List[Document], table: str=None, schema: str=None, embedding_column: str='embedding', content_column: str='document', metadata_column: str='cmetadata', chunk_size: int=8192, chunk_overlap: int=200, store_full_document: bool=True, **kwargs) -> Dict[str, Any]` — Add documents using late chunking strategy.
- `async def document_search(self, query: str, table: str=None, schema: str=None, limit: int=10, search_chunks: bool=True, search_full_docs: bool=False, rerank_with_context: bool=True, context_window: int=2, **kwargs) -> List[SearchResult]` — Search with late chunking context awareness.
- `async def collection_exists(self, table: str, schema: str='public') -> bool` — Check if a collection (table) exists in the database.
- `async def delete_collection(self, table: str, schema: str='public') -> None` — Delete a collection (table) from the database.
- `async def create_collection(self, table: str, schema: str='public', dimension: int=768, index_type: str='COSINE', metric_type: str='L2', id_column: Optional[str]=None, **kwargs) -> None` — Create a new collection (table) in the database.
