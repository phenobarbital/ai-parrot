"""Flow Primitives — VectorStoreMixin.

Copied from ``parrot.bots.flow.storage.mixin`` into the shared core
storage location.  Relative imports updated for the new package depth.
"""
from __future__ import annotations

import asyncio
from typing import Any, List, Optional, Tuple

from parrot._imports import lazy_import
from .....models.crew import AgentResult, VectorStoreProtocol


class VectorStoreMixin:
    """Mixin to add FAISS vector store capabilities to ExecutionMemory."""

    def __init__(
        self,
        *args,
        embedding_model: Optional[VectorStoreProtocol] = None,
        dimension: int = 384,
        index_type: str = "Flat",
        **kwargs,
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
                _st = lazy_import(
                    "sentence_transformers",
                    package_name="sentence-transformers",
                    extra="embeddings",
                )
                if isinstance(embedding_model, str):
                    self._raw_embedding_model = _st.SentenceTransformer(embedding_model)
                # Initialise FAISS index based on type
                if index_type == "FlatIP":
                    self._faiss_index = faiss.IndexFlatIP(dimension)
                elif index_type == "HNSW":
                    self._faiss_index = faiss.IndexHNSWFlat(
                        dimension, 32, faiss.METRIC_INNER_PRODUCT
                    )
                else:  # Default FlatL2
                    self._faiss_index = faiss.IndexFlatL2(dimension)
                self._faiss_available = True
            except (ImportError, AttributeError):
                self._faiss_index = None
                self._faiss_available = False

    @property
    def embedding_model(self):
        """Return the raw (sync) embedding model for FAISS operations.

        If the stored model is an ``EmbeddingModel`` wrapper (async encode),
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
        """Break result into semantically meaningful chunks."""
        text = result.to_text()

        if len(text) < 500:
            return [text]

        chunks: List[str] = []
        sections = text.split("\n\n")
        current_chunk: List[str] = []
        current_length = 0

        for section in sections:
            if current_length + len(section) > 500 and current_chunk:
                chunks.append("\n".join(current_chunk))
                current_chunk = [section]
                current_length = len(section)
            else:
                current_chunk.append(section)
                current_length += len(section)

        if current_chunk:
            chunks.append("\n".join(current_chunk))

        return chunks

    async def _vectorize_result_async(self, result: AgentResult):
        """Async task to vectorize and index a result.

        Uses ``asyncio.to_thread`` to offload the CPU-bound
        ``SentenceTransformer.encode`` call so the event loop is not blocked.
        """
        if not self._faiss_available or not self.embedding_model or self._faiss_index is None:
            return

        chunks = self._chunk_result(result)

        for chunk in chunks:
            self._vector_chunks.append((chunk, result.agent_id))

        all_texts = [chunk for chunk, _ in self._vector_chunks]
        # Offload blocking CPU-bound encode to a thread pool to avoid blocking
        # the event loop.
        embeddings = await asyncio.to_thread(
            self.embedding_model.encode, all_texts, convert_to_numpy=True
        )
        embeddings = embeddings.astype("float32")

        self._faiss_index.reset()
        self._faiss_index.add(embeddings)

    def search_similar(
        self, query: str, top_k: int = 5
    ) -> List[Tuple[str, AgentResult, float]]:
        """Search for semantically similar result chunks.

        Note: This is a synchronous method — the underlying ``encode`` call is
        CPU-bound.  Callers running inside an async context should use
        ``asyncio.to_thread(memory.search_similar, query, top_k)`` to avoid
        blocking the event loop.
        """
        if (
            not self._faiss_available
            or self._faiss_index is None
            or self._faiss_index.ntotal == 0
        ):
            return []

        query_embedding = self.embedding_model.encode([query], convert_to_numpy=True)
        query_embedding = query_embedding.astype("float32")

        if len(query_embedding.shape) == 1:
            query_embedding = query_embedding.reshape(1, -1)

        k = min(top_k, self._faiss_index.ntotal)
        D, I = self._faiss_index.search(query_embedding, k)

        results: List[Tuple[str, AgentResult, float]] = []
        for idx, distance in zip(I[0], D[0]):
            if 0 <= idx < len(self._vector_chunks):
                chunk_text, agent_id = self._vector_chunks[idx]
                if agent_result := self.results.get(agent_id):  # type: ignore[attr-defined]
                    results.append((chunk_text, agent_result, float(distance)))

        return results

    def _clear_vectors(self):
        """Clear vector store data."""
        self._vector_chunks.clear()
        if self._faiss_index:
            self._faiss_index.reset()
