"""Elasticsearch/OpenSearch database source for DatabaseToolkit.

Implements ``AbstractDatabaseSource`` for Elasticsearch and OpenSearch using
the asyncdb ``elastic`` driver. Overrides ``validate_query()`` with JSON DSL
validation. Discovers schema via index mappings API.

Single source for both Elasticsearch and OpenSearch — behavior differences
are handled by the asyncdb driver.

Part of FEAT-062 — DatabaseToolkit.
"""
from __future__ import annotations

import json
import logging
import time
from typing import Any

from asyncdb import AsyncDB

from parrot.tools.database.base import (
    AbstractDatabaseSource,
    ColumnMeta,
    MetadataResult,
    QueryResult,
    RowResult,
    TableMeta,
    ValidationResult,
)
from parrot.tools.database.sources import register_source

# Valid top-level keys for an Elasticsearch/OpenSearch query body
_VALID_ES_KEYS: frozenset[str] = frozenset({
    "query", "aggs", "aggregations", "size", "from", "sort",
    "_source", "highlight", "post_filter", "suggest", "script_fields",
    "stored_fields", "docvalue_fields", "explain", "version",
    "track_total_hits", "timeout", "terminate_after",
})


@register_source("elastic")
class ElasticSource(AbstractDatabaseSource):
    """Elasticsearch/OpenSearch database source.

    Validates queries as JSON DSL bodies containing recognized
    Elasticsearch query keys. Discovers schema via index ``_mapping`` API.
    Works with both Elasticsearch and OpenSearch (asyncdb handles differences).
    """

    driver = "elastic"
    sqlglot_dialect = None  # Non-SQL: JSON DSL

    def __init__(self) -> None:
        """Initialize ElasticSource with a logger."""
        self.logger = logging.getLogger("Parrot.Toolkits.Database.Elasticsearch")

    async def get_default_credentials(self) -> dict[str, Any]:
        """Return default Elasticsearch credentials.

        Returns:
            Empty dict (no default Elasticsearch credentials configured).
        """
        from parrot.interfaces.database import get_default_credentials
        dsn = get_default_credentials("elastic")
        return {"dsn": dsn} if dsn else {}

    async def validate_query(self, query: str) -> ValidationResult:
        """Validate an Elasticsearch/OpenSearch JSON DSL query body.

        The query must be a JSON object containing at least one recognized
        Elasticsearch query key (``query``, ``aggs``, ``size``, etc.).

        Args:
            query: JSON string representing an Elasticsearch query body.

        Returns:
            ValidationResult with dialect ``"json-dsl"``.
        """
        try:
            parsed = json.loads(query)
        except json.JSONDecodeError as exc:
            return ValidationResult(valid=False, error=str(exc), dialect="json-dsl")

        if not isinstance(parsed, dict):
            return ValidationResult(
                valid=False,
                error="Elasticsearch query must be a JSON object",
                dialect="json-dsl",
            )
        if not (parsed.keys() & _VALID_ES_KEYS):
            return ValidationResult(
                valid=False,
                error=f"Query must contain at least one of: {sorted(_VALID_ES_KEYS)}",
                dialect="json-dsl",
            )
        return ValidationResult(valid=True, dialect="json-dsl")

    async def get_metadata(
        self,
        credentials: dict[str, Any],
        tables: list[str] | None = None,
    ) -> MetadataResult:
        """Discover Elasticsearch schema via index mappings.

        Returns index names as TableMeta and field properties (type, etc.)
        as ColumnMeta, derived from the ``_mapping`` API response.

        Args:
            credentials: Connection credentials (host, port, auth).
            tables: Optional list of index names (patterns) to inspect.

        Returns:
            MetadataResult with indices as tables and field mappings as columns.
        """
        self.logger.debug("get_metadata called, tables=%s", tables)
        dsn = credentials.get("dsn")
        params = {k: v for k, v in credentials.items() if k != "dsn"} or None

        db = AsyncDB("elastic", dsn=dsn, params=params)
        result_tables = []

        async with await db.connection() as conn:
            try:
                # Get index mappings
                if hasattr(conn, "get_mappings"):
                    index_pattern = ",".join(tables) if tables else "*"
                    mappings = await conn.get_mappings(index_pattern)
                elif hasattr(conn, "_connection"):
                    client = conn._connection  # type: ignore[attr-defined]
                    index_pattern = ",".join(tables) if tables else "*"
                    response = await client.indices.get_mapping(index=index_pattern)
                    mappings = dict(response)
                else:
                    mappings = {}

                for index_name, mapping_data in mappings.items():
                    if index_name.startswith("."):
                        continue  # Skip system indices
                    columns = []
                    props = (
                        mapping_data.get("mappings", {}).get("properties", {})
                        or mapping_data.get("properties", {})
                    )
                    for field_name, field_props in props.items():
                        col = ColumnMeta(
                            name=field_name,
                            data_type=field_props.get("type", "object"),
                            nullable=True,
                        )
                        columns.append(col)
                    result_tables.append(TableMeta(
                        name=index_name,
                        columns=columns,
                    ))
            except Exception as exc:
                self.logger.warning("Could not get index mappings: %s", exc)

        return MetadataResult(driver=self.driver, tables=result_tables)

    async def query(
        self,
        credentials: dict[str, Any],
        sql: str,
        params: dict[str, Any] | None = None,
    ) -> QueryResult:
        """Execute an Elasticsearch JSON DSL query and return all hits.

        Args:
            credentials: Connection credentials. Include ``index`` for the
                target index name.
            sql: JSON DSL query body string.
            params: Ignored (query is embedded in the JSON body).

        Returns:
            QueryResult with document hits and execution metadata.
        """
        self.logger.debug("query called")
        start = time.monotonic()
        dsn = credentials.get("dsn")
        index = credentials.get("index", credentials.get("table", "_all"))
        conn_params = {k: v for k, v in credentials.items() if k not in ("dsn", "index", "table")} or None

        try:
            query_body = json.loads(sql)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Invalid Elasticsearch JSON DSL: {exc}") from exc

        db = AsyncDB("elastic", dsn=dsn, params=conn_params)
        async with await db.connection() as conn:
            try:
                client = conn._connection  # type: ignore[attr-defined]
                response = await client.search(index=index, body=query_body)
                hits = response.get("hits", {}).get("hits", [])
                docs = [hit.get("_source", {}) for hit in hits]
            except Exception as exc:
                self.logger.error("Elasticsearch query error: %s", exc)
                raise

        elapsed_ms = (time.monotonic() - start) * 1000
        rows_list = [d if isinstance(d, dict) else {} for d in (docs or [])]
        columns = list(rows_list[0].keys()) if rows_list else []

        return QueryResult(
            driver=self.driver,
            rows=rows_list,
            row_count=len(rows_list),
            columns=columns,
            execution_time_ms=round(elapsed_ms, 3),
        )

    async def query_row(
        self,
        credentials: dict[str, Any],
        sql: str,
        params: dict[str, Any] | None = None,
    ) -> RowResult:
        """Execute an Elasticsearch JSON DSL query and return the first hit.

        Args:
            credentials: Connection credentials.
            sql: JSON DSL query body string.
            params: Ignored.

        Returns:
            RowResult with the first document hit or found=False.
        """
        self.logger.debug("query_row called")
        start = time.monotonic()
        dsn = credentials.get("dsn")
        index = credentials.get("index", credentials.get("table", "_all"))
        conn_params = {k: v for k, v in credentials.items() if k not in ("dsn", "index", "table")} or None

        try:
            query_body = json.loads(sql)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Invalid Elasticsearch JSON DSL: {exc}") from exc

        # Limit to 1 result
        query_body["size"] = 1

        db = AsyncDB("elastic", dsn=dsn, params=conn_params)
        async with await db.connection() as conn:
            try:
                client = conn._connection  # type: ignore[attr-defined]
                response = await client.search(index=index, body=query_body)
                hits = response.get("hits", {}).get("hits", [])
                doc = hits[0].get("_source", {}) if hits else None
            except Exception as exc:
                self.logger.error("Elasticsearch query_row error: %s", exc)
                raise

        elapsed_ms = (time.monotonic() - start) * 1000

        return RowResult(
            driver=self.driver,
            row=doc if isinstance(doc, dict) else None,
            found=doc is not None,
            execution_time_ms=round(elapsed_ms, 3),
        )
