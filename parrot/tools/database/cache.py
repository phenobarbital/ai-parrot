# ============================================================================
# SCHEMA-AWARE METADATA CACHE
# ============================================================================
from typing import Dict, List, Optional
import re
import yaml
from cachetools import TTLCache
from navconfig.logging import logging
from .models import SchemaMetadata, TableMetadata
from ...stores.abstract import AbstractStore


def _try_create_faiss_store() -> Optional[AbstractStore]:
    """Attempt to create an in-memory FAISSStore; return None if unavailable."""
    try:
        from ...stores.faiss_store import FAISSStore
        return FAISSStore(
            collection_name="schema_metadata",
            embedding_model="sentence-transformers/all-mpnet-base-v2",
            use_database=False,
        )
    except (ImportError, Exception):
        return None


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
        # Auto-create an in-memory FAISSStore when none provided
        if vector_store is None:
            vector_store = _try_create_faiss_store()
            if vector_store is not None:
                logging.getLogger("Parrot.SchemaMetadataCache").info(
                    "SchemaMetadataCache: auto-created in-memory FAISSStore"
                )
            else:
                logging.getLogger("Parrot.SchemaMetadataCache").info(
                    "SchemaMetadataCache: faiss-cpu not available — running LRU-only mode"
                )

        self.vector_store = vector_store
        self.vector_enabled = vector_store is not None

        # Schema-level caches
        self.schema_cache: Dict[str, SchemaMetadata] = {}
        self.table_access_stats: Dict[str, int] = {}

        self.logger = logging.getLogger("Parrot.SchemaMetadataCache")

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
        cache_key = self._table_cache_key(metadata.schema, metadata.tablename)

        # Store in hot cache
        self.hot_cache[cache_key] = metadata

        # Update schema cache
        if metadata.schema not in self.schema_cache:
            self.schema_cache[metadata.schema] = SchemaMetadata(
                schema=metadata.schema,
                database_name="navigator",  # Could be dynamic
                table_count=0,
                view_count=0
            )

        schema_meta = self.schema_cache[metadata.schema]
        if metadata.table_type == 'BASE TABLE':
            schema_meta.tables[metadata.tablename] = metadata
        else:
            schema_meta.views[metadata.tablename] = metadata

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
                metadata_filters={"schema_name": {"$in": schema_names}},
            )

            if results:
                converted = await self._convert_vector_results(results)
                if converted:
                    return converted
        except Exception as exc:
            self.logger.warning("Vector store search failed, falling back to LRU: %s", exc)

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

                self.logger.debug(
                    f"🔍 SEARCHING SCHEMA '{schema_name}': {len(all_objects)} tables available"
                )

                for table_name, table_meta in all_objects.items():
                    score = self._calculate_relevance_score(table_name, table_meta, keywords)

                    if score > 0:
                        self.logger.debug(
                            f"🔍 MATCH: {table_name} scored {score}"
                        )
                        # IMPORTANT: Return the actual TableMetadata object, not a tuple
                        results.append(table_meta)  # FIX: was (table_meta_copy, score)

                        if len(results) >= limit:
                            break

                if len(results) >= limit:
                    break

        # FIX: Sort by a different method since we're not storing scores anymore
        # For now, just return in order found (cache already does some relevance filtering)
        final_results = results[:limit]

        self.logger.info(f"🔍 SEARCH: Found {len(final_results)} results")

        # DEBUG: Log what we're returning
        for i, table in enumerate(final_results):
            self.logger.debug(f"  Result {i+1}: {table.schema}.{table.tablename}")

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
        return [word for word in words if word not in stop_words and len(word) > 2]

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

    async def _search_vector_store(
        self,
        schema_name: str,
        table_name: str
    ) -> Optional[TableMetadata]:
        """Search vector store for a specific table by schema+name."""
        if not self.vector_enabled:
            return None
        try:
            results = await self.vector_store.similarity_search(
                f"{schema_name}.{table_name}",
                k=1,
                metadata_filters={"schema_name": schema_name},
            )
            if results:
                converted = await self._convert_vector_results(results)
                return converted[0] if converted else None
        except Exception as exc:
            self.logger.warning(
                "Vector store read failed for %s.%s: %s", schema_name, table_name, exc
            )
        return None

    async def _store_in_vector_store(self, metadata: TableMetadata):
        """Store table metadata in the vector store."""
        if not self.vector_enabled:
            return
        try:
            from ...stores.models import Document
            document = Document(
                page_content=metadata.to_yaml_context(),
                metadata={
                    "type": "table_metadata",
                    "schema_name": metadata.schema,
                    "tablename": metadata.tablename,
                    "table_type": metadata.table_type,
                    "full_name": metadata.full_name,
                },
            )
            await self.vector_store.add_documents([document])
        except Exception as exc:
            self.logger.warning(
                "Vector store write failed for %s.%s: %s",
                metadata.schema, metadata.tablename, exc,
            )

    async def _convert_vector_results(self, results) -> List[TableMetadata]:
        """Convert vector store SearchResult objects back into TableMetadata."""
        converted = []
        for result in results:
            try:
                # Support both object-style (SearchResult) and dict-style results
                if hasattr(result, "content"):
                    content = result.content
                    meta = getattr(result, "metadata", {}) or {}
                elif isinstance(result, dict):
                    content = result.get("content", "")
                    meta = result.get("metadata", {})
                else:
                    continue

                if not content:
                    continue

                data = yaml.safe_load(content)
                if not isinstance(data, dict):
                    continue

                schema_name = meta.get("schema_name", "")
                tablename = meta.get("tablename", "")
                full_name = data.get("table", meta.get("full_name", ""))

                # Normalise columns: YAML stores list of dicts with name/type/nullable/description
                raw_columns = data.get("columns", [])
                columns = []
                for col in raw_columns:
                    if isinstance(col, dict):
                        columns.append({
                            "name": col.get("name", ""),
                            "type": col.get("type", ""),
                            "nullable": col.get("nullable", True),
                            "comment": col.get("description"),
                        })

                table_metadata = TableMetadata(
                    schema=schema_name,
                    tablename=tablename,
                    table_type=data.get("type", "BASE TABLE"),
                    full_name=full_name,
                    comment=data.get("description"),
                    columns=columns,
                    primary_keys=data.get("primary_keys") or [],
                    row_count=data.get("row_count"),
                    sample_data=[],
                )
                converted.append(table_metadata)
            except Exception as exc:
                self.logger.warning("Failed to convert vector result: %s", exc)
        return converted
