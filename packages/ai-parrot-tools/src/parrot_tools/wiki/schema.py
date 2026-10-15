"""Schema plane tools and toolkit (moved from parrot.knowledge.wiki.schema — FEAT-540 M3)."""

from __future__ import annotations

from parrot.knowledge.wiki.project import WikiProjectConfig
from parrot.knowledge.wiki.schema.operations import (
    SchemaLookupInput,
    SchemaNeighborsInput,
    SchemaSearchInput,
    SchemaSourcesInput,
    op_schema_lookup,
    op_schema_neighbors,
    op_schema_search,
    op_schema_sources,
)
from parrot.knowledge.wiki.schema.service import SchemaPlaneService
from parrot.knowledge.wiki.store import BaseWikiStore
from parrot.tools.abstract import (
    AbstractTool,
    ToolResult,
)
from parrot.tools.toolkit import AbstractToolkit
from pathlib import Path
from typing import (
    Any,
    Optional,
)


class _SchemaTool(AbstractTool):
    """Shared plumbing for read-only schema-plane tools."""

    def __init__(self, service: SchemaPlaneService) -> None:
        super().__init__(name=self.name, description=self.description)
        self._service = service


class WikiSchemaLookupTool(_SchemaTool):
    """Look up one table in the schema plane: DDL, columns, relations, annotations, age and staleness."""

    name = "wiki_schema_lookup"
    description = __doc__
    args_schema = SchemaLookupInput

    def __init__(self, service: SchemaPlaneService, annotation_store: Optional[BaseWikiStore] = None) -> None:
        super().__init__(service)
        self._annotation_store = annotation_store

    async def _execute(self, ref: str) -> ToolResult:
        """Look up one table reference without database introspection."""
        result = await op_schema_lookup(
            None, SchemaLookupInput(ref=ref), service=self._service, annotation_store=self._annotation_store
        )
        if result.is_error:
            return ToolResult(success=False, status="error", result=None, error=result.text)
        assert result.data is not None
        status = result.data.pop("status", None)
        if status is None:
            return ToolResult(result=result.data)
        return ToolResult(result=result.data, status=status)


class WikiSchemaSearchTool(_SchemaTool):
    """Full-text search over table names, column names and comments in the schema plane."""

    name = "wiki_schema_search"
    description = __doc__
    args_schema = SchemaSearchInput

    async def _execute(self, query: str, limit: int = 20) -> ToolResult:
        """Search stored schema records."""
        result = await op_schema_search(None, SchemaSearchInput(query=query, limit=limit), service=self._service)
        if result.is_error:
            return ToolResult(success=False, status="error", result=None, error=result.text)
        assert result.data is not None
        return ToolResult(result=result.data["result"])


class WikiSchemaNeighborsTool(_SchemaTool):
    """Foreign-key join paths from a table, up to `depth` hops, each with the (src_column -> dst_column) pair."""

    name = "wiki_schema_neighbors"
    description = __doc__
    args_schema = SchemaNeighborsInput

    async def _execute(self, ref: str, depth: int = 1) -> ToolResult:
        """Return foreign-key paths from a table."""
        result = await op_schema_neighbors(None, SchemaNeighborsInput(ref=ref, depth=depth), service=self._service)
        if result.is_error:
            return ToolResult(success=False, status="error", result=None, error=result.text)
        assert result.data is not None
        return ToolResult(result=result.data["result"])


class WikiSchemaSourcesTool(_SchemaTool):
    """List the declared SQL sources (alias, dialect, schemas). DSNs are never exposed — only env-var names."""

    name = "wiki_schema_sources"
    description = __doc__
    args_schema = SchemaSourcesInput

    async def _execute(self) -> ToolResult:
        """List configured schema sources without resolving their DSNs."""
        result = await op_schema_sources(None, SchemaSourcesInput(), service=self._service)
        if result.is_error:
            return ToolResult(success=False, status="error", result=None, error=result.text)
        assert result.data is not None
        return ToolResult(result=result.data["result"])


def create_schema_tools(
    store: BaseWikiStore,
    root: Optional[Path],
    config: WikiProjectConfig,
    service: Optional[SchemaPlaneService] = None,
) -> list[AbstractTool]:
    """Return the four read tools bound to ``service``; ``[]`` when no plane is available."""
    if service is None or not config.schema_plane.enabled:
        return []
    return [
        WikiSchemaLookupTool(service, annotation_store=store),
        WikiSchemaSearchTool(service),
        WikiSchemaNeighborsTool(service),
        WikiSchemaSourcesTool(service),
    ]


class SchemaPlaneToolkit(AbstractToolkit):
    """Read-only access to the SQL schema plane: lookup, search, neighbors, and sources."""

    tool_prefix = "schema"

    def __init__(self, service: SchemaPlaneService, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._service = service

    async def lookup(self, ref: str) -> dict[str, Any]:
        """Look up one table (DDL, columns, relations, annotations, age, stale)."""
        result = await self._service.lookup(ref)
        return {"candidates": result} if isinstance(result, list) else result.model_dump(mode="json")

    async def search(self, query: str, limit: int = 20) -> list[dict[str, Any]]:
        """Full-text search over table names, column names and comments."""
        return await self._service.search(query, limit=limit)

    async def neighbors(self, ref: str, depth: int = 1) -> list[dict[str, Any]]:
        """Foreign-key join paths from a table up to ``depth`` hops."""
        return await self._service.neighbors(ref, depth=depth)

    async def sources(self) -> list[dict[str, Any]]:
        """Declared SQL sources (alias, dialect, schemas, and DSN env-var name)."""
        return [source.model_dump(mode="json") for source in await self._service.sources()]
