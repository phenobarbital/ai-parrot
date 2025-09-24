from collections import defaultdict
from typing import List, Dict, Any
from sentence_transformers import SentenceTransformer
import faiss

class KnowledgeBaseStore:
    """Lightweight in-memory store for validated facts."""

    def __init__(
        self,
        embedding_model: str = "paraphrase-MiniLM-L3-v2",  # 384D model
        dimension: int = 384,
        index_type: str = "Flat",  # or "HNSW" for larger KBs
    ):
        self.embeddings = SentenceTransformer(embedding_model)
        self.dimension = dimension

        # FAISS index
        if index_type == "Flat":
            self.index = faiss.IndexFlatIP(dimension)  # Inner product for cosine
        else:
            self.index = faiss.IndexHNSWFlat(dimension, 32)

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
            category = fact.get('metadata', {}).get('category')
            if category:
                self.category_index[category].append(fact_id)
            # Index by entities
            for key in ['subject', 'object']:
                entity = fact.get('metadata', {}).get(key)
                if entity:
                    self.entity_index[entity].append(fact_id)

        embeddings = self.embeddings.encode(texts, normalize_embeddings=True)
        self.index.add(embeddings)

        self.fact_metadata.extend(
            [f.get('metadata', {}) for f in facts]
        )

    async def search_facts(
        self,
        query: str,
        k: int = 5,
        score_threshold: float = 0.7
    ) -> List[Dict[str, Any]]:
        """Ultra-fast fact retrieval."""
        query_embedding = self.embeddings.encode(
            [query],
            normalize_embeddings=True
        )

        scores, indices = self.index.search(query_embedding, k)

        results = []
        for score, idx in zip(scores[0], indices[0]):
            if score >= score_threshold:
                results.append({
                    'fact': self.facts[idx],
                    'score': float(score),
                    'metadata': self.fact_metadata[idx]
                })

        return results

    def get_facts_by_category(self, category: str) -> List[Dict]:
        """Retrieve all facts in a category."""
        indices = self.category_index.get(category, [])
        return [self.facts[i] for i in indices]

    def get_entity_facts(self, entity: str) -> List[Dict]:
        """Get all facts related to an entity."""
        indices = self.entity_index.get(entity, [])
        return [self.facts[i] for i in indices]
