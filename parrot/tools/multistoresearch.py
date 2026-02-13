from typing import List, Dict, Any, Optional, Tuple, Union
import asyncio
from dataclasses import dataclass
from enum import Enum
import hashlib
from pydantic import BaseModel, Field

# Third-party imports
try:
    import bm25s
except ImportError:
    bm25s = None

from navconfig.logging import logging

# Parrot imports
from .abstract import AbstractTool
from ..stores.models import SearchResult, Document
# Import specific store classes for type hinting if needed, 
# but we'll use duck typing or base classes to avoid circular imports if possible.
from ..stores.postgres import PgVectorStore
from ..stores.arango import ArangoDBStore
# FAISSStore might be imported if needed for type hints, valid check below
try:
    from ..stores.faiss_store import FAISSStore
except ImportError:
    FAISSStore = Any 


class StoreType(Enum):
    """DB Store type"""
    PGVECTOR = "pgvector"
    FAISS = "faiss"
    ARANGO = "arango"


class MultiStoreSearchSchema(BaseModel):
    query: str = Field(..., description="The search query")
    k: Optional[int] = Field(None, description="Number of results to return")


class MultiStoreSearchTool(AbstractTool):
    """
    Multi-store search tool with BM25 reranking.

    Performs parallel searches across pgVector, FAISS, and ArangoDB,
    then applies BM25S for intelligent reranking and priority selection.
    """

    
    args_schema = MultiStoreSearchSchema

    def __init__(
        self,
        pgvector_store: Optional[PgVectorStore] = None,
        faiss_store: Optional[Any] = None,  # FAISSStore
        arango_store: Optional[ArangoDBStore] = None,
        k: int = 10,
        k_per_store: int = 20,  # Fetch more initially for better reranking
        bm25_weights: Optional[Dict[str, float]] = None,
        enable_stores: Optional[List[StoreType]] = None,
        **kwargs
    ):
        super().__init__(**kwargs)
        self.pgvector_store = pgvector_store
        self.faiss_store = faiss_store
        self.arango_store = arango_store
        self.k = k
        self.k_per_store = k_per_store

        # Store-specific weights for final scoring
        self.bm25_weights = bm25_weights or {
            'pgvector': 1.0,
            'faiss': 0.9,
            'arango': 0.95
        }

        # Allow selective enabling of stores
        # Default to enabled if store instance is provided
        self.enabled_stores = enable_stores or []
        if not enable_stores:
             if self.pgvector_store:
                 self.enabled_stores.append(StoreType.PGVECTOR)
             if self.faiss_store:
                 self.enabled_stores.append(StoreType.FAISS)
             if self.arango_store:
                 self.enabled_stores.append(StoreType.ARANGO)

        self._bm25 = None
        self.logger = logging.getLogger("MultiStoreSearchTool")

    name = "multi_store_search"

    async def _search_pgvector(
        self,
        query: str,
        k: int
    ) -> List[SearchResult]:
        """Search pgVector store"""
        if not self.pgvector_store:
            return []
            
        try:
            # PgVectorStore.similarity_search returns List[SearchResult]
            results = await self.pgvector_store.similarity_search(
                query=query,
                limit=k
            )
            
            # Tag source and ensure consistent scoring
            for r in results:
                r.search_source = 'pgvector'
                # Ensure score is float
                if not isinstance(r.score, float):
                    r.score = float(r.score) if r.score is not None else 0.0
                     
            return results
        except Exception as e:
            self.logger.error(f"PgVector search error: {e}")
            return []

    async def _search_faiss(
        self,
        query: str,
        k: int
    ) -> List[SearchResult]:
        """Search FAISS store"""
        if not self.faiss_store:
            return []
            
        try:
            # FAISSStore.similarity_search returns List[SearchResult]
            # method signature: similarity_search(query, k=..., limit=...)
            results = await self.faiss_store.similarity_search(
                query=query,
                limit=k
            )

            for r in results:
                r.search_source = 'faiss'
                if not hasattr(r, 'score') or r.score is None:
                    r.score = 0.0
                else:
                    r.score = float(r.score)

            return results
        except Exception as e:
            self.logger.error(f"FAISS search error: {e}")
            return []

    async def _search_arango(
        self,
        query: str,
        k: int
    ) -> List[SearchResult]:
        """Search ArangoDB"""
        if not self.arango_store:
            return []
            
        try:
            # ArangoDBStore.similarity_search returns List[SearchResult]
            # method signature: similarity_search(query, limit=...)
            results = await self.arango_store.similarity_search(
                query=query,
                limit=k
            )

            for r in results:
                r.search_source = 'arango'
                if not hasattr(r, 'score') or r.score is None:
                    r.score = 0.0
                else:
                    r.score = float(r.score)

            return results

        except Exception as e:
            self.logger.error(f"ArangoDB search error: {e}")
            return []

    def _prepare_bm25_corpus(
        self,
        results: List[SearchResult]
    ) -> Tuple[List[List[str]], List[SearchResult]]:
        """Prepare corpus for BM25 tokenization"""
        corpus = []
        valid_results = []

        for result in results:
            if not result.content:
                continue
                
            # Simple tokenization - enhance with proper tokenizer if needed
            # Using simple split for now
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
        Rerank results using BM25S algorithm or fallback to rank_bm25
        """
        if not results:
            return []

        try:
            # Prepare corpus
            corpus, valid_results = self._prepare_bm25_corpus(results)

            if not corpus:
                return results

            # Tokenize query
            query_tokens = query.lower().split()
            if not query_tokens:
                return results

            # 1. Try BM25S (optimized)
            if bm25s:
                try:
                    retriever = bm25s.BM25()
                    retriever.index(corpus)
                    
                    _ = retriever.retrieve(
                        bm25s.tokenize([query_tokens]),
                        k=len(corpus)
                    )
                    # bm25s.retrieve returns (documents, scores)
                    # We need to map scores back to our valid_results
                    # The return format of retrieve depends on version but typically documents, scores
                    # Here we might need to match indices if retrieve reorders.
                    # Actually bm25s often returns top-k. Since k=len(corpus), we get all.
                    # But the order might change.
                    
                    # Simpler approach: calculate scores for each document manually if index doesn't preserve order ease
                    # Or trust that we provided corpus in order.
                    # Let's use rank_bm25 logic if bm25s usage is complex to map back 1:1 without IDs
                    # But let's try to use the scores if possible.
                    
                    # If bm25s is complex, let's stick to rank_bm25 for reliability unless performance is critical
                    # Fallback block below uses rank_bm25
                    raise ImportError("Force fallback to rank_bm25 for simplicity") 
                    
                except Exception:
                    # Fallback to standard logic
                    pass

            # 2. Fallback to rank_bm25
            from rank_bm25 import BM25Okapi

            bm25 = BM25Okapi(corpus)
            bm25_scores = bm25.get_scores(query_tokens)

            for idx, result in enumerate(valid_results):
                bm25_score = float(bm25_scores[idx])
                
                # Normalize BM25 score roughly (it's unbound, but usually 0-20ish)
                # Sigmoid or simply scaling? Let's keep it simple.
                # If we want to combine with cosine (0-1), we should scale bm25.
                # For now, let's assume it provides a boost.
                
                source_weight = self.bm25_weights.get(getattr(result, 'search_source', 'unknown'), 1.0)

                # Hybrid scoring: 
                # Original score (often Cosine 0-1) + scaled BM25 + source bias
                # Scale bm25 by 0.1 to make it a booster rather than dominator
                result.score = (
                    0.5 * result.score +
                    0.1 * bm25_score +
                    0.1 * source_weight
                )

            # Sort by combined score
            valid_results.sort(key=lambda x: x.score, reverse=True)

            return valid_results

        except ImportError:
            self.logger.warning("BM25 libraries not found, skipping reranking")
            return results
        except Exception as e:
            self.logger.error(f"Reranking error: {e}")
            return results

    async def _execute(
        self,
        query: str,
        k: Optional[int] = None,
        **kwargs
    ) -> List[Dict[str, Any]]:
        """
        Execute multi-store search with BM25 reranking
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

        if not tasks:
            self.logger.warning("No stores enabled for search")
            return []

        # Execute searches concurrently
        search_results_list = await asyncio.gather(*tasks, return_exceptions=True)

        # Flatten and filter results
        all_results = []
        for result_set in search_results_list:
            if isinstance(result_set, list):
                all_results.extend(result_set)
            elif isinstance(result_set, Exception):
                self.logger.error(f"Search task failed: {result_set}")

        # Remove duplicates
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
                'source': getattr(r, 'search_source', 'unknown'),
                'id': getattr(r, 'id', None),
                'rank': idx + 1
            }
            for idx, r in enumerate(top_k)
        ]

    def _deduplicate_results(
        self,
        results: List[SearchResult],
        similarity_threshold: float = 0.95
    ) -> List[SearchResult]:
        """
        Remove duplicate results. 
        Prioritizes:
        1. Exact ID match (if IDs exist)
        2. Content hash match
        """
        if not results:
            return []

        unique_results = []
        seen_ids = set()
        seen_content_hashes = set()

        # Sort by score first so we keep the highest scoring version of a duplicate
        # (Though scores might be incomparable across stores without normalization)
        results.sort(key=lambda x: float(x.score) if x.score is not None else 0.0, reverse=True)

        for result in results:
            # 1. ID based deduplication
            if hasattr(result, 'id') and result.id:
                if result.id in seen_ids:
                    continue
                seen_ids.add(result.id)

            # 2. Content based deduplication
            if result.content:
                # Normalize content for hashing (strip whitespace)
                content_sample = result.content.strip()
                # SHA256 for robust hashing
                content_hash = hashlib.sha256(content_sample.encode('utf-8')).hexdigest()
                
                if content_hash in seen_content_hashes:
                   continue
                seen_content_hashes.add(content_hash)

            unique_results.append(result)

        return unique_results

    async def __call__(self, query: str, **kwargs) -> List[Dict[str, Any]]:
        """Convenience method for direct calling"""
        return await self.execute(query, **kwargs)
