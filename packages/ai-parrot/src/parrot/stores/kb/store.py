"""KnowledgeBaseStore — In-memory fact store with FAISS-backed similarity search.

Embedding models are loaded lazily via ``EmbeddingRegistry`` on first access to
``self.embeddings``.  Construction no longer loads a ``SentenceTransformer``
directly, eliminating 5-30 s startup latency when the KB is never queried.

Two ``KnowledgeBaseStore`` instances sharing the same ``embedding_model`` name
will reuse a single cached ``EmbeddingModel`` object from the registry.
"""
from collections import defaultdict
from typing import List, Dict, Any


class KnowledgeBaseStore:
    """Lightweight in-memory store for validated facts.

    Args:
        embedding_model: HuggingFace model name (e.g. ``"all-MiniLM-L6-v2"``).
            The model is loaded lazily on first ``add_facts()`` / ``search_facts()``
            call via ``EmbeddingRegistry``.
        dimension: Embedding vector dimension (must match the model output).
        index_type: FAISS index type — ``"Flat"`` (exact) or ``"HNSW"``
            (approximate, faster for larger KBs).
    """

    def __init__(
        self,
        embedding_model: str = "all-MiniLM-L6-v2",  # 384D model
        dimension: int = 384,
        index_type: str = "Flat",  # or "HNSW" for larger KBs
    ):
        try:
            import faiss  # noqa: F401 — trigger ImportError early if missing
        except ImportError as e:
            raise ImportError(
                "Please install 'faiss-cpu' (or 'faiss-gpu') to use KnowledgeBaseStore."
            ) from e

        # Store the model name but do NOT load the model yet (lazy via registry)
        self._embedding_model_name: str = embedding_model
        self._embeddings = None  # loaded on first access via .embeddings property

        self.dimension = dimension
        self.score_threshold = 0.5

        # FAISS index is lightweight — eagerly initialised
        if index_type == "FlatIP":
            self.index = faiss.IndexFlatIP(dimension)
        else:
            # HNSW with IP metric
            self.index = faiss.IndexHNSWFlat(dimension, 32, faiss.METRIC_INNER_PRODUCT)

        # Store facts and metadata
        self.facts: List[str] = []
        self.fact_metadata: List[dict] = []
        self.category_index = defaultdict(list)  # Fast category lookup
        self.entity_index = defaultdict(list)    # Entity-based retrieval

    # ------------------------------------------------------------------
    # Lazy embedding property
    # ------------------------------------------------------------------

    @property
    def embeddings(self):
        """Return the cached embedding model, loading it on first access.

        Uses ``EmbeddingRegistry`` for deduplication — multiple
        ``KnowledgeBaseStore`` instances with the same model name share one
        object.

        Returns:
            The ``EmbeddingModel`` instance (or a ``SentenceTransformer``-
            compatible object returned by the registry).
        """
        if self._embeddings is None:
            from parrot.embeddings import EmbeddingRegistry  # local import — avoids circular
            registry = EmbeddingRegistry.instance()
            self._embeddings = registry.get_or_create_sync(
                self._embedding_model_name,
                "huggingface",
            )
        return self._embeddings

    @embeddings.setter
    def embeddings(self, value):
        """Allow direct assignment (for testing / backwards compat)."""
        self._embeddings = value

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def add_fact(self, fact: Dict[str, Any]):
        """Add a single validated fact to the KB."""
        await self.add_facts([fact])

    async def add_facts(self, facts: List[Dict[str, Any]]):
        """Add validated facts to the KB.

        Triggers lazy loading of the embedding model on first call.

        Args:
            facts: List of fact dicts.  Each dict must have a ``"content"``
                key and an optional ``"metadata"`` dict.
        """
        if not facts:
            return

        texts = []
        for fact in facts:
            fact_id = len(self.facts)
            self.facts.append(fact)
            texts.append(fact['content'])
            if category := fact.get('metadata', {}).get('category'):
                self.category_index[category].append(fact_id)
            # Index by entities
            for key in ['subject', 'object']:
                if entity := fact.get('metadata', {}).get(key):
                    self.entity_index[entity].append(fact_id)

        embeddings = await self.embeddings.encode(texts, normalize_embeddings=True)
        self.index.add(embeddings)

        self.fact_metadata.extend(
            [f.get('metadata', {}) for f in facts]
        )

    def _tokenize(self, text: str) -> set:
        return {t.lower() for t in text.split()}

    async def search_facts(
        self,
        query: str,
        k: int = 5,
        score_threshold: float = 0.5
    ) -> List[Dict[str, Any]]:
        """Ultra-fast fact retrieval.

        Triggers lazy loading of the embedding model on first call.

        Args:
            query: Free-text query string.
            k: Maximum number of results to return.
            score_threshold: Minimum cosine similarity score (0-1).

        Returns:
            List of result dicts with ``"fact"``, ``"score"``, and
            ``"metadata"`` keys, sorted by descending score.
        """
        query_embedding = await self.embeddings.encode(
            [query],
            normalize_embeddings=True
        )
        # Important: k should not exceed number of facts
        actual_k = min(k, len(self.facts))
        scores, indices = self.index.search(query_embedding, actual_k)
        threshold = score_threshold or self.score_threshold

        results = []
        for score, idx in zip(scores[0], indices[0]):
            if idx == -1:
                continue
            if float(score) >= threshold:
                results.append({
                    'fact': self.facts[idx],
                    'score': float(score),
                    'metadata': self.fact_metadata[idx]
                })
        # doing a re-ranking based on token overlap
        # after collecting FAISS candidates as `results` with "score" = cosine
        q_tokens = self._tokenize(query)
        for r in results:
            tags = set((r["metadata"].get("tags") or []))
            overlap = len(q_tokens & {t.lower() for t in tags})
            r["score"] += 0.05 * overlap  # tiny boost per overlapping tag
        results.sort(key=lambda x: x["score"], reverse=True)
        return results

    def get_facts_by_category(self, category: str) -> List[Dict]:
        """Retrieve all facts in a category.

        Args:
            category: Category string.

        Returns:
            List of fact dicts.
        """
        indices = self.category_index.get(category, [])
        return [self.facts[i] for i in indices]

    def get_entity_facts(self, entity: str) -> List[Dict]:
        """Get all facts related to an entity.

        Args:
            entity: Entity string.

        Returns:
            List of fact dicts.
        """
        indices = self.entity_index.get(entity, [])
        return [self.facts[i] for i in indices]

    async def close(self):
        """Cleanup resources if needed."""
        pass
