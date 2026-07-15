---
type: Wiki Entity
title: DocumentDb
id: class:parrot.interfaces.documentdb.DocumentDb
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Interface for managing DocumentDB connections using asyncdb "documentdb"
  driver.
---

# DocumentDb

Defined in [`parrot.interfaces.documentdb`](../summaries/mod:parrot.interfaces.documentdb.md).

```python
class DocumentDb
```

Interface for managing DocumentDB connections using asyncdb "documentdb" driver.

This class provides a high-level async interface for common DocumentDB operations
including reads, writes, streaming, and background fire-and-forget saves with
automatic retry on failure.

The class supports async context manager protocol for clean resource management:

    async with DocumentDb() as db:
        await db.write("my_collection", {"key": "value"})

Configuration is read from environment variables via navconfig:
    - DOCUMENTDB_HOSTNAME: Database host (default: localhost)
    - DOCUMENTDB_PORT: Database port (default: 27017)
    - DOCUMENTDB_USERNAME: Authentication username
    - DOCUMENTDB_PASSWORD: Authentication password
    - DOCUMENTDB_DBNAME: Database name (default: navigator)
    - DOCUMENTDB_USE_SSL: Enable SSL/TLS (default: True)
    - DOCUMENTDB_TLS_CA_FILE: Path to CA certificate file

## Methods

- `def db(self) -> AsyncDB` — Return the AsyncDB driver instance, creating it if necessary.
- `def is_connected(self) -> bool` — Check if we have an active connection.
- `def failed_writes(self) -> List[FailedWrite]` — Get a copy of the failed writes queue for inspection.
- `def failed_writes_count(self) -> int` — Get the count of failed writes awaiting retry.
- `def pending_background_tasks(self) -> int` — Get the count of currently running background tasks.
- `async def documentdb_connect(self) -> None` — Establish connection to DocumentDB.
- `def documentdb_connection(self)` — Get a context manager for DocumentDB connection.
- `async def close(self) -> None` — Close the DocumentDB connection and cleanup resources.
- `async def get_collection(self, collection_name: str)` — Return a Motor collection handle from the active connection.
- `async def find_documents(self, collection_name: str, query: dict, sort: Optional[List[tuple]]=None, limit: Optional[int]=None, projection: Optional[dict]=None) -> List[dict]` — Query a collection with optional sort/limit using a raw Motor cursor.
- `async def update_one(self, collection_name: str, query: dict, update_data: dict, upsert: bool=False) -> Any` — Update a single document matching the query.
- `async def delete_many(self, collection_name: str, query: dict) -> Any` — Delete all documents matching the query.
- `async def read(self, collection_name: str, query: Optional[dict]=None, limit: Optional[int]=None, projection: Optional[dict]=None, sort: Optional[List[tuple]]=None, **kwargs) -> List[dict]` — Read documents from a collection.
- `async def read_one(self, collection_name: str, query: dict, **kwargs) -> Optional[dict]` — Read a single document from a collection.
- `async def exists(self, collection_name: str, query: dict) -> bool` — Check if a document matching the query exists.
- `async def write(self, collection_name: str, data: Union[dict, List[dict]], **kwargs) -> Any` — Write document(s) to a collection.
- `async def update(self, collection_name: str, query: dict, update_data: dict, upsert: bool=False, **kwargs) -> Any` — Update documents matching a query.
- `async def delete(self, collection_name: str, query: dict, **kwargs) -> Any` — Delete documents matching a query.
- `def save_background(self, collection_name: str, data: Union[dict, List[dict]], on_success: Optional[Callable[[Any], None]]=None, on_error: Optional[Callable[[Exception], None]]=None) -> asyncio.Task` — Fire-and-forget save operation with automatic retry.
- `async def retry_failed_writes(self) -> Dict[str, int]` — Retry all failed writes in the queue.
- `def clear_failed_writes(self) -> int` — Clear all failed writes from the queue.
- `async def iterate(self, collection_name: str, query: Optional[dict]=None, batch_size: int=100, projection: Optional[dict]=None) -> AsyncGenerator[dict, None]` — Iterate over documents using a cursor (memory-efficient streaming).
- `async def read_chunks(self, collection_name: str, query: Optional[dict]=None, chunk_size: int=100) -> AsyncGenerator[List[dict], None]` — Yield documents in chunks (batches).
- `async def create_collection(self, collection_name: str, indexes: Optional[List[Union[str, dict]]]=None, **kwargs) -> bool` — Explicitly create a collection.
- `async def create_indexes(self, collection_name: str, keys: List[Union[str, tuple, dict]]) -> None` — Create indexes on a collection.
- `async def create_bucket(self, bucket_name: str, **kwargs) -> Any` — Create a GridFS bucket for storing large files.
- `async def list_collections(self) -> List[str]` — List all collections in the database.
- `async def drop_collection(self, collection_name: str) -> bool` — Drop (delete) a collection.
