"""Embedding stage for GraphIndex.

Batch-embeds ``UniversalNode`` summaries and titles via
``EmbeddingModel.encode()``, builds an in-memory FAISS index for fast
similarity search, and persists embeddings to pgvector for durable storage.
"""

from __future__ import annotations

import logging
from typing import Optional

import faiss
import numpy as np

from parrot.embeddings.registry import EmbeddingRegistry
from parrot.knowledge.graphindex.schema import UniversalNode

logger = logging.getLogger(__name__)


class GraphIndexEmbedder:
    """Batch-embed UniversalNode summaries and manage vector indices.

    Provides an in-memory FAISS index for fast similarity search and
    pgvector persistence for durable storage.

    Args:
        model_name: Name of the embedding model to use via
            ``EmbeddingRegistry``.
        dimension: Embedding vector dimension.  Must match the model output.
            Defaults to 384 (all-MiniLM-L6-v2 style).
        pgvector_dsn: Optional DSN for pgvector persistence.  If ``None``,
            only the in-memory FAISS index is populated.
    """

    def __init__(
        self,
        model_name: str = "default",
        dimension: int = 384,
        pgvector_dsn: Optional[str] = None,
    ) -> None:
        self._model_name = model_name
        self.dimension = dimension
        self.pgvector_dsn = pgvector_dsn

        self.model = EmbeddingRegistry.instance().get_or_create_sync(model_name)
        self.index: faiss.IndexFlatL2 = faiss.IndexFlatL2(dimension)
        self._node_id_map: list[str] = []  # FAISS int position → node_id

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    async def embed_nodes(
        self, nodes: list[UniversalNode], batch_size: int = 64
    ) -> list[UniversalNode]:
        """Batch-embed nodes and populate ``embedding_ref``.

        Processes nodes in batches.  If embedding fails for a batch, all
        nodes in that batch are persisted with ``embedding_ref=None`` and
        the error is logged.

        Args:
            nodes: List of ``UniversalNode`` instances to embed.
            batch_size: Number of nodes per embedding call.

        Returns:
            The same nodes with ``embedding_ref`` populated (or ``None`` on
            failure).
        """
        if not nodes:
            return nodes

        for batch_start in range(0, len(nodes), batch_size):
            batch = nodes[batch_start : batch_start + batch_size]
            texts = [self._get_embed_text(n) for n in batch]

            try:
                vectors = await self.model.encode(texts)

                # Validate output shape
                if vectors.ndim == 1:
                    vectors = vectors.reshape(1, -1)

                # Ensure float32 for FAISS
                vectors = vectors.astype(np.float32)

                # Normalise for cosine similarity (L2-normalise)
                norms = np.linalg.norm(vectors, axis=1, keepdims=True)
                norms = np.where(norms == 0, 1.0, norms)
                vectors = vectors / norms

                # Add to FAISS index
                start_pos = self.index.ntotal
                self.index.add(vectors)

                # Record node_id → FAISS position mapping
                for i, node in enumerate(batch):
                    faiss_pos = start_pos + i
                    self._node_id_map.append(node.node_id)
                    node.embedding_ref = f"faiss:{faiss_pos}"

                    # Optional pgvector persistence
                    if self.pgvector_dsn:
                        await self._persist_to_pgvector(node.node_id, vectors[i])

            except Exception as exc:
                logger.error(
                    "Embedding failed for batch starting at index %d: %s",
                    batch_start,
                    exc,
                )
                for node in batch:
                    node.embedding_ref = None

        return nodes

    async def search_similar(
        self, query_text: str, top_k: int = 10
    ) -> list[tuple[str, float]]:
        """Search for similar nodes by text query using FAISS.

        Args:
            query_text: Natural language query text.
            top_k: Maximum number of results to return.

        Returns:
            List of ``(node_id, distance)`` tuples sorted by ascending
            L2 distance (smaller = more similar).
        """
        if self.index.ntotal == 0:
            return []

        k = min(top_k, self.index.ntotal)

        try:
            query_vec = (await self.model.encode([query_text])).astype(np.float32)
            if query_vec.ndim == 1:
                query_vec = query_vec.reshape(1, -1)
            # Normalise
            norm = np.linalg.norm(query_vec, axis=1, keepdims=True)
            if norm[0, 0] != 0:
                query_vec = query_vec / norm

            distances, indices = self.index.search(query_vec, k)
        except Exception as exc:
            logger.error("FAISS search failed: %s", exc)
            return []

        results: list[tuple[str, float]] = []
        for idx, dist in zip(indices[0], distances[0]):
            if idx < len(self._node_id_map):
                results.append((self._node_id_map[idx], float(dist)))
        return results

    def get_embedding(self, node_id: str) -> Optional[np.ndarray]:
        """Retrieve the embedding vector for a specific node.

        Args:
            node_id: The node to look up.

        Returns:
            A ``numpy.ndarray`` of shape ``(dimension,)``, or ``None`` if
            the node is not indexed.
        """
        try:
            faiss_pos = self._node_id_map.index(node_id)
        except ValueError:
            return None

        vec = self.index.reconstruct(faiss_pos)
        return vec

    def _get_embed_text(self, node: UniversalNode) -> str:
        """Get the text to embed: prefer summary, fall back to title.

        Args:
            node: The node to embed.

        Returns:
            The text string to encode.
        """
        return node.summary or node.title

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    async def _persist_to_pgvector(
        self, node_id: str, embedding: np.ndarray
    ) -> None:
        """Write a single embedding to pgvector.

        This is a stub implementation that logs on failure.  Full pgvector
        integration requires a live database connection passed via
        ``pgvector_dsn``.

        Args:
            node_id: The node identifier (used as the primary key).
            embedding: The embedding vector to persist.
        """
        logger.debug("pgvector persistence for node %s (not yet implemented)", node_id)
