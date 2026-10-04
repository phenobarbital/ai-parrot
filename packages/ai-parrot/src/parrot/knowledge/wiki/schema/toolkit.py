"""SchemaPlaneToolkit — the four schema-plane reads for any ai-parrot agent (FEAT-600 M5)."""

from __future__ import annotations

from typing import Any

from parrot.knowledge.wiki.schema.service import SchemaPlaneService
from parrot.tools.toolkit import AbstractToolkit


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
