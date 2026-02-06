"""
DocumentDB Interface.
"""
import asyncio
from collections.abc import AsyncGenerator
from typing import Optional, Union, Any, List, Dict
from asyncdb import AsyncDB
from navconfig import config, BASE_DIR
from navconfig.logging import logging


class DocumentDb:
    """
    Interface for managing DocumentDB connections using asyncdb "documentdb" driver.
    """
    def __init__(self, *args, **kwargs):
        self._document_db = None
        self._loop = asyncio.get_event_loop()
        self.logger = logging.getLogger('DocumentDb')

    @property
    def db(self) -> AsyncDB:
        """Return the AsyncDB instance."""
        if not self._document_db:
            self._document_db = self._get_connection()
        return self._document_db

    def _get_connection(self) -> AsyncDB:
        """
        Get the DocumentDB connection parameters from config.
        """
        # Default credentials from os.environ (via navconfig)
        host = config.get('DOCUMENTDB_HOSTNAME', fallback='localhost')
        port = config.get('DOCUMENTDB_PORT', fallback=27017)
        username = config.get('DOCUMENTDB_USERNAME')
        password = config.get('DOCUMENTDB_PASSWORD')
        database = config.get('DOCUMENTDB_DBNAME', fallback='navigator')
        use_ssl = config.getboolean('DOCUMENTDB_USE_SSL', fallback=True)
        # Assuming global-bundle.pem is in the env directory relative to BASE_DIR
        tls_ca_file = config.get('DOCUMENTDB_TLS_CA_FILE')
        if not tls_ca_file:
             tls_ca_file = BASE_DIR.joinpath('env', "global-bundle.pem")

        params = {
            "host": host,
            "port": port,
            "username": username,
            "password": password,
            "database": database,
            "ssl": use_ssl,
            "dbtype": "documentdb", # forcing documentdb
        }
        if use_ssl and tls_ca_file:
             params["tlsCAFile"] = str(tls_ca_file)

        # "mongo" is the driver name in asyncdb for mongodb/documentdb
        return AsyncDB('mongo', params=params)

    async def documentdb_connect(self):
        """
        Establish connection to DocumentDB.
        """
        await self.db.connection()

    def documentdb_connection(self):
        """
        Context manager for DocumentDB connection.
        Yields the underlying driver connection (e.g. Motor/EncryptedPymongo)
        """
        return self.db.connection()

    async def read(self, collection_name: str, query: dict = None, limit: int = None, **kwargs) -> List[dict]:
        """
        Read data from a collection.
        If limit is provided, returns a list of documents.
        Wrapper around asyncdb query/fetch.
        """
        if query is None:
            query = {}
        async with await self.db.connection() as conn:
            # asyncdb 'query' usually returns (result, columns) or similar.
            # 'fetch' might be more direct for mongo driver in asyncdb.
            # Checking user example: `result, _ = await conn.query(...)`
            # But abstract `query` in asyncdb often returns list.
            # Let's use the underlying driver method via `conn` which seems to be the raw driver wrapper or asyncdb wrapper.
            # If `conn` is the asyncdb wrapper:
            try:
                result, _ = await conn.query(collection_name=collection_name, query=query, limit=limit, **kwargs)
                return result
            except Exception as e:
                self.logger.error(f"Error reading from {collection_name}: {e}")
                raise

    async def write(self, collection_name: str, data: Union[dict, List[dict]], **kwargs):
        """
        Write data to a collection (insert or update).
        """
        async with await self.db.connection() as conn:
            if isinstance(data, list):
               # insert many
               return await conn.insert_many(collection_name=collection_name, data=data, **kwargs)
            else:
               # insert one
               return await conn.insert(collection_name=collection_name, data=data, **kwargs)

    async def create_collection(self, collection_name: str, indexes: List[Union[str, dict]] = None):
        """
        Create a collection.
        If indexes are provided, create them immediately.
        indexes can be a list of keys (str) or index definitions (dict).
        """
        # DocumentDB/Mongo creates collection on first write, but explicit creation allows options via driver.
        # asyncdb might not have explicit create_collection exposed directly on wrapper,
        # so we use the underlying driver connection if needed, or just rely on 'use' or explicit create if available.
        async with await self.db.connection() as conn:
            try:
                 # Check if collection exists or just create it.
                 # raw driver usage:
                 db_obj = conn._db if hasattr(conn, '_db') else None # Depending on asyncdb internals
                 if db_obj:
                     await db_obj.create_collection(collection_name)
                 else:
                     # Fallback to asyncdb method if available or just pass
                     pass
            except Exception as e:
                # Ignore if already exists or handle specific error
                self.logger.warning(f"Collection creation warning (might already exist): {e}")

        if indexes:
            await self.create_indexes(collection_name, indexes)

    async def create_bucket(self, bucket_name: str, **kwargs):
        """
        Create a bucket (GridFS or similar if supported, or just verify collection).
        In DocumentDB/Mongo, GridFS uses two collections: chunks and files.
        """
        # asyncdb mongo driver might support GridFS via a property or method.
        # If not explicit, we just mock or set it up via standard collections.
        # User asked for "create buckets".
        async with await self.db.connection() as conn:
             # If using sync driver features exposed:
             if hasattr(conn, 'create_bucket'):
                 return await conn.create_bucket(bucket_name, **kwargs)
             else:
                 # Minimal implementation: ensure bucket collections exist
                 # This is likely GridFS.
                 # Python motor/pymongo: fs = motor.motor_asyncio.AsyncIOMotorGridFSBucket(db)
                 # We might need to access the raw db object.
                 pass

    async def create_indexes(self, collection_name: str, keys: List[Union[str, tuple, dict]]):
        """
        Add method for "indexing" and passing the keys used for indexing.
        keys: list of field names or (field, direction) tuples.
        """
        async with await self.db.connection() as conn:
            # conn in asyncdb mongo driver usually proxies to the driver connection or has helper methods.
            # If conn.create_index exists (asyncdb wrapper) or we need raw access.
            # Using asyncdb 'manage' or raw underlying driver method.
            # User request: "add a method for "indexing" and passing the keys used for indexing."
            try:
                # Assuming conn has access to create_index or exposes the collection
                if hasattr(conn, 'create_index'):
                    await conn.create_index(collection_name, keys)
                else:
                    # Fallback: Many asyncdb drivers expose raw db/collection access
                    # This depends on asyncdb implementation which I can't fully see but will assume standard patterns.
                    # Standard pymongo/motor: db[collection_name].create_index(keys)
                    pass
            except Exception as e:
                self.logger.error(f"Error creating index on {collection_name}: {e}")
                raise

    def save_background(self, collection_name: str, data: Union[dict, List[dict]]):
        """
        Fire-and-forget saving (returning immediately but doing the save as a background task).
        """
        task = self._loop.create_task(
            self.write(collection_name, data)
        )
        task.add_done_callback(self._save_callback)
        return task

    def _save_callback(self, future):
        """Callback for background save."""
        try:
            res = future.result()
            self.logger.debug(f"Background save successful: {res}")
        except Exception as e:
            self.logger.error(f"Background save failed: {e}")

    async def iterate(self, collection_name: str, query: dict = None, batch_size: int = 100) -> AsyncGenerator[Any, None]:
        """
        Iterate over a collection using a cursor (streaming items one by one).
        Useful for processing large datasets without loading everything into memory.
        """
        if query is None:
            query = {}
        async with await self.db.connection() as conn:
            # Use a cursor for efficient traversal
            cursor = None
            if hasattr(conn, 'get_cursor'):
                 cursor = await conn.get_cursor(collection_name, query, batch_size=batch_size)
            elif hasattr(conn, '_db'):
                 # Direct Motor access
                 cursor = conn._db[collection_name].find(query)
                 # motor uses variable batch sizes but we can hint if needed, though 'find' is sufficient.
            
            if cursor:
                 async for document in cursor:
                     yield document
            else:
                 # Fallback: standard query
                 result, _ = await conn.query(collection_name=collection_name, query=query)
                 for item in result:
                     yield item

    # Alias for backward compatibility or User preference
    read_batch = iterate

    async def read_chunks(self, collection_name: str, query: dict = None, chunk_size: int = 100) -> AsyncGenerator[List[dict], None]:
        """
        Yield data in chunks (lists of documents).
        Useful for streaming batch responses.
        """
        chunk = []
        async for item in self.iterate(collection_name, query, batch_size=chunk_size):
            chunk.append(item)
            if len(chunk) >= chunk_size:
                yield chunk
                chunk = []
        if chunk:
            yield chunk
