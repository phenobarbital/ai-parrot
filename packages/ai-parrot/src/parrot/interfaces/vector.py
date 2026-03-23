"""
VectorInterface - Interface for vector store and search functionality.

This interface provides methods for managing vector stores and performing
various search operations including ensemble search and result fusion.
"""
import copy
import importlib
from typing import List, Dict, Any
from ..stores import AbstractStore, supported_stores
from ..stores.models import StoreConfig


class VectorInterface:
    """
    Interface for vector store management and search operations.
    
    This interface provides methods for:
    - Configuring and managing vector stores
    - Performing ensemble searches (similarity + MMR)
    - Combining and reranking search results
    - Reciprocal rank fusion
    """

    def _apply_store_config(self, config: StoreConfig) -> None:
        """Apply StoreConfig to agent."""
        store_kwargs = {
            'vector_store': config.vector_store,
            'embedding_model': config.embedding_model,
            'dimension': config.dimension,
            **config.extra
        }
        if config.table:
            store_kwargs['table'] = config.table
        if config.schema:
            store_kwargs['schema'] = config.schema
        if config.dsn:
            store_kwargs['dsn'] = config.dsn
        # Define the store:
        self.define_store(**store_kwargs)

    def _get_database_store(self, store: dict) -> AbstractStore:
        """Get the VectorStore Class from the store configuration."""
        name = store.get('name')
        if not name:
            vector_driver = store.get('vector_database', 'PgVectorStore')
            name = next(
                (k for k, v in supported_stores.items() if v == vector_driver), None
            )
        store_cls = supported_stores.get(name)
        cls_path = f"parrot.stores.{name}"
        try:
            module = importlib.import_module(cls_path, package=name)
            store_cls = getattr(module, store_cls)
            if 'embedding_model' not in store:
                store['embedding_model'] = self.embedding_model
            if 'embedding' not in store:
                store['embedding'] = self.embeddings
            self.logger.notice(
                f"Using VectorStore: {store_cls.__name__} for {name} with Embedding {store['embedding_model']}"  # noqa
            )
            try:
                return store_cls(
                    **store
                )
            except Exception as err:
                self.logger.error(
                    f"Error configuring VectorStore: {err}"
                )
                raise
        except ImportError as e:
            self.logger.error(f"Error importing VectorStore: {e}")
            raise
        except Exception:
            raise

    def configure_store(self, **kwargs):
        """Configure Vector Store."""
        if isinstance(self._vector_store, list):
            for st in self._vector_store:
                try:
                    store_cls = self._get_database_store(st)
                    store_cls.use_database = self._use_vector
                    self.stores.append(store_cls)
                except ImportError:
                    continue
        elif isinstance(self._vector_store, dict):
            store_cls = self._get_database_store(self._vector_store)
            store_cls.use_database = self._use_vector
            self.stores.append(store_cls)
        else:
            raise ValueError(f"Invalid Vector Store Config: {self._vector_store}")

        self.logger.info(f"Configured Vector Stores: {self.stores}")
        if self.stores:
            self.store = self.stores[0]

    def define_store(
        self,
        vector_store: str = 'postgres',
        **kwargs
    ):
        """Define the Vector Store."""
        self._use_vector = True
        self._vector_store = {
            "name": vector_store,
            **kwargs
        }

    async def _ensemble_search(
        self,
        store,
        question: str,
        config: dict,
        score_threshold: float,
        metric_type: str,
        search_kwargs: dict = None
    ) -> dict:
        """Perform ensemble search combining similarity and MMR approaches."""

        # Perform similarity search
        similarity_results = await store.similarity_search(
            query=question,
            limit=config['similarity_limit'],
            score_threshold=score_threshold,
            metric=metric_type,
            **(search_kwargs or {})
        )
        # Perform MMR search
        mmr_search_kwargs = {
            "k": config['mmr_limit'],
            "fetch_k": config['mmr_limit'] * 2,
            "lambda_mult": 0.4,
        }
        if search_kwargs:
            mmr_search_kwargs |= search_kwargs
        mmr_results = await store.mmr_search(
            query=question,
            score_threshold=score_threshold,
            **mmr_search_kwargs
        )
        # Combine and rerank results
        final_results = self._combine_search_results(
            similarity_results,
            mmr_results,
            config
        )

        return {
            'similarity_results': similarity_results,
            'mmr_results': mmr_results,
            'final_results': final_results
        }

    def _combine_search_results(self, similarity_results: list, mmr_results: list, config: dict) -> list:
        """Combine and rerank results from different search methods."""

        # Create a mapping of content to results for deduplication
        content_map = {}
        all_results = []

        # Add similarity results with their weights and ranks
        for rank, result in enumerate(similarity_results):
            content_key = self._get_content_key(result.content)
            if content_key not in content_map:
                # Create a copy of the result and add ensemble information
                result_copy = result.model_copy() if hasattr(result, 'model_copy') else result.copy()
                result_copy.ensemble_score = result.score * config['similarity_weight']
                result_copy.search_source = 'similarity'
                result_copy.similarity_rank = rank
                result_copy.mmr_rank = None

                content_map[content_key] = result_copy
                all_results.append(result_copy)

        # Add MMR results, handling duplicates
        for rank, result in enumerate(mmr_results):
            content_key = self._get_content_key(result.content)
            if content_key in content_map:
                # If duplicate, boost the score and update metadata
                existing = content_map[content_key]
                mmr_score = result.score * config['mmr_weight']
                existing.ensemble_score += mmr_score
                existing.search_source = 'both'
                existing.mmr_rank = rank
            else:
                # New result from MMR
                result_copy = result.model_copy() if hasattr(result, 'model_copy') else result.copy()
                result_copy.ensemble_score = result.score * config['mmr_weight']
                result_copy.search_source = 'mmr'
                result_copy.similarity_rank = None
                result_copy.mmr_rank = rank

                content_map[content_key] = result_copy
                all_results.append(result_copy)

        # Rerank based on method
        rerank_method = config.get('rerank_method', 'weighted_score')

        if rerank_method == 'weighted_score':
            # Sort by ensemble score
            all_results.sort(key=lambda x: x.ensemble_score, reverse=True)

        elif rerank_method == 'rrf':
            # Reciprocal Rank Fusion
            all_results = self._reciprocal_rank_fusion(similarity_results, mmr_results)

        elif rerank_method == 'interleave':
            # Interleave results from both searches
            all_results = self._interleave_results(similarity_results, mmr_results)

        # Return top results
        final_limit = config.get('final_limit', 5)
        return all_results[:final_limit]

    def _reciprocal_rank_fusion(self, similarity_results: list, mmr_results: list, k: int = 60) -> list:
        """Implement Reciprocal Rank Fusion for combining ranked lists."""

        # Create score mappings and result mappings
        content_scores = {}
        result_map = {}

        # Add similarity scores and track results
        for rank, result in enumerate(similarity_results):
            content_key = self._get_content_key(result.content)
            rrf_score = 1 / (k + rank + 1)
            content_scores[content_key] = content_scores.get(content_key, 0) + rrf_score

            if content_key not in result_map:
                result_copy = result.model_copy() if hasattr(result, 'model_copy') else result.copy()
                result_copy.similarity_rank = rank
                result_copy.mmr_rank = None
                result_copy.search_source = 'similarity'
                result_map[content_key] = result_copy

        # Add MMR scores and update results
        for rank, result in enumerate(mmr_results):
            content_key = self._get_content_key(result.content)
            rrf_score = 1 / (k + rank + 1)
            content_scores[content_key] = content_scores.get(content_key, 0) + rrf_score

            if content_key in result_map:
                # Update existing result
                result_map[content_key].mmr_rank = rank
                result_map[content_key].search_source = 'both'
            else:
                # New result from MMR
                result_copy = result.model_copy() if hasattr(result, 'model_copy') else result.copy()
                result_copy.similarity_rank = None
                result_copy.mmr_rank = rank
                result_copy.search_source = 'mmr'
                result_map[content_key] = result_copy

        # Set ensemble scores based on RRF and sort
        for content_key, rrf_score in content_scores.items():
            if content_key in result_map:
                result_map[content_key].ensemble_score = rrf_score

        # Sort by RRF score
        sorted_items = sorted(content_scores.items(), key=lambda x: x[1], reverse=True)

        # Return sorted results
        return [result_map[content_key] for content_key, _ in sorted_items if content_key in result_map]

    def _interleave_results(self, similarity_results: list, mmr_results: list) -> list:
        """Interleave results from both search methods."""

        interleaved = []
        seen_content = set()

        max_len = max(len(similarity_results), len(mmr_results))

        for i in range(max_len):
            # Add from similarity first
            if i < len(similarity_results):
                result = similarity_results[i]
                content_key = self._get_content_key(result.content)
                if content_key not in seen_content:
                    result_copy = result.model_copy() if hasattr(result, 'model_copy') else result.copy()
                    result_copy.ensemble_score = 1.0 - (i * 0.1)  # Decreasing score based on position
                    result_copy.search_source = 'similarity'
                    result_copy.similarity_rank = i
                    result_copy.mmr_rank = None

                    interleaved.append(result_copy)
                    seen_content.add(content_key)

            # Add from MMR
            if i < len(mmr_results):
                result = mmr_results[i]
                content_key = self._get_content_key(result.content)
                if content_key not in seen_content:
                    result_copy = result.model_copy() if hasattr(result, 'model_copy') else result.copy()
                    result_copy.ensemble_score = 0.9 - (i * 0.1)  # Slightly lower base score for MMR
                    result_copy.search_source = 'mmr'
                    result_copy.similarity_rank = None
                    result_copy.mmr_rank = i

                    interleaved.append(result_copy)
                    seen_content.add(content_key)

        return interleaved

    def _get_content_key(self, content: str) -> str:
        """Generate a key for content deduplication."""
        # Simple approach: use first 100 characters, normalized
        return content[:100].lower().strip()

    def _copy_result(self, result):
        """Create a copy of a search result."""
        # This depends on your result object structure
        # Adjust based on your actual result class
        return copy.deepcopy(result)
