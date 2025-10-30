"""
ArangoDBStore: Vector Store implementation for ArangoDB.

Provides comprehensive vector storage with graph support, including:
- Database and collection management
- Graph creation and management
- Document operations with upsert support
- Vector similarity search
- Full-text search (BM25)
- Hybrid search (vector + text)
- Graph-enhanced retrieval
"""
from typing import Any, Dict, List, Optional, Union, Callable
import uuid
import asyncio
from collections.abc import Callable as CallableType

from navconfig.logging import logging
from asyncdb import AsyncDB

from .abstract import AbstractStore
from .models import Document, SearchResult, DistanceStrategy
from ..conf import EMBEDDING_DEFAULT_MODEL


class ArangoDBStore(AbstractStore):
    """
    ArangoDB Vector Store with native graph support.

    Features:
    - Multi-model database (documents, graphs, key-value)
    - Native graph operations for knowledge graphs
    - ArangoSearch for full-text and vector search
    - Hybrid search combining semantic and keyword
    - Graph-enhanced RAG with relationship context
    """

    def __init__(
        self,
        database: str = "_system",
        collection_name: str = "documents",
        embedding_column: str = "embedding",
        text_column: str = "content",
        metadata_column: str = "metadata",
        id_column: str = "_key",
        embedding_model: Union[dict, str] = None,
        embedding: Optional[Callable] = None,
        distance_strategy: DistanceStrategy = DistanceStrategy.COSINE,
        # ArangoDB specific
        host: str = "127.0.0.1",
        port: int = 8529,
        protocol: str = "http",
        username: str = "root",
        password: str = "",
        default_graph: Optional[str] = None,
        default_view: Optional[str] = None,
        # Collection options
        edge_collection: str = "relationships",
        auto_create_view: bool = True,
        view_analyzer: str = "text_en",
        **kwargs
    ):
        """
        Initialize ArangoDB Vector Store.

        Args:
            database: Database name
            collection_name: Default collection for documents
            embedding_column: Field name for embeddings
            text_column: Field name for text content
            metadata_column: Field name for metadata
            id_column: Field name for document ID (_key)
            embedding_model: Embedding model configuration
            embedding: Custom embedding function
            distance_strategy: Distance metric (COSINE, L2, DOT_PRODUCT)
            host: ArangoDB host
            port: ArangoDB port
            protocol: Connection protocol (http/https)
            username: Database username
            password: Database password
            default_graph: Default graph name
            default_view: Default ArangoSearch view name
            edge_collection: Default edge collection name
            auto_create_view: Auto-create ArangoSearch view
            view_analyzer: Text analyzer for views
        """
        # Initialize parent class
        super().__init__(
            embedding_model=embedding_model,
            embedding=embedding,
            **kwargs
        )

        # Store configuration
        self.database = database
        self.collection_name = collection_name
        self.embedding_column = embedding_column
        self.text_column = text_column
        self.metadata_column = metadata_column
        self.id_column = id_column
        self.distance_strategy = distance_strategy

        # ArangoDB connection parameters
        self.connection_params = {
            "host": host,
            "port": port,
            "protocol": protocol,
            "username": username,
            "password": password,
            "database": database
        }

        # Graph and search configuration
        self.default_graph = default_graph
        self.default_view = default_view or f"{collection_name}_view"
        self.edge_collection = edge_collection
        self.auto_create_view = auto_create_view
        self.view_analyzer = view_analyzer

        # AsyncDB connection
        self._db: Optional[AsyncDB] = None
        self._connection = None

        self.logger = logging.getLogger("ArangoDBStore")

    async def connection(self) -> tuple:
        """
        Establish connection to ArangoDB.

        Returns:
            Tuple of (connection, None) or (None, error)
        """
        try:
            if self._db is None or not self._db._connected:
                self._db = AsyncDB("arangodb", params=self.connection_params)
                await self._db.connection()
                self._connection = self._db._connection
                self._connected = True

                # Auto-create collection and view if needed
                if self.collection_name:
                    await self.create_collection(self.collection_name)

                    if self.auto_create_view:
                        await self._ensure_search_view()

                self.logger.info(
                    f"Connected to ArangoDB: {self.database}/{self.collection_name}"
                )

            return (self._connection, None)

        except Exception as e:
            self.logger.error(f"Connection error: {e}", exc_info=True)
            return (None, str(e))

    async def disconnect(self) -> None:
        """Close ArangoDB connection."""
        if self._db:
            try:
                await self._db.close()
                self._connected = False
                self.logger.info("Disconnected from ArangoDB")
            except Exception as e:
                self.logger.error(f"Disconnect error: {e}")
            finally:
                self._db = None
                self._connection = None

    def get_vector(self, metric_type: str = None, **kwargs):
        """Get vector store instance."""
        return self

    # Database Management

    async def create_database(self, database_name: str) -> bool:
        """
        Create a new database.

        Args:
            database_name: Name of database to create

        Returns:
            True if successful
        """
        try:
            await self._db.create_database(database_name)
            self.logger.info(f"Created database: {database_name}")
            return True
        except Exception as e:
            self.logger.error(f"Error creating database {database_name}: {e}")
            raise

    async def drop_database(self, database_name: str) -> bool:
        """
        Drop a database.

        Args:
            database_name: Name of database to drop

        Returns:
            True if successful
        """
        try:
            await self._db.drop_database(database_name)
            self.logger.info(f"Dropped database: {database_name}")
            return True
        except Exception as e:
            self.logger.error(f"Error dropping database {database_name}: {e}")
            raise

    async def use_database(self, database_name: str) -> None:
        """
        Switch to a different database.

        Args:
            database_name: Database to switch to
        """
        await self._db.use(database_name)
        self.database = database_name
        self.logger.info(f"Switched to database: {database_name}")

    # Collection Management

    async def create_collection(
        self,
        collection: str,
        edge: bool = False,
        **kwargs
    ) -> bool:
        """
        Create a collection (document or edge).

        Args:
            collection: Collection name
            edge: If True, create edge collection
            **kwargs: Additional collection properties

        Returns:
            True if created or already exists
        """
        try:
            if await self._db.collection_exists(collection):
                self.logger.debug(f"Collection {collection} already exists")
                return True

            await self._db.create_collection(collection, edge=edge, **kwargs)
            self.logger.info(
                f"Created collection: {collection} (edge={edge})"
            )
            return True

        except Exception as e:
            self.logger.error(f"Error creating collection {collection}: {e}")
            raise

    async def delete_collection(self, collection: str) -> bool:
        """
        Drop a collection.

        Args:
            collection: Collection name to drop

        Returns:
            True if successful
        """
        try:
            await self._db.drop_collection(collection)
            self.logger.info(f"Dropped collection: {collection}")
            return True
        except Exception as e:
            self.logger.error(f"Error dropping collection {collection}: {e}")
            raise

    async def collection_exists(self, collection: str) -> bool:
        """
        Check if collection exists.

        Args:
            collection: Collection name

        Returns:
            True if exists
        """
        return await self._db.collection_exists(collection)

    # Graph Management

    async def create_graph(
        self,
        graph_name: str,
        vertex_collections: List[str],
        edge_collection: str = None,
        orphan_collections: List[str] = None
    ) -> bool:
        """
        Create a named graph.

        Args:
            graph_name: Name of the graph
            vertex_collections: List of vertex collection names
            edge_collection: Edge collection name (defaults to self.edge_collection)
            orphan_collections: Vertex collections without edges

        Returns:
            True if successful
        """
        try:
            edge_col = edge_collection or self.edge_collection

            # Create edge collection if it doesn't exist
            await self.create_collection(edge_col, edge=True)

            # Create vertex collections
            for vcol in vertex_collections:
                await self.create_collection(vcol, edge=False)

            # Define edge definitions
            edge_definitions = [{
                'edge_collection': edge_col,
                'from_vertex_collections': vertex_collections,
                'to_vertex_collections': vertex_collections
            }]

            # Create graph
            await self._db.create_graph(
                graph_name,
                edge_definitions=edge_definitions,
                orphan_collections=orphan_collections or []
            )

            self.logger.info(f"Created graph: {graph_name}")
            return True

        except Exception as e:
            self.logger.error(f"Error creating graph {graph_name}: {e}")
            raise

    async def drop_graph(
        self,
        graph_name: str,
        drop_collections: bool = False
    ) -> bool:
        """
        Drop a graph.

        Args:
            graph_name: Graph name
            drop_collections: If True, also drop associated collections

        Returns:
            True if successful
        """
        try:
            await self._db.drop_graph(graph_name, drop_collections=drop_collections)
            self.logger.info(f"Dropped graph: {graph_name}")
            return True
        except Exception as e:
            self.logger.error(f"Error dropping graph {graph_name}: {e}")
            raise

    async def graph_exists(self, graph_name: str) -> bool:
        """Check if graph exists."""
        return await self._db.graph_exists(graph_name)

    # ArangoSearch View Management

    async def _ensure_search_view(self) -> None:
        """Ensure ArangoSearch view exists for the collection."""
        try:
            # Create view with both text and vector search capabilities
            links = {
                self.collection_name: {
                    'fields': {
                        self.text_column: {
                            'analyzers': [self.view_analyzer]
                        },
                        self.embedding_column: {
                            'analyzers': ['identity']
                        }
                    }
                }
            }

            await self._db.create_arangosearch_view(
                view_name=self.default_view,
                links=links
            )

            self.logger.info(f"Created ArangoSearch view: {self.default_view}")

        except Exception as e:
            # View might already exist
            self.logger.debug(f"View creation: {e}")

    async def create_view(
        self,
        view_name: str,
        collections: List[str],
        text_fields: List[str] = None,
        vector_field: str = None,
        analyzer: str = None,
        **kwargs
    ) -> bool:
        """
        Create an ArangoSearch view.

        Args:
            view_name: Name for the view
            collections: Collections to include
            text_fields: Text fields to index
            vector_field: Vector field to index
            analyzer: Text analyzer (defaults to view_analyzer)
            **kwargs: Additional view properties

        Returns:
            True if successful
        """
        try:
            analyzer = analyzer or self.view_analyzer
            text_fields = text_fields or [self.text_column]
            vector_field = vector_field or self.embedding_column

            links = {}
            for collection in collections:
                fields = {}

                # Add text fields
                for field in text_fields:
                    fields[field] = {'analyzers': [analyzer]}

                # Add vector field
                if vector_field:
                    fields[vector_field] = {'analyzers': ['identity']}

                links[collection] = {'fields': fields}

            await self._db.create_arangosearch_view(
                view_name=view_name,
                links=links,
                **kwargs
            )

            self.logger.info(f"Created view: {view_name}")
            return True

        except Exception as e:
            self.logger.error(f"Error creating view {view_name}: {e}")
            raise

    async def drop_view(self, view_name: str) -> bool:
        """Drop an ArangoSearch view."""
        try:
            await self._db.drop_arangosearch_view(view_name)
            self.logger.info(f"Dropped view: {view_name}")
            return True
        except Exception as e:
            self.logger.error(f"Error dropping view {view_name}: {e}")
            raise

    # Document Operations

    async def add_document(
        self,
        document: Union[Document, dict],
        collection: str = None,
        upsert: bool = True,
        upsert_key: Optional[str] = None,
        upsert_metadata_keys: Optional[List[str]] = None,
        **kwargs
    ) -> Dict[str, Any]:
        """
        Add a single document with upsert support.

        Args:
            document: Document to add (Document object or dict)
            collection: Collection name (defaults to self.collection_name)
            upsert: If True, update existing document if key exists
            upsert_key: Specific key field to use for upsert matching
            upsert_metadata_keys: Metadata fields to match for upsert
            **kwargs: Additional arguments

        Returns:
            Inserted/updated document metadata
        """
        collection = collection or self.collection_name

        # Convert Document to dict
        if isinstance(document, Document):
            doc_dict = self._document_to_dict(document)
        else:
            doc_dict = document.copy()

        # Generate embedding if needed
        if self.embedding_column not in doc_dict and self.text_column in doc_dict:
            text = doc_dict[self.text_column]
            embedding = await self._generate_embedding(text)
            doc_dict[self.embedding_column] = embedding

        try:
            if upsert:
                # Find existing document
                existing_doc = await self._find_existing_document(
                    doc_dict,
                    collection,
                    upsert_key,
                    upsert_metadata_keys
                )

                if existing_doc:
                    # Update existing
                    doc_dict['_key'] = existing_doc['_key']
                    result = await self._db.update_document(
                        collection,
                        doc_dict,
                        return_new=True
                    )
                    self.logger.debug(f"Updated document: {doc_dict['_key']}")
                    return result

            # Insert new document
            if '_key' not in doc_dict:
                doc_dict['_key'] = str(uuid.uuid4())

            result = await self._db.insert_document(
                collection,
                doc_dict,
                return_new=True
            )
            self.logger.debug(f"Inserted document: {doc_dict['_key']}")
            return result

        except Exception as e:
            self.logger.error(f"Error adding document: {e}")
            raise

    async def add_documents(
        self,
        documents: List[Union[Document, dict]],
        collection: str = None,
        upsert: bool = True,
        batch_size: int = 100,
        **kwargs
    ) -> int:
        """
        Add multiple documents.

        Args:
            documents: List of documents to add
            collection: Collection name
            upsert: If True, update existing documents
            batch_size: Batch size for bulk operations
            **kwargs: Additional arguments

        Returns:
            Number of documents processed
        """
        collection = collection or self.collection_name
        count = 0

        # Process in batches
        for i in range(0, len(documents), batch_size):
            batch = documents[i:i + batch_size]

            for doc in batch:
                try:
                    await self.add_document(
                        doc,
                        collection=collection,
                        upsert=upsert,
                        **kwargs
                    )
                    count += 1
                except Exception as e:
                    self.logger.error(f"Error adding document in batch: {e}")

        self.logger.info(f"Added {count} documents to {collection}")
        return count

    async def save_documents(
        self,
        documents: List[Union[Document, dict]],
        collection: str = None,
        **kwargs
    ) -> int:
        """
        Save documents with upsert (alias for add_documents with upsert=True).

        Args:
            documents: Documents to save
            collection: Collection name
            **kwargs: Additional arguments

        Returns:
            Number of documents saved
        """
        return await self.add_documents(
            documents,
            collection=collection,
            upsert=True,
            **kwargs
        )

    async def delete_documents_by_filter(
        self,
        filter_dict: Dict[str, Any],
        collection: str = None,
        **kwargs
    ) -> int:
        """
        Delete documents matching filter conditions.

        Args:
            filter_dict: Filter conditions (e.g., {'category': 'test'})
            collection: Collection name
            **kwargs: Additional arguments

        Returns:
            Number of documents deleted
        """
        collection = collection or self.collection_name

        # Build AQL filter conditions
        filter_conditions = []
        bind_vars = {}

        for key, value in filter_dict.items():
            var_name = f"filter_{key}"
            filter_conditions.append(f"doc.{key} == @{var_name}")
            bind_vars[var_name] = value

        filter_clause = " AND ".join(filter_conditions)

        # Delete query
        query = f"""
        FOR doc IN {collection}
            FILTER {filter_clause}
            REMOVE doc IN {collection}
            RETURN OLD
        """

        try:
            results, error = await self._db.query(query, bind_vars=bind_vars)

            if error:
                raise Exception(error)

            count = len(results) if results else 0
            self.logger.info(f"Deleted {count} documents from {collection}")
            return count

        except Exception as e:
            self.logger.error(f"Error deleting documents: {e}")
            raise

    # Search Methods

    async def similarity_search(
        self,
        query: str,
        collection: str = None,
        limit: int = 10,
        similarity_threshold: float = 0.0,
        search_strategy: str = "auto",
        metadata_filters: Union[dict, None] = None,
        include_graph_context: bool = False,
        **kwargs
    ) -> List[SearchResult]:
        """
        Perform vector similarity search.

        Args:
            query: Query text
            collection: Collection to search
            limit: Maximum results
            similarity_threshold: Minimum similarity score
            search_strategy: Search strategy (auto, vector, hybrid)
            metadata_filters: Metadata filter conditions
            include_graph_context: Include graph neighbors
            **kwargs: Additional arguments

        Returns:
            List of SearchResult objects
        """
        collection = collection or self.collection_name
        view_name = kwargs.get('view_name', self.default_view)

        # Generate query embedding
        query_embedding = await self._generate_embedding(query)

        # Build filter conditions
        filter_conditions = self._build_filter_conditions(metadata_filters)

        try:
            results = await self._db.vector_search(
                view_name=view_name,
                collection=collection,
                query_vector=query_embedding,
                vector_field=self.embedding_column,
                top_k=limit,
                filter_conditions=filter_conditions,
                include_similarity=True
            )

            # Filter by threshold
            filtered = [
                r for r in results
                if r.get('similarity', 0) >= similarity_threshold
            ]

            # Convert to SearchResult objects
            search_results = self._to_search_results(filtered)

            # Add graph context if requested
            if include_graph_context and self.default_graph:
                search_results = await self._enrich_with_graph_context(
                    search_results
                )

            return search_results

        except Exception as e:
            self.logger.error(f"Similarity search error: {e}")
            raise

    async def fulltext_search(
        self,
        query: str,
        collection: str = None,
        text_fields: List[str] = None,
        limit: int = 10,
        min_score: float = 0.0,
        analyzer: str = None,
        metadata_filters: dict = None,
        **kwargs
    ) -> List[SearchResult]:
        """
        Perform full-text search using BM25.

        Args:
            query: Search query text
            collection: Collection to search
            text_fields: Fields to search
            limit: Maximum results
            min_score: Minimum BM25 score
            analyzer: Text analyzer
            metadata_filters: Metadata filters
            **kwargs: Additional arguments

        Returns:
            List of SearchResult objects
        """
        view_name = kwargs.get('view_name', self.default_view)
        text_fields = text_fields or [self.text_column]
        analyzer = analyzer or self.view_analyzer

        try:
            results = await self._db.fulltext_search(
                view_name=view_name,
                query_text=query,
                fields=text_fields,
                analyzer=analyzer,
                top_k=limit,
                min_score=min_score
            )

            return self._to_search_results(results, score_field='score')

        except Exception as e:
            self.logger.error(f"Full-text search error: {e}")
            raise

    async def hybrid_search(
        self,
        query: str,
        collection: str = None,
        limit: int = 10,
        text_weight: float = 0.5,
        vector_weight: float = 0.5,
        text_fields: List[str] = None,
        analyzer: str = None,
        metadata_filters: dict = None,
        **kwargs
    ) -> List[SearchResult]:
        """
        Perform hybrid search combining vector and text.

        Args:
            query: Search query
            collection: Collection to search
            limit: Maximum results
            text_weight: Weight for text score (0-1)
            vector_weight: Weight for vector score (0-1)
            text_fields: Text fields to search
            analyzer: Text analyzer
            metadata_filters: Metadata filters
            **kwargs: Additional arguments

        Returns:
            List of SearchResult objects
        """
        collection = collection or self.collection_name
        view_name = kwargs.get('view_name', self.default_view)
        text_fields = text_fields or [self.text_column]
        analyzer = analyzer or self.view_analyzer

        # Generate embedding
        query_embedding = await self._generate_embedding(query)

        try:
            results = await self._db.hybrid_search(
                view_name=view_name,
                collection=collection,
                query_text=query,
                query_vector=query_embedding,
                text_fields=text_fields,
                vector_field=self.embedding_column,
                text_weight=text_weight,
                vector_weight=vector_weight,
                analyzer=analyzer,
                top_k=limit
            )

            return self._to_search_results(results, score_field='combined_score')

        except Exception as e:
            self.logger.error(f"Hybrid search error: {e}")
            raise

    async def document_search(
        self,
        query: str,
        search_type: str = "similarity",
        collection: str = None,
        limit: int = 10,
        **kwargs
    ) -> List[SearchResult]:
        """
        Unified document search interface.

        Args:
            query: Search query
            search_type: Type of search (similarity, fulltext, hybrid)
            collection: Collection to search
            limit: Maximum results
            **kwargs: Additional search parameters

        Returns:
            List of SearchResult objects
        """
        if search_type == "similarity":
            return await self.similarity_search(
                query, collection=collection, limit=limit, **kwargs
            )
        elif search_type == "fulltext":
            return await self.fulltext_search(
                query, collection=collection, limit=limit, **kwargs
            )
        elif search_type == "hybrid":
            return await self.hybrid_search(
                query, collection=collection, limit=limit, **kwargs
            )
        else:
            raise ValueError(f"Unknown search type: {search_type}")

    # Required AbstractStore methods

    async def from_documents(
        self,
        documents: List[Any],
        collection: Union[str, None] = None,
        **kwargs
    ) -> 'ArangoDBStore':
        """
        Create vector store from documents.

        Args:
            documents: List of Document objects
            collection: Collection name
            **kwargs: Additional arguments

        Returns:
            Self
        """
        collection = collection or self.collection_name

        # Ensure collection exists
        await self.create_collection(collection)

        # Add documents
        await self.add_documents(documents, collection=collection, **kwargs)

        return self

    # Helper Methods

    def _document_to_dict(self, document: Document) -> dict:
        """Convert Document object to dictionary."""
        doc_dict = {
            self.text_column: document.page_content,
            self.metadata_column: document.metadata or {}
        }

        # Add any existing embedding
        if hasattr(document, 'embedding') and document.embedding:
            doc_dict[self.embedding_column] = document.embedding

        return doc_dict

    async def _generate_embedding(self, text: str) -> List[float]:
        """Generate embedding for text."""
        if self._embed_ is None:
            raise ValueError("No embedding model configured")

        # Handle both sync and async embeddings
        import inspect
        if inspect.iscoroutinefunction(self._embed_.embed_query):
            return await self._embed_.embed_query(text)
        else:
            return await asyncio.get_event_loop().run_in_executor(
                None, self._embed_.embed_query, text
            )

    async def _find_existing_document(
        self,
        doc_dict: dict,
        collection: str,
        upsert_key: Optional[str],
        upsert_metadata_keys: Optional[List[str]]
    ) -> Optional[dict]:
        """Find existing document for upsert operation."""
        # Check by explicit key
        if upsert_key and upsert_key in doc_dict:
            query = f"""
            FOR doc IN {collection}
                FILTER doc.{upsert_key} == @key_value
                LIMIT 1
                RETURN doc
            """
            bind_vars = {'key_value': doc_dict[upsert_key]}

            result = await self._db.fetch_one(query, bind_vars=bind_vars)
            if result:
                return result

        # Check by metadata keys
        if upsert_metadata_keys and self.metadata_column in doc_dict:
            metadata = doc_dict[self.metadata_column]
            conditions = []
            bind_vars = {}

            for key in upsert_metadata_keys:
                if key in metadata:
                    var_name = f"meta_{key}"
                    conditions.append(f"doc.{self.metadata_column}.{key} == @{var_name}")
                    bind_vars[var_name] = metadata[key]

            if conditions:
                filter_clause = " AND ".join(conditions)
                query = f"""
                FOR doc IN {collection}
                    FILTER {filter_clause}
                    LIMIT 1
                    RETURN doc
                """

                result = await self._db.fetch_one(query, bind_vars=bind_vars)
                if result:
                    return result

        return None

    def _build_filter_conditions(
        self,
        metadata_filters: Optional[dict]
    ) -> Optional[List[str]]:
        """Build AQL filter conditions from metadata filters."""
        if not metadata_filters:
            return None

        conditions = []
        for key, value in metadata_filters.items():
            if isinstance(value, (list, tuple)):
                # IN condition
                values_str = ", ".join([f"'{v}'" for v in value])
                conditions.append(f"doc.{self.metadata_column}.{key} IN [{values_str}]")
            else:
                # Equality condition
                conditions.append(f"doc.{self.metadata_column}.{key} == '{value}'")

        return conditions

    def _to_search_results(
        self,
        results: List[dict],
        score_field: str = 'similarity'
    ) -> List[SearchResult]:
        """Convert ArangoDB results to SearchResult objects."""
        search_results = []

        for result in results:
            # Extract document
            doc = result.get('document', result)

            # Extract score
            score = result.get(score_field, 0.0)

            # Create Document object
            document = Document(
                page_content=doc.get(self.text_column, ""),
                metadata=doc.get(self.metadata_column, {})
            )

            # Create SearchResult
            search_result = SearchResult(
                document=document,
                score=score,
                metadata={
                    '_id': doc.get('_id'),
                    '_key': doc.get('_key'),
                    **doc.get(self.metadata_column, {})
                }
            )

            search_results.append(search_result)

        return search_results

    async def _enrich_with_graph_context(
        self,
        search_results: List[SearchResult]
    ) -> List[SearchResult]:
        """Enrich results with graph context."""
        if not self.default_graph:
            return search_results

        enriched = []
        for result in search_results:
            doc_id = result.metadata.get('_id')

            if doc_id:
                try:
                    # Get related nodes
                    neighbors = await self._db.find_related_nodes(
                        node_id=doc_id,
                        max_depth=1,
                        limit=5,
                        graph_name=self.default_graph
                    )

                    # Add to metadata
                    result.metadata['graph_context'] = neighbors
                except Exception as e:
                    self.logger.debug(f"Could not get graph context: {e}")

            enriched.append(result)

        return enriched

    async def prepare_embedding_table(
        self,
        collection: str = None,
        recreate: bool = False,
        **kwargs
    ) -> bool:
        """
        Prepare collection for vector storage.

        Args:
            collection: Collection name
            recreate: If True, drop and recreate collection
            **kwargs: Additional arguments

        Returns:
            True if successful
        """
        collection = collection or self.collection_name

        # Drop if recreate
        if recreate and await self.collection_exists(collection):
            await self.delete_collection(collection)

        # Create collection
        await self.create_collection(collection)

        # Create search view
        await self._ensure_search_view()

        self.logger.info(f"Prepared collection: {collection}")
        return True
