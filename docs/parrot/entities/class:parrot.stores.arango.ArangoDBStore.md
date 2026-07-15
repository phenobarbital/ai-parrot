---
type: Wiki Entity
title: ArangoDBStore
id: class:parrot.stores.arango.ArangoDBStore
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: ArangoDB Vector Store with native graph support.
relates_to:
- concept: class:parrot.stores.abstract.AbstractStore
  rel: extends
---

# ArangoDBStore

Defined in [`parrot.stores.arango`](../summaries/mod:parrot.stores.arango.md).

```python
class ArangoDBStore(AbstractStore)
```

ArangoDB Vector Store with native graph support.

Features:
- Multi-model database (documents, graphs, key-value)
- Native graph operations for knowledge graphs
- ArangoSearch for full-text and vector search
- Hybrid search combining semantic and keyword
- Graph-enhanced RAG with relationship context

## Methods

- `async def connection(self) -> tuple` — Establish connection to ArangoDB.
- `async def disconnect(self) -> None` — Close ArangoDB connection.
- `def get_vector(self, metric_type: str=None, **kwargs)` — Get vector store instance.
- `async def create_database(self, database_name: str) -> bool` — Create a new database.
- `async def drop_database(self, database_name: str) -> bool` — Drop a database.
- `async def use_database(self, database_name: str) -> None` — Switch to a different database.
- `async def create_collection(self, collection: str, edge: bool=False, **kwargs) -> bool` — Create a collection (document or edge).
- `async def delete_collection(self, collection: str) -> bool` — Drop a collection.
- `async def collection_exists(self, collection: str) -> bool` — Check if collection exists.
- `async def create_graph(self, graph_name: str, vertex_collections: List[str], edge_collection: str=None, orphan_collections: List[str]=None) -> bool` — Create a named graph.
- `async def drop_graph(self, graph_name: str, drop_collections: bool=False) -> bool` — Drop a graph.
- `async def graph_exists(self, graph_name: str) -> bool` — Check if graph exists.
- `async def create_view(self, view_name: str, collections: List[str], text_fields: List[str]=None, vector_field: str=None, analyzer: str=None, **kwargs) -> bool` — Create an ArangoSearch view.
- `async def drop_view(self, view_name: str) -> bool` — Drop an ArangoSearch view.
- `async def add_document(self, document: Union[Document, dict], collection: str=None, upsert: bool=True, upsert_key: Optional[str]=None, upsert_metadata_keys: Optional[List[str]]=None, **kwargs) -> Dict[str, Any]` — Add a single document with upsert support.
- `async def add_documents(self, documents: List[Union[Document, dict]], collection: str=None, upsert: bool=True, batch_size: int=100, **kwargs) -> int` — Add multiple documents.
- `async def save_documents(self, documents: List[Union[Document, dict]], collection: str=None, **kwargs) -> int` — Save documents with upsert (alias for add_documents with upsert=True).
- `async def delete_documents_by_filter(self, filter_dict: Dict[str, Any], collection: str=None, **kwargs) -> int` — Delete documents matching filter conditions.
- `async def similarity_search(self, query: str, collection: str=None, limit: int=10, similarity_threshold: float=0.0, search_strategy: str='auto', metadata_filters: Union[dict, None]=None, include_graph_context: bool=False, **kwargs) -> List[SearchResult]` — Perform vector similarity search.
- `async def fulltext_search(self, query: str, collection: str=None, text_fields: List[str]=None, limit: int=10, min_score: float=0.0, analyzer: str=None, metadata_filters: dict=None, **kwargs) -> List[SearchResult]` — Perform full-text search using BM25.
- `async def hybrid_search(self, query: str, collection: str=None, limit: int=10, text_weight: float=0.5, vector_weight: float=0.5, text_fields: List[str]=None, analyzer: str=None, metadata_filters: dict=None, **kwargs) -> List[SearchResult]` — Perform hybrid search combining vector and text.
- `async def document_search(self, query: str, search_type: str='similarity', collection: str=None, limit: int=10, **kwargs) -> List[SearchResult]` — Unified document search interface.
- `async def from_documents(self, documents: List[Any], collection: Union[str, None]=None, **kwargs) -> 'ArangoDBStore'` — Create vector store from documents.
- `async def prepare_embedding_table(self, collection: str=None, recreate: bool=False, **kwargs) -> bool` — Prepare collection for vector storage.
