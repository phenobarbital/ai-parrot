"""
Database Agent Architecture for AI-Parrot.

This module provides an abstract base for database introspection agents
that can analyze database schemas and generate queries from natural language.
"""

from abc import abstractmethod
from typing import Dict, Any, List, Optional
from dataclasses import dataclass
from pathlib import Path
import json
import asyncio
from pydantic import Field
from sqlalchemy.ext.asyncio import AsyncEngine
from ..abstract import AbstractBot
from ...tools.abstract import (
    AbstractTool,
    ToolResult,
    AbstractToolArgsSchema
)
from ...stores.abstract import AbstractStore


@dataclass
class TableMetadata:
    """Metadata for a database table."""
    name: str
    schema: str
    columns: List[Dict[str, Any]]
    primary_keys: List[str]
    foreign_keys: List[Dict[str, Any]]
    indexes: List[Dict[str, Any]]
    description: Optional[str] = None
    sample_data: Optional[List[Dict[str, Any]]] = None


@dataclass
class DatabaseSchema:
    """Complete database schema information."""
    database_name: str
    database_type: str
    tables: List[TableMetadata]
    views: List[TableMetadata]
    functions: List[Dict[str, Any]]
    procedures: List[Dict[str, Any]]
    metadata: Dict[str, Any]


class QueryGenerationArgs(AbstractToolArgsSchema):
    """Arguments for query generation tool."""
    natural_language_query: str = Field(
        description="Natural language description of the desired query"
    )
    target_tables: Optional[List[str]] = Field(
        default=None,
        description="Specific tables to focus on (optional)"
    )
    query_type: str = Field(
        default="SELECT",
        description="Type of query to generate (SELECT, INSERT, UPDATE, DELETE)"
    )
    include_explanation: bool = Field(
        default=True,
        description="Whether to include explanation of the generated query"
    )


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
        default=10,
        description="Maximum number of results to return"
    )


class AbstractDBAgent(AbstractBot):
    """
    Abstract base class for database introspection agents.

    This agent analyzes database schemas, stores metadata in a knowledge base,
    and generates queries from natural language descriptions.
    """

    def __init__(
        self,
        name: str = "DatabaseAgent",
        connection_string: str = None,
        schema_name: str = None,
        knowledge_store: AbstractStore = None,
        auto_analyze_schema: bool = True,
        **kwargs
    ):
        """
        Initialize the database agent.

        Args:
            name: Agent name
            connection_string: Database connection string
            schema_name: Target schema name
            knowledge_store: Vector store for schema metadata
            auto_analyze_schema: Whether to automatically analyze schema on init
        """
        super().__init__(name=name, **kwargs)

        self.connection_string = connection_string
        self.schema_name = schema_name
        self.knowledge_store = knowledge_store
        self.auto_analyze_schema = auto_analyze_schema

        # Initialize database-specific components
        self.engine: Optional[AsyncEngine] = None
        self.schema_metadata: Optional[DatabaseSchema] = None

        # Add database-specific tools
        self._setup_database_tools()

        if self.auto_analyze_schema and self.connection_string:
            asyncio.create_task(self.initialize_schema())

    async def initialize_schema(self):
        """Initialize database connection and analyze schema."""
        try:
            await self.connect_database()
            self.schema_metadata = await self.extract_schema_metadata()

            if self.knowledge_store:
                await self.store_schema_in_knowledge_base()

        except Exception as e:
            self.logger.error(f"Failed to initialize schema: {e}")
            raise

    def _setup_database_tools(self):
        """Setup database-specific tools."""
        # Add schema search tool
        schema_search_tool = SchemaSearchTool(agent=self)
        self.tool_manager.register_tool(schema_search_tool)

        # Add query generation tool
        query_gen_tool = QueryGenerationTool(agent=self)
        self.tool_manager.register_tool(query_gen_tool)

    @abstractmethod
    async def connect_database(self) -> None:
        """Connect to the database. Must be implemented by subclasses."""
        pass

    @abstractmethod
    async def extract_schema_metadata(self) -> DatabaseSchema:
        """
        Extract complete schema metadata from the database.
        Must be implemented by subclasses based on database type.
        """
        pass

    @abstractmethod
    async def generate_query(
        self,
        natural_language_query: str,
        target_tables: Optional[List[str]] = None,
        query_type: str = "SELECT"
    ) -> Dict[str, Any]:
        """
        Generate database query from natural language.
        Must be implemented by subclasses based on database type.
        """
        pass

    @abstractmethod
    async def execute_query(self, query: str) -> Dict[str, Any]:
        """
        Execute a query against the database.
        Must be implemented by subclasses based on database type.
        """
        pass

    async def store_schema_in_knowledge_base(self) -> None:
        """Store schema metadata in the knowledge base for retrieval."""
        if not self.knowledge_store or not self.schema_metadata:
            return

        documents = []

        # Store table metadata
        for table in self.schema_metadata.tables:
            table_doc = {
                "content": self._format_table_for_storage(table),
                "metadata": {
                    "type": "table_schema",
                    "database": self.schema_metadata.database_name,
                    "schema": table.schema,
                    "table_name": table.name,
                    "database_type": self.schema_metadata.database_type
                }
            }
            documents.append(table_doc)

        # Store view metadata
        for view in self.schema_metadata.views:
            view_doc = {
                "content": self._format_table_for_storage(view, is_view=True),
                "metadata": {
                    "type": "view_schema",
                    "database": self.schema_metadata.database_name,
                    "schema": view.schema,
                    "view_name": view.name,
                    "database_type": self.schema_metadata.database_type
                }
            }
            documents.append(view_doc)

        # Store in knowledge base
        await self.knowledge_store.add_documents(documents)

    def _format_table_for_storage(self, table: TableMetadata, is_view: bool = False) -> str:
        """Format table metadata for storage in knowledge base."""
        object_type = "VIEW" if is_view else "TABLE"

        content = f"""
{object_type}: {table.schema}.{table.name}
Description: {table.description or 'No description available'}

Columns:
"""
        for col in table.columns:
            nullable = "NULL" if col.get('nullable', True) else "NOT NULL"
            default = f" DEFAULT {col['default']}" if col.get('default') else ""
            content += f"  - {col['name']}: {col['type']} {nullable}{default}\n"
            if col.get('description'):
                content += f"    Description: {col['description']}\n"

        if table.primary_keys:
            content += f"\nPrimary Keys: {', '.join(table.primary_keys)}\n"

        if table.foreign_keys:
            content += "\nForeign Keys:\n"
            for fk in table.foreign_keys:
                content += f"  - {fk['column']} -> {fk['referenced_table']}.{fk['referenced_column']}\n"

        if table.indexes:
            content += "\nIndexes:\n"
            for idx in table.indexes:
                content += f"  - {idx['name']}: {', '.join(idx['columns'])}\n"

        if table.sample_data:
            content += "\nSample Data:\n"
            for i, row in enumerate(table.sample_data[:3]):  # Limit to 3 rows
                content += f"  Row {i+1}: {json.dumps(row, default=str)}\n"

        return content

    async def search_schema(
        self,
        search_term: str,
        search_type: str = "all",
        limit: int = 10
    ) -> List[Dict[str, Any]]:
        """
        Search for tables/columns in the schema metadata.
        """
        if not self.knowledge_store:
            # Fallback to local search if no knowledge store
            return self._local_schema_search(search_term, search_type, limit)

        # Search in knowledge base
        query = f"database schema {search_term}"
        results = await self.knowledge_store.similarity_search(query, k=limit)

        formatted_results = []
        for result in results:
            formatted_results.append({
                "content": result.page_content,
                "metadata": result.metadata,
                "relevance_score": getattr(result, 'score', 0.0)
            })

        return formatted_results

    def _local_schema_search(
        self,
        search_term: str,
        search_type: str = "all",
        limit: int = 10
    ) -> List[Dict[str, Any]]:
        """Local search in schema metadata when knowledge store is not available."""
        if not self.schema_metadata:
            return []

        results = []
        search_term_lower = search_term.lower()

        # Search tables
        if search_type in ["all", "tables"]:
            for table in self.schema_metadata.tables:
                if search_term_lower in table.name.lower():
                    results.append({
                        "type": "table",
                        "name": table.name,
                        "schema": table.schema,
                        "content": self._format_table_for_storage(table),
                        "relevance_score": 1.0
                    })

        # Search columns
        if search_type in ["all", "columns"]:
            for table in self.schema_metadata.tables:
                for col in table.columns:
                    if search_term_lower in col['name'].lower():
                        results.append({
                            "type": "column",
                            "table_name": table.name,
                            "column_name": col['name'],
                            "column_type": col['type'],
                            "table_schema": table.schema,
                            "relevance_score": 0.8
                        })

        return results[:limit]


class SchemaSearchTool(AbstractTool):
    """Tool for searching database schema metadata."""

    name = "schema_search"
    description = "Search for tables, columns, or other database objects in the schema"
    args_schema = SchemaSearchArgs

    def __init__(self, agent: AbstractDBAgent, **kwargs):
        super().__init__(**kwargs)
        self.agent = agent

    async def _execute(
        self,
        search_term: str,
        search_type: str = "all",
        limit: int = 10
    ) -> ToolResult:
        """Search the database schema."""
        try:
            results = await self.agent.search_schema(search_term, search_type, limit)

            return ToolResult(
                status="success",
                result=results,
                metadata={
                    "search_term": search_term,
                    "search_type": search_type,
                    "results_count": len(results)
                }
            )
        except Exception as e:
            return ToolResult(
                status="error",
                result=None,
                error=str(e),
                metadata={"search_term": search_term}
            )


class QueryGenerationTool(AbstractTool):
    """Tool for generating database queries from natural language."""

    name = "generate_query"
    description = "Generate database queries from natural language descriptions"
    args_schema = QueryGenerationArgs

    def __init__(self, agent: AbstractDBAgent, **kwargs):
        super().__init__(**kwargs)
        self.agent = agent

    async def _execute(
        self,
        natural_language_query: str,
        target_tables: Optional[List[str]] = None,
        query_type: str = "SELECT",
        include_explanation: bool = True
    ) -> ToolResult:
        """Generate a database query from natural language."""
        try:
            result = await self.agent.generate_query(
                natural_language_query=natural_language_query,
                target_tables=target_tables,
                query_type=query_type
            )

            if include_explanation:
                # Add explanation using LLM
                explanation_prompt = f"""
                Explain this database query in simple terms:

                Query: {result.get('query', '')}
                Tables involved: {result.get('tables_used', [])}

                Provide a clear explanation of what this query does.
                """

                explanation_response = await self.agent.llm_client.generate_response(
                    prompt=explanation_prompt,
                    model=self.agent.model_name
                )

                result['explanation'] = explanation_response.output

            return ToolResult(
                status="success",
                result=result,
                metadata={
                    "query_type": query_type,
                    "target_tables": target_tables or [],
                    "natural_language_query": natural_language_query
                }
            )
        except Exception as e:
            return ToolResult(
                status="error",
                result=None,
                error=str(e),
                metadata={
                    "natural_language_query": natural_language_query
                }
            )
