"""
DocumentDB Interface.

Provides an async interface for managing DocumentDB/MongoDB connections
using the asyncdb library with Motor driver.

Features:
- Async-first design with proper connection management
- Fire-and-forget background saves with automatic retry
- Failed writes queue for inspection and manual retry
- Streaming iteration for large datasets
- Chunked reading for batch processing
- Async context manager support for clean resource handling

Usage:
    async with DocumentDb() as db:
        await db.write("conversations", {"user": "alice", "message": "hello"})

    # Or for fire-and-forget:
    db = DocumentDb()
    await db.documentdb_connect()
    db.save_background("logs", {"event": "user_login"})
"""
import asyncio
from collections import deque
from collections.abc import AsyncGenerator
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional, Union, Any, List, Dict, Callable

from asyncdb import AsyncDB
from navconfig import config, BASE_DIR
from navconfig.logging import logging


@dataclass
class FailedWrite:
    """
    Represents a failed write operation for later retry or inspection.

    Attributes:
        collection: Name of the target collection
        data: The document(s) that failed to write
        error: The exception that caused the failure
        timestamp: When the failure occurred (UTC)
        retries: Number of retry attempts made
    """
    collection: str
    data: Union[dict, List[dict]]
    error: Exception
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    retries: int = 0

    def __repr__(self) -> str:
        return (
            f"FailedWrite(collection={self.collection!r}, "
            f"error={type(self.error).__name__}, "
            f"retries={self.retries}, "
            f"timestamp={self.timestamp.isoformat()})"
        )


class DocumentDb:
    """
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
    """

    # Class-level defaults for retry behavior
    DEFAULT_MAX_RETRIES = 3
    DEFAULT_FAILED_WRITES_LIMIT = 1000
    DEFAULT_RETRY_BASE_DELAY = 1.0  # seconds

    def __init__(
        self,
        max_retries: int = DEFAULT_MAX_RETRIES,
        failed_writes_limit: int = DEFAULT_FAILED_WRITES_LIMIT,
        retry_base_delay: float = DEFAULT_RETRY_BASE_DELAY,
        **kwargs
    ):
        """
        Initialize the DocumentDb interface.

        Args:
            max_retries: Maximum number of retry attempts for failed writes
            failed_writes_limit: Maximum number of failed writes to keep in queue
            retry_base_delay: Base delay for exponential backoff (seconds)
            **kwargs: Additional arguments (reserved for future use)
        """
        self._document_db: Optional[AsyncDB] = None
        self._connected: bool = False
        self.logger = logging.getLogger('DocumentDb')

        # Retry configuration
        self._max_retries = max_retries
        self._retry_base_delay = retry_base_delay

        # Queue for failed writes - allows inspection and manual retry
        self._failed_writes: deque[FailedWrite] = deque(maxlen=failed_writes_limit)

        # Track active background tasks for graceful shutdown
        self._background_tasks: set[asyncio.Task] = set()

    @property
    def db(self) -> AsyncDB:
        """
        Return the AsyncDB instance, creating it if necessary.

        Note: This creates the connection object but doesn't establish
        the actual network connection. Call documentdb_connect() for that.
        """
        if not self._document_db:
            self._document_db = self._get_connection()
        return self._document_db

    @property
    def is_connected(self) -> bool:
        """Check if we have an active connection."""
        return self._connected and self._document_db is not None

    @property
    def failed_writes(self) -> List[FailedWrite]:
        """
        Get a copy of the failed writes queue for inspection.

        Returns:
            List of FailedWrite objects representing operations that failed
            after all retry attempts were exhausted.
        """
        return list(self._failed_writes)

    @property
    def failed_writes_count(self) -> int:
        """Get the count of failed writes awaiting retry."""
        return len(self._failed_writes)

    @property
    def pending_background_tasks(self) -> int:
        """Get the count of currently running background tasks."""
        # Clean up completed tasks first
        self._background_tasks = {t for t in self._background_tasks if not t.done()}
        return len(self._background_tasks)

    def _get_connection(self) -> AsyncDB:
        """
        Build the AsyncDB connection object from configuration.

        Reads connection parameters from environment variables via navconfig
        and constructs an AsyncDB instance configured for DocumentDB/MongoDB.

        Returns:
            Configured AsyncDB instance (not yet connected)
        """
        # Read credentials from environment (via navconfig)
        host = config.get('DOCUMENTDB_HOSTNAME', fallback='localhost')
        port = config.get('DOCUMENTDB_PORT', fallback=27017)
        username = config.get('DOCUMENTDB_USERNAME')
        password = config.get('DOCUMENTDB_PASSWORD')
        database = config.get('DOCUMENTDB_DBNAME', fallback='navigator')
        use_ssl = config.getboolean('DOCUMENTDB_USE_SSL', fallback=True)
        dbtype = config.get('DOCUMENTDB_DBTYPE', fallback='mongodb')

        # TLS certificate handling - default to AWS global bundle
        tls_ca_file = config.get('DOCUMENTDB_TLS_CA_FILE')
        if not tls_ca_file:
            tls_ca_file = BASE_DIR.joinpath('env', "global-bundle.pem")

        auth_source = config.get('DOCUMENTDB_AUTH_SOURCE', fallback='admin')
        engine = config.get('DOCUMENTDB_ENGINE', fallback='mongo')

        params = {
            "host": host,
            "port": port,
            "username": username,
            "password": password,
            "database": database,
            "ssl": use_ssl,
            "dbtype": dbtype,
            "authsource": auth_source
        }

        if use_ssl and tls_ca_file:
            params["tlsCAFile"] = str(tls_ca_file)

        self.logger.debug(f"Configuring DocumentDB connection to {host}:{port}/{database}")

        # "mongo" is the driver name in asyncdb for mongodb/documentdb
        return AsyncDB(engine, params=params)

    # =========================================================================
    # Connection Management
    # =========================================================================

    async def documentdb_connect(self) -> None:
        """
        Establish connection to DocumentDB.

        This method explicitly opens the connection. It's called automatically
        when using the async context manager protocol.

        Raises:
            ConnectionError: If unable to establish connection
        """
        try:
            await self.db.connection()  # pylint: disable=E1101
            self._connected = True
            self.logger.info("DocumentDB connection established")
        except Exception as e:
            self._connected = False
            self.logger.error(f"Failed to connect to DocumentDB: {e}")
            raise ConnectionError(f"DocumentDB connection failed: {e}") from e

    def documentdb_connection(self):
        """
        Get a context manager for DocumentDB connection.

        Returns the underlying driver connection for use in async with statements.
        Prefer using the class-level async context manager when possible.

        Returns:
            Async context manager yielding the driver connection
        """
        return self.db.connection()  # pylint: disable=E1101

    async def close(self) -> None:
        """
        Close the DocumentDB connection and cleanup resources.

        This method:
        1. Waits for pending background tasks to complete (with timeout)
        2. Closes the database connection
        3. Resets internal state

        Should be called when done with the database, or use async context manager.
        """
        # Wait for background tasks with a reasonable timeout
        if self._background_tasks:
            pending = [t for t in self._background_tasks if not t.done()]
            if pending:
                self.logger.info(f"Waiting for {len(pending)} background tasks to complete...")
                try:
                    await asyncio.wait(pending, timeout=10.0)
                except Exception as e:
                    self.logger.warning(f"Error waiting for background tasks: {e}")

                # Cancel any still-pending tasks
                still_pending = [t for t in pending if not t.done()]
                for task in still_pending:
                    task.cancel()
                    self.logger.warning(f"Cancelled pending background task: {task.get_name()}")

        # Close the database connection
        if self._document_db:
            try:
                await self._document_db.close()  # pylint: disable=E1101
                self.logger.info("DocumentDB connection closed")
            except Exception as e:
                self.logger.warning(f"Error closing DocumentDB connection: {e}")
            finally:
                self._document_db = None
                self._connected = False

    async def __aenter__(self) -> "DocumentDb":
        """Async context manager entry - establishes connection."""
        await self.documentdb_connect()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        """Async context manager exit - closes connection."""
        await self.close()

    # =========================================================================
    # Read Operations
    # =========================================================================

    async def read(
        self,
        collection_name: str,
        query: Optional[dict] = None,
        limit: Optional[int] = None,
        projection: Optional[dict] = None,
        sort: Optional[List[tuple]] = None,
        **kwargs
    ) -> List[dict]:
        """
        Read documents from a collection.

        Args:
            collection_name: Name of the collection to query
            query: MongoDB query filter (default: {} for all documents)
            limit: Maximum number of documents to return
            projection: Fields to include/exclude in results
            sort: List of (field, direction) tuples for sorting
            **kwargs: Additional arguments passed to the driver

        Returns:
            List of documents matching the query

        Raises:
            Exception: On database errors
        """
        if query is None:
            query = {}

        async with await self.db.connection() as conn:  # pylint: disable=E1101
            try:
                result, _ = await conn.query(
                    collection_name=collection_name,
                    query=query,
                    limit=limit,
                    **kwargs
                )
                return result if result else []
            except Exception as e:
                self.logger.error(f"Error reading from {collection_name}: {e}")
                raise

    async def read_one(
        self,
        collection_name: str,
        query: dict,
        **kwargs
    ) -> Optional[dict]:
        """
        Read a single document from a collection.

        Args:
            collection_name: Name of the collection
            query: MongoDB query filter
            **kwargs: Additional arguments passed to the driver

        Returns:
            The matching document, or None if not found
        """
        results = await self.read(collection_name, query, limit=1, **kwargs)
        return results[0] if results else None

    async def exists(self, collection_name: str, query: dict) -> bool:
        """
        Check if a document matching the query exists.

        Args:
            collection_name: Name of the collection
            query: MongoDB query filter

        Returns:
            True if at least one matching document exists
        """
        result = await self.read_one(collection_name, query)
        return result is not None

    # =========================================================================
    # Write Operations
    # =========================================================================

    async def write(
        self,
        collection_name: str,
        data: Union[dict, List[dict]],
        **kwargs
    ) -> Any:
        """
        Write document(s) to a collection.

        Automatically detects whether to use insert_one or insert_many
        based on the input type.

        Args:
            collection_name: Name of the target collection
            data: Single document (dict) or list of documents
            **kwargs: Additional arguments passed to the driver

        Returns:
            Insert result from the driver (contains inserted_id(s))

        Raises:
            Exception: On database errors
        """
        async with await self.db.connection() as conn:  # pylint: disable=E1101
            try:
                # Ensure data is a list if it's a single dict, because asyncdb.write expects Iterable of docs
                if isinstance(data, dict):
                    data = [data]

                return await conn.write(
                    collection=collection_name,
                    data=data,
                    **kwargs
                )
            except Exception as e:
                self.logger.error(f"Error writing to {collection_name}: {e}")
                raise

    async def update(
        self,
        collection_name: str,
        query: dict,
        update_data: dict,
        upsert: bool = False,
        **kwargs
    ) -> Any:
        """
        Update documents matching a query.

        Args:
            collection_name: Name of the target collection
            query: MongoDB query filter to find documents to update
            update_data: Update operations (should include $set, $inc, etc.)
            upsert: If True, insert a new document if no match found
            **kwargs: Additional arguments passed to the driver

        Returns:
            Update result from the driver
        """
        async with await self.db.connection() as conn:  # pylint: disable=E1101
            try:
                if hasattr(conn, 'update'):
                    return await conn.update(
                        collection_name=collection_name,
                        query=query,
                        data=update_data,
                        upsert=upsert,
                        **kwargs
                    )
                else:
                    # Fallback to raw driver if available
                    self.logger.warning(
                        "update() not available on connection wrapper, "
                        "attempting raw driver access"
                    )
                    raise NotImplementedError("Update not supported by current driver")
            except Exception as e:
                self.logger.error(f"Error updating {collection_name}: {e}")
                raise

    async def delete(
        self,
        collection_name: str,
        query: dict,
        **kwargs
    ) -> Any:
        """
        Delete documents matching a query.

        Args:
            collection_name: Name of the target collection
            query: MongoDB query filter (empty dict would delete all!)
            **kwargs: Additional arguments passed to the driver

        Returns:
            Delete result from the driver

        Raises:
            ValueError: If query is empty (safety check)
        """
        if not query:
            raise ValueError(
                "Empty query would delete all documents. "
                "Use delete_all() if this is intentional."
            )

        async with await self.db.connection() as conn:  # pylint: disable=E1101
            try:
                if hasattr(conn, 'delete'):
                    return await conn.delete(
                        collection_name=collection_name,
                        query=query,
                        **kwargs
                    )
                else:
                    self.logger.warning(
                        f"delete() not available on connection wrapper"
                    )
                    raise NotImplementedError("Delete not supported by current driver")
            except Exception as e:
                self.logger.error(f"Error deleting from {collection_name}: {e}")
                raise

    # =========================================================================
    # Background (Fire-and-Forget) Operations
    # =========================================================================

    def save_background(
        self,
        collection_name: str,
        data: Union[dict, List[dict]],
        on_success: Optional[Callable[[Any], None]] = None,
        on_error: Optional[Callable[[Exception], None]] = None
    ) -> asyncio.Task:
        """
        Fire-and-forget save operation with automatic retry.

        This method returns immediately after scheduling the write operation
        as a background task. The actual write happens asynchronously with
        automatic retry on failure using exponential backoff.

        IMPORTANT: Must be called from within an async context (running event loop).

        Args:
            collection_name: Name of the target collection
            data: Document(s) to save
            on_success: Optional callback called with result on successful save
            on_error: Optional callback called with exception after all retries fail

        Returns:
            The asyncio.Task handling the background save

        Raises:
            RuntimeError: If called outside an async context

        Example:
            # Simple fire-and-forget
            db.save_background("logs", {"event": "page_view", "url": "/home"})

            # With callbacks
            db.save_background(
                "important_data",
                document,
                on_success=lambda r: print(f"Saved: {r.inserted_id}"),
                on_error=lambda e: alert_admin(e)
            )
        """
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError as e:
            self.logger.error(
                "save_background() must be called from within an async context"
            )
            raise RuntimeError(
                "save_background() requires a running event loop. "
                "Use 'await write()' for synchronous contexts."
            ) from e

        # Create the background task
        task = loop.create_task(
            self._save_with_retry(collection_name, data, on_success, on_error),
            name=f"bg_save_{collection_name}_{id(data)}"
        )

        # Track the task for graceful shutdown
        self._background_tasks.add(task)
        task.add_done_callback(self._background_tasks.discard)

        return task

    async def _save_with_retry(
        self,
        collection_name: str,
        data: Union[dict, List[dict]],
        on_success: Optional[Callable[[Any], None]] = None,
        on_error: Optional[Callable[[Exception], None]] = None,
        retry_count: int = 0
    ) -> Optional[Any]:
        """
        Internal method that performs the actual save with retry logic.

        Uses exponential backoff: delay = base_delay * (2 ^ retry_count)
        """
        try:
            result = await self.write(collection_name, data)
            self.logger.debug(
                f"Background save to '{collection_name}' successful "
                f"(attempt {retry_count + 1})"
            )
            if on_success:
                try:
                    on_success(result)
                except Exception as cb_error:
                    self.logger.warning(f"on_success callback error: {cb_error}")
            return result

        except Exception as e:
            self.logger.warning(
                f"Background save to '{collection_name}' failed "
                f"(attempt {retry_count + 1}/{self._max_retries + 1}): {e}"
            )

            if retry_count < self._max_retries:
                # Calculate delay with exponential backoff
                delay = self._retry_base_delay * (2 ** retry_count)
                self.logger.debug(f"Retrying in {delay:.1f}s...")
                await asyncio.sleep(delay)

                # Recursive retry
                return await self._save_with_retry(
                    collection_name, data, on_success, on_error, retry_count + 1
                )
            else:
                # All retries exhausted - record the failure
                self.logger.error(
                    f"Background save to '{collection_name}' failed permanently "
                    f"after {self._max_retries + 1} attempts"
                )

                failed_write = FailedWrite(
                    collection=collection_name,
                    data=data,
                    error=e,
                    retries=retry_count + 1
                )
                self._failed_writes.append(failed_write)

                if on_error:
                    try:
                        on_error(e)
                    except Exception as cb_error:
                        self.logger.warning(f"on_error callback error: {cb_error}")

                return None

    async def retry_failed_writes(self) -> Dict[str, int]:
        """
        Retry all failed writes in the queue.

        Attempts to write each failed operation again. Successfully written
        items are removed from the queue; still-failing items are re-queued
        with incremented retry count (up to 2x max_retries for manual retries).

        Returns:
            Dict with 'successful', 'failed', and 'total' counts

        Example:
            result = await db.retry_failed_writes()
            print(f"Recovered {result['successful']} of {result['total']} failed writes")
        """
        if not self._failed_writes:
            return {'successful': 0, 'failed': 0, 'total': 0}

        total = len(self._failed_writes)
        successful = 0
        still_failing = []

        # Process all items currently in queue
        for _ in range(total):
            if not self._failed_writes:
                break
            failed = self._failed_writes.popleft()

            try:
                await self.write(failed.collection, failed.data)
                successful += 1
                self.logger.info(
                    f"Successfully retried failed write to '{failed.collection}'"
                )
            except Exception as e:
                failed.retries += 1
                failed.error = e
                failed.timestamp = datetime.now(timezone.utc)

                # Allow more retries for manual retry than automatic
                max_manual_retries = self._max_retries * 2
                if failed.retries < max_manual_retries:
                    still_failing.append(failed)
                else:
                    self.logger.error(
                        f"Permanently failed write to '{failed.collection}' "
                        f"after {failed.retries} total attempts"
                    )

        # Re-queue items that still failed
        for item in still_failing:
            self._failed_writes.append(item)

        return {
            'successful': successful,
            'failed': len(still_failing),
            'total': total
        }

    def clear_failed_writes(self) -> int:
        """
        Clear all failed writes from the queue.

        Use this to discard failed writes that are no longer relevant.

        Returns:
            Number of failed writes that were cleared
        """
        count = len(self._failed_writes)
        self._failed_writes.clear()
        self.logger.info(f"Cleared {count} failed writes from queue")
        return count

    # =========================================================================
    # Streaming / Iteration Operations
    # =========================================================================

    async def iterate(
        self,
        collection_name: str,
        query: Optional[dict] = None,
        batch_size: int = 100,
        projection: Optional[dict] = None
    ) -> AsyncGenerator[dict, None]:
        """
        Iterate over documents using a cursor (memory-efficient streaming).

        This method yields documents one by one without loading the entire
        result set into memory, making it suitable for processing large
        collections.

        Args:
            collection_name: Name of the collection to iterate
            query: MongoDB query filter (default: {} for all documents)
            batch_size: Number of documents to fetch per batch from server
            projection: Fields to include/exclude

        Yields:
            Individual documents from the collection

        Example:
            async for doc in db.iterate("large_collection", {"status": "pending"}):
                await process_document(doc)
        """
        if query is None:
            query = {}

        async with await self.db.connection() as conn:  # pylint: disable=E1101
            cursor = None

            # Try to get a proper cursor for memory-efficient iteration
            if hasattr(conn, 'get_cursor'):
                cursor = await conn.get_cursor(
                    collection_name, query, batch_size=batch_size
                )
            elif hasattr(conn, '_db'):
                # Direct Motor/PyMongo access
                cursor = conn._db[collection_name].find(query)
                if hasattr(cursor, 'batch_size'):
                    cursor = cursor.batch_size(batch_size)

            if cursor:
                async for document in cursor:
                    yield document
            else:
                # FALLBACK: Load everything into memory
                # This defeats the purpose of streaming!
                self.logger.warning(
                    f"⚠️ Cursor not available for '{collection_name}'. "
                    f"Falling back to full query - ALL DATA WILL BE LOADED INTO MEMORY! "
                    f"Consider using read() with limit for large collections."
                )
                result, _ = await conn.query(
                    collection_name=collection_name, query=query
                )
                for item in (result or []):
                    yield item

    # Alias for API compatibility
    read_batch = iterate

    async def read_chunks(
        self,
        collection_name: str,
        query: Optional[dict] = None,
        chunk_size: int = 100
    ) -> AsyncGenerator[List[dict], None]:
        """
        Yield documents in chunks (batches).

        Useful for batch processing where you want to handle multiple
        documents at once rather than one at a time.

        Args:
            collection_name: Name of the collection
            query: MongoDB query filter
            chunk_size: Number of documents per chunk

        Yields:
            Lists of documents, each list containing up to chunk_size items

        Example:
            async for batch in db.read_chunks("events", chunk_size=500):
                await bulk_process(batch)  # Process 500 at a time
        """
        chunk: List[dict] = []

        async for item in self.iterate(collection_name, query, batch_size=chunk_size):
            chunk.append(item)
            if len(chunk) >= chunk_size:
                yield chunk
                chunk = []

        # Don't forget the last partial chunk
        if chunk:
            yield chunk

    # =========================================================================
    # Collection Management
    # =========================================================================

    async def create_collection(
        self,
        collection_name: str,
        indexes: Optional[List[Union[str, dict]]] = None,
        **kwargs
    ) -> bool:
        """
        Explicitly create a collection.

        Note: DocumentDB/MongoDB automatically creates collections on first write,
        but explicit creation allows setting options and ensuring the collection
        exists before use.

        Args:
            collection_name: Name of the collection to create
            indexes: Optional list of indexes to create (see create_indexes)
            **kwargs: Additional options passed to create_collection

        Returns:
            True if collection was created, False if it already existed
        """
        async with await self.db.connection() as conn:  # pylint: disable=E1101
            try:
                # Try to access the underlying database object
                db_obj = getattr(conn, '_db', getattr(conn, '_database', None))

                if db_obj is not None:
                    await db_obj.create_collection(collection_name, **kwargs)
                    self.logger.info(f"Created collection '{collection_name}'")
                    created = True
                else:
                    # asyncdb might not expose create_collection directly
                    # Collection will be created on first write
                    self.logger.info(
                        f"Cannot explicitly create collection '{collection_name}'. "
                        f"It will be created automatically on first write."
                    )
                    created = False

            except Exception as e:
                error_str = str(e).lower()
                if 'already exists' in error_str or 'namespaceexists' in error_str:
                    self.logger.debug(f"Collection '{collection_name}' already exists")
                    created = False
                else:
                    self.logger.error(f"Error creating collection '{collection_name}': {e}")
                    raise

        # Create indexes if provided
        if indexes:
            await self.create_indexes(collection_name, indexes)

        return created

    @staticmethod
    def _normalize_index_spec(key):
        """Normalize an index spec into (keys, options) for Motor/pymongo.

        Accepts:
            - str: single ascending field  → (field_name, {})
            - tuple: (field, direction)    → ([(field, direction)], {})
            - dict: {"keys": [...], **opts} → (keys_list, opts)

        Returns:
            Tuple of (index_keys, index_options)
        """
        if isinstance(key, str):
            return key, {}
        if isinstance(key, tuple):
            return [key], {}
        if isinstance(key, dict):
            spec = dict(key)  # shallow copy to avoid mutating caller
            index_keys = spec.pop('keys', spec.pop('key', None))
            if index_keys is None:
                raise ValueError(
                    f"Dict index spec must contain 'keys' or 'key': {key}"
                )
            return index_keys, spec
        raise TypeError(f"Unsupported index spec type: {type(key)}")

    async def create_indexes(
        self,
        collection_name: str,
        keys: List[Union[str, tuple, dict]]
    ) -> None:
        """
        Create indexes on a collection.

        Args:
            collection_name: Name of the collection
            keys: Index specifications. Can be:
                  - str: Single field name (ascending index)
                  - tuple: (field_name, direction) where direction is 1 or -1
                  - dict: Full index specification with options

        Example:
            # Simple single-field indexes
            await db.create_indexes("users", ["email", "created_at"])

            # With direction
            await db.create_indexes("events", [("timestamp", -1)])

            # Full specification
            await db.create_indexes("products", [
                {"keys": [("sku", 1)], "unique": True},
                {"keys": [("name", "text")]}  # Text index
            ])
        """
        async with await self.db.connection() as conn:  # pylint: disable=E1101
            try:
                if hasattr(conn, 'create_index'):
                    for key in keys:
                        index_keys, index_opts = self._normalize_index_spec(key)
                        await conn.create_index(
                            collection_name, index_keys, **index_opts
                        )
                        self.logger.debug(
                            f"Created index on '{collection_name}': {key}"
                        )
                elif hasattr(conn, '_db') or hasattr(conn, '_database'):
                    # Direct access to Motor/PyMongo collection
                    db_obj = getattr(
                        conn, '_db', getattr(conn, '_database', None)
                    )
                    collection = db_obj[collection_name]
                    for key in keys:
                        index_keys, index_opts = self._normalize_index_spec(key)
                        await collection.create_index(
                            index_keys, **index_opts
                        )
                        self.logger.debug(
                            f"Created index on '{collection_name}': {key}"
                        )
                else:
                    self.logger.warning(
                        f"Cannot create indexes on '{collection_name}': "
                        f"No index creation method available on connection wrapper"
                    )

            except Exception as e:
                self.logger.error(
                    f"Error creating index on '{collection_name}': {e}"
                )
                raise

    async def create_bucket(self, bucket_name: str, **kwargs) -> Any:
        """
        Create a GridFS bucket for storing large files.

        GridFS is MongoDB's specification for storing large files by splitting
        them into chunks. Each bucket uses two collections: {bucket}.chunks
        and {bucket}.files.

        Args:
            bucket_name: Name of the bucket (default is 'fs')
            **kwargs: Additional options for bucket creation

        Returns:
            The GridFS bucket object if creation successful

        Note:
            GridFS support depends on the underlying driver capabilities.
        """
        async with await self.db.connection() as conn:  # pylint: disable=E1101
            if hasattr(conn, 'create_bucket'):
                bucket = await conn.create_bucket(bucket_name, **kwargs)
                self.logger.info(f"Created GridFS bucket '{bucket_name}'")
                return bucket
            elif hasattr(conn, '_db') or hasattr(conn, '_database'):
                # Try Motor's GridFSBucket
                try:
                    db_obj = getattr(conn, '_db', getattr(conn, '_database', None))
                    from motor.motor_asyncio import AsyncIOMotorGridFSBucket
                    bucket = AsyncIOMotorGridFSBucket(
                        db_obj, bucket_name=bucket_name, **kwargs
                    )
                    self.logger.info(f"Created GridFS bucket '{bucket_name}'")
                    return bucket
                except ImportError:
                    self.logger.warning(
                        "Motor GridFSBucket not available. "
                        "Install motor for GridFS support."
                    )
            else:
                self.logger.warning(
                    f"Cannot create bucket '{bucket_name}': "
                    f"GridFS not supported by current driver configuration"
                )
            return None

    async def list_collections(self) -> List[str]:
        """
        List all collections in the database.

        Returns:
            List of collection names
        """
        async with await self.db.connection() as conn:  # pylint: disable=E1101
            if hasattr(conn, '_db') or hasattr(conn, '_database'):
                db_obj = getattr(conn, '_db', getattr(conn, '_database', None))
                return await db_obj.list_collection_names()
            elif hasattr(conn, 'list_collections'):
                return await conn.list_collections()
            else:
                self.logger.warning("Cannot list collections: method not available")
                return []

    async def drop_collection(self, collection_name: str) -> bool:
        """
        Drop (delete) a collection.

        WARNING: This permanently deletes all documents in the collection!

        Args:
            collection_name: Name of the collection to drop

        Returns:
            True if collection was dropped
        """
        async with await self.db.connection() as conn:  # pylint: disable=E1101
            try:
                if hasattr(conn, '_db') or hasattr(conn, '_database'):
                    db_obj = getattr(conn, '_db', getattr(conn, '_database', None))
                    await db_obj.drop_collection(collection_name)
                elif hasattr(conn, 'drop_collection'):
                    await conn.drop_collection(collection_name)
                else:
                    raise NotImplementedError("drop_collection not available")

                self.logger.info(f"Dropped collection '{collection_name}'")
                return True
            except Exception as e:
                self.logger.error(f"Error dropping collection '{collection_name}': {e}")
                raise
