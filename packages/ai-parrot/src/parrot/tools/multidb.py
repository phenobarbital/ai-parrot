"""
Multi-Tier Schema Metadata Caching System for AI-Parrot DatabaseTool

This system implements intelligent schema caching with three tiers:
1. In-memory cache for frequently accessed tables
2. Vector database for semantic discovery of related tables
3. Direct database extraction as last resort

The key insight: 90% of queries hit the same 10% of tables, so we optimize
for this common case while gracefully handling discovery of new tables.
"""

from typing import Dict, List, Optional, Any, Set
from collections import defaultdict, OrderedDict
import asyncio
from datetime import datetime, timedelta
from dataclasses import dataclass, asdict
from enum import Enum
import logging
import json
import yaml


from ..stores.abstract import AbstractStore
from .abstract import AbstractTool


class MetadataFormat(str, Enum):
    """Supported metadata formats for schema representation."""
    YAML_OPTIMIZED = "yaml_optimized"  # Custom YAML format for LLM context
    JSON_SCHEMA = "json_schema"        # Full JSON Schema specification
    AVRO_SCHEMA = "avro_schema"        # Avro schema format
    COMPACT_YAML = "compact_yaml"      # Minimal YAML for quick parsing


@dataclass
class TableMetadata:
    """
    Optimized table metadata structure designed for both caching efficiency
    and LLM comprehension. This format balances completeness with conciseness.
    """
    table_name: str
    schema_name: str
    database_type: str

    # Core structure information
    columns: List[Dict[str, Any]]  # Simplified column definitions
    primary_keys: List[str]
    foreign_keys: List[Dict[str, str]]  # {column, references_table.column}
    indexes: List[Dict[str, Any]]

    # Semantic information for LLM context
    description: Optional[str] = None
    business_purpose: Optional[str] = None  # Inferred from usage patterns
    common_joins: List[str] = None         # Tables commonly joined with this one
    sample_data: Optional[Dict[str, List]] = None  # Small sample for context

    # Metadata about the metadata
    row_count_estimate: Optional[int] = None
    last_updated: datetime = None
    access_frequency: int = 0              # How often this table is queried
    cache_timestamp: datetime = None

    def to_llm_context(self, format_type: MetadataFormat = MetadataFormat.YAML_OPTIMIZED) -> str:
        """
        Convert table metadata to LLM-friendly format.

        This is a critical method - the format needs to be:
        1. Concise enough to fit in LLM context windows
        2. Rich enough to generate accurate queries
        3. Structured enough for reliable parsing
        """
        if format_type == MetadataFormat.YAML_OPTIMIZED:
            return self._to_yaml_optimized()
        elif format_type == MetadataFormat.COMPACT_YAML:
            return self._to_compact_yaml()
        elif format_type == MetadataFormat.JSON_SCHEMA:
            return self._to_json_schema()
        else:
            raise ValueError(f"Unsupported format: {format_type}")

    def _to_yaml_optimized(self) -> str:
        """
        Generate YAML format optimized for LLM understanding.

        This format prioritizes clarity and includes business context
        that helps the LLM generate more intuitive queries.
        """
        # Build the core structure
        schema_dict = {
            'table': f"{self.schema_name}.{self.table_name}",
            'purpose': self.business_purpose or self.description or "Data table",
            'columns': {}
        }

        # Simplify column information for LLM consumption
        for col in self.columns:
            col_info = {
                'type': self._simplify_data_type(col.get('type', 'unknown')),
                'nullable': col.get('nullable', True)
            }

            # Add semantic hints that help LLMs generate better queries
            if col.get('description'):
                col_info['description'] = col['description']
            if col['name'] in self.primary_keys:
                col_info['primary_key'] = True
            if self._is_foreign_key(col['name']):
                col_info['references'] = self._get_foreign_key_reference(col['name'])

            schema_dict['columns'][col['name']] = col_info

        # Add relationship information
        if self.common_joins:
            schema_dict['commonly_joined_with'] = self.common_joins[:5]  # Limit context size

        # Add sample data if available (helps LLM understand data patterns)
        if self.sample_data:
            schema_dict['sample_data'] = {
                col: values[:3]  # Just first 3 samples to avoid context bloat
                for col, values in self.sample_data.items()
            }

        # Add usage hints
        if self.row_count_estimate:
            if self.row_count_estimate > 1000000:
                schema_dict['size_hint'] = 'large_table'
            elif self.row_count_estimate > 10000:
                schema_dict['size_hint'] = 'medium_table'
            else:
                schema_dict['size_hint'] = 'small_table'

        return yaml.dump(schema_dict, default_flow_style=False, sort_keys=False)

    def _simplify_data_type(self, db_type: str) -> str:
        """
        Convert database-specific types to LLM-friendly generic types.

        This mapping helps LLMs understand what operations are valid
        on different column types without getting lost in database-specific details.
        """
        type_mappings = {
            # Numeric types
            'bigint': 'integer', 'int8': 'integer', 'serial8': 'integer',
            'integer': 'integer', 'int4': 'integer', 'serial': 'integer',
            'smallint': 'integer', 'int2': 'integer',
            'decimal': 'decimal', 'numeric': 'decimal', 'money': 'decimal',
            'real': 'decimal', 'float4': 'decimal',
            'double precision': 'decimal', 'float8': 'decimal',

            # Text types
            'character varying': 'text', 'varchar': 'text', 'char': 'text',
            'text': 'text', 'string': 'text',

            # Date/time types
            'timestamp': 'datetime', 'timestamptz': 'datetime',
            'date': 'date', 'time': 'time',

            # Boolean
            'boolean': 'boolean', 'bool': 'boolean',

            # JSON
            'json': 'json', 'jsonb': 'json',

            # Arrays and special types
            'array': 'array', 'uuid': 'uuid'
        }

        # Extract base type (remove size specifications, etc.)
        base_type = db_type.lower().split('(')[0].strip()
        return type_mappings.get(base_type, 'unknown')

    def _is_foreign_key(self, column_name: str) -> bool:
        """Check if a column is a foreign key."""
        return any(fk['column'] == column_name for fk in (self.foreign_keys or []))

    def _get_foreign_key_reference(self, column_name: str) -> Optional[str]:
        """Get the table.column that this foreign key references."""
        for fk in (self.foreign_keys or []):
            if fk['column'] == column_name:
                return fk['references']
        return None


class SchemaMetadataCache:
    """
    Multi-tier caching system for database schema metadata.

    This class orchestrates the three-tier caching strategy:
    Tier 1: In-memory LRU cache for hot tables
    Tier 2: Vector store for semantic discovery
    Tier 3: Direct database extraction

    The cache learns from usage patterns and optimizes for common access patterns.
    """

    def __init__(
        self,
        vector_store: Optional[AbstractStore] = None,
        memory_cache_size: int = 100,
        cache_ttl_hours: int = 24,
        background_update: bool = True
    ):
        """
        Initialize the multi-tier caching system.

        Args:
            vector_store: Vector database for semantic schema search
            memory_cache_size: Maximum number of tables to keep in memory
            cache_ttl_hours: How long to keep cached metadata valid
            background_update: Whether to update vector store in background
        """
        self.vector_store = vector_store
        self.cache_ttl = timedelta(hours=cache_ttl_hours)
        self.background_update = background_update

        # Tier 1: In-memory cache with LRU eviction
        self.memory_cache: OrderedDict[str, TableMetadata] = OrderedDict()
        self.memory_cache_size = memory_cache_size

        # Usage tracking for intelligent caching decisions
        self.access_counts = defaultdict(int)
        self.last_access = {}

        # Background tasks for non-blocking vector store updates
        self.pending_updates: Set[str] = set()
        self.update_tasks = []

        self.logger = logging.getLogger(__name__)

    def _generate_cache_key(self, schema_name: str, table_name: str, database_type: str) -> str:
        """Generate a unique cache key for a table."""
        return f"{database_type}:{schema_name}.{table_name}"

    async def get_table_metadata(
        self,
        schema_name: str,
        table_name: str,
        database_type: str,
        database_extractor_func: Optional[callable] = None
    ) -> Optional[TableMetadata]:
        """
        Get table metadata using the three-tier caching strategy.

        This is the main entry point that implements the intelligent caching logic:
        1. Check in-memory cache first (fastest)
        2. Fall back to vector store semantic search
        3. Extract directly from database if needed
        4. Update higher tiers with new information
        """
        cache_key = self._generate_cache_key(schema_name, table_name, database_type)
        self._record_access(cache_key)

        # Tier 1: Check in-memory cache
        if cache_key in self.memory_cache:
            metadata = self.memory_cache[cache_key]

            # Check if cache entry is still valid
            if self._is_cache_valid(metadata):
                self.logger.debug(f"Cache hit (memory): {cache_key}")
                self._move_to_front(cache_key)  # LRU bookkeeping
                return metadata
            else:
                self.logger.debug(f"Cache expired (memory): {cache_key}")
                del self.memory_cache[cache_key]

        # Tier 2: Check vector store
        if self.vector_store:
            vector_metadata = await self._search_vector_store(schema_name, table_name, database_type)
            if vector_metadata and self._is_cache_valid(vector_metadata):
                self.logger.debug(f"Cache hit (vector): {cache_key}")
                self._add_to_memory_cache(cache_key, vector_metadata)
                return vector_metadata

        # Tier 3: Extract from database directly
        if database_extractor_func:
            self.logger.debug(f"Cache miss, extracting from database: {cache_key}")
            fresh_metadata = await database_extractor_func(schema_name, table_name)

            if fresh_metadata:
                # Update all cache tiers with fresh data
                fresh_metadata.cache_timestamp = datetime.utcnow()
                self._add_to_memory_cache(cache_key, fresh_metadata)

                # Schedule background update to vector store (non-blocking)
                if self.vector_store and self.background_update:
                    self._schedule_vector_store_update(cache_key, fresh_metadata)

                return fresh_metadata

        # Nothing found
        self.logger.warning(f"No metadata found for {cache_key}")
        return None

    async def get_context_for_query(
        self,
        table_names: List[str],
        schema_name: str = "public",
        database_type: str = "postgresql",
        format_type: MetadataFormat = MetadataFormat.YAML_OPTIMIZED,
        database_extractor_func: Optional[callable] = None
    ) -> str:
        """
        Build comprehensive LLM context for a set of tables.

        This method orchestrates the retrieval of multiple table metadata
        and formats it into a cohesive context for LLM query generation.
        """
        context_parts = []
        retrieved_tables = []

        # Collect metadata for all requested tables
        for table_name in table_names:
            metadata = await self.get_table_metadata(
                schema_name, table_name, database_type, database_extractor_func
            )

            if metadata:
                retrieved_tables.append(metadata)
            else:
                self.logger.warning(f"Could not retrieve metadata for {table_name}")

        # Build comprehensive context
        if retrieved_tables:
            context_parts.append(f"# Database Schema Context ({database_type})")
            context_parts.append(f"# Available tables: {len(retrieved_tables)}")
            context_parts.append("")

            # Add individual table schemas
            for metadata in retrieved_tables:
                context_parts.append(metadata.to_llm_context(format_type))
                context_parts.append("")

            # Add relationship information if multiple tables
            if len(retrieved_tables) > 1:
                relationships = self._analyze_table_relationships(retrieved_tables)
                if relationships:
                    context_parts.append("# Table Relationships")
                    for rel in relationships:
                        context_parts.append(f"- {rel}")
                    context_parts.append("")

        return "\n".join(context_parts)

    def _record_access(self, cache_key: str):
        """Record access for usage pattern analysis."""
        self.access_counts[cache_key] += 1
        self.last_access[cache_key] = datetime.utcnow()

    def _is_cache_valid(self, metadata: TableMetadata) -> bool:
        """Check if cached metadata is still valid."""
        if not metadata.cache_timestamp:
            return False

        age = datetime.utcnow() - metadata.cache_timestamp
        return age < self.cache_ttl

    def _add_to_memory_cache(self, cache_key: str, metadata: TableMetadata):
        """Add metadata to in-memory cache with LRU eviction."""
        # Remove if already exists (for LRU reordering)
        if cache_key in self.memory_cache:
            del self.memory_cache[cache_key]

        # Add to front of cache
        self.memory_cache[cache_key] = metadata

        # Evict least recently used items if over capacity
        while len(self.memory_cache) > self.memory_cache_size:
            oldest_key = next(iter(self.memory_cache))
            del self.memory_cache[oldest_key]
            self.logger.debug(f"Evicted from memory cache: {oldest_key}")

    def _move_to_front(self, cache_key: str):
        """Move cache item to front for LRU ordering."""
        metadata = self.memory_cache.pop(cache_key)
        self.memory_cache[cache_key] = metadata

    async def _search_vector_store(
        self,
        schema_name: str,
        table_name: str,
        database_type: str
    ) -> Optional[TableMetadata]:
        """Search vector store for table metadata."""
        if not self.vector_store:
            return None

        try:
            # Create search query that combines exact and semantic matching
            search_query = f"{schema_name}.{table_name} {database_type} table schema"

            # Search the vector store
            results = await self.vector_store.similarity_search(
                query=search_query,
                limit=1,
                filter_metadata={"database_type": database_type}
            )

            if results and len(results) > 0:
                # Deserialize the stored metadata
                metadata_dict = results[0].get('metadata', {})
                if 'table_metadata' in metadata_dict:
                    return TableMetadata(**metadata_dict['table_metadata'])

        except Exception as e:
            self.logger.warning(f"Vector store search failed: {e}")

        return None

    def _schedule_vector_store_update(self, cache_key: str, metadata: TableMetadata):
        """Schedule background update to vector store (non-blocking)."""
        if cache_key not in self.pending_updates:
            self.pending_updates.add(cache_key)
            task = asyncio.create_task(self._update_vector_store(cache_key, metadata))
            self.update_tasks.append(task)

    async def _update_vector_store(self, cache_key: str, metadata: TableMetadata):
        """Update vector store with new metadata in background."""
        try:
            if not self.vector_store:
                return

            # Create searchable text content
            content = metadata.to_llm_context()

            # Create metadata for vector store
            vector_metadata = {
                "table_name": metadata.table_name,
                "schema_name": metadata.schema_name,
                "database_type": metadata.database_type,
                "table_metadata": asdict(metadata),
                "last_updated": datetime.utcnow().isoformat()
            }

            # Store in vector database
            await self.vector_store.add_documents([{
                "content": content,
                "metadata": vector_metadata,
                "id": cache_key
            }])

            self.logger.debug(f"Updated vector store: {cache_key}")

        except Exception as e:
            self.logger.error(f"Failed to update vector store for {cache_key}: {e}")
        finally:
            self.pending_updates.discard(cache_key)

    def _analyze_table_relationships(self, tables: List[TableMetadata]) -> List[str]:
        """Analyze relationships between multiple tables."""
        relationships = []
        table_names = {t.table_name for t in tables}

        for table in tables:
            for fk in (table.foreign_keys or []):
                ref_table = fk['references'].split('.')[0]
                if ref_table in table_names:
                    relationships.append(
                        f"{table.table_name}.{fk['column']} → {fk['references']}"
                    )

        return relationships

    async def cleanup(self):
        """Clean up background tasks and resources."""
        # Wait for pending vector store updates to complete
        if self.update_tasks:
            await asyncio.gather(*self.update_tasks, return_exceptions=True)

        self.logger.info("Schema metadata cache cleanup completed")

    def get_cache_stats(self) -> Dict[str, Any]:
        """Get caching statistics for monitoring and debugging."""
        return {
            "memory_cache_size": len(self.memory_cache),
            "memory_cache_capacity": self.memory_cache_size,
            "total_access_count": sum(self.access_counts.values()),
            "unique_tables_accessed": len(self.access_counts),
            "pending_vector_updates": len(self.pending_updates),
            "most_accessed_tables": sorted(
                self.access_counts.items(),
                key=lambda x: x[1],
                reverse=True
            )[:10]
        }


# Integration with the main DatabaseTool
class EnhancedDatabaseTool(AbstractTool):
    """
    Enhanced DatabaseTool with intelligent multi-tier schema caching.

    This version integrates the sophisticated caching system to provide
    lightning-fast schema access and intelligent query context building.
    """

    def __init__(self, vector_store: Optional[AbstractStore] = None, **kwargs):
        super().__init__(**kwargs)

        # Initialize the multi-tier caching system
        self.schema_cache = SchemaMetadataCache(
            vector_store=vector_store,
            memory_cache_size=100,
            cache_ttl_hours=24,
            background_update=True
        )

    async def _build_intelligent_context(
        self,
        natural_language_query: str,
        database_flavor: str,
        schema_names: List[str] = ["public"]
    ) -> str:
        """
        Build intelligent context using the multi-tier caching system.

        This method demonstrates how the caching system integrates with
        the main DatabaseTool to provide fast, contextual schema information.
        """
        # Extract likely table names from natural language query
        # This is a simplified version - you'd want more sophisticated NLP here
        potential_tables = self._extract_table_names_from_query(natural_language_query)

        # Get metadata for each table using the caching system
        context = await self.schema_cache.get_context_for_query(
            table_names=potential_tables,
            schema_name=schema_names[0],
            database_type=database_flavor,
            database_extractor_func=self._extract_table_metadata_from_database
        )

        return context

    def _extract_table_names_from_query(self, query: str) -> List[str]:
        """
        Extract likely table names from natural language query.

        This is a simplified implementation. In practice, you'd want:
        1. NLP-based entity extraction
        2. Similarity search against known table names
        3. Business glossary matching
        """
        # Simple keyword-based extraction for demonstration
        common_table_patterns = ['sales', 'orders', 'customers', 'products', 'users']
        query_lower = query.lower()

        found_tables = []
        for pattern in common_table_patterns:
            if pattern in query_lower:
                found_tables.append(pattern)

        return found_tables if found_tables else ['sales']  # Default fallback

    async def _extract_table_metadata_from_database(
        self,
        schema_name: str,
        table_name: str
    ) -> Optional[TableMetadata]:
        """
        Extract metadata directly from database.

        This method integrates with your existing database extraction logic
        but formats the result for the caching system.
        """
        # This would integrate with your existing schema extraction logic
        # For demonstration, returning a mock metadata object
        return TableMetadata(
            table_name=table_name,
            schema_name=schema_name,
            database_type="postgresql",
            columns=[
                {"name": "id", "type": "integer", "nullable": False},
                {"name": "name", "type": "varchar", "nullable": True},
                {"name": "created_at", "type": "timestamp", "nullable": False}
            ],
            primary_keys=["id"],
            foreign_keys=[],
            indexes=[],
            last_updated=datetime.utcnow()
        )
