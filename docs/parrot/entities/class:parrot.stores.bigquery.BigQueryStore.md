---
type: Wiki Entity
title: BigQueryStore
id: class:parrot.stores.bigquery.BigQueryStore
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: A BigQuery vector store implementation for storing and searching embeddings.
relates_to:
- concept: class:parrot.stores.abstract.AbstractStore
  rel: extends
---

# BigQueryStore

Defined in [`parrot.stores.bigquery`](../summaries/mod:parrot.stores.bigquery.md).

```python
class BigQueryStore(AbstractStore)
```

A BigQuery vector store implementation for storing and searching embeddings.
This store provides vector similarity search capabilities using BigQuery's ML functions.

## Methods

- `def get_vector(self, metric_type: str=None, **kwargs)`
- `async def connection(self)` — Initialize BigQuery client.
- `async def initialize_database(self)` — Initialize BigQuery dataset and any required setup.
- `async def dataset_exists(self, dataset: str=None) -> bool` — Check if a dataset exists in BigQuery.
- `async def create_dataset(self, dataset: str=None, location: str='US') -> Any` — Create a new dataset in BigQuery.
- `async def collection_exists(self, table: str, dataset: str=None) -> bool` — Check if a collection (table) exists in BigQuery.
- `async def create_collection(self, table: str, dataset: str=None, dimension: int=768, id_column: str=None, embedding_column: str=None, document_column: str=None, metadata_column: str=None, **kwargs) -> None` — Create a new collection (table) in BigQuery.
- `async def drop_collection(self, table: str, dataset: str=None) -> None` — Drops the specified table in the given dataset.
- `async def prepare_embedding_table(self, table: str, dataset: str=None, dimension: int=768, id_column: str='id', embedding_column: str='embedding', document_column: str='document', metadata_column: str='metadata', **kwargs) -> bool` — Prepare an existing BigQuery table for embedding storage.
- `async def add_documents(self, documents: List[Document], table: str=None, dataset: str=None, embedding_column: str='embedding', content_column: str='document', metadata_column: str='metadata', **kwargs) -> None` — Add documents to BigQuery table with embeddings.
- `async def similarity_search(self, query: str, table: str=None, dataset: str=None, k: Optional[int]=None, limit: int=None, metadata_filters: Optional[Dict[str, Any]]=None, score_threshold: Optional[float]=None, metric: str=None, embedding_column: str='embedding', content_column: str='document', metadata_column: str='metadata', id_column: str='id', **kwargs) -> List[SearchResult]` — Perform similarity search using BigQuery ML functions.
- `async def mmr_search(self, query: str, table: str=None, dataset: str=None, k: int=10, fetch_k: int=None, lambda_mult: float=0.5, metadata_filters: Optional[Dict[str, Any]]=None, score_threshold: Optional[float]=None, metric: str=None, embedding_column: str='embedding', content_column: str='document', metadata_column: str='metadata', id_column: str='id', **kwargs) -> List[SearchResult]` — Perform Maximal Marginal Relevance (MMR) search.
- `async def delete_documents(self, documents: Optional[List[Document]]=None, pk: str='source_type', values: Optional[Union[str, List[str]]]=None, table: Optional[str]=None, dataset: Optional[str]=None, metadata_column: Optional[str]=None, **kwargs) -> int` — Delete documents from BigQuery table based on metadata field values.
- `async def delete_documents_by_filter(self, filter_dict: Dict[str, Union[str, List[str]]], table: Optional[str]=None, dataset: Optional[str]=None) -> int` — Deletes documents based on multiple metadata field conditions.
- `async def delete_documents_by_ids(self, document_ids: List[str], table: Optional[str]=None, dataset: Optional[str]=None, id_column: Optional[str]=None, **kwargs) -> int` — Delete documents by their IDs.
- `async def delete_all_documents(self, table: Optional[str]=None, dataset: Optional[str]=None, confirm: bool=False, **kwargs) -> int` — Delete ALL documents from the BigQuery table.
- `async def count_documents_by_filter(self, filter_dict: Dict[str, Union[str, List[str]]], table: Optional[str]=None, dataset: Optional[str]=None, metadata_column: Optional[str]=None, **kwargs) -> int` — Count documents that would be affected by a filter.
- `async def delete_collection(self, table: str, dataset: str=None) -> None` — Delete a collection (table) from BigQuery.
- `async def from_documents(self, documents: List[Document], table: str=None, dataset: str=None, embedding_column: str='embedding', content_column: str='document', metadata_column: str='metadata', chunk_size: int=8192, chunk_overlap: int=200, store_full_document: bool=True, **kwargs) -> Dict[str, Any]` — Add documents using late chunking strategy (if available).
- `async def disconnect(self) -> None` — Disconnect from BigQuery (cleanup resources).
