"""InfluxDB time-series database source for DatabaseToolkit.

Implements ``AbstractDatabaseSource`` for InfluxDB using the asyncdb ``influx``
driver with Flux query language. Overrides ``validate_query()`` with Flux
pattern-based validation. Discovers schema by listing buckets and field keys.

Part of FEAT-062 — DatabaseToolkit.
"""
from __future__ import annotations

import logging
import re
import time
from typing import Any

from parrot.tools.databasequery.base import (
    AbstractDatabaseSource,
    ColumnMeta,
    MetadataResult,
    QueryResult,
    RowResult,
    TableMeta,
    ValidationResult,
)
from parrot.tools.databasequery.sources import register_source

# Pattern to detect the mandatory from(bucket:...) clause in Flux queries
_FLUX_FROM_PATTERN = re.compile(r"from\s*\(\s*bucket\s*:", re.IGNORECASE)


@register_source("influx")
class InfluxSource(AbstractDatabaseSource):
    """InfluxDB time-series database source.

    Uses Flux query language (InfluxDB v2+). Validates queries by checking
    for the required ``from(bucket:...)`` clause. Discovers schema by
    listing buckets and field keys.
    """

    driver = "influx"
    sqlglot_dialect = None  # Non-SQL: Flux query language

    def __init__(self) -> None:
        """Initialize InfluxSource with a logger."""
        self.logger = logging.getLogger("Parrot.Toolkits.Database.InfluxDB")

    async def get_default_credentials(self) -> dict[str, Any]:
        """Return default InfluxDB credentials.

        Returns:
            Empty dict (no default InfluxDB credentials configured).
        """
        from parrot.interfaces.database import get_default_credentials
        dsn = get_default_credentials("influx")
        return {"dsn": dsn} if dsn else {}

    async def validate_query(self, query: str) -> ValidationResult:
        """Validate a Flux query string.

        A valid Flux query must contain a ``from(bucket:...)`` clause.
        This is a lightweight pattern-match validation (no full Flux parser).

        Args:
            query: Flux query string.

        Returns:
            ValidationResult with dialect ``"flux"``.
        """
        query = query.strip()
        if not query:
            return ValidationResult(
                valid=False,
                error="Empty query",
                dialect="flux",
            )
        if not _FLUX_FROM_PATTERN.search(query):
            return ValidationResult(
                valid=False,
                error="Flux query must contain a from(bucket:...) clause",
                dialect="flux",
            )
        return ValidationResult(valid=True, dialect="flux")

    async def get_metadata(
        self,
        credentials: dict[str, Any],
        tables: list[str] | None = None,
    ) -> MetadataResult:
        """Discover InfluxDB schema: buckets as tables, field keys as columns.

        Uses Flux ``buckets()`` to list buckets and ``schema.fieldKeys()``
        to discover field keys for each bucket.

        Args:
            credentials: Connection credentials (token, org, url).
            tables: Optional list of bucket names to inspect.

        Returns:
            MetadataResult with buckets as TableMeta and field keys as
            ColumnMeta.
        """
        self.logger.debug("get_metadata called, tables=%s", tables)
        dsn = credentials.get("dsn")
        params = {k: v for k, v in credentials.items() if k != "dsn"} or None

        db = self._get_db("influx", dsn, params)
        result_tables = []

        async with await db.connection() as conn:
            # List buckets using Flux
            try:
                buckets_query = "buckets()"
                bucket_rows = await conn.query(buckets_query)
                bucket_names = [
                    r.get("name", "") for r in (bucket_rows or [])
                    if isinstance(r, dict) and r.get("name", "").startswith("_") is False
                ]
            except Exception as exc:
                self.logger.warning("Could not list buckets: %s", exc)
                bucket_names = []

            if tables:
                bucket_names = [b for b in bucket_names if b in tables]

            for bucket_name in bucket_names:
                columns = []
                try:
                    # Get field keys for this bucket
                    field_query = f'''
import "influxdata/influxdb/schema"
schema.fieldKeys(bucket: "{bucket_name}")
'''
                    field_rows = await conn.query(field_query.strip())
                    for row in (field_rows or []):
                        field_name = row.get("_value", "") if isinstance(row, dict) else str(row)
                        if field_name:
                            columns.append(ColumnMeta(
                                name=field_name,
                                data_type="field",
                                nullable=True,
                            ))
                    # Add standard Flux measurement columns
                    columns.insert(0, ColumnMeta(name="_time", data_type="timestamp", nullable=False))
                    columns.insert(1, ColumnMeta(name="_measurement", data_type="string", nullable=False))
                    columns.insert(2, ColumnMeta(name="_field", data_type="string", nullable=False))
                    columns.insert(3, ColumnMeta(name="_value", data_type="float", nullable=True))
                except Exception as exc:
                    self.logger.warning("Could not get field keys for bucket %s: %s", bucket_name, exc)

                result_tables.append(TableMeta(
                    name=bucket_name,
                    schema_name="influxdb",
                    columns=columns,
                ))

        return MetadataResult(driver=self.driver, tables=result_tables)

    async def query(
        self,
        credentials: dict[str, Any],
        sql: str,
        params: dict[str, Any] | None = None,
    ) -> QueryResult:
        """Execute a Flux query and return all results.

        Args:
            credentials: Connection credentials (token, org, url).
            sql: Flux query string.
            params: Ignored (Flux queries are self-contained).

        Returns:
            QueryResult with records and execution metadata.
        """
        self.logger.debug("query called: %s", sql[:100])
        start = time.monotonic()
        dsn = credentials.get("dsn")
        conn_params = {k: v for k, v in credentials.items() if k != "dsn"} or None

        db = self._get_db("influx", dsn, conn_params)
        async with await db.connection() as conn:
            rows = await conn.query(sql)

        elapsed_ms = (time.monotonic() - start) * 1000
        rows_list = [dict(r) if not isinstance(r, dict) else r for r in (rows or [])]
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
        """Execute a Flux query and return the first record.

        Args:
            credentials: Connection credentials.
            sql: Flux query string.
            params: Ignored for Flux queries.

        Returns:
            RowResult with the first record or found=False.
        """
        self.logger.debug("query_row called: %s", sql[:100])
        start = time.monotonic()
        dsn = credentials.get("dsn")
        conn_params = {k: v for k, v in credentials.items() if k != "dsn"} or None

        db = self._get_db("influx", dsn, conn_params)
        async with await db.connection() as conn:
            rows = await conn.query(sql)

        elapsed_ms = (time.monotonic() - start) * 1000
        row_dict = None
        rows_list = rows or []
        if rows_list:
            first = rows_list[0]
            row_dict = dict(first) if not isinstance(first, dict) else first

        return RowResult(
            driver=self.driver,
            row=row_dict,
            found=row_dict is not None,
            execution_time_ms=round(elapsed_ms, 3),
        )
