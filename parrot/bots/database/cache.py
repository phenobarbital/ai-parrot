# ============================================================================
# SCHEMA-AWARE METADATA CACHE
# ============================================================================
from typing import Dict, List, Optional
import re
from cachetools import TTLCache
from navconfig.logging import logging
from .models import SchemaMetadata, TableMetadata
from ...stores.abstract import AbstractStore

class SchemaMetadataCache:
    """Two-tier caching: LRU (hot data) + Optional Vector Store (cold/searchable data)."""

    def __init__(
        self,
        vector_store: Optional[AbstractStore] = None,
        lru_maxsize: int = 500,  # Increased for large schema count
        lru_ttl: int = 1800      # 30 minutes
    ):
        # Tier 1: LRU Cache for frequently accessed metadata
        self.hot_cache = TTLCache(maxsize=lru_maxsize, ttl=lru_ttl)

        # Tier 2: Optional Vector Store for similarity search and persistence
        self.vector_store = vector_store
        self.vector_enabled = vector_store is not None

        # Schema-level caches
        self.schema_cache: Dict[str, SchemaMetadata] = {}
        self.table_access_stats: Dict[str, int] = {}

        self.logger = logging.getLogger("Parrot.SchemaMetadataCache")

        if not self.vector_enabled:
            print("Vector store not provided - using LRU cache only")

    def _table_cache_key(self, schema_name: str, table_name: str) -> str:
        """Generate cache key for table metadata."""
        return f"table:{schema_name}:{table_name}"

    def _schema_cache_key(self, schema_name: str) -> str:
        """Generate cache key for schema metadata."""
        return f"schema:{schema_name}"

    async def get_table_metadata(
        self,
        schema_name: str,
        table_name: str
    ) -> Optional[TableMetadata]:
        """Get table metadata with access tracking."""
        cache_key = self._table_cache_key(schema_name, table_name)

        # Check hot cache first
        if cache_key in self.hot_cache:
            metadata = self.hot_cache[cache_key]
            self._track_access(cache_key)
            return metadata

        # Check schema cache
        if schema_name in self.schema_cache:
            schema_meta = self.schema_cache[schema_name]
            all_objects = schema_meta.get_all_objects()
            if table_name in all_objects:
                metadata = all_objects[table_name]
                # Promote to hot cache
                self.hot_cache[cache_key] = metadata
                self._track_access(cache_key)
                return metadata

        # Check vector store only if enabled
        if self.vector_enabled:
            search_results = await self._search_vector_store(schema_name, table_name)
            if search_results:
                # Store in hot cache
                self.hot_cache[cache_key] = search_results
                self._track_access(cache_key)
                return search_results

        return None

    async def store_table_metadata(self, metadata: TableMetadata):
        """Store table metadata in available cache tiers."""
        cache_key = self._table_cache_key(metadata.schema_name, metadata.table_name)

        # Store in hot cache
        self.hot_cache[cache_key] = metadata

        # Update schema cache
        if metadata.schema_name not in self.schema_cache:
            self.schema_cache[metadata.schema_name] = SchemaMetadata(
                schema_name=metadata.schema_name,
                database_name="navigator",  # Could be dynamic
                table_count=0,
                view_count=0
            )

        schema_meta = self.schema_cache[metadata.schema_name]
        if metadata.table_type == 'BASE TABLE':
            schema_meta.tables[metadata.table_name] = metadata
        else:
            schema_meta.views[metadata.table_name] = metadata

        # Store in vector store only if enabled
        if self.vector_enabled:
            await self._store_in_vector_store(metadata)

    async def search_similar_tables(
        self,
        schema_names: List[str],
        query: str,
        limit: int = 5
    ) -> List[TableMetadata]:
        """Search for similar tables within allowed schemas."""
        if not self.vector_enabled:
            # Fallback: search in LRU cache and schema cache
            return self._search_cache_only(schema_names, query, limit)

        # Search with multi-schema filter
        search_query = f"schemas:{','.join(schema_names)} {query}"
        try:
            results = await self.vector_store.similarity_search(
                search_query,
                k=limit,
                filter={"schema_name": {"$in": schema_names}}  # Multi-schema filter
            )

            # Convert results back to TableMetadata
            return await self._convert_vector_results(results)
        except Exception:
            # Fallback to cache-only search
            return self._search_cache_only(schema_names, query, limit)

    def _search_cache_only(
        self,
        schema_names: List[str],
        query: str,
        limit: int
    ) -> List[TableMetadata]:
        """Fallback search using only cache when vector store unavailable."""
        results = []
        query_lower = query.lower()
        keywords = self._extract_search_keywords(query_lower)

        self.logger.notice(
            f"🔍 SEARCH: Extracted keywords from '{query}': {keywords}"
        )

        # Search through schema caches
        for schema_name in schema_names:
            if schema_name in self.schema_cache:
                schema_meta = self.schema_cache[schema_name]
                all_objects = schema_meta.get_all_objects()

                for table_name, table_meta in all_objects.items():
                    score = self._calculate_relevance_score(table_name, table_meta, keywords)

                    if score > 0:
                        self.logger.debug(
                            f"🔍 MATCH: {table_name} scored {score}"
                        )
                        # Add the score to the table metadata for sorting
                        table_meta_copy = table_meta
                        results.append((table_meta_copy, score))

                        if len(results) >= limit:
                            break

                if len(results) >= limit:
                    break

        # Sort by relevance score (highest first) and return just the TableMetadata objects
        results.sort(key=lambda x: x[1], reverse=True)
        final_results = [table_meta for table_meta, score in results]

        self.logger.info(f"🔍 SEARCH: Found {len(final_results)} results")
        return final_results

    def _extract_search_keywords(self, query: str) -> List[str]:
        """Extract meaningful keywords from a natural language query."""
        # Convert to lowercase and remove common stop words
        stop_words = {
            'get', 'show', 'find', 'list', 'select', 'by', 'from', 'the', 'a', 'an',
            'and', 'or', 'of', 'to', 'in', 'on', 'at', 'for', 'with', 'top', 'all'
        }

        # Split on non-alphanumeric characters and filter
        words = re.findall(r'\b[a-zA-Z]+\b', query.lower())
        keywords = [word for word in words if word not in stop_words and len(word) > 2]

        return keywords

    def _calculate_relevance_score(
        self,
        table_name: str,
        table_meta: TableMetadata,
        keywords: List[str]
    ) -> float:
        """Calculate relevance score for a table based on keywords."""
        score = 0.0

        table_name_lower = table_name.lower()
        column_names = [col['name'].lower() for col in table_meta.columns]

        for keyword in keywords:
            keyword_lower = keyword.lower()

            if keyword_lower == table_name_lower:
                score += 10.0
                self.logger.debug(f"Exact table match: '{keyword}' == '{table_name}'")

            elif keyword_lower in table_name_lower:
                score += 5.0
                self.logger.debug(f"Partial table match: '{keyword}' in '{table_name}'")

            elif keyword_lower in column_names:
                score += 8.0
                self.logger.debug(f"Column match: '{keyword}' found in columns")

            elif any(keyword_lower in col_name for col_name in column_names):
                score += 3.0
                self.logger.debug(f"Partial column match: '{keyword}' partially matches column")

            elif table_meta.comment and keyword_lower in table_meta.comment.lower():
                score += 2.0
                self.logger.debug(f"Comment match: '{keyword}' in table comment")

        return score

    def get_schema_overview(self, schema_name: str) -> Optional[SchemaMetadata]:
        """Get complete schema overview."""
        return self.schema_cache.get(schema_name)

    def get_hot_tables(self, schema_names: List[str], limit: int = 10) -> List[tuple[str, str, int]]:
        """Get most frequently accessed tables across allowed schemas."""
        schema_access = []

        for schema_name in schema_names:
            schema_prefix = f"table:{schema_name}:"
            for key, count in self.table_access_stats.items():
                if key.startswith(schema_prefix):
                    table_name = key.replace(schema_prefix, "")
                    schema_access.append((schema_name, table_name, count))

        return sorted(schema_access, key=lambda x: x[2], reverse=True)[:limit]

    def _track_access(self, cache_key: str):
        """Track table access for hot table identification."""
        self.table_access_stats[cache_key] = self.table_access_stats.get(cache_key, 0) + 1

    async def _search_vector_store(self, schema_name: str, table_name: str) -> Optional[TableMetadata]:
        """Search vector store for specific table."""
        if not self.vector_enabled:
            return None
        # Implementation depends on your vector store
        return None

    async def _store_in_vector_store(self, metadata: TableMetadata):
        """Store metadata in vector store."""
        if not self.vector_enabled:
            return
        try:
            document = {
                "content": metadata.to_yaml_context(),
                "metadata": {
                    "type": "table_metadata",
                    "schema_name": metadata.schema_name,
                    "table_name": metadata.table_name,
                    "table_type": metadata.table_type,
                    "full_name": metadata.full_name
                }
            }
            await self.vector_store.add_documents([document])
        except Exception:
            pass  # Silent failure for vector store issues

    async def _convert_vector_results(self, results) -> List[TableMetadata]:
        """Convert vector store results to TableMetadata objects."""
        # Implementation depends on your vector store format
        return []
