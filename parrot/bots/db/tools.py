from typing import Any, Dict, List, Optional
from dataclasses import dataclass
from pydantic import Field
from ..abstract import AbstractBot
from ...tools.abstract import (
    AbstractTool,
    ToolResult,
    AbstractToolArgsSchema
)

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

class SchemaSearchTool(AbstractTool):
    """Tool for searching database schema metadata."""

    name = "schema_search"
    description = "Search for tables, columns, or other database objects in the schema"
    args_schema = SchemaSearchArgs

    def __init__(self, agent: AbstractBot, **kwargs):
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

    def __init__(self, agent: AbstractBot, **kwargs):
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

                explanation_response = await self.agent.llm.ask(
                    prompt=explanation_prompt,
                    model=self.agent.llm.model
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
