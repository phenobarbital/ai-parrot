from __future__ import annotations
from typing import List, Tuple, Optional, Any, TYPE_CHECKING
from parrot._imports import lazy_import
from ....models.crew import AgentResult, VectorStoreProtocol


class VectorStoreMixin:
    """Mixin to add FAISS vector store capabilities to ExecutionMemory"""

    def __init__(
        self,
        *args,
        embedding_model: Optional[VectorStoreProtocol] = None,
        dimension: int = 384,
        index_type: str = "Flat",
        **kwargs
    ):
        super().__init__(*args, **kwargs)
        self._raw_embedding_model = embedding_model
        self.dimension = dimension
        self._faiss_index: Optional[Any] = None
        self._vector_chunks: List[Tuple[str, str]] = []  # (chunk_text, agent_id)
        self._faiss_available = False

        if embedding_model:
            try:
                faiss = lazy_import("faiss", package_name="faiss-cpu", extra="embeddings")
                _st = lazy_import("sentence_transformers", package_name="sentence-transformers", extra="embeddings")
                if isinstance(embedding_model, str):
                    self._raw_embedding_model = _st.SentenceTransformer(embedding_model)
                # Initialize FAISS index based on type
                if index_type == "FlatIP":
                    self._faiss_index = faiss.IndexFlatIP(dimension)
                elif index_type == "HNSW":
                    self._faiss_index = faiss.IndexHNSWFlat(dimension, 32, faiss.METRIC_INNER_PRODUCT)
                else:  # Default to FlatL2
                    self._faiss_index = faiss.IndexFlatL2(dimension)
                self._faiss_available = True

            except (ImportError, AttributeError):
                self._faiss_index = None
                self._faiss_available = False

    @property
    def embedding_model(self):
        """Return the raw (sync) embedding model for FAISS operations.

        If the stored model is an EmbeddingModel wrapper (async encode),
        extract the underlying library model via its ``.model`` property.
        """
        from parrot.embeddings.base import EmbeddingModel
        obj = self._raw_embedding_model
        if isinstance(obj, EmbeddingModel):
            return obj.model
        return obj

    @embedding_model.setter
    def embedding_model(self, value):
        self._raw_embedding_model = value

    def _chunk_result(self, result: AgentResult) -> List[str]:
        """Break down result into semantically meaningful chunks"""
        text = result.to_text()

        # Simple chunking - can be enhanced
        if len(text) < 500:
            return [text]

        chunks = []
        sections = text.split('\n\n')
        current_chunk = []
        current_length = 0

        for section in sections:
            if current_length + len(section) > 500 and current_chunk:
                chunks.append('\n'.join(current_chunk))
                current_chunk = [section]
                current_length = len(section)
            else:
                current_chunk.append(section)
                current_length += len(section)

        if current_chunk:
            chunks.append('\n'.join(current_chunk))

        return chunks

    async def _vectorize_result_async(self, result: AgentResult):
        """Async task to vectorize and index a result"""
        if not self._faiss_available or not self.embedding_model or self._faiss_index is None:
            return

        # Chunk the result
        chunks = self._chunk_result(result)

        # Store chunks with agent reference
        for chunk in chunks:
            self._vector_chunks.append((chunk, result.agent_id))

        # Generate embeddings for all chunks
        all_texts = [chunk for chunk, _ in self._vector_chunks]
        embeddings = self.embedding_model.encode(all_texts, convert_to_numpy=True)

        # Ensure correct dtype and shape
        embeddings = embeddings.astype('float32')

        # Rebuild index with all embeddings
        self._faiss_index.reset()
        self._faiss_index.add(embeddings)

    def search_similar(self, query: str, top_k: int = 5) -> List[Tuple[str, AgentResult, float]]:
        """Search for semantically similar result chunks"""
        if not self._faiss_available or self._faiss_index is None or self._faiss_index.ntotal == 0:
            return []

        # Generate query embedding
        query_embedding = self.embedding_model.encode([query], convert_to_numpy=True)
        query_embedding = query_embedding.astype('float32')

        # Ensure correct shape (1, dimension)
        if len(query_embedding.shape) == 1:
            query_embedding = query_embedding.reshape(1, -1)

        # Search FAISS - API correcta
        k = min(top_k, self._faiss_index.ntotal)
        D, I = self._faiss_index.search(query_embedding, k)

        results = []
        for idx, distance in zip(I[0], D[0]):
            if idx < len(self._vector_chunks) and idx >= 0:  # idx puede ser -1 si no hay suficientes resultados
                chunk_text, agent_id = self._vector_chunks[idx]
                if (agent_result := self.results.get(agent_id)):
                    results.append((chunk_text, agent_result, float(distance)))

        return results

    def _clear_vectors(self):
        """Clear vector store data"""
        self._vector_chunks.clear()
        if self._faiss_index:
            self._faiss_index.reset()
