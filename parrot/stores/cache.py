from typing import List, Dict, Optional
import asyncio
import json
import hashlib
import redis.asyncio as redis
import numpy as np
from sklearn.metrics.pairwise import cosine_similarity
from ..conf import REDIS_HISTORY_URL

class SemanticVectorCache:
    """A class to handle caching of semantic vectors using Redis.
    It allows storing and retrieving semantically similar query results
    based on cosine similarity of embeddings.
    It uses Redis for storage and retrieval, with a configurable similarity threshold.
    """
    def __init__(self, redis_url: str = None, similarity_threshold: float = 0.95):
        """
        Initializes the semantic vector cache with Redis connection.
        """
        self.redis_url = redis_url or REDIS_HISTORY_URL
        self.threshold = similarity_threshold
        self.pool = redis.ConnectionPool.from_url(
            redis_url,
            max_connections=20,
            decode_responses=True,
            retry_on_timeout=True,
            health_check_interval=30
        )
        self.client = redis.Redis(connection_pool=self.pool)
        self.prefix = "semantic:"

    async def get_similar_cached_results(
        self,
        query_embedding: np.ndarray,
        top_k: int = 10
    ) -> Optional[List[Dict]]:
        """Search for semantically similar cached queries"""
        try:
            # Get all cached query embeddings
            pattern = f"{self.prefix}query:*"
            keys = await self.client.keys(pattern)

            if not keys:
                return None

            # Batch retrieve cached queries
            cached_queries = await self.client.mget(keys)

            # Find best semantic match
            max_similarity = 0
            best_match_key = None

            for key, cached_data in zip(keys, cached_queries):
                if cached_data:
                    data = json.loads(cached_data)
                    cached_embedding = np.array(data['query_embedding'])

                    similarity = cosine_similarity(
                        query_embedding.reshape(1, -1),
                        cached_embedding.reshape(1, -1)
                    )[0][0]

                    if similarity > max_similarity and similarity >= self.threshold:
                        max_similarity = similarity
                        best_match_key = key.replace('query:', 'results:')

            if best_match_key:
                results = await self.client.get(best_match_key)
                if results:
                    return json.loads(results)

            return None

        except Exception as e:
            print(f"Semantic cache search error: {e}")
            return None

    async def cache_search_results(
        self,
        query_embedding: np.ndarray,
        results: List[Dict],
        ttl: int = 1800
    ):
        """Cache search results with semantic indexing"""
        query_id = hashlib.sha256(query_embedding.tobytes()).hexdigest()[:16]

        query_key = f"{self.prefix}query:{query_id}"
        results_key = f"{self.prefix}results:{query_id}"

        try:
            query_data = {
                'query_embedding': query_embedding.tolist(),
                'timestamp': asyncio.get_event_loop().time()
            }

            # Store both query and results atomically
            pipe = self.client.pipeline()
            pipe.setex(query_key, ttl, json.dumps(query_data))
            pipe.setex(results_key, ttl, json.dumps(results))
            await pipe.execute()

            return True

        except Exception as e:
            print(f"Cache storage error: {e}")
            return False
