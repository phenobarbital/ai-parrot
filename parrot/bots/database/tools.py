from pydantic import Field
from ..abstract import AbstractBot
from ...tools.abstract import (
    AbstractTool,
    ToolResult,
    AbstractToolArgsSchema
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
