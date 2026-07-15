---
type: Wiki Entity
title: AbstractStore
id: class:parrot.stores.abstract.AbstractStore
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: AbstractStore class.
---

# AbstractStore

Defined in [`parrot.stores.abstract`](../summaries/mod:parrot.stores.abstract.md).

```python
class AbstractStore(ABC)
```

AbstractStore class.

    Base class for all Database Vector Stores.
Args:
    embeddings (str): Embedding name.

Supported Vector Stores:
    - Qdrant
    - Milvus
    - Faiss
    - Chroma
    - PgVector

## Methods

- `def connected(self) -> bool`
- `def is_connected(self)`
- `async def connection(self) -> tuple`
- `def get_connection(self) -> Any`
- `def engine(self)`
- `async def disconnect(self) -> None`
- `def get_vector(self, metric_type: str=None, **kwargs)`
- `def get_vectorstore(self)`
- `async def similarity_search(self, query: str, collection: Union[str, None]=None, limit: int=2, similarity_threshold: float=0.0, search_strategy: str='auto', metadata_filters: Union[dict, None]=None, include_parents: bool=False, **kwargs) -> list` — Perform a vector similarity search.
- `async def from_documents(self, documents: List[Any], collection: Union[str, None]=None, **kwargs) -> Callable` — Create Vector Store from Documents.
- `async def create_collection(self, collection: str) -> None` — Create Collection in Vector Store.
- `async def add_documents(self, documents: List[Any], collection: Union[str, None]=None, **kwargs) -> None` — Add Documents to Vector Store.
- `def create_embedding(self, embedding_model: dict, **kwargs)` — Create Embedding Model (via EmbeddingRegistry for deduplication).
- `def get_default_embedding(self)` — Return the default embedding model via the registry.
- `async def generate_embedding(self, documents: List[Any]) -> List[Any]`
- `async def prepare_embedding_table(self, tablename: str, conn: Any=None, embedding_column: str='embedding', document_column: str='document', metadata_column: str='cmetadata', dimension: int=None, id_column: str='id', use_jsonb: bool=True, drop_columns: bool=False, create_all_indexes: bool=True, **kwargs)` — Prepare a Table as an embedding table with advanced features.
- `async def delete_documents(self, documents: Optional[Any]=None, pk: str='source_type', values: Optional[Union[str, List[str]]]=None, table: Optional[str]=None, schema: Optional[str]=None, collection: Optional[str]=None, **kwargs) -> int` — Delete Documents from the Vector Store.
- `async def delete_documents_by_filter(self, search_filter: Dict[str, Union[str, List[str]]], table: Optional[str]=None, schema: Optional[str]=None, collection: Optional[str]=None, **kwargs) -> int` — Delete Documents by filter.
