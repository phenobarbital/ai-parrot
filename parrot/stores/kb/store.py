from collections import defaultdict
from typing import List, Dict, Any

class KnowledgeBaseStore:
    """Lightweight in-memory store for validated facts."""

    def __init__(
        self,
        embedding_model: str = "all-MiniLM-L6-v2",  # 384D model
        dimension: int = 384,
        index_type: str = "Flat",  # or "HNSW" for larger KBs
    ):
        try:
            from sentence_transformers import SentenceTransformer
            import faiss
        except ImportError as e:
            raise ImportError(
                "Please install 'sentence-transformers' and 'faiss-cpu' to use KnowledgeBaseStore."
            ) from e
        self.embeddings = SentenceTransformer(embedding_model)
        self.dimension = dimension
        self.score_threshold = 0.45
        # FAISS index
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

    async def add_fact(self, fact: Dict[str, Any]):
        """Add a single validated fact to the KB."""
        await self.add_facts([fact])

    async def add_facts(self, facts: List[Dict[str, Any]]):
        """Add validated facts to the KB."""
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

        embeddings = self.embeddings.encode(texts, normalize_embeddings=True)
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
        score_threshold: float = 0.4
    ) -> List[Dict[str, Any]]:
        """Ultra-fast fact retrieval."""
        query_embedding = self.embeddings.encode(
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
        """Retrieve all facts in a category."""
        indices = self.category_index.get(category, [])
        return [self.facts[i] for i in indices]

    def get_entity_facts(self, entity: str) -> List[Dict]:
        """Get all facts related to an entity."""
        indices = self.entity_index.get(entity, [])
        return [self.facts[i] for i in indices]

    async def close(self):
        """Cleanup resources if needed."""
        pass
