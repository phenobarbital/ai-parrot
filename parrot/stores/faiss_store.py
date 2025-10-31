"""
FAISSStore: In-memory Vector Store implementation using FAISS.

Provides high-performance vector similarity search with:
- In-memory vector storage with FAISS indexes
- Multiple distance metrics (Cosine, L2, Inner Product)
- CPU-only execution (GPU support removed)
- MMR (Maximal Marginal Relevance) search
- Metadata filtering
- Collection management
- Async context manager support
"""
from typing import Any, Dict, List, Optional, Union, Callable
import uuid
import pickle
from pathlib import Path
import numpy as np
from navconfig.logging import logging
from sklearn.metrics.pairwise import cosine_similarity, euclidean_distances

try:
    import faiss
    FAISS_AVAILABLE = True
except ImportError:
    FAISS_AVAILABLE = False
    faiss = None

from .abstract import AbstractStore
from .models import Document, SearchResult, DistanceStrategy


class FAISSStore(AbstractStore):
    """
    An in-memory FAISS vector store implementation, completely independent of Langchain.

    This store provides high-performance vector similarity search using FAISS indexes
    with support for multiple distance metrics and metadata filtering.

    Features:
    - Multiple FAISS index types (Flat, IVF, HNSW)
    - CPU-only execution
    - Cosine, L2, and Inner Product distance metrics
    - MMR (Maximal Marginal Relevance) search
    - Metadata filtering
    - Persistent storage via save/load
    """

    def __init__(
        self,
        collection_name: str = "default",
        id_column: str = 'id',
        embedding_column: str = 'embedding',
        document_column: str = 'document',
        text_column: str = 'text',
        metadata_column: str = 'metadata',
        embedding_model: Union[dict, str] = "sentence-transformers/all-mpnet-base-v2",
        embedding: Optional[Callable] = None,
        distance_strategy: DistanceStrategy = DistanceStrategy.COSINE,
        index_type: str = "Flat",  # Options: "Flat", "IVF", "HNSW"
        nlist: int = 100,  # For IVF indexes
        nprobe: int = 10,  # For IVF search
        m: int = 32,  # For HNSW
        ef_construction: int = 40,  # For HNSW
        ef_search: int = 16,  # For HNSW
        **kwargs
    ):
        """
        Initialize FAISSStore with the specified parameters.

        Args:
            collection_name: Name of the collection/index
            id_column: Name of the ID column
            embedding_column: Name of the embedding column
            document_column: Name of the document content column
            text_column: Name of the text column
            metadata_column: Name of the metadata column
            embedding_model: Embedding model configuration (dict or string)
            embedding: Custom embedding function
            distance_strategy: Distance metric to use (COSINE, EUCLIDEAN_DISTANCE, etc.)
            index_type: Type of FAISS index ("Flat", "IVF", "HNSW")
            nlist: Number of clusters for IVF indexes
            nprobe: Number of clusters to probe for IVF search
            m: Number of connections per layer for HNSW
            ef_construction: Size of dynamic candidate list for HNSW construction
            ef_search: Size of dynamic candidate list for HNSW search
        """
        if not FAISS_AVAILABLE:
            raise ImportError(
                "FAISS is not installed. Please install it with: pip install faiss-cpu"
            )

        # Store configuration
        self.collection_name = collection_name
        self._id_column: str = id_column
        self._embedding_column: str = embedding_column
        self._document_column: str = document_column
        self._text_column: str = text_column
        self._metadata_column: str = metadata_column

        # FAISS configuration
        self.index_type = index_type
        self.nlist = nlist
        self.nprobe = nprobe
        self.m = m
        self.ef_construction = ef_construction
        self.ef_search = ef_search

        # Distance strategy
        self.distance_strategy = distance_strategy

        # Initialize parent class
        super().__init__(
            embedding_model=embedding_model,
            embedding=embedding,
            **kwargs
        )

        # Collections store: {collection_name: collection_data}
        self._collections: Dict[str, Dict[str, Any]] = {}

        # Initialize logger
        self.logger = logging.getLogger("FAISSStore")

        # Connection state
        self._connected: bool = False
        self._connection = None  # For compatibility with abstract interface

        # Initialize default collection
        if collection_name:
            self._initialize_collection(collection_name)

    def _initialize_collection(self, collection_name: str) -> None:
        """Initialize a new collection with empty data structures."""
        if collection_name not in self._collections:
            self._collections[collection_name] = {
                'index': None,  # FAISS index
                'documents': {},  # {id: document_content}
                'metadata': {},  # {id: metadata_dict}
                'embeddings': {},  # {id: embedding_vector}
                'id_to_idx': {},  # {id: faiss_index_position}
                'idx_to_id': {},  # {faiss_index_position: id}
                'dimension': None,
                'is_trained': False,
            }
            self.logger.info(f"Initialized collection: {collection_name}")

    def define_collection_table(
        self,
        collection_name: str,
        dimension: int = 384,
        **kwargs
    ) -> Dict[str, Any]:
        """
        Define an in-memory collection table for saving vector + metadata information.

        This method is compatible with the PgVectorStore pattern but operates in-memory.

        Args:
            collection_name: Name of the collection
            dimension: Dimension of the embedding vectors
            **kwargs: Additional arguments (for compatibility)

        Returns:
            Dictionary representing the collection structure
        """
        if collection_name not in self._collections:
            self._initialize_collection(collection_name)

        collection = self._collections[collection_name]
        collection['dimension'] = dimension

        # Create FAISS index based on configuration
        index = self._create_faiss_index(dimension)
        collection['index'] = index

        self.logger.info(
            f"Defined collection table '{collection_name}' with dimension {dimension}"
        )

        return {
            'collection_name': collection_name,
            'dimension': dimension,
            'index_type': self.index_type,
            'distance_strategy': self.distance_strategy.value,
        }

    def _create_faiss_index(self, dimension: int) -> Any:
        """
        Create a FAISS index based on the configured index type and distance strategy.

        Args:
            dimension: Dimension of the embedding vectors

        Returns:
            FAISS index object
        """
        # Determine the metric type based on distance strategy
        if self.distance_strategy == DistanceStrategy.COSINE:
            # For cosine similarity, we'll normalize vectors and use inner product
            metric = faiss.METRIC_INNER_PRODUCT
        elif self.distance_strategy == DistanceStrategy.EUCLIDEAN_DISTANCE:
            metric = faiss.METRIC_L2
        elif self.distance_strategy in [DistanceStrategy.DOT_PRODUCT, DistanceStrategy.MAX_INNER_PRODUCT]:
            metric = faiss.METRIC_INNER_PRODUCT
        else:
            # Default to inner product
            metric = faiss.METRIC_INNER_PRODUCT

        # Create index based on type
        if self.index_type == "Flat":
            index = faiss.IndexFlatIP(dimension) if metric == faiss.METRIC_INNER_PRODUCT else faiss.IndexFlatL2(dimension)

        elif self.index_type == "IVF":
            # IVF (Inverted File Index) for faster search on large datasets
            quantizer = faiss.IndexFlatIP(dimension) if metric == faiss.METRIC_INNER_PRODUCT else faiss.IndexFlatL2(dimension)
            index = faiss.IndexIVFFlat(quantizer, dimension, self.nlist, metric)
            index.nprobe = self.nprobe

        elif self.index_type == "HNSW":
            # HNSW (Hierarchical Navigable Small World) for very fast search
            index = faiss.IndexHNSWFlat(dimension, self.m, metric)
            index.hnsw.efConstruction = self.ef_construction
            index.hnsw.efSearch = self.ef_search

        else:
            raise ValueError(f"Unsupported index type: {self.index_type}")

        self.logger.info(
            f"Created FAISS index: type={self.index_type}, "
            f"metric={metric}, dimension={dimension}, cpu_only=True"
        )

        return index

    async def connection(self) -> bool:
        """
        Establish connection (for compatibility with AbstractStore).

        Since FAISS is in-memory, this just marks the store as connected.

        Returns:
            True if successful
        """
        if not self._connected:
            self._connected = True
            self._connection = True  # Dummy connection for compatibility
            self.logger.info("FAISSStore connection established (in-memory)")
        return True

    async def disconnect(self) -> None:
        """
        Disconnect and cleanup resources.

        Clears all in-memory data.
        """
        if not self._connected:
            return
        # Clear indexes
        for _, collection in self._collections.items():
            if collection.get('index'):
                del collection['index']

        # Clear collections
        self._collections.clear()

        self._connected = False
        self._connection = None
        self.logger.info("FAISSStore disconnected and resources cleared")

    async def __aenter__(self):
        """Async context manager entry."""
        if not self._connected:
            await self.connection()
        self._context_depth += 1
        return self

    async def __aexit__(self, exc_type, exc_value, traceback):
        """Async context manager exit."""
        # Free embedding resources
        if self._embed_:
            await self._free_resources()

        try:
            # Only disconnect if we're exiting the outermost context
            self._context_depth -= 1
            if self._context_depth <= 0:
                await self.disconnect()
                self._context_depth = 0
        except RuntimeError:
            pass

    async def prepare_embedding_table(
        self,
        collection: str = None,
        dimension: int = None,
        **kwargs
    ) -> bool:
        """
        Prepare the embedding table/collection for storing vectors.

        Args:
            collection: Collection name
            dimension: Embedding dimension
            **kwargs: Additional arguments

        Returns:
            True if successful
        """
        collection = collection or self.collection_name
        dimension = dimension or self.dimension

        if collection not in self._collections:
            self.define_collection_table(collection, dimension, **kwargs)
        else:
            # Update dimension if needed
            if dimension and self._collections[collection]['dimension'] != dimension:
                self._collections[collection]['dimension'] = dimension
                # Recreate index with new dimension
                self._collections[collection]['index'] = self._create_faiss_index(dimension)
                self.logger.info(f"Updated collection '{collection}' dimension to {dimension}")

        return True

    async def create_embedding_table(
        self,
        collection: str = None,
        dimension: int = None,
        **kwargs
    ) -> None:
        """
        Create an embedding table/collection (alias for prepare_embedding_table).

        Args:
            collection: Collection name
            dimension: Embedding dimension
            **kwargs: Additional arguments
        """
        await self.prepare_embedding_table(collection, dimension, **kwargs)

    async def create_collection(self, collection: str, **kwargs) -> None:
        """
        Create a new collection.

        Args:
            collection: Collection name
            **kwargs: Additional arguments (e.g., dimension)
        """
        dimension = kwargs.get('dimension', self.dimension)
        await self.create_embedding_table(collection, dimension, **kwargs)

    async def add_documents(
        self,
        documents: List[Document],
        collection: str = None,
        embedding_column: str = None,
        content_column: str = None,
        metadata_column: str = None,
        **kwargs
    ) -> None:
        """
        Add documents to the FAISS store.

        Args:
            documents: List of Document objects to add
            collection: Collection name (optional, uses default if not provided)
            embedding_column: Name of the embedding column (for compatibility)
            content_column: Name of the content column (for compatibility)
            metadata_column: Name of the metadata column (for compatibility)
            **kwargs: Additional arguments
        """
        if not self._connected:
            await self.connection()

        collection = collection or self.collection_name

        # Ensure collection exists
        if collection not in self._collections:
            self._initialize_collection(collection)

        collection_data = self._collections[collection]

        # Extract texts and metadata
        texts = [doc.page_content for doc in documents]
        metadatas = [doc.metadata for doc in documents]

        # Generate embeddings
        embeddings = self._embed_.embed_documents(texts)

        # Convert to numpy array
        if isinstance(embeddings, list):
            embeddings = np.array(embeddings, dtype=np.float32)
        elif not isinstance(embeddings, np.ndarray):
            embeddings = np.array(embeddings, dtype=np.float32)

        # Ensure 2D array
        if embeddings.ndim == 1:
            embeddings = embeddings.reshape(1, -1)

        # Set dimension if not set
        if collection_data['dimension'] is None:
            collection_data['dimension'] = embeddings.shape[1]
            collection_data['index'] = self._create_faiss_index(embeddings.shape[1])

        # Normalize embeddings for cosine similarity
        if self.distance_strategy == DistanceStrategy.COSINE:
            faiss.normalize_L2(embeddings)

        # Train index if needed (for IVF)
        if self.index_type == "IVF" and not collection_data['is_trained']:
            if len(embeddings) >= self.nlist:
                collection_data['index'].train(embeddings)
                collection_data['is_trained'] = True
                self.logger.info(f"Trained IVF index for collection '{collection}'")
            else:
                self.logger.warning(
                    f"Not enough vectors to train IVF index "
                    f"(need {self.nlist}, got {len(embeddings)}). Using Flat index temporarily."
                )

        # Get current index size
        current_idx = collection_data['index'].ntotal

        # Add to FAISS index
        collection_data['index'].add(embeddings)

        # Store documents, metadata, and embeddings
        for i, (text, metadata, embedding) in enumerate(zip(texts, metadatas, embeddings)):
            doc_id = str(uuid.uuid4())
            idx = current_idx + i

            collection_data['documents'][doc_id] = text
            collection_data['metadata'][doc_id] = metadata or {}
            collection_data['embeddings'][doc_id] = embedding
            collection_data['id_to_idx'][doc_id] = idx
            collection_data['idx_to_id'][idx] = doc_id

        self.logger.info(
            f"✅ Successfully added {len(documents)} documents to collection '{collection}'"
        )

    def get_distance_strategy(
        self,
        query_embedding: np.ndarray,
        metric: str = None
    ) -> str:
        """
        Return the appropriate distance strategy based on the metric or configured strategy.

        Args:
            query_embedding: Query embedding vector (for compatibility)
            metric: Optional metric string ('COSINE', 'L2', 'IP', 'DOT')

        Returns:
            Distance strategy as string
        """
        strategy = metric or self.distance_strategy

        # Convert string metrics to DistanceStrategy enum if needed
        if isinstance(strategy, str):
            metric_mapping = {
                'COSINE': DistanceStrategy.COSINE,
                'L2': DistanceStrategy.EUCLIDEAN_DISTANCE,
                'EUCLIDEAN': DistanceStrategy.EUCLIDEAN_DISTANCE,
                'IP': DistanceStrategy.MAX_INNER_PRODUCT,
                'DOT': DistanceStrategy.DOT_PRODUCT,
                'DOT_PRODUCT': DistanceStrategy.DOT_PRODUCT,
                'MAX_INNER_PRODUCT': DistanceStrategy.MAX_INNER_PRODUCT
            }
            strategy = metric_mapping.get(strategy.upper(), DistanceStrategy.COSINE)

        return strategy

    async def similarity_search(
        self,
        query: str,
        collection: str = None,
        k: Optional[int] = None,
        limit: int = None,
        metadata_filters: Optional[Dict[str, Any]] = None,
        score_threshold: Optional[float] = None,
        metric: str = None,
        embedding_column: str = None,
        content_column: str = None,
        metadata_column: str = None,
        id_column: str = None,
        **kwargs
    ) -> List[SearchResult]:
        """
        Perform similarity search with optional threshold filtering.

        Args:
            query: The search query text
            collection: Collection name (optional, uses default if not provided)
            k: Number of results to return (alias for limit)
            limit: Maximum number of results to return
            metadata_filters: Dictionary of metadata filters to apply
            score_threshold: Minimum score threshold (results below threshold filtered out)
            metric: Distance metric to use ('COSINE', 'L2', 'IP')
            embedding_column: Name of the embedding column (for compatibility)
            content_column: Name of the content column (for compatibility)
            metadata_column: Name of the metadata column (for compatibility)
            id_column: Name of the ID column (for compatibility)
            **kwargs: Additional arguments

        Returns:
            List of SearchResult objects with content, metadata, score, and id
        """
        if not self._connected:
            await self.connection()

        collection = collection or self.collection_name

        if k and not limit:
            limit = k
        if not limit:
            limit = 10

        # Ensure collection exists
        if collection not in self._collections:
            self.logger.warning(f"Collection '{collection}' not found")
            return []

        collection_data = self._collections[collection]

        if collection_data['index'] is None or collection_data['index'].ntotal == 0:
            self.logger.warning(f"Collection '{collection}' is empty")
            return []

        # Generate query embedding
        query_embedding = self._embed_.embed_query(query)

        # Convert to numpy array
        if isinstance(query_embedding, list):
            query_embedding = np.array(query_embedding, dtype=np.float32)
        elif not isinstance(query_embedding, np.ndarray):
            query_embedding = np.array(query_embedding, dtype=np.float32)

        # Ensure 2D array
        if query_embedding.ndim == 1:
            query_embedding = query_embedding.reshape(1, -1)

        # Normalize for cosine similarity
        if self.distance_strategy == DistanceStrategy.COSINE:
            faiss.normalize_L2(query_embedding)

        # Search FAISS index
        # For metadata filtering, we need to search more results and filter
        search_k = limit * 3 if metadata_filters else limit
        search_k = min(search_k, collection_data['index'].ntotal)

        distances, indices = collection_data['index'].search(query_embedding, search_k)

        # Convert distances to scores
        # FAISS returns distances, but we want similarity scores (higher is better)
        distances = distances[0]  # Get first row
        indices = indices[0]  # Get first row

        # Convert to scores based on metric
        if self.distance_strategy == DistanceStrategy.COSINE:
            # For cosine with normalized vectors, distance is actually similarity
            scores = distances
        elif self.distance_strategy == DistanceStrategy.EUCLIDEAN_DISTANCE:
            # Convert distance to similarity
            scores = 1.0 / (1.0 + distances)
        else:
            # For inner product, distance is already similarity-like
            scores = distances

        # Build results
        results = []
        for idx, score in zip(indices, scores):
            if idx == -1:  # FAISS returns -1 for empty slots
                continue

            # Get document ID
            doc_id = collection_data['idx_to_id'].get(idx)
            if doc_id is None:
                continue

            # Get document data
            content = collection_data['documents'].get(doc_id, "")
            metadata = collection_data['metadata'].get(doc_id, {})

            # Apply metadata filters
            if metadata_filters:
                match = True
                for key, value in metadata_filters.items():
                    if metadata.get(key) != value:
                        match = False
                        break
                if not match:
                    continue

            # Apply score threshold
            if score_threshold is not None:
                if self.distance_strategy == DistanceStrategy.EUCLIDEAN_DISTANCE:
                    # For L2 distance, lower is better, so invert the check
                    if distances[np.where(indices == idx)[0][0]] > score_threshold:
                        continue
                else:
                    # For cosine and inner product, higher is better
                    if score < score_threshold:
                        continue

            # Create search result
            result = SearchResult(
                id=doc_id,
                content=content,
                metadata=metadata,
                score=float(score)
            )
            results.append(result)

            # Stop if we have enough results
            if len(results) >= limit:
                break

        self.logger.debug(
            f"Similarity search in collection '{collection}': "
            f"found {len(results)} results (limit={limit})"
        )

        return results

    async def mmr_search(
        self,
        query: str,
        collection: str = None,
        k: int = 4,
        fetch_k: Optional[int] = None,
        lambda_mult: float = 0.5,
        metadata_filters: Optional[Dict[str, Any]] = None,
        score_threshold: Optional[float] = None,
        metric: str = None,
        embedding_column: str = None,
        content_column: str = None,
        metadata_column: str = None,
        id_column: str = None,
        **kwargs
    ) -> List[SearchResult]:
        """
        Perform MMR (Maximal Marginal Relevance) search for diversity.

        MMR balances relevance with diversity by selecting documents that are:
        1. Relevant to the query
        2. Diverse from already selected documents

        Args:
            query: The search query text
            collection: Collection name (optional, uses default if not provided)
            k: Number of results to return
            fetch_k: Number of candidates to fetch (default: k*3)
            lambda_mult: Diversity parameter (0-1)
                - 1.0 = maximum relevance (no diversity)
                - 0.0 = maximum diversity (no relevance)
            metadata_filters: Dictionary of metadata filters to apply
            score_threshold: Minimum score threshold
            metric: Distance metric to use ('COSINE', 'L2', 'IP')
            embedding_column: Name of the embedding column (for compatibility)
            content_column: Name of the content column (for compatibility)
            metadata_column: Name of the metadata column (for compatibility)
            id_column: Name of the ID column (for compatibility)
            **kwargs: Additional arguments

        Returns:
            List of SearchResult objects ordered by MMR score
        """
        if not self._connected:
            await self.connection()

        collection = collection or self.collection_name

        # Default to fetching 3x more candidates than final results
        if fetch_k is None:
            fetch_k = max(k * 3, 20)

        # Step 1: Get initial candidates using similarity search
        candidates = await self.similarity_search(
            query=query,
            collection=collection,
            limit=fetch_k,
            metadata_filters=metadata_filters,
            score_threshold=score_threshold,
            metric=metric,
            embedding_column=embedding_column,
            content_column=content_column,
            metadata_column=metadata_column,
            id_column=id_column,
            **kwargs
        )

        if len(candidates) <= k:
            # If we have fewer candidates than requested results, return all
            return candidates

        # Step 2: Get embeddings for MMR computation
        collection_data = self._collections[collection]
        candidate_embeddings = {}
        for result in candidates:
            embedding = collection_data['embeddings'].get(result.id)
            if embedding is not None:
                candidate_embeddings[result.id] = embedding

        # Step 3: Get query embedding
        query_embedding = self._embed_.embed_query(query)
        if isinstance(query_embedding, list):
            query_embedding = np.array(query_embedding, dtype=np.float32)
        elif not isinstance(query_embedding, np.ndarray):
            query_embedding = np.array(query_embedding, dtype=np.float32)

        # Step 4: Run MMR algorithm
        selected_results = self._mmr_algorithm(
            query_embedding=query_embedding,
            candidates=candidates,
            candidate_embeddings=candidate_embeddings,
            k=k,
            lambda_mult=lambda_mult,
            metric=metric or self.distance_strategy
        )

        self.logger.info(
            f"MMR search in collection '{collection}': "
            f"selected {len(selected_results)} results from {len(candidates)} candidates "
            f"(λ={lambda_mult})"
        )

        return selected_results

    def _mmr_algorithm(
        self,
        query_embedding: np.ndarray,
        candidates: List[SearchResult],
        candidate_embeddings: Dict[str, np.ndarray],
        k: int,
        lambda_mult: float,
        metric: Union[str, DistanceStrategy]
    ) -> List[SearchResult]:
        """
        Core MMR algorithm implementation (same as PgVectorStore).

        Args:
            query_embedding: Query embedding vector
            candidates: List of candidate SearchResult objects
            candidate_embeddings: Dictionary mapping doc ID to embedding vector
            k: Number of results to select
            lambda_mult: MMR diversity parameter (0-1)
            metric: Distance metric to use

        Returns:
            List of selected SearchResult objects ordered by MMR score
        """
        if len(candidates) <= k:
            return candidates

        # Convert query embedding to numpy array
        if not isinstance(query_embedding, np.ndarray):
            query_embedding = np.array(query_embedding, dtype=np.float32)

        # Prepare data structures
        selected_indices = []
        remaining_indices = list(range(len(candidates)))

        # Step 1: Select the most relevant document first
        query_similarities = []
        for candidate in candidates:
            doc_embedding = candidate_embeddings.get(candidate.id)
            if doc_embedding is not None:
                similarity = self._compute_similarity(query_embedding, doc_embedding, metric)
                query_similarities.append(similarity)
            else:
                # Fallback to distance score if embedding not available
                query_similarities.append(1.0 / (1.0 + candidate.score))

        # Select the most similar document first
        best_idx = np.argmax(query_similarities)
        selected_indices.append(best_idx)
        remaining_indices.remove(best_idx)

        # Step 2: Iteratively select remaining documents using MMR
        for _ in range(min(k - 1, len(remaining_indices))):
            mmr_scores = []

            for idx in remaining_indices:
                candidate = candidates[idx]
                doc_embedding = candidate_embeddings.get(candidate.id)

                if doc_embedding is None:
                    # Fallback scoring if embedding not available
                    mmr_score = lambda_mult * query_similarities[idx]
                    mmr_scores.append(mmr_score)
                    continue

                # Relevance: similarity to query
                relevance = query_similarities[idx]

                # Diversity: maximum similarity to already selected documents
                max_similarity_to_selected = 0.0
                for selected_idx in selected_indices:
                    selected_candidate = candidates[selected_idx]
                    selected_embedding = candidate_embeddings.get(selected_candidate.id)

                    if selected_embedding is not None:
                        similarity = self._compute_similarity(doc_embedding, selected_embedding, metric)
                        max_similarity_to_selected = max(max_similarity_to_selected, similarity)

                # MMR formula: λ * relevance - (1-λ) * max_similarity_to_selected
                mmr_score = (
                    lambda_mult * relevance -
                    (1.0 - lambda_mult) * max_similarity_to_selected
                )
                mmr_scores.append(mmr_score)

            # Select document with highest MMR score
            if mmr_scores:
                best_remaining_idx = np.argmax(mmr_scores)
                best_idx = remaining_indices[best_remaining_idx]
                selected_indices.append(best_idx)
                remaining_indices.remove(best_idx)

        # Step 3: Return selected results with MMR scores in metadata
        selected_results = []
        for i, idx in enumerate(selected_indices):
            result = candidates[idx]
            # Add MMR ranking to metadata
            enhanced_metadata = dict(result.metadata)
            enhanced_metadata['mmr_rank'] = i + 1
            enhanced_metadata['mmr_lambda'] = lambda_mult
            enhanced_metadata['original_rank'] = idx + 1

            enhanced_result = SearchResult(
                id=result.id,
                content=result.content,
                metadata=enhanced_metadata,
                score=result.score
            )
            selected_results.append(enhanced_result)

        return selected_results

    def _compute_similarity(
        self,
        embedding1: np.ndarray,
        embedding2: np.ndarray,
        metric: Union[str, DistanceStrategy]
    ) -> float:
        """
        Compute similarity between two embeddings based on the specified metric.

        Args:
            embedding1: First embedding vector (numpy array or list)
            embedding2: Second embedding vector (numpy array or list)
            metric: Distance metric ('COSINE', 'L2', 'IP', etc.)

        Returns:
            Similarity score (higher = more similar)
        """
        # Convert to numpy arrays if needed
        if isinstance(embedding1, list):
            embedding1 = np.array(embedding1, dtype=np.float32)
        if isinstance(embedding2, list):
            embedding2 = np.array(embedding2, dtype=np.float32)

        # Ensure embeddings are numpy arrays
        if not isinstance(embedding1, np.ndarray):
            embedding1 = np.array(embedding1, dtype=np.float32)
        if not isinstance(embedding2, np.ndarray):
            embedding2 = np.array(embedding2, dtype=np.float32)

        # Ensure embeddings are 2D arrays for sklearn
        emb1 = embedding1.reshape(1, -1)
        emb2 = embedding2.reshape(1, -1)

        # Convert string metrics to DistanceStrategy enum if needed
        if isinstance(metric, str):
            metric_mapping = {
                'COSINE': DistanceStrategy.COSINE,
                'L2': DistanceStrategy.EUCLIDEAN_DISTANCE,
                'EUCLIDEAN': DistanceStrategy.EUCLIDEAN_DISTANCE,
                'IP': DistanceStrategy.MAX_INNER_PRODUCT,
                'DOT': DistanceStrategy.DOT_PRODUCT,
                'DOT_PRODUCT': DistanceStrategy.DOT_PRODUCT,
                'MAX_INNER_PRODUCT': DistanceStrategy.MAX_INNER_PRODUCT
            }
            strategy = metric_mapping.get(metric.upper(), DistanceStrategy.COSINE)
        else:
            strategy = metric

        if strategy == DistanceStrategy.COSINE:
            # Cosine similarity (returns similarity, not distance)
            similarity = cosine_similarity(emb1, emb2)[0, 0]
            return float(similarity)

        elif strategy == DistanceStrategy.EUCLIDEAN_DISTANCE:
            # Convert Euclidean distance to similarity
            distance = euclidean_distances(emb1, emb2)[0, 0]
            similarity = 1.0 / (1.0 + distance)
            return float(similarity)

        elif strategy in [DistanceStrategy.MAX_INNER_PRODUCT, DistanceStrategy.DOT_PRODUCT]:
            # Dot product (inner product)
            similarity = np.dot(embedding1.flatten(), embedding2.flatten())
            return float(similarity)

        else:
            # Default to cosine similarity
            similarity = cosine_similarity(emb1, emb2)[0, 0]
            return float(similarity)

    # Additional methods for compatibility

    def get_vector(self, metric_type: str = None, **kwargs):
        """
        Get the FAISS vector store (for compatibility).

        Args:
            metric_type: Distance metric type
            **kwargs: Additional arguments

        Returns:
            The FAISSStore instance itself
        """
        return self

    async def from_documents(
        self,
        documents: List[Document],
        collection: Union[str, None] = None,
        **kwargs
    ) -> 'FAISSStore':
        """
        Create Vector Store from Documents.

        Args:
            documents: List of Documents
            collection: Collection Name
            **kwargs: Additional Arguments

        Returns:
            The FAISSStore instance
        """
        await self.add_documents(documents, collection=collection, **kwargs)
        return self

    # Persistence methods

    def save(self, file_path: Union[str, Path]) -> None:
        """
        Save the FAISS store to disk.

        Args:
            file_path: Path to save the store
        """
        file_path = Path(file_path)
        file_path.parent.mkdir(parents=True, exist_ok=True)

        # Prepare data for saving
        save_data = {
            'collections': {},
            'config': {
                'collection_name': self.collection_name,
                'distance_strategy': self.distance_strategy.value,
                'index_type': self.index_type,
                'dimension': self.dimension,
            }
        }

        # Save each collection
        for coll_name, coll_data in self._collections.items():
            # Save FAISS index
            index_path = file_path.parent / f"{file_path.stem}_{coll_name}.index"
            if coll_data['index'] is not None:
                faiss.write_index(coll_data['index'], str(index_path))

            # Save metadata and documents
            save_data['collections'][coll_name] = {
                'documents': coll_data['documents'],
                'metadata': coll_data['metadata'],
                'embeddings': {k: v.tolist() for k, v in coll_data['embeddings'].items()},
                'id_to_idx': coll_data['id_to_idx'],
                'idx_to_id': coll_data['idx_to_id'],
                'dimension': coll_data['dimension'],
                'is_trained': coll_data['is_trained'],
                'index_path': str(index_path),
            }

        # Save to pickle
        with open(file_path, 'wb') as f:
            pickle.dump(save_data, f)

        self.logger.info(f"Saved FAISS store to {file_path}")

    def load(self, file_path: Union[str, Path]) -> None:
        """
        Load the FAISS store from disk.

        Args:
            file_path: Path to load the store from
        """
        file_path = Path(file_path)

        with open(file_path, 'rb') as f:
            save_data = pickle.load(f)

        # Restore config
        config = save_data.get('config', {})
        self.collection_name = config.get('collection_name', self.collection_name)

        # Restore collections
        for coll_name, coll_data in save_data['collections'].items():
            self._initialize_collection(coll_name)

            # Load FAISS index
            index_path = coll_data['index_path']
            if Path(index_path).exists():
                index = faiss.read_index(index_path)

                self._collections[coll_name]['index'] = index

            # Load metadata and documents
            self._collections[coll_name]['documents'] = coll_data['documents']
            self._collections[coll_name]['metadata'] = coll_data['metadata']
            self._collections[coll_name]['embeddings'] = {
                k: np.array(v, dtype=np.float32)
                for k, v in coll_data['embeddings'].items()
            }
            self._collections[coll_name]['id_to_idx'] = coll_data['id_to_idx']
            self._collections[coll_name]['idx_to_id'] = coll_data['idx_to_id']
            self._collections[coll_name]['dimension'] = coll_data['dimension']
            self._collections[coll_name]['is_trained'] = coll_data['is_trained']

        self.logger.info(f"Loaded FAISS store from {file_path}")

    def __str__(self) -> str:
        return f"FAISSStore(collection={self.collection_name}, index_type={self.index_type})"

    def __repr__(self) -> str:
        return (
            f"<FAISSStore(collection='{self.collection_name}', "
            f"index_type='{self.index_type}', "
            f"distance_strategy='{self.distance_strategy.value}', "
            "cpu_only=True)>"
        )
