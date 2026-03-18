"""Embedding provider for episodic memory.

Lazy-loads sentence-transformers on first use. Uses asyncio.to_thread()
for non-blocking embedding in async contexts.
"""
from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .models import EpisodicMemory

logger = logging.getLogger(__name__)


class EpisodeEmbeddingProvider:
    """Lazy-loading sentence-transformers embedding provider.

    The model is loaded only on the first call to embed() or embed_batch(),
    keeping import time minimal for applications that don't need embeddings
    immediately.

    Args:
        model_name: HuggingFace model identifier.
        dimension: Expected embedding dimension (validated on first load).
        device: Torch device string ("cpu", "cuda", etc.).
        batch_size: Maximum batch size for embed_batch().
    """

    def __init__(
        self,
        model_name: str = "sentence-transformers/all-MiniLM-L6-v2",
        dimension: int = 384,
        device: str = "cpu",
        batch_size: int = 32,
    ) -> None:
        self._model_name = model_name
        self._dimension = dimension
        self._device = device
        self._batch_size = batch_size
        self._model: Any = None

    @property
    def dimension(self) -> int:
        """Return the embedding dimension."""
        return self._dimension

    def _load_model(self) -> None:
        """Import and load the sentence-transformers model.

        Raises:
            ImportError: If sentence-transformers is not installed.
        """
        if self._model is not None:
            return

        try:
            from sentence_transformers import SentenceTransformer
        except ImportError:
            raise ImportError(
                "sentence-transformers is required for EpisodeEmbeddingProvider. "
                "Install it with: uv pip install sentence-transformers"
            )

        logger.info("Loading embedding model: %s", self._model_name)
        self._model = SentenceTransformer(
            self._model_name, device=self._device
        )
        logger.info(
            "Embedding model loaded: dim=%d, device=%s",
            self._dimension,
            self._device,
        )

    def _encode_sync(self, texts: list[str]) -> list[list[float]]:
        """Synchronous encoding (runs in thread pool)."""
        self._load_model()
        embeddings = self._model.encode(
            texts,
            batch_size=self._batch_size,
            normalize_embeddings=True,
            show_progress_bar=False,
        )
        return [vec.tolist() for vec in embeddings]

    async def embed(self, text: str) -> list[float]:
        """Embed a single text string.

        Lazy-loads the model on first call. Runs encoding in a thread
        to avoid blocking the event loop.

        Args:
            text: Text to embed.

        Returns:
            Embedding vector of length self.dimension.
        """
        results = await asyncio.to_thread(self._encode_sync, [text])
        return results[0]

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Embed multiple texts efficiently.

        Lazy-loads the model on first call. Runs encoding in a thread
        to avoid blocking the event loop.

        Args:
            texts: List of texts to embed.

        Returns:
            List of embedding vectors.
        """
        if not texts:
            return []
        return await asyncio.to_thread(self._encode_sync, texts)

    @staticmethod
    def get_searchable_text(episode: EpisodicMemory) -> str:
        """Build the text used for embedding an episode.

        Concatenates situation, action_taken, and lesson_learned
        (if available) into a single searchable string.

        Args:
            episode: The episode to build text for.

        Returns:
            Formatted text for embedding.
        """
        parts = [episode.situation, episode.action_taken]
        if episode.lesson_learned:
            parts.append(episode.lesson_learned)
        return " | ".join(parts)
