"""
Database Agent Architecture for AI-Parrot.

This module provides an abstract base for database introspection agents
that can analyze database schemas and generate queries from natural language.
"""

from abc import abstractmethod
from typing import Dict, Any, List, Optional, Union
import json
import asyncio
from sqlalchemy.ext.asyncio import AsyncEngine
from ..abstract import AbstractBot
from ...tools.manager import (
    ToolManager,
)
from ...stores.abstract import AbstractStore
from .prompts import DB_AGENT_PROMPT, BASIC_HUMAN_PROMPT
from .tools import (
    SchemaSearchTool,
    QueryGenerationTool,
    DatabaseSchema,
    TableMetadata,
)
from ...tools.asdb import DatabaseQueryTool


class AbstractDBAgent(AbstractBot):
    """
    Abstract base class for database introspection agents.

    This agent analyzes database schemas, stores metadata in a knowledge base,
    and generates queries from natural language descriptions.
    """
    system_prompt_template: str = DB_AGENT_PROMPT
    human_prompt_template = BASIC_HUMAN_PROMPT

    def __init__(
        self,
        name: str = "DatabaseAgent",
        credentials: Union[str, Dict[str, Any]] = None,
        schema_name: Optional[str] = None,
        knowledge_store: AbstractStore = None,
        auto_analyze_schema: bool = True,
        **kwargs
    ):
        """
        Initialize the database agent.

        Args:
            name: Agent name
            credentials: Database connection credentials
            schema_name: Target schema name (optional)
            knowledge_store: Vector store for schema metadata
            auto_analyze_schema: Whether to automatically analyze schema on init
        """
        super().__init__(name=name, **kwargs)

        self.credentials = credentials
        self.schema_name = schema_name
        self.knowledge_store = knowledge_store
        self.auto_analyze_schema = auto_analyze_schema

        # Initialize database-specific components
        self.engine: Optional[AsyncEngine] = None
        self.schema_metadata: Optional[DatabaseSchema] = None

        # Initialize tool manager
        self.tool_manager = ToolManager(
            logger=self.logger,
            debug=self._debug
        )

        # Add database-specific tools
        self._setup_database_tools()
        try:
            self.loop = asyncio.get_running_loop()
        except RuntimeError:
            self.loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self.loop)

        # if self.auto_analyze_schema and self.connection_string:
        #    asyncio.create_task(self.initialize_schema())

    async def initialize_schema(self):
        """Initialize database connection and analyze schema."""
        try:
            # first: configure the agent:
            await self.configure()
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

        # Add database query tool
        db_query_tool = DatabaseQueryTool(agent=self)
        self.tool_manager.register_tool(db_query_tool)

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
