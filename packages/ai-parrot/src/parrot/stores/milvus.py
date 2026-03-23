"""
MilvusStore: Vector Store implementation using Milvus.

Provides vector similarity search with:
- Milvus collection management
- Multiple distance metrics (Cosine, L2, Inner Product)
- Metadata filtering via dynamic fields
- Async context manager support
- Document CRUD operations
"""
from typing import Any, Dict, List, Optional, Union, Callable
import uuid
import numpy as np
from navconfig.logging import logging

try:
    from pymilvus import (
        MilvusClient,
        CollectionSchema,
        FieldSchema,
        DataType,
    )
    MILVUS_AVAILABLE = True
except ImportError:
    MILVUS_AVAILABLE = False

from .abstract import AbstractStore
from .models import Document, SearchResult, DistanceStrategy
from ..conf import (
    MILVUS_HOST,
    MILVUS_PORT,
    MILVUS_PROTOCOL,
    MILVUS_URL,
    MILVUS_TOKEN,
    MILVUS_USER,
    MILVUS_PASSWORD,
    MILVUS_SECURE,
    MILVUS_SERVER_NAME,
    MILVUS_CA_CERT,
    MILVUS_SERVER_CERT,
    MILVUS_SERVER_KEY,
    MILVUS_USE_TLSv2,
)

# Mapping from DistanceStrategy to Milvus metric types
_METRIC_MAP = {
    DistanceStrategy.COSINE: "COSINE",
    DistanceStrategy.EUCLIDEAN_DISTANCE: "L2",
    DistanceStrategy.MAX_INNER_PRODUCT: "IP",
    DistanceStrategy.DOT_PRODUCT: "IP",
    DistanceStrategy.JACCARD: "JACCARD",
}

_STR_METRIC_MAP = {
    "COSINE": "COSINE",
    "L2": "L2",
    "EUCLIDEAN": "L2",
    "EUCLIDEAN_DISTANCE": "L2",
    "IP": "IP",
    "DOT": "IP",
    "DOT_PRODUCT": "IP",
    "MAX_INNER_PRODUCT": "IP",
    "JACCARD": "JACCARD",
}


class MilvusStore(AbstractStore):
    """
    A Milvus vector store implementation using pymilvus MilvusClient.

    This store interacts with a Milvus instance for vector similarity search,
    document management, and collection operations.
    """

    def __init__(
        self,
        collection_name: str = "default",
        id_column: str = "id",
        embedding_column: str = "embedding",
        document_column: str = "document",
        text_column: str = "text",
        metadata_column: str = "metadata",
        embedding_model: Union[dict, str] = "sentence-transformers/all-mpnet-base-v2",
        embedding: Optional[Callable] = None,
        distance_strategy: DistanceStrategy = DistanceStrategy.COSINE,
        index_type: str = "IVF_FLAT",
        nlist: int = 128,
        nprobe: int = 16,
        ef_construction: int = 200,
        ef: int = 100,
        auto_create: bool = False,
        uri: Optional[str] = None,
        token: Optional[str] = None,
        **kwargs
    ):
        """
        Initialize MilvusStore.

        Args:
            collection_name: Name of the Milvus collection.
            id_column: Name of the primary key field.
            embedding_column: Name of the vector field.
            document_column: Name of the document content field.
            text_column: Name of the text field.
            metadata_column: Name of the metadata field (stored as JSON string).
            embedding_model: Embedding model configuration.
            embedding: Custom embedding callable.
            distance_strategy: Distance metric to use.
            index_type: Milvus index type (IVF_FLAT, HNSW, FLAT, etc.).
            nlist: Number of clusters for IVF indexes.
            nprobe: Number of clusters to probe for IVF search.
            ef_construction: HNSW construction parameter.
            ef: HNSW search parameter.
            auto_create: Automatically create collection on connect if missing.
            uri: Milvus server URI. If not provided, built from config.
            token: Authentication token. If not provided, read from config.
        """
        if not MILVUS_AVAILABLE:
            raise ImportError(
                "pymilvus is not installed. Install it with: pip install pymilvus"
            )

        self._id_column: str = id_column
        self._embedding_column: str = embedding_column
        self._document_column: str = document_column
        self._text_column: str = text_column
        self._metadata_column: str = metadata_column
        self.distance_strategy = distance_strategy
        self._index_type: str = index_type
        self._nlist: int = nlist
        self._nprobe: int = nprobe
        self._ef_construction: int = ef_construction
        self._ef: int = ef
        self._auto_create: bool = auto_create

        # Build URI from config if not provided
        if uri:
            self._uri = uri
        elif MILVUS_URL:
            self._uri = MILVUS_URL
        else:
            self._uri = f"{MILVUS_PROTOCOL}://{MILVUS_HOST}:{MILVUS_PORT}"

        # Token / credentials
        self._token = token or MILVUS_TOKEN
        self._user = kwargs.get("user", MILVUS_USER)
        self._password = kwargs.get("password", MILVUS_PASSWORD)

        # TLS configuration
        self._secure = kwargs.get("secure", MILVUS_SECURE)
        self._server_name = kwargs.get("server_name", MILVUS_SERVER_NAME)
        self._ca_cert = kwargs.get("ca_cert", MILVUS_CA_CERT)
        self._server_cert = kwargs.get("server_cert", MILVUS_SERVER_CERT)
        self._server_key = kwargs.get("server_key", MILVUS_SERVER_KEY)
        self._use_tls_v2 = kwargs.get("use_tls_v2", MILVUS_USE_TLSv2)

        super().__init__(
            embedding_model=embedding_model,
            embedding=embedding,
            collection_name=collection_name,
            **kwargs
        )
        self.logger = logging.getLogger("MilvusStore")

    # ------------------------------------------------------------------
    # Connection management
    # ------------------------------------------------------------------

    async def connection(self) -> None:
        """Establish connection to the Milvus server."""
        if self._connected and self._connection is not None:
            return

        connect_kwargs: Dict[str, Any] = {
            "uri": self._uri,
        }

        # Authentication
        if self._token:
            connect_kwargs["token"] = self._token
        elif self._user and self._password:
            connect_kwargs["token"] = f"{self._user}:{self._password}"

        # TLS / SSL
        if self._secure:
            connect_kwargs["secure"] = True
        if self._server_name:
            connect_kwargs["server_name"] = self._server_name
        if self._ca_cert:
            connect_kwargs["server_pem_path"] = self._ca_cert

        try:
            self._connection = MilvusClient(**connect_kwargs)
            self._connected = True
            self.logger.info(
                f"Connected to Milvus at {self._uri}"
            )
            if self._auto_create:
                exists = await self.collection_exists(self.collection_name)
                if not exists:
                    await self.create_collection(self.collection_name)
        except Exception as e:
            self._connected = False
            self.logger.error(f"Failed to connect to Milvus: {e}")
            raise

    async def disconnect(self) -> None:
        """Close the Milvus connection."""
        if self._connection is not None:
            try:
                self._connection.close()
            except Exception as e:
                self.logger.warning(f"Error closing Milvus connection: {e}")
            finally:
                self._connection = None
                self._connected = False
                self.logger.info("Disconnected from Milvus")

    async def initialize_database(self) -> None:
        """Initialize database-level resources.

        For Milvus this is a no-op; collections are created explicitly.
        """
        if not self._connected:
            await self.connection()

    # ------------------------------------------------------------------
    # Distance helpers
    # ------------------------------------------------------------------

    def get_distance_strategy(
        self,
        metric: Optional[str] = None,
        **kwargs
    ) -> str:
        """Return the Milvus metric type string for the current strategy.

        Args:
            metric: Optional override metric string.

        Returns:
            A Milvus-compatible metric type string (e.g. ``"COSINE"``).
        """
        if metric:
            upper = metric.upper()
            return _STR_METRIC_MAP.get(upper, "COSINE")
        if isinstance(self.distance_strategy, DistanceStrategy):
            return _METRIC_MAP.get(self.distance_strategy, "COSINE")
        if isinstance(self.distance_strategy, str):
            return _STR_METRIC_MAP.get(self.distance_strategy.upper(), "COSINE")
        return "COSINE"

    def get_vector(self, metric_type: str = None, **kwargs):
        """Return the underlying MilvusClient instance."""
        return self._connection

    # ------------------------------------------------------------------
    # Collection management
    # ------------------------------------------------------------------

    async def collection_exists(self, collection: str = None) -> bool:
        """Check whether a collection exists in Milvus.

        Args:
            collection: Collection name. Defaults to ``self.collection_name``.

        Returns:
            ``True`` if the collection exists.
        """
        if not self._connected:
            await self.connection()
        collection = collection or self.collection_name
        try:
            return self._connection.has_collection(collection_name=collection)
        except Exception as e:
            self.logger.error(f"Error checking collection existence: {e}")
            return False

    async def create_collection(
        self,
        collection: str = None,
        dimension: int = None,
        metric_type: str = None,
        index_type: str = None,
        **kwargs
    ) -> None:
        """Create a new collection in Milvus with a vector index.

        Args:
            collection: Collection name.
            dimension: Vector dimension.  Defaults to ``self.dimension``.
            metric_type: Distance metric.  Defaults to configured strategy.
            index_type: Index algorithm.  Defaults to ``self._index_type``.
        """
        if not self._connected:
            await self.connection()

        collection = collection or self.collection_name
        dimension = dimension or self.dimension
        metric = metric_type or self.get_distance_strategy()
        idx_type = index_type or self._index_type

        if self._connection.has_collection(collection_name=collection):
            self.logger.info(f"Collection '{collection}' already exists")
            return

        # Build schema
        schema = self._connection.create_schema(
            auto_id=False,
            enable_dynamic_field=True,
        )
        schema.add_field(
            field_name=self._id_column,
            datatype=DataType.VARCHAR,
            is_primary=True,
            max_length=128,
        )
        schema.add_field(
            field_name=self._embedding_column,
            datatype=DataType.FLOAT_VECTOR,
            dim=dimension,
        )
        schema.add_field(
            field_name=self._document_column,
            datatype=DataType.VARCHAR,
            max_length=65535,
        )
        schema.add_field(
            field_name=self._text_column,
            datatype=DataType.VARCHAR,
            max_length=65535,
        )
        schema.add_field(
            field_name=self._metadata_column,
            datatype=DataType.JSON,
        )

        # Build index params
        index_params = self._connection.prepare_index_params()
        index_extra: Dict[str, Any] = {}
        if idx_type == "IVF_FLAT":
            index_extra = {"nlist": self._nlist}
        elif idx_type == "HNSW":
            index_extra = {
                "M": kwargs.get("M", 16),
                "efConstruction": self._ef_construction,
            }
        index_params.add_index(
            field_name=self._embedding_column,
            index_type=idx_type,
            metric_type=metric,
            params=index_extra,
        )

        self._connection.create_collection(
            collection_name=collection,
            schema=schema,
            index_params=index_params,
        )
        self.logger.info(
            f"Created collection '{collection}' "
            f"(dim={dimension}, metric={metric}, index={idx_type})"
        )

    async def drop_collection(self, collection: str = None) -> None:
        """Drop a collection from Milvus.

        Args:
            collection: Collection name to drop.
        """
        if not self._connected:
            await self.connection()
        collection = collection or self.collection_name
        try:
            self._connection.drop_collection(collection_name=collection)
            self.logger.info(f"Dropped collection '{collection}'")
        except Exception as e:
            self.logger.error(f"Error dropping collection '{collection}': {e}")
            raise

    async def create_embedding_table(
        self,
        collection: str = None,
        dimension: int = None,
        metric_type: str = None,
        index_type: str = None,
        **kwargs
    ) -> None:
        """Alias for ``create_collection`` to match PgVectorStore interface."""
        await self.create_collection(
            collection=collection,
            dimension=dimension,
            metric_type=metric_type,
            index_type=index_type,
            **kwargs,
        )

    async def prepare_embedding_table(
        self,
        tablename: str,
        conn: Any = None,
        embedding_column: str = "embedding",
        document_column: str = "document",
        metadata_column: str = "metadata",
        dimension: int = None,
        id_column: str = "id",
        use_jsonb: bool = True,
        drop_columns: bool = False,
        create_all_indexes: bool = True,
        **kwargs
    ) -> None:
        """Prepare a collection as an embedding table.

        For Milvus this delegates to ``create_collection`` since Milvus
        collections are schemaless beyond the defined fields.
        """
        await self.create_collection(
            collection=tablename,
            dimension=dimension or self.dimension,
            **kwargs
        )

    # ------------------------------------------------------------------
    # Document operations
    # ------------------------------------------------------------------

    async def add_documents(
        self,
        documents: List[Document],
        collection: str = None,
        **kwargs
    ) -> None:
        """Add documents to a Milvus collection.

        Each document is embedded, assigned a UUID, and inserted together
        with its text content and metadata.

        Args:
            documents: List of ``Document`` objects.
            collection: Target collection name.
        """
        if not self._connected:
            await self.connection()
        collection = collection or self.collection_name

        texts = [doc.page_content for doc in documents]
        embeddings = self._embed_.embed_documents(texts)
        metadatas = [doc.metadata for doc in documents]

        rows: List[Dict[str, Any]] = []
        for i, doc in enumerate(documents):
            emb = embeddings[i]
            if isinstance(emb, np.ndarray):
                emb = emb.tolist()
            rows.append({
                self._id_column: str(uuid.uuid4()),
                self._embedding_column: emb,
                self._document_column: doc.page_content,
                self._text_column: doc.page_content,
                self._metadata_column: metadatas[i] or {},
            })

        try:
            self._connection.insert(
                collection_name=collection,
                data=rows,
            )
            self.logger.info(
                f"Added {len(documents)} documents to '{collection}'"
            )
        except Exception as e:
            self.logger.error(f"Error adding documents: {e}")
            raise

    async def from_documents(
        self,
        documents: List[Any],
        collection: str = None,
        **kwargs
    ) -> "MilvusStore":
        """Create the collection (if needed) and add documents.

        Args:
            documents: List of ``Document`` objects.
            collection: Collection name.

        Returns:
            ``self`` for chaining.
        """
        collection = collection or self.collection_name
        if not await self.collection_exists(collection):
            await self.create_collection(collection=collection, **kwargs)
        await self.add_documents(documents, collection=collection, **kwargs)
        return self

    async def update_documents_by_filter(
        self,
        updates: Dict[str, Any],
        filter_dict: Dict[str, Any],
        collection: str = None,
        **kwargs
    ) -> int:
        """Update documents matching a metadata filter.

        Milvus does not support in-place updates; this method performs a
        query-delete-reinsert cycle for matching documents.

        Args:
            updates: Dictionary of field values to update.
            filter_dict: Metadata filter criteria.
            collection: Collection name.

        Returns:
            Number of updated documents.
        """
        if not self._connected:
            await self.connection()
        collection = collection or self.collection_name

        filter_expr = self._build_metadata_filter(filter_dict)
        try:
            results = self._connection.query(
                collection_name=collection,
                filter=filter_expr,
                output_fields=["*"],
            )
            if not results:
                return 0

            # Delete originals
            ids = [r[self._id_column] for r in results]
            self._connection.delete(
                collection_name=collection,
                filter=f'{self._id_column} in {ids}',
            )

            # Re-insert with updates
            for row in results:
                for key, value in updates.items():
                    if key == self._metadata_column:
                        row[self._metadata_column].update(value)
                    else:
                        row[key] = value

            self._connection.insert(
                collection_name=collection,
                data=results,
            )
            self.logger.info(
                f"Updated {len(results)} documents in '{collection}'"
            )
            return len(results)
        except Exception as e:
            self.logger.error(f"Error updating documents: {e}")
            raise

    # ------------------------------------------------------------------
    # Delete operations
    # ------------------------------------------------------------------

    async def delete_documents(
        self,
        documents: Optional[List[Document]] = None,
        pk: str = "source_type",
        values: Optional[Union[str, List[str]]] = None,
        table: Optional[str] = None,
        schema: Optional[str] = None,
        collection: Optional[str] = None,
        **kwargs
    ) -> int:
        """Delete documents by metadata field values.

        Args:
            documents: If provided, extract ``pk`` values from metadata.
            pk: Metadata key to match against.
            values: Explicit value(s) to match.
            collection: Collection name override.

        Returns:
            Number of deleted documents.
        """
        if not self._connected:
            await self.connection()
        collection = collection or table or self.collection_name

        delete_values: List[str] = []
        if values is not None:
            delete_values = [values] if isinstance(values, str) else list(values)
        elif documents:
            for doc in documents:
                if hasattr(doc, "metadata") and doc.metadata and pk in doc.metadata:
                    val = doc.metadata[pk]
                    if val and val not in delete_values:
                        delete_values.append(val)
        else:
            raise ValueError("Either 'documents' or 'values' must be provided")

        if not delete_values:
            self.logger.warning(f"No values found for field '{pk}' to delete")
            return 0

        total_deleted = 0
        try:
            for val in delete_values:
                filter_expr = f'{self._metadata_column}["{pk}"] == "{val}"'
                # Query to count
                matches = self._connection.query(
                    collection_name=collection,
                    filter=filter_expr,
                    output_fields=[self._id_column],
                )
                if not matches:
                    continue
                ids = [m[self._id_column] for m in matches]
                self._connection.delete(
                    collection_name=collection,
                    filter=f'{self._id_column} in {ids}',
                )
                total_deleted += len(ids)
                self.logger.info(
                    f"Deleted {len(ids)} documents with {pk}='{val}' "
                    f"from '{collection}'"
                )
            return total_deleted
        except Exception as e:
            self.logger.error(f"Error deleting documents: {e}")
            raise RuntimeError(f"Failed to delete documents: {e}") from e

    async def delete_documents_by_filter(
        self,
        search_filter: Dict[str, Union[str, List[str]]],
        table: Optional[str] = None,
        schema: Optional[str] = None,
        collection: Optional[str] = None,
        **kwargs
    ) -> int:
        """Delete documents matching multiple metadata conditions.

        Args:
            search_filter: Dictionary of metadata field → value(s).
            collection: Collection name override.

        Returns:
            Number of deleted documents.
        """
        if not self._connected:
            await self.connection()
        collection = collection or table or self.collection_name

        if not search_filter:
            raise ValueError("search_filter cannot be empty")

        filter_expr = self._build_metadata_filter(search_filter)
        try:
            matches = self._connection.query(
                collection_name=collection,
                filter=filter_expr,
                output_fields=[self._id_column],
            )
            if not matches:
                return 0
            ids = [m[self._id_column] for m in matches]
            self._connection.delete(
                collection_name=collection,
                filter=f'{self._id_column} in {ids}',
            )
            self.logger.info(
                f"Deleted {len(ids)} documents from '{collection}' "
                f"with filter: {search_filter}"
            )
            return len(ids)
        except Exception as e:
            self.logger.error(f"Error deleting documents by filter: {e}")
            raise RuntimeError(
                f"Failed to delete documents by filter: {e}"
            ) from e

    async def delete_documents_by_ids(
        self,
        document_ids: List[str],
        collection: Optional[str] = None,
        **kwargs
    ) -> int:
        """Delete documents by their primary key IDs.

        Args:
            document_ids: List of document IDs to delete.
            collection: Collection name override.

        Returns:
            Number of deleted documents.
        """
        if not self._connected:
            await self.connection()
        collection = collection or self.collection_name

        if not document_ids:
            self.logger.warning("No document IDs provided for deletion")
            return 0

        try:
            self._connection.delete(
                collection_name=collection,
                filter=f'{self._id_column} in {document_ids}',
            )
            self.logger.info(
                f"Deleted {len(document_ids)} documents by ID from '{collection}'"
            )
            return len(document_ids)
        except Exception as e:
            self.logger.error(f"Error deleting documents by IDs: {e}")
            raise RuntimeError(
                f"Failed to delete documents by IDs: {e}"
            ) from e

    # ------------------------------------------------------------------
    # Search operations
    # ------------------------------------------------------------------

    async def similarity_search(
        self,
        query: str,
        collection: str = None,
        limit: int = 10,
        similarity_threshold: float = 0.0,
        search_strategy: str = "auto",
        metadata_filters: Optional[Dict[str, Any]] = None,
        metric: str = None,
        additional_columns: Optional[List[str]] = None,
        **kwargs
    ) -> List[SearchResult]:
        """Perform vector similarity search against a Milvus collection.

        Args:
            query: Search query text.
            collection: Collection name.
            limit: Maximum number of results.
            similarity_threshold: Minimum score threshold.
            metadata_filters: Metadata key/value filter conditions.
            metric: Distance metric override.
            additional_columns: Extra fields to return.

        Returns:
            List of ``SearchResult`` objects ordered by relevance.
        """
        if not self._connected:
            await self.connection()
        collection = collection or self.collection_name

        # Embed the query
        query_embedding = self._embed_.embed_query(query)
        if isinstance(query_embedding, np.ndarray):
            query_embedding = query_embedding.tolist()

        # Build search params
        milvus_metric = self.get_distance_strategy(metric=metric)
        search_params: Dict[str, Any] = {"metric_type": milvus_metric}
        if self._index_type == "IVF_FLAT":
            search_params["params"] = {"nprobe": self._nprobe}
        elif self._index_type == "HNSW":
            search_params["params"] = {"ef": self._ef}

        # Output fields
        output_fields = [
            self._document_column,
            self._text_column,
            self._metadata_column,
        ]
        if additional_columns:
            output_fields.extend(additional_columns)

        # Build filter expression
        filter_expr = ""
        if metadata_filters:
            filter_expr = self._build_metadata_filter(metadata_filters)

        try:
            results = self._connection.search(
                collection_name=collection,
                data=[query_embedding],
                anns_field=self._embedding_column,
                search_params=search_params,
                limit=limit,
                output_fields=output_fields,
                filter=filter_expr if filter_expr else "",
            )

            search_results: List[SearchResult] = []
            if results and len(results) > 0:
                for hit in results[0]:
                    score = hit.get("distance", 0.0)

                    # Apply threshold
                    if similarity_threshold and score < similarity_threshold:
                        continue

                    entity = hit.get("entity", {})
                    metadata = entity.get(self._metadata_column, {})
                    if isinstance(metadata, str):
                        try:
                            metadata = self._json.loads(metadata)
                        except Exception:
                            metadata = {}

                    # Append additional columns into metadata
                    if additional_columns:
                        for col in additional_columns:
                            if col in entity:
                                metadata[col] = entity[col]

                    content = entity.get(
                        self._document_column,
                        entity.get(self._text_column, ""),
                    )

                    search_results.append(
                        SearchResult(
                            id=str(hit.get("id", "")),
                            content=content or "",
                            metadata=metadata,
                            score=score,
                        )
                    )

            return search_results

        except Exception as e:
            self.logger.error(f"Error during similarity search: {e}")
            raise

    async def document_search(
        self,
        query: str,
        collection: str = None,
        limit: int = 10,
        search_chunks: bool = True,
        search_full_docs: bool = False,
        **kwargs
    ) -> List[SearchResult]:
        """Search with chunk-awareness support.

        Args:
            query: Search query text.
            collection: Collection name.
            limit: Number of results.
            search_chunks: Search chunk-level embeddings.
            search_full_docs: Also search full-document embeddings.

        Returns:
            List of ``SearchResult`` objects.
        """
        results: List[SearchResult] = []

        if search_chunks:
            chunk_filters = {"is_chunk": True}
            chunk_results = await self.similarity_search(
                query=query,
                collection=collection,
                limit=limit * 2,
                metadata_filters=chunk_filters,
                **kwargs,
            )
            results.extend(chunk_results)

        if search_full_docs:
            doc_filters = {"is_full_document": True}
            doc_results = await self.similarity_search(
                query=query,
                collection=collection,
                limit=limit,
                metadata_filters=doc_filters,
                **kwargs,
            )
            results.extend(doc_results)

        # Sort by score (lower distance = more similar for L2/cosine distance)
        results.sort(key=lambda x: x.score)
        return results[:limit]

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _build_metadata_filter(
        self,
        filter_dict: Dict[str, Any],
    ) -> str:
        """Build a Milvus boolean filter expression from a metadata dict.

        Handles single values and list values (OR within a key, AND across keys).

        Args:
            filter_dict: Metadata key-value filter conditions.

        Returns:
            A Milvus-compatible filter expression string.
        """
        conditions: List[str] = []
        for key, value in filter_dict.items():
            if isinstance(value, (list, tuple)):
                or_parts = []
                for v in value:
                    or_parts.append(
                        f'{self._metadata_column}["{key}"] == {self._quote_value(v)}'
                    )
                conditions.append(f"({' or '.join(or_parts)})")
            elif isinstance(value, bool):
                bool_str = "true" if value else "false"
                conditions.append(
                    f'{self._metadata_column}["{key}"] == {bool_str}'
                )
            else:
                conditions.append(
                    f'{self._metadata_column}["{key}"] == {self._quote_value(value)}'
                )
        return " and ".join(conditions)

    @staticmethod
    def _quote_value(value: Any) -> str:
        """Quote a filter value for Milvus expression syntax."""
        if isinstance(value, bool):
            return "true" if value else "false"
        if isinstance(value, (int, float)):
            return str(value)
        return f'"{value}"'
