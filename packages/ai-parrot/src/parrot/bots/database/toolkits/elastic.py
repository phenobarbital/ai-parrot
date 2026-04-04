"""ElasticToolkit — Elasticsearch DSL query support.

Inherits directly from ``DatabaseToolkit`` since Elasticsearch uses
its own DSL, not SQL.
"""
from __future__ import annotations

import time
from typing import Any, Dict, List, Optional

from ..models import QueryExecutionResponse, TableMetadata
from .base import DatabaseToolkit


class ElasticToolkit(DatabaseToolkit):
    """Elasticsearch toolkit with DSL query support.

    Exposes index search, DSL query generation/execution, and
    aggregation as LLM-callable tools.
    """

    exclude_tools: tuple[str, ...] = (
        "start", "stop", "cleanup", "get_table_metadata", "health_check",
    )

    def __init__(self, dsn: str, **kwargs: Any) -> None:
        super().__init__(dsn=dsn, database_type="elasticsearch", **kwargs)

    def _get_asyncdb_driver(self) -> str:
        return "elasticsearch"

    # ------------------------------------------------------------------
    # Abstract method implementations
    # ------------------------------------------------------------------

    async def search_schema(
        self,
        search_term: str,
        schema_name: Optional[str] = None,
        limit: int = 10,
    ) -> List[TableMetadata]:
        """Search for Elasticsearch indices matching the search term."""
        return await self.search_indices(search_term, limit=limit)

    async def execute_query(
        self,
        query: str,
        limit: int = 1000,
        timeout: int = 30,
    ) -> QueryExecutionResponse:
        """Execute an Elasticsearch DSL query (as JSON string)."""
        import json
        try:
            dsl = json.loads(query) if isinstance(query, str) else query
        except json.JSONDecodeError:
            return QueryExecutionResponse(
                success=False, row_count=0, execution_time_ms=0.0,
                schema_used=self.primary_schema,
                error_message="Invalid JSON DSL query",
            )
        return await self._execute_dsl(dsl, limit=limit, timeout=timeout)

    # ------------------------------------------------------------------
    # ES-specific LLM tools
    # ------------------------------------------------------------------

    async def search_indices(
        self,
        search_term: str,
        limit: int = 10,
    ) -> List[TableMetadata]:
        """Search for Elasticsearch indices matching *search_term*.

        Args:
            search_term: Pattern to match index names.
            limit: Maximum results.

        Returns:
            List of ``TableMetadata`` representing indices.
        """
        if self.cache_partition:
            cached = await self.cache_partition.search_similar_tables(
                self.allowed_schemas, search_term, limit=limit
            )
            if cached:
                return cached

        try:
            if self._connection is None:
                return []
            async with await self._connection.connection() as conn:
                # Use the _cat/indices API via asyncdb
                result, error = await conn.query(f"_cat/indices/{search_term}*?format=json")
                if error or not result:
                    return []
                results: List[TableMetadata] = []
                for idx in result:
                    name = idx.get("index", "") if isinstance(idx, dict) else str(idx)
                    meta = TableMetadata(
                        schema="default",
                        tablename=name,
                        table_type="INDEX",
                        full_name=name,
                        columns=[],
                        primary_keys=["_id"],
                        foreign_keys=[],
                        indexes=[],
                    )
                    if self.cache_partition:
                        await self.cache_partition.store_table_metadata(meta)
                    results.append(meta)
                    if len(results) >= limit:
                        break
                return results
        except Exception as exc:
            self.logger.warning("ES index search failed: %s", exc)
            return []

    async def generate_dsl_query(
        self,
        natural_language: str,
        index: Optional[str] = None,
    ) -> str:
        """Generate context for Elasticsearch DSL query generation.

        Args:
            natural_language: User's question.
            index: Target index name.

        Returns:
            Context string for DSL generation.
        """
        context = f"Generate an Elasticsearch DSL query (JSON) for: {natural_language}"
        if index:
            context += f"\nTarget index: {index}"
        return context

    async def run_aggregation(
        self,
        index: str,
        agg_body: str,
    ) -> QueryExecutionResponse:
        """Run an Elasticsearch aggregation.

        Args:
            index: Target index.
            agg_body: Aggregation JSON body.

        Returns:
            ``QueryExecutionResponse`` with aggregation results.
        """
        import json
        try:
            body = json.loads(agg_body) if isinstance(agg_body, str) else agg_body
        except json.JSONDecodeError:
            return QueryExecutionResponse(
                success=False, row_count=0, execution_time_ms=0.0,
                schema_used=self.primary_schema,
                error_message="Invalid JSON aggregation body",
            )
        body["size"] = 0  # aggregations only
        return await self._execute_dsl(body, index=index, limit=0, timeout=60)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _execute_dsl(
        self,
        dsl: Dict[str, Any],
        index: Optional[str] = None,
        limit: int = 1000,
        timeout: int = 30,
    ) -> QueryExecutionResponse:
        """Execute an Elasticsearch DSL query."""
        import json
        start = time.monotonic()
        try:
            if self._connection is None:
                elapsed = (time.monotonic() - start) * 1000
                return QueryExecutionResponse(
                    success=False, row_count=0, execution_time_ms=elapsed,
                    schema_used=self.primary_schema,
                    error_message="Not connected",
                )
            async with await self._connection.connection() as conn:
                target = index or (self.allowed_schemas[0] if self.allowed_schemas else "*")
                result, error = await conn.query(
                    f"{target}/_search", json.dumps(dsl)
                )
                elapsed = (time.monotonic() - start) * 1000
                if error:
                    return QueryExecutionResponse(
                        success=False, row_count=0, execution_time_ms=elapsed,
                        schema_used=self.primary_schema, error_message=str(error),
                    )
                hits = result.get("hits", {}).get("hits", []) if isinstance(result, dict) else []
                data = [h.get("_source", h) for h in hits]
                if limit and len(data) > limit:
                    data = data[:limit]
                return QueryExecutionResponse(
                    success=True, row_count=len(data), data=data,
                    execution_time_ms=elapsed, schema_used=self.primary_schema,
                )
        except Exception as exc:
            elapsed = (time.monotonic() - start) * 1000
            return QueryExecutionResponse(
                success=False, row_count=0, execution_time_ms=elapsed,
                schema_used=self.primary_schema, error_message=str(exc),
            )
