"""InfluxDBToolkit — InfluxDB Flux query support.

Inherits directly from ``DatabaseToolkit`` (not ``SQLToolkit``) since
InfluxDB uses Flux query language, not SQL.
"""
from __future__ import annotations

import time
from typing import Any, Dict, List, Optional

from ..models import QueryExecutionResponse, TableMetadata
from .base import DatabaseToolkit


class InfluxDBToolkit(DatabaseToolkit):
    """InfluxDB toolkit with Flux query language support.

    Exposes measurement search, Flux query generation/execution, and
    bucket exploration as LLM-callable tools.
    """

    exclude_tools: tuple[str, ...] = (
        "start", "stop", "cleanup", "get_table_metadata", "health_check",
    )

    def __init__(
        self,
        dsn: str,
        org: str = "default",
        allowed_schemas: Optional[List[str]] = None,
        **kwargs: Any,
    ) -> None:
        self.org = org
        super().__init__(
            dsn=dsn,
            allowed_schemas=allowed_schemas or ["default"],
            database_type="influxdb",
            **kwargs,
        )

    def _get_asyncdb_driver(self) -> str:
        return "influx"

    # ------------------------------------------------------------------
    # Abstract method implementations
    # ------------------------------------------------------------------

    async def search_schema(
        self,
        search_term: str,
        schema_name: Optional[str] = None,
        limit: int = 10,
    ) -> List[TableMetadata]:
        """Search for InfluxDB measurements matching the search term.

        Args:
            search_term: Measurement name pattern.
            schema_name: Bucket name (optional).
            limit: Maximum results.

        Returns:
            List of ``TableMetadata`` representing measurements.
        """
        return await self.search_measurements(search_term, bucket=schema_name, limit=limit)

    async def execute_query(
        self,
        query: str,
        limit: int = 1000,
        timeout: int = 30,
    ) -> QueryExecutionResponse:
        """Execute a Flux query.

        Args:
            query: Flux query string.
            limit: Maximum rows.
            timeout: Timeout in seconds.

        Returns:
            ``QueryExecutionResponse`` with results.
        """
        return await self.execute_flux_query(query, limit=limit, timeout=timeout)

    # ------------------------------------------------------------------
    # InfluxDB-specific LLM tools
    # ------------------------------------------------------------------

    async def search_measurements(
        self,
        search_term: str,
        bucket: Optional[str] = None,
        limit: int = 10,
    ) -> List[TableMetadata]:
        """Search for InfluxDB measurements matching *search_term*.

        Args:
            search_term: Pattern to match measurement names.
            bucket: Restrict to a specific bucket.
            limit: Maximum results.

        Returns:
            List of ``TableMetadata`` representing measurements.
        """
        # Cache-first
        if self.cache_partition:
            target = [bucket] if bucket else self.allowed_schemas
            cached = await self.cache_partition.search_similar_tables(
                target, search_term, limit=limit
            )
            if cached:
                return cached

        # Query InfluxDB for measurement names
        target_bucket = bucket or (self.allowed_schemas[0] if self.allowed_schemas else "default")
        flux = (
            f'import "influxdata/influxdb/schema"\n'
            f'schema.measurements(bucket: "{target_bucket}")'
        )
        try:
            if self._connection is None:
                return []
            async with await self._connection.connection() as conn:
                result, error = await conn.query(flux)
                if error or not result:
                    return []

                results: List[TableMetadata] = []
                for row in result:
                    name = row.get("_value", "") if isinstance(row, dict) else str(row)
                    if search_term.lower() in name.lower():
                        meta = TableMetadata(
                            schema=target_bucket,
                            tablename=name,
                            table_type="MEASUREMENT",
                            full_name=f"{target_bucket}.{name}",
                            columns=[],
                            primary_keys=["_time"],
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
            self.logger.warning("InfluxDB measurement search failed: %s", exc)
            return []

    async def generate_flux_query(
        self,
        natural_language: str,
        bucket: Optional[str] = None,
        measurement: Optional[str] = None,
    ) -> str:
        """Generate context for Flux query generation.

        Args:
            natural_language: User's question in plain English.
            bucket: Target bucket.
            measurement: Target measurement.

        Returns:
            Context string for Flux query generation.
        """
        target_bucket = bucket or (self.allowed_schemas[0] if self.allowed_schemas else "default")
        context = f'Generate a Flux query for: {natural_language}\n\nBucket: "{target_bucket}"'
        if measurement:
            context += f'\nMeasurement: "{measurement}"'
        return context

    async def execute_flux_query(
        self,
        query: str,
        limit: int = 1000,
        timeout: int = 30,
    ) -> QueryExecutionResponse:
        """Execute a Flux query and return results.

        Args:
            query: Flux query string.
            limit: Max rows.
            timeout: Timeout seconds.

        Returns:
            ``QueryExecutionResponse``.
        """
        start = time.monotonic()
        try:
            if self._connection is None:
                elapsed = (time.monotonic() - start) * 1000
                return QueryExecutionResponse(
                    success=False, row_count=0, execution_time_ms=elapsed,
                    schema_used=self.primary_schema,
                    error_message="Not connected (call start() first)",
                )
            async with await self._connection.connection() as conn:
                result, error = await conn.query(query)
                elapsed = (time.monotonic() - start) * 1000
                if error:
                    return QueryExecutionResponse(
                        success=False, row_count=0, execution_time_ms=elapsed,
                        schema_used=self.primary_schema, error_message=str(error),
                    )
                data = [dict(row) for row in result] if result else []
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

    async def explore_buckets(self) -> List[str]:
        """List available InfluxDB buckets.

        Returns:
            List of bucket names.
        """
        flux = 'buckets()'
        try:
            if self._connection is None:
                return []
            async with await self._connection.connection() as conn:
                result, error = await conn.query(flux)
                if error or not result:
                    return []
                return [
                    row.get("name", str(row)) if isinstance(row, dict) else str(row)
                    for row in result
                ]
        except Exception as exc:
            self.logger.warning("Failed to list buckets: %s", exc)
            return []
