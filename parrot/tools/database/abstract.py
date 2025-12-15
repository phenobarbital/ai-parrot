from typing import Any, Dict, List, Optional
from abc import ABC, abstractmethod
from pydantic import Field
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession
from sqlalchemy.orm import sessionmaker
from navconfig.logging import logging
from ..abstract import (
    AbstractTool,
    ToolResult,
    AbstractToolArgsSchema
)
from ...stores.abstract import AbstractStore
from ...conf import asyncpg_sqlalchemy_url
from .models import TableMetadata
from .cache import SchemaMetadataCache


class SchemaSearchArgs(AbstractToolArgsSchema):
    """Arguments for schema search tool."""
    search_term: str = Field(
        description="Term to search for in table names, column names, or descriptions"
    )
    schema_name: Optional[str] = Field(
        default=None,
        description="Schema name to search in"
    )
    table_name: Optional[str] = Field(
        default=None,
        description="Table name to search in"
    )
    search_type: str = Field(
        default="all",
        description="Type of search: 'tables', 'columns', 'descriptions', or 'all'"
    )
    limit: int = Field(
        default=5,
        description="Maximum number of results to return"
    )


class AbstractSchemaManagerTool(AbstractTool, ABC):
    """
    Abstract base for database-specific schema management tools.

    Handles all schema-related operations:
    - Schema analysis and metadata extraction
    - Schema search and discovery
    - Metadata caching and retrieval
    """

    name = "SchemaManagerTool"
    description = "Comprehensive schema management for database operations"
    args_schema = SchemaSearchArgs

    def __init__(
        self,
        allowed_schemas: List[str],
        engine: AsyncEngine = None,
        metadata_cache: SchemaMetadataCache = None,
        vector_store: Optional[AbstractStore] = None,
        dsn: Optional[str] = None,
        database_type: str = "postgresql",
        session_maker: Optional[sessionmaker] = None,
        **kwargs
    ):
        super().__init__(**kwargs)
        self.dsn = dsn or asyncpg_sqlalchemy_url
        self.database_type = database_type
        self.allowed_schemas = allowed_schemas
        # Database components
        self.engine: Optional[AsyncEngine] = engine or self._get_engine(
            dsn=self.dsn,
            search_path=",".join(allowed_schemas)
        )
        # Schema-aware components
        self.metadata_cache = metadata_cache or SchemaMetadataCache(
            vector_store=vector_store,  # Optional - can be None
            lru_maxsize=500,  # Large cache for many tables
            lru_ttl=1800     # 30 minutes
        )
        # Vector Store:
        self.knowledge_store = vector_store

        if session_maker:
            self.session_maker = session_maker
        else:
            self.session_maker = sessionmaker(
                self.engine,
                class_=AsyncSession,
                expire_on_commit=False
            )

        self.logger = logging.getLogger(f"{self.__class__.__name__}")
        self.logger.debug(
            f"Initialized with {len(allowed_schemas)} schemas: {allowed_schemas}"
        )

    def _get_engine(self, dsn: str, search_path: str) -> AsyncEngine:
        """Create and return an AsyncEngine for the given DSN."""
        from sqlalchemy.ext.asyncio import create_async_engine
        return create_async_engine(
            dsn,
            echo=False,
            pool_pre_ping=True,
            pool_recycle=3600,
            # Multi-schema search path
            connect_args={
                "server_settings": {
                    "search_path": search_path
                }
            }
        )

    async def _execute(
        self,
        search_term: str,
        search_type: str = "all",
        limit: int = 10
    ) -> ToolResult:
        """Execute schema search with the provided parameters."""
        try:
            raw_results = await self.search_schema(search_term, search_type, limit)

            formatted_results = []
            for table in raw_results:
                formatted_result = await self._format_table_result(table, search_term, search_type)
                if formatted_result:
                    formatted_results.append(formatted_result)

            return ToolResult(
                status="success",
                result=formatted_results,
                metadata={
                    "search_term": search_term,
                    "search_type": search_type,
                    "results_count": len(formatted_results),
                    "searched_schemas": self.allowed_schemas
                }
            )
        except Exception as e:
            self.logger.error(f"Schema search failed: {e}")
            return ToolResult(
                status="error",
                result=None,
                error=str(e),
                metadata={"search_term": search_term}
            )

    async def analyze_all_schemas(self) -> Dict[str, int]:
        """
        Analyze all allowed schemas and populate metadata cache.
        Returns dict of schema_name -> table_count.
        """
        self.logger.info(f"Analyzing schemas: {self.allowed_schemas}")

        results = {}
        total_tables = 0

        for schema_name in self.allowed_schemas:
            try:
                table_count = await self.analyze_schema(schema_name)
                results[schema_name] = table_count
                total_tables += table_count
                self.logger.info(f"Schema '{schema_name}': {table_count} tables/views analyzed")
            except Exception as e:
                self.logger.warning(f"Failed to analyze schema '{schema_name}': {e}")
                results[schema_name] = 0
                continue

        self.logger.info(
            f"Analysis completed. Total: {total_tables} tables across {len(self.allowed_schemas)} schemas"
        )
        return results

    @abstractmethod
    async def analyze_schema(self, schema_name: str) -> int:
        """
        Analyze individual schema and return table count.
        Must be implemented by database-specific subclasses.
        """
        pass

    @abstractmethod
    async def analyze_table(
        self,
        session: AsyncSession,
        schema_name: str,
        table_name: str,
        table_type: str,
        comment: Optional[str]
    ) -> TableMetadata:
        """
        Analyze individual table metadata.
        Must be implemented by database-specific subclasses.
        """
        pass

    async def search_schema(
        self,
        search_term: str,
        search_type: str = "all",
        limit: int = 10
    ) -> List[TableMetadata]:
        """Search database schema - returns raw TableMetadata for agent use."""
        self.logger.debug(
            f"🔍 SCHEMA SEARCH: '{search_term}' (type: {search_type}, limit: {limit})")

        tables = await self.metadata_cache.search_similar_tables(
            schema_names=self.allowed_schemas,
            query=search_term,
            limit=limit
        )

        self.logger.info(f"✅ SEARCH COMPLETE: Found {len(tables)} results")
        return tables

    async def _format_table_result(
        self,
        table: TableMetadata,
        search_term: str,
        search_type: str
    ) -> Optional[Dict[str, Any]]:
        """Format a table metadata object into a search result."""

        # Always return since cache already did filtering
        return {
            "type": "table",
            "schema": table.schema,
            "tablename": table.tablename,
            "full_name": table.full_name,
            "table_type": table.table_type,
            "description": table.comment,
            "columns": [
                {
                    "name": col.get('name'),
                    "type": col.get('type'),
                    "nullable": col.get('nullable', True),
                    "description": col.get('description')
                }
                for col in table.columns
            ],
            "row_count": table.row_count,
            "sample_data": table.sample_data[:3] if table.sample_data else [],
            "search_term": search_term,
            "search_type": search_type
        }

    async def get_table_details(
        self,
        schema: str,
        tablename: str
    ) -> Optional[TableMetadata]:
        """Get detailed metadata for a specific table."""
        if schema not in self.allowed_schemas:
            self.logger.warning(
                f"Schema '{schema}' not in allowed schemas: {self.allowed_schemas}"
            )
            return None

        try:
            return await self.metadata_cache.get_table_metadata(schema, tablename)
        except Exception as e:
            self.logger.error(f"Failed to get table details for {schema}.{tablename}: {e}")
            return None

    async def get_schema_overview(self, schema_name: str) -> Optional[Dict[str, Any]]:
        """Get overview of a specific schema."""
        if schema_name not in self.allowed_schemas:
            return None

        if schema_meta := self.metadata_cache.get_schema_overview(schema_name):
            return {
                "schema": schema_meta.schema,
                "database_name": schema_meta.database_name,
                "table_count": schema_meta.table_count,
                "view_count": schema_meta.view_count,
                "total_rows": schema_meta.total_rows,
                "last_analyzed": schema_meta.last_analyzed.isoformat() if schema_meta.last_analyzed else None,
                "tables": list(schema_meta.tables.keys()),
                "views": list(schema_meta.views.keys())
            }
        return None

    def get_allowed_schemas(self) -> List[str]:
        """Get the list of schemas this tool can search."""
        return self.allowed_schemas.copy()
