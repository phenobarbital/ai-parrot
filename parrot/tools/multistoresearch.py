from abc import abstractmethod
from typing import List, Dict, Any, Optional, Tuple
import asyncio
from dataclasses import dataclass
from enum import Enum
from arangoasync import ArangoClient
from arangoasync.auth import Auth
import bm25s

# Assuming these are your existing imports
from .abstract import AbstractTool
from ..stores import Store  # Your pgVector implementation
# You'll need: pip install bm25s rank-bm25 faiss-cpu aioarango


@dataclass
class SearchResult:
    """Unified search result across different stores"""
    content: str
    metadata: Dict[str, Any]
    score: float
    source: str  # 'pgvector', 'faiss', 'arango'
    original_rank: int


class StoreType(Enum):
    PGVECTOR = "pgvector"
    FAISS = "faiss"
    ARANGO = "arango"


class MultiStoreSearchTool(AbstractTool):
    """
    Multi-store search tool with BM25 reranking.

    Performs parallel searches across pgVector, FAISS, and ArangoDB,
    then applies BM25S for intelligent reranking and priority selection.
    """

    def __init__(
        self,
        pgvector_store: Store,
        faiss_store: Any,  # Your FAISS wrapper
        arango_config: Dict[str, Any],
        k: int = 10,
        k_per_store: int = 20,  # Fetch more initially for better reranking
        bm25_weights: Optional[Dict[str, float]] = None,
        enable_stores: Optional[List[StoreType]] = None,
        **kwargs
    ):
        super().__init__(**kwargs)
        self.pgvector_store = pgvector_store
        self.faiss_store = faiss_store
        self.arango_config = arango_config
        self.k = k
        self.k_per_store = k_per_store

        # Store-specific weights for final scoring
        self.bm25_weights = bm25_weights or {
            'pgvector': 1.0,
            'faiss': 0.9,
            'arango': 0.95
        }

        # Allow selective enabling of stores
        self.enabled_stores = enable_stores or [
            StoreType.PGVECTOR,
            StoreType.FAISS,
            StoreType.ARANGO
        ]

        self._arango_client = None
        self._bm25 = None

    @property
    def name(self) -> str:
        return "multi_store_search"

    @property
    def description(self) -> str:
        return (
            "Search across multiple vector stores (pgVector, FAISS, ArangoDB) "
            "with BM25S reranking for optimal results"
        )

    async def _search_pgvector(
        self,
        query: str,
        k: int
    ) -> List[SearchResult]:
        """Search pgVector store"""
        try:
            # Assuming your Store has an async search method
            results = await self.pgvector_store.asearch(
                query=query,
                k=k
            )

            return [
                SearchResult(
                    content=doc.page_content if hasattr(doc, 'page_content') else str(doc),
                    metadata=doc.metadata if hasattr(doc, 'metadata') else {},
                    score=score,
                    source='pgvector',
                    original_rank=idx
                )
                for idx, (doc, score) in enumerate(results)
            ]
        except Exception as e:
            print(f"PgVector search error: {e}")
            return []

    async def _search_faiss(
        self,
        query: str,
        k: int
    ) -> List[SearchResult]:
        """Search FAISS store"""
        try:
            # Adapt to your FAISS implementation
            results = await asyncio.to_thread(
                self.faiss_store.similarity_search_with_score,
                query,
                k=k
            )

            return [
                SearchResult(
                    content=doc.page_content if hasattr(doc, 'page_content') else str(doc),
                    metadata=doc.metadata if hasattr(doc, 'metadata') else {},
                    score=score,
                    source='faiss',
                    original_rank=idx
                )
                for idx, (doc, score) in enumerate(results)
            ]
        except Exception as e:
            print(f"FAISS search error: {e}")
            return []

    async def _search_arango(
        self,
        query: str,
        k: int
    ) -> List[SearchResult]:
        """Search ArangoDB using AQL with fulltext or vector search"""
        try:
            if not self._arango_client:
                self._arango_client = ArangoClient(
                    hosts=self.arango_config.get('hosts', 'http://localhost:8529')
                )

            db = await self._arango_client.db(
                self.arango_config['database'],
                username=self.arango_config['username'],
                password=self.arango_config['password']
            )

            # AQL query - adapt based on your schema
            collection = self.arango_config.get('collection', 'documents')

            # Example with fulltext search - adjust to your needs
            aql = f"""
                FOR doc IN FULLTEXT({collection}, "content", @query, @k)
                RETURN {{
                    content: doc.content,
                    metadata: doc.metadata,
                    _key: doc._key
                }}
            """

            cursor = await db.aql.execute(
                aql,
                bind_vars={'query': query, 'k': k}
            )

            results = []
            async for idx, doc in enumerate(cursor):
                results.append(
                    SearchResult(
                        content=doc['content'],
                        metadata=doc.get('metadata', {}),
                        score=1.0 / (idx + 1),  # Simple ranking score
                        source='arango',
                        original_rank=idx
                    )
                )

            return results

        except Exception as e:
            print(f"ArangoDB search error: {e}")
            return []

    def _prepare_bm25_corpus(
        self,
        results: List[SearchResult]
    ) -> Tuple[List[List[str]], List[SearchResult]]:
        """Prepare corpus for BM25 tokenization"""
        corpus = []
        valid_results = []

        for result in results:
            # Simple tokenization - enhance with proper tokenizer if needed
            if tokens := result.content.lower().split():
                corpus.append(tokens)
                valid_results.append(result)

        return corpus, valid_results

    def _rerank_with_bm25(
        self,
        query: str,
        results: List[SearchResult]
    ) -> List[SearchResult]:
        """
        Rerank results using BM25S algorithm

        BM25S is an improved variant that considers document length
        and applies saturation to term frequencies.
        """
        if not results:
            return []

        try:
            # Prepare corpus
            corpus, valid_results = self._prepare_bm25_corpus(results)

            if not corpus:
                return results

            # Create BM25 index
            retriever = bm25s.BM25()
            retriever.index(corpus)

            # Tokenize query
            query_tokens = query.lower().split()

            # Get BM25 scores
            bm25_scores, _ = retriever.retrieve(
                bm25s.tokenize([query_tokens]),
                k=len(corpus)
            )

            # Combine BM25 scores with original scores and source weights
            for idx, result in enumerate(valid_results):
                bm25_score = float(bm25_scores[0][idx])
                source_weight = self.bm25_weights.get(result.source, 1.0)

                # Hybrid scoring: BM25 + original score + source weight
                result.score = (
                    0.6 * bm25_score +
                    0.3 * result.score +
                    0.1 * source_weight
                )

            # Sort by combined score
            valid_results.sort(key=lambda x: x.score, reverse=True)

            return valid_results

        except ImportError:
            # Fallback: use rank-bm25 if bm25s not available
            from rank_bm25 import BM25Okapi

            corpus, valid_results = self._prepare_bm25_corpus(results)

            if not corpus:
                return results

            bm25 = BM25Okapi(corpus)
            query_tokens = query.lower().split()
            bm25_scores = bm25.get_scores(query_tokens)

            for idx, result in enumerate(valid_results):
                source_weight = self.bm25_weights.get(result.source, 1.0)
                result.score = (
                    0.6 * bm25_scores[idx] +
                    0.3 * result.score +
                    0.1 * source_weight
                )

            valid_results.sort(key=lambda x: x.score, reverse=True)
            return valid_results

    async def execute(
        self,
        query: str,
        k: Optional[int] = None,
        **kwargs
    ) -> List[Dict[str, Any]]:
        """
        Execute multi-store search with BM25 reranking

        Args:
            query: Search query
            k: Number of results to return (overrides default)

        Returns:
            List of top-k reranked results
        """
        k = k or self.k

        # Prepare search tasks
        tasks = []

        if StoreType.PGVECTOR in self.enabled_stores:
            tasks.append(self._search_pgvector(query, self.k_per_store))

        if StoreType.FAISS in self.enabled_stores:
            tasks.append(self._search_faiss(query, self.k_per_store))

        if StoreType.ARANGO in self.enabled_stores:
            tasks.append(self._search_arango(query, self.k_per_store))

        # Execute searches concurrently
        search_results = await asyncio.gather(*tasks, return_exceptions=True)

        # Flatten and filter results
        all_results = []
        for result_set in search_results:
            if isinstance(result_set, list):
                all_results.extend(result_set)

        # Remove duplicates based on content similarity
        all_results = self._deduplicate_results(all_results)

        # Apply BM25 reranking
        reranked_results = self._rerank_with_bm25(query, all_results)

        # Return top-k
        top_k = reranked_results[:k]

        return [
            {
                'content': r.content,
                'metadata': r.metadata,
                'score': r.score,
                'source': r.source,
                'rank': idx + 1
            }
            for idx, r in enumerate(top_k)
        ]

    def _deduplicate_results(
        self,
        results: List[SearchResult],
        similarity_threshold: float = 0.9
    ) -> List[SearchResult]:
        """Remove near-duplicate results using simple similarity"""
        if not results:
            return []

        unique_results = []
        seen_contents = set()

        for result in results:
            # Simple deduplication - enhance with embedding similarity if needed
            content_hash = hash(result.content[:100])  # Use first 100 chars

            if content_hash not in seen_contents:
                seen_contents.add(content_hash)
                unique_results.append(result)

        return unique_results

    async def __call__(self, query: str, **kwargs) -> List[Dict[str, Any]]:
        """Convenience method for direct calling"""
        return await self.execute(query, **kwargs)
