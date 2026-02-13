import unittest
from unittest.mock import AsyncMock, MagicMock, patch
import asyncio
from typing import List

from parrot.stores.models import SearchResult
from parrot.tools.multistoresearch import MultiStoreSearchTool, StoreType

class TestMultiStoreSearchTool(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        # Mock Stores
        self.mock_pgvector = AsyncMock()
        self.mock_faiss = AsyncMock()
        self.mock_arango = AsyncMock()

        # Setup standard return values
        self.mock_pgvector.similarity_search.return_value = [
            SearchResult(id="pg1", content="Foo Bar PG", metadata={"src": "pg"}, score=0.9)
        ]
        self.mock_faiss.similarity_search.return_value = [
            SearchResult(id="faiss1", content="Foo Bar FAISS", metadata={"src": "faiss"}, score=0.85)
        ]
        self.mock_arango.similarity_search.return_value = [
            SearchResult(id="arango1", content="Foo Bar Arango", metadata={"src": "arango"}, score=0.88)
        ]

        self.tool = MultiStoreSearchTool(
            pgvector_store=self.mock_pgvector,
            faiss_store=self.mock_faiss,
            arango_store=self.mock_arango,
            k=5,
            enable_stores=[StoreType.PGVECTOR, StoreType.FAISS, StoreType.ARANGO]
        )

    async def test_search_all_stores_enabled(self):
        query = "test query"
        results = await self.tool.execute(query=query)
        
        # Verify calls
        self.mock_pgvector.similarity_search.assert_called_once()
        self.mock_faiss.similarity_search.assert_called_once()
        self.mock_arango.similarity_search.assert_called_once()
        
        # We expect 3 results initially (1 from each)
        self.assertEqual(len(results.result), 3)
        
        sources = {r['source'] for r in results.result}
        self.assertEqual(sources, {'pgvector', 'faiss', 'arango'})

    async def test_deduplication_exact_id(self):
        # Setup duplicates by ID
        self.mock_pgvector.similarity_search.return_value = [
            SearchResult(id="dup1", content="Content A", score=0.9)
        ]
        self.mock_faiss.similarity_search.return_value = [
            SearchResult(id="dup1", content="Content A copy", score=0.8) # Same ID
        ]
        self.mock_arango.similarity_search.return_value = []

        results = await self.tool.execute(query="query")
        
        # Should only have 1 result because of ID deduplication
        self.assertEqual(len(results.result), 1)
        # Should keep the higher score one (pgvector 0.9)
        self.assertEqual(results.result[0]['source'], 'pgvector')

    async def test_deduplication_content_hash(self):
        # Setup duplicates by Content
        self.mock_pgvector.similarity_search.return_value = [
            SearchResult(id="pg1", content="Exact unique content", score=0.9)
        ]
        # Same content, different ID
        self.mock_faiss.similarity_search.return_value = [
            SearchResult(id="faiss1", content="Exact unique content", score=0.8) 
        ]
        self.mock_arango.similarity_search.return_value = []

        results = await self.tool.execute(query="query")
        
        self.assertEqual(len(results.result), 1)
        self.assertEqual(results.result[0]['source'], 'pgvector')

    async def test_selective_stores(self):
        # Enable only PgVector
        self.tool.enabled_stores = [StoreType.PGVECTOR]
        
        await self.tool.execute(query="query")
        
        self.mock_pgvector.similarity_search.assert_called_once()
        self.mock_faiss.similarity_search.assert_not_called()
        self.mock_arango.similarity_search.assert_not_called()

    async def test_reranking_fallback(self):
        # Mock that bm25s is missing to test fallback or basic scoring
        with patch('parrot.tools.multistoresearch.bm25s', None):
            # We also need to mock rank_bm25 if it's not installed, 
            # but let's assume if it is installed it works, or if not it handles gracefully.
            # For this test, we just want to ensure it doesn't crash.
            
            # Since we can't easily uninstall packages in test, we just rely on the fallback logic
            # inside _rerank_with_bm25 catching ImportError if rank_bm25 is missing too.
            
            results = await self.tool.execute(query="query")
            self.assertTrue(len(results.result) > 0)
            # Scores should be modified or at least present
            self.assertIsNotNone(results.result[0]['score'])

if __name__ == "__main__":
    unittest.main()
