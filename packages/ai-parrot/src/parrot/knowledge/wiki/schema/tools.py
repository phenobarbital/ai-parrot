"""Schema-plane MCP tools — read-only, one action per tool (FEAT-600 M5)."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

from pydantic import BaseModel, Field

from parrot.knowledge.wiki.project import WikiProjectConfig
from parrot.knowledge.wiki.schema.models import LookupResult
from parrot.knowledge.wiki.schema.service import SchemaPlaneService
from parrot.knowledge.wiki.store import BaseWikiStore
from parrot.tools.abstract import AbstractTool, ToolResult


class SchemaLookupInput(BaseModel):
    """Arguments for ``wiki_schema_lookup``."""

    ref: str = Field(
        ...,
        description="table:<origin>/<schema>.<table>, bare <origin>:<schema>.<table>, or <schema>.<table>",
    )


class SchemaSearchInput(BaseModel):
    """Arguments for ``wiki_schema_search``."""

    query: str = Field(..., description="Words to match in table names, column names and comments")
    limit: int = Field(default=20, ge=1, le=100)


class SchemaNeighborsInput(BaseModel):
    """Arguments for ``wiki_schema_neighbors``."""

    ref: str = Field(..., description="Table reference (same forms as lookup)")
    depth: int = Field(default=1, ge=1, le=4)


class SchemaSourcesInput(BaseModel):
    """Arguments for ``wiki_schema_sources``."""


class _SchemaTool(AbstractTool):
    """Shared plumbing for read-only schema-plane tools."""

    def __init__(self, service: SchemaPlaneService) -> None:
        super().__init__(name=self.name, description=self.description)
        self._service = service

    async def _guard(self, coro: Any) -> ToolResult:
        """Run a service operation and normalize expected lookup errors."""
        try:
            return ToolResult(result=await coro)
        except (KeyError, ValueError) as exc:
            return ToolResult(success=False, status="error", result=None, error=str(exc))


def _lookup_text(result: LookupResult) -> str:
    """Render a compact lookup response containing DDL and its columns."""
    columns = ["| Column | Type | Nullable |", "| --- | --- | --- |"]
    columns.extend(
        f"| {column.name} | {column.data_type} | {'yes' if column.nullable else 'no'} |" for column in result.columns
    )
    return f"## DDL\n\n{result.ddl}\n\n## Columns\n\n" + "\n".join(columns)


class WikiSchemaLookupTool(_SchemaTool):
    """Look up one table in the schema plane: DDL, columns, relations, annotations, age and staleness."""

    name = "wiki_schema_lookup"
    description = __doc__
    args_schema = SchemaLookupInput

    async def _execute(self, ref: str) -> ToolResult:
        """Look up one table reference without database introspection."""
        result = await self._guard(self._service.lookup(ref))
        if isinstance(result.result, list):
            result.status = "ambiguous"
            result.result = {"candidates": result.result}
        elif result.success and isinstance(result.result, LookupResult):
            payload = result.result.model_dump(mode="json")
            payload["text"] = _lookup_text(result.result)
            result.result = payload
        return result


class WikiSchemaSearchTool(_SchemaTool):
    """Full-text search over table names, column names and comments in the schema plane."""

    name = "wiki_schema_search"
    description = __doc__
    args_schema = SchemaSearchInput

    async def _execute(self, query: str, limit: int = 20) -> ToolResult:
        """Search stored schema records."""
        return await self._guard(self._service.search(query, limit=limit))


class WikiSchemaNeighborsTool(_SchemaTool):
    """Foreign-key join paths from a table, up to `depth` hops, each with the (src_column -> dst_column) pair."""

    name = "wiki_schema_neighbors"
    description = __doc__
    args_schema = SchemaNeighborsInput

    async def _execute(self, ref: str, depth: int = 1) -> ToolResult:
        """Return foreign-key paths from a table."""
        return await self._guard(self._service.neighbors(ref, depth=depth))


class WikiSchemaSourcesTool(_SchemaTool):
    """List the declared SQL sources (alias, dialect, schemas). DSNs are never exposed — only env-var names."""

    name = "wiki_schema_sources"
    description = __doc__
    args_schema = SchemaSourcesInput

    async def _execute(self) -> ToolResult:
        """List configured schema sources without resolving their DSNs."""
        return await self._guard(self._service.sources())


def create_schema_tools(
    store: BaseWikiStore,
    root: Optional[Path],
    config: WikiProjectConfig,
    service: Optional[SchemaPlaneService] = None,
) -> list[AbstractTool]:
    """Return the four read tools bound to ``service``; ``[]`` when no plane is available."""
    if service is None or not config.schema.enabled:
        return []
    return [
        WikiSchemaLookupTool(service),
        WikiSchemaSearchTool(service),
        WikiSchemaNeighborsTool(service),
        WikiSchemaSourcesTool(service),
    ]
