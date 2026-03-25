"""MongoDB database source for DatabaseToolkit.

Implements ``AbstractDatabaseSource`` for MongoDB using the asyncdb ``mongo``
driver. Overrides ``validate_query()`` with JSON-based validation (filter
documents and aggregation pipelines). Discovers schema via collection listing
and ``$sample`` aggregation for field inference.

This is the base class for ``DocumentDBSource`` and ``AtlasSource``.

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

# Maximum number of documents to sample for field inference
_SAMPLE_SIZE = 100


@register_source("mongo")
class MongoSource(AbstractDatabaseSource):
    """MongoDB database source.

    Uses the asyncdb ``mongo`` driver with JSON-based query validation.
    Supports both filter-only queries and command-style queries.
    """

    driver = "mongo"
    sqlglot_dialect = None  # Non-SQL: custom validation

    def __init__(self) -> None:
        """Initialize MongoSource with a logger."""
        self.logger = logging.getLogger("Parrot.Toolkits.Database.MongoDB")

    async def get_default_credentials(self) -> dict[str, Any]:
        """Return default MongoDB credentials.

        Returns:
            Empty dict (no default MongoDB credentials configured).
        """
        from parrot.interfaces.database import get_default_credentials
        dsn = get_default_credentials("mongo")
        return {"dsn": dsn} if dsn else {}

    async def validate_query(self, query: str) -> ValidationResult:
        """Validate a MongoDB query string (JSON format).

        Accepts:
        - A JSON object (filter document): ``{"status": "active"}``
        - A JSON array of objects (aggregation pipeline):
          ``[{"$match": {...}}, {"$group": {...}}]``

        Args:
            query: JSON string representing a filter or pipeline.

        Returns:
            ValidationResult indicating whether the query is valid JSON
            in the expected format.
        """
        try:
            parsed = json.loads(query)
        except json.JSONDecodeError as exc:
            return ValidationResult(valid=False, error=str(exc), dialect="json")

        if isinstance(parsed, dict):
            return ValidationResult(valid=True, dialect="json")
        if isinstance(parsed, list) and all(isinstance(d, dict) for d in parsed):
            return ValidationResult(valid=True, dialect="json-pipeline")
        return ValidationResult(
            valid=False,
            error="Query must be a JSON object (filter) or array of objects (pipeline)",
            dialect="json",
        )

    def _get_connection(self, credentials: dict[str, Any]) -> AsyncDB:
        """Create a MongoDB AsyncDB connection.

        Args:
            credentials: Connection credentials. Supports ``dsn``, ``params``,
                or individual connection fields.

        Returns:
            AsyncDB instance configured for MongoDB.
        """
        dsn = credentials.get("dsn")
        dbtype = getattr(self, "dbtype", None)
        params = credentials.get("params") or {
            k: v for k, v in credentials.items() if k != "dsn"
        }
        if dbtype and params:
            params["dbtype"] = dbtype
        elif dbtype:
            params = {"dbtype": dbtype}
        return AsyncDB("mongo", dsn=dsn, params=params or None)

    def _infer_type(self, value: Any) -> str:
        """Infer a MongoDB field type string from a Python value.

        Args:
            value: Any Python value from a sampled document.

        Returns:
            Type string (e.g., ``"string"``, ``"int"``, ``"array"``).
        """
        from datetime import datetime
        if isinstance(value, bool):
            return "bool"
        if isinstance(value, int):
            return "int"
        if isinstance(value, float):
            return "double"
        if isinstance(value, str):
            return "string"
        if isinstance(value, list):
            return "array"
        if isinstance(value, dict):
            return "object"
        if isinstance(value, datetime):
            return "date"
        if value is None:
            return "null"
        return "unknown"

    async def get_metadata(
        self,
        credentials: dict[str, Any],
        tables: list[str] | None = None,
    ) -> MetadataResult:
        """Discover MongoDB schema: collections and inferred field types.

        Lists all collection names and uses ``$sample`` to infer field names
        and types from a small sample of documents.

        Args:
            credentials: Connection credentials (including ``database`` key).
            tables: Optional list of collection names to inspect.

        Returns:
            MetadataResult with collections as TableMeta and inferred fields
            as ColumnMeta.
        """
        self.logger.debug("get_metadata called, tables=%s", tables)
        db = self._get_connection(credentials)
        database_name = credentials.get("database", credentials.get("db", ""))

        async with await db.connection() as conn:
            # Get collection names
            try:
                if hasattr(conn, "list_collection_names"):
                    collection_names = await conn.list_collection_names()
                else:
                    # Fallback: use the connection's underlying client
                    client = conn._connection  # type: ignore[attr-defined]
                    db_obj = client[database_name] if database_name else client.get_default_database()
                    collection_names = await db_obj.list_collection_names()
            except Exception as exc:
                self.logger.warning("Could not list collections: %s", exc)
                collection_names = []

            if tables:
                collection_names = [c for c in collection_names if c in tables]

            result_tables = []
            for coll_name in collection_names:
                columns = []
                try:
                    # Sample documents to infer field types
                    sample_pipeline = [{"$sample": {"size": _SAMPLE_SIZE}}]
                    if hasattr(conn, "aggregate"):
                        docs = await conn.aggregate(coll_name, sample_pipeline)
                    else:
                        client = conn._connection  # type: ignore[attr-defined]
                        db_obj = client[database_name] if database_name else client.get_default_database()
                        coll = db_obj[coll_name]
                        cursor = coll.aggregate(sample_pipeline)
                        docs = await cursor.to_list(length=_SAMPLE_SIZE)

                    # Infer field names and types from sampled docs
                    field_types: dict[str, str] = {}
                    for doc in (docs or []):
                        if isinstance(doc, dict):
                            for field, value in doc.items():
                                if field not in field_types:
                                    field_types[field] = self._infer_type(value)

                    for field_name, field_type in field_types.items():
                        columns.append(ColumnMeta(
                            name=field_name,
                            data_type=field_type,
                            nullable=True,
                        ))
                except Exception as exc:
                    self.logger.warning("Could not sample collection %s: %s", coll_name, exc)

                result_tables.append(TableMeta(
                    name=coll_name,
                    schema_name=database_name or None,
                    columns=columns,
                ))

        return MetadataResult(driver=self.driver, tables=result_tables)

    async def query(
        self,
        credentials: dict[str, Any],
        sql: str,
        params: dict[str, Any] | None = None,
    ) -> QueryResult:
        """Execute a MongoDB query (JSON filter or command).

        Supports two query forms:
        - Filter-only: ``{"status": "active"}`` — uses ``collection_name``
          from credentials.
        - Command-style: ``{"find": "users", "filter": {...}, "limit": 10}``

        Args:
            credentials: Connection credentials (must include ``collection_name``
                for filter-only queries, or ``database`` for command-style).
            sql: JSON query string (filter document or command).
            params: Ignored for MongoDB (filters are embedded in the query).

        Returns:
            QueryResult with documents and execution metadata.
        """
        self.logger.debug("query called")
        start = time.monotonic()
        db = self._get_connection(credentials)
        database_name = credentials.get("database", credentials.get("db", ""))
        collection_name = credentials.get("collection_name", credentials.get("collection", ""))

        try:
            query_doc = json.loads(sql)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Invalid MongoDB query JSON: {exc}") from exc

        async with await db.connection() as conn:
            try:
                client = conn._connection  # type: ignore[attr-defined]
                db_obj = client[database_name] if database_name else client.get_default_database()

                if isinstance(query_doc, dict) and ("find" in query_doc or "aggregate" in query_doc):
                    # Command-style query
                    result = await db_obj.command(query_doc)
                    docs = result.get("cursor", {}).get("firstBatch", [])
                elif isinstance(query_doc, list):
                    # Aggregation pipeline
                    coll = db_obj[collection_name]
                    cursor = coll.aggregate(query_doc)
                    docs = await cursor.to_list(length=None)
                else:
                    # Simple filter
                    coll = db_obj[collection_name]
                    cursor = coll.find(query_doc)
                    docs = await cursor.to_list(length=None)
            except Exception as exc:
                self.logger.error("MongoDB query error: %s", exc)
                raise

        elapsed_ms = (time.monotonic() - start) * 1000
        # Convert ObjectId and other non-serializable types to strings
        rows_list = []
        for doc in (docs or []):
            if isinstance(doc, dict):
                rows_list.append({k: str(v) if not isinstance(v, (str, int, float, bool, type(None))) else v
                                  for k, v in doc.items()})
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
        """Execute a MongoDB query and return a single document.

        Args:
            credentials: Connection credentials.
            sql: JSON filter document.
            params: Ignored for MongoDB.

        Returns:
            RowResult with a single document or found=False.
        """
        self.logger.debug("query_row called")
        start = time.monotonic()
        db = self._get_connection(credentials)
        database_name = credentials.get("database", credentials.get("db", ""))
        collection_name = credentials.get("collection_name", credentials.get("collection", ""))

        try:
            query_doc = json.loads(sql)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Invalid MongoDB query JSON: {exc}") from exc

        async with await db.connection() as conn:
            try:
                client = conn._connection  # type: ignore[attr-defined]
                db_obj = client[database_name] if database_name else client.get_default_database()
                coll = db_obj[collection_name]
                doc = await coll.find_one(query_doc if isinstance(query_doc, dict) else {})
            except Exception as exc:
                self.logger.error("MongoDB query_row error: %s", exc)
                raise

        elapsed_ms = (time.monotonic() - start) * 1000
        row_dict = None
        if doc and isinstance(doc, dict):
            row_dict = {k: str(v) if not isinstance(v, (str, int, float, bool, type(None))) else v
                        for k, v in doc.items()}

        return RowResult(
            driver=self.driver,
            row=row_dict,
            found=row_dict is not None,
            execution_time_ms=round(elapsed_ms, 3),
        )
