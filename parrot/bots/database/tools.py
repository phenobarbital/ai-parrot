from typing import Any, Dict, List, Optional
from pydantic import Field
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession
from sqlalchemy.orm import sessionmaker
from navconfig.logging import logging
from ...tools.abstract import (
    AbstractTool,
    ToolResult,
    AbstractToolArgsSchema
)
from .models import TableMetadata
from .cache import SchemaMetadataCache


class SchemaSearchArgs(AbstractToolArgsSchema):
    """Arguments for schema search tool."""
    search_term: str = Field(
        description="Term to search for in table names, column names, or descriptions"
    )
    search_type: str = Field(
        default="all",
        description="Type of search: 'tables', 'columns', 'descriptions', or 'all'"
    )
    limit: int = Field(
        default=5,
        description="Maximum number of results to return"
    )


class SchemaSearchTool(AbstractTool):
    """
    Tool for searching database schema metadata.

    Independent tool that can be reused across different agents.
    Takes minimal dependencies: engine, cache, and allowed schemas.
    """

    name = "SchemaSearchTool"
    description = "Search for tables, views, columns, or other database objects in the schema"
    args_schema = SchemaSearchArgs

    def __init__(
        self,
        engine: AsyncEngine,
        metadata_cache: SchemaMetadataCache,
        allowed_schemas: List[str],
        session_maker: Optional[sessionmaker] = None,
        **kwargs
    ):
        super().__init__(**kwargs)
        self.engine = engine
        self.metadata_cache = metadata_cache
        self.allowed_schemas = allowed_schemas

        # Create session maker if not provided
        if session_maker:
            self.session_maker = session_maker
        else:
            self.session_maker = sessionmaker(
                self.engine,
                class_=AsyncSession,
                expire_on_commit=False
            )

        self.logger = logging.getLogger("SchemaSearchTool")
        self.logger.debug(f"Initialized with {len(allowed_schemas)} schemas: {allowed_schemas}")


    async def _execute(
        self,
        search_term: str,
        search_type: str = "all",
        limit: int = 5
    ) -> ToolResult:
        """Execute schema search with the provided parameters."""
        try:
            # Get raw TableMetadata objects
            raw_results = await self.search_schema(search_term, search_type, limit)

            # Format them for the tool result
            formatted_results = []
            for table in raw_results:
                formatted_result = await self._format_table_result(table, search_term, search_type)
                if formatted_result:
                    formatted_results.append(formatted_result)

            return ToolResult(
                status="success",
                result=formatted_results,  # Tool returns formatted dictionaries
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

    async def search_schema(
        self,
        search_term: str,
        search_type: str = "all",
        limit: int = 10
    ) -> List[Dict[str, Any]]:
        """
        Search database schema for tables, columns, and other objects.

        This is the core search logic moved from the agent.
        """
        self.logger.debug(
            f"🔍 SCHEMA SEARCH: '{search_term}' (type: {search_type}, limit: {limit})"
        )

        # Use metadata cache for search
        tables = await self.metadata_cache.search_similar_tables(
            schema_names=self.allowed_schemas,
            query=search_term,
            limit=limit
        )

        self.logger.info(
            f"✅ SEARCH COMPLETE: Found {len(tables)} results"
        )
        return tables

    async def _format_table_result(
        self,
        table: TableMetadata,
        search_term: str,
        search_type: str
    ) -> Optional[Dict[str, Any]]:
        """Format a table metadata object into a search result."""
        search_term_lower = search_term.lower()

        # Base result structure
        result = {
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
            "sample_data": table.sample_data[:3] if table.sample_data else []
        }

        # Add relevance scoring - FIX: Always return the table since cache already filtered
        # The cache's _search_cache_only method already did the relevance filtering
        relevance_score = 1.0  # Default score since cache already filtered
        match_reasons = []

        # Table name matches
        if search_term_lower in table.tablename.lower():
            relevance_score += 10.0
            match_reasons.append(f"Table name contains '{search_term}'")

        # Column matches
        matching_columns = []
        for col in table.columns:
            if search_term_lower in col.get('name', '').lower():
                relevance_score += 5.0
                matching_columns.append(col.get('name'))

        if matching_columns:
            match_reasons.append(f"Columns match: {', '.join(matching_columns)}")

        # Description matches
        if table.comment and search_term_lower in table.comment.lower():
            relevance_score += 3.0
            match_reasons.append("Description contains search term")

        result.update({
            "relevance_score": relevance_score,
            "match_reasons": match_reasons
        })

        return result

    async def get_table_details(
        self,
        schema: str,
        tablename: str
    ) -> Optional[TableMetadata]:
        """Get detailed metadata for a specific table."""
        if schema not in self.allowed_schemas:
            self.logger.warning(f"Schema '{schema}' not in allowed schemas: {self.allowed_schemas}")
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

        schema_meta = self.metadata_cache.get_schema_overview(schema_name)
        if not schema_meta:
            return None

        return {
            "schema": schema_meta.schema,  # Updated attribute name
            "database_name": schema_meta.database_name,
            "table_count": schema_meta.table_count,
            "view_count": schema_meta.view_count,
            "total_rows": schema_meta.total_rows,
            "last_analyzed": schema_meta.last_analyzed.isoformat() if schema_meta.last_analyzed else None,
            "tables": list(schema_meta.tables.keys()),
            "views": list(schema_meta.views.keys())
        }

    def get_allowed_schemas(self) -> List[str]:
        """Get the list of schemas this tool can search."""
        return self.allowed_schemas.copy()
