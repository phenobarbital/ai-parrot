"""DocumentDBToolkit — MongoDB Query Language (MQL) support.

Inherits directly from ``DatabaseToolkit`` since DocumentDB/MongoDB
uses its own query language, not SQL.
"""
from __future__ import annotations

import time
from typing import Any, Dict, List, Optional

from ..models import QueryExecutionResponse, TableMetadata
from .base import DatabaseToolkit


class DocumentDBToolkit(DatabaseToolkit):
    """DocumentDB/MongoDB toolkit with MQL support.

    Exposes collection search, MQL query generation/execution, and
    collection exploration as LLM-callable tools.
    """

    exclude_tools: tuple[str, ...] = (
        "start", "stop", "cleanup", "get_table_metadata", "health_check",
    )

    def __init__(self, dsn: str, database_name: str = "default", **kwargs: Any) -> None:
        self.database_name = database_name
        super().__init__(dsn=dsn, database_type="documentdb", **kwargs)

    def _get_asyncdb_driver(self) -> str:
        return "motor"

    # ------------------------------------------------------------------
    # Abstract method implementations
    # ------------------------------------------------------------------

    async def search_schema(
        self,
        search_term: str,
        schema_name: Optional[str] = None,
        limit: int = 10,
    ) -> List[TableMetadata]:
        """Search for collections matching the search term."""
        return await self.search_collections(search_term, database=schema_name, limit=limit)

    async def execute_query(
        self,
        query: str,
        limit: int = 1000,
        timeout: int = 30,
    ) -> QueryExecutionResponse:
        """Execute a MongoDB query (JSON string)."""
        import json
        start = time.monotonic()
        try:
            cmd = json.loads(query) if isinstance(query, str) else query
        except json.JSONDecodeError:
            return QueryExecutionResponse(
                success=False, row_count=0, execution_time_ms=0.0,
                schema_used=self.primary_schema,
                error_message="Invalid JSON MQL query",
            )
        try:
            if self._connection is None:
                elapsed = (time.monotonic() - start) * 1000
                return QueryExecutionResponse(
                    success=False, row_count=0, execution_time_ms=elapsed,
                    schema_used=self.primary_schema,
                    error_message="Not connected",
                )
            async with await self._connection.connection() as conn:
                result, error = await conn.query(json.dumps(cmd))
                elapsed = (time.monotonic() - start) * 1000
                if error:
                    return QueryExecutionResponse(
                        success=False, row_count=0, execution_time_ms=elapsed,
                        schema_used=self.primary_schema, error_message=str(error),
                    )
                data = list(result) if result else []
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

    # ------------------------------------------------------------------
    # DocumentDB-specific LLM tools
    # ------------------------------------------------------------------

    async def search_collections(
        self,
        search_term: str,
        database: Optional[str] = None,
        limit: int = 10,
    ) -> List[TableMetadata]:
        """Search for MongoDB/DocumentDB collections matching *search_term*.

        Args:
            search_term: Pattern to match collection names.
            database: Restrict to a specific database.
            limit: Maximum results.

        Returns:
            List of ``TableMetadata`` representing collections.
        """
        if self.cache_partition:
            target = [database] if database else self.allowed_schemas
            cached = await self.cache_partition.search_similar_tables(
                target, search_term, limit=limit
            )
            if cached:
                return cached

        try:
            if self._connection is None:
                return []
            async with await self._connection.connection() as conn:
                # List collections
                result, error = await conn.query("listCollections")
                if error or not result:
                    return []
                results: List[TableMetadata] = []
                db = database or self.database_name
                for coll in result:
                    name = coll.get("name", str(coll)) if isinstance(coll, dict) else str(coll)
                    if search_term.lower() in name.lower():
                        meta = TableMetadata(
                            schema=db,
                            tablename=name,
                            table_type="COLLECTION",
                            full_name=f"{db}.{name}",
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
            self.logger.warning("Collection search failed: %s", exc)
            return []

    async def generate_mql_query(
        self,
        natural_language: str,
        collection: Optional[str] = None,
    ) -> str:
        """Generate context for MongoDB query generation.

        Args:
            natural_language: User's question.
            collection: Target collection name.

        Returns:
            Context string for MQL generation.
        """
        context = f"Generate a MongoDB query (JSON) for: {natural_language}"
        if collection:
            context += f"\nTarget collection: {collection}"
        context += f"\nDatabase: {self.database_name}"
        return context

    async def explore_collection(
        self,
        collection: str,
        sample_size: int = 5,
    ) -> str:
        """Explore a collection's structure by sampling documents.

        Args:
            collection: Collection name.
            sample_size: Number of documents to sample.

        Returns:
            String describing the collection's field structure.
        """
        import json
        try:
            if self._connection is None:
                return "Not connected."
            cmd = json.dumps({"find": collection, "limit": sample_size})
            async with await self._connection.connection() as conn:
                result, error = await conn.query(cmd)
                if error or not result:
                    return f"Could not explore collection: {error or 'no data'}"
                # Analyze field structure
                fields: Dict[str, set] = {}
                docs = list(result)[:sample_size]
                for doc in docs:
                    if isinstance(doc, dict):
                        for key, val in doc.items():
                            if key not in fields:
                                fields[key] = set()
                            fields[key].add(type(val).__name__)
                lines = [f"Collection: {collection} ({len(docs)} sampled)"]
                for field_name, types in sorted(fields.items()):
                    lines.append(f"  {field_name}: {', '.join(sorted(types))}")
                return "\n".join(lines)
        except Exception as exc:
            return f"Error exploring collection: {exc}"
