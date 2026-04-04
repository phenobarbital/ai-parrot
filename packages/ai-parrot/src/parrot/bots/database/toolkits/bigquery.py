"""BigQueryToolkit — BigQuery-specific overrides of ``SQLToolkit``.

Provides BigQuery-specific schema introspection via
``INFORMATION_SCHEMA.TABLES``/``COLUMNS``, dry-run cost estimation for
EXPLAIN, and support for project/dataset-based DSNs.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from .sql import SQLToolkit


class BigQueryToolkit(SQLToolkit):
    """BigQuery-specific toolkit.

    Overrides dialect hooks for BigQuery's introspection, dry-run cost
    estimation, and project/dataset DSN format.
    """

    def __init__(
        self,
        dsn: Optional[str] = None,
        project_id: Optional[str] = None,
        credentials_file: Optional[str] = None,
        allowed_schemas: Optional[List[str]] = None,
        primary_schema: Optional[str] = None,
        backend: str = "asyncdb",
        **kwargs: Any,
    ) -> None:
        # BigQuery uses project_id + dataset instead of traditional DSN
        self.project_id = project_id
        self.credentials_file = credentials_file
        effective_dsn = dsn or f"bigquery://{project_id or 'default'}"
        super().__init__(
            dsn=effective_dsn,
            allowed_schemas=allowed_schemas or ["default"],
            primary_schema=primary_schema,
            backend=backend,
            database_type="bigquery",
            **kwargs,
        )

    # ------------------------------------------------------------------
    # Dialect hooks
    # ------------------------------------------------------------------

    def _get_explain_prefix(self) -> str:
        """BigQuery uses dry-run for cost estimation (no EXPLAIN ANALYZE)."""
        return "-- DRY RUN COST ESTIMATION"

    def _get_information_schema_query(
        self,
        search_term: str,
        schemas: List[str],
    ) -> tuple[str, Dict[str, Any]]:
        """BigQuery uses dataset.INFORMATION_SCHEMA.TABLES."""
        # BigQuery information_schema queries differ from ANSI
        dataset = schemas[0] if schemas else "default"
        safe_dataset = self._validate_identifier(dataset)
        sql = f"""
            SELECT
                table_schema,
                table_name,
                table_type
            FROM `{safe_dataset}`.INFORMATION_SCHEMA.TABLES
            WHERE table_name LIKE :term
            ORDER BY table_name
            LIMIT :limit
        """
        return sql, {
            "term": f"%{search_term}%",
            "limit": 20,
        }

    def _get_columns_query(
        self, schema: str, table: str
    ) -> tuple[str, Dict[str, Any]]:
        """BigQuery column introspection."""
        safe_schema = self._validate_identifier(schema)
        sql = f"""
            SELECT
                column_name,
                data_type,
                is_nullable,
                column_default,
                ordinal_position
            FROM `{safe_schema}`.INFORMATION_SCHEMA.COLUMNS
            WHERE table_name = :table
            ORDER BY ordinal_position
        """
        return sql, {"table": table}

    def _get_primary_keys_query(
        self, schema: str, table: str
    ) -> tuple[str, Dict[str, Any]]:
        """BigQuery doesn't have traditional primary keys.

        Returns an empty query that will produce no results.
        """
        return "SELECT '' AS column_name WHERE FALSE", {}

    def _get_sample_data_query(
        self, schema: str, table: str, limit: int = 3
    ) -> str:
        safe_schema = self._validate_identifier(schema)
        safe_table = self._validate_identifier(table)
        return f"SELECT * FROM `{safe_schema}`.`{safe_table}` LIMIT {int(limit)}"

    def _get_asyncdb_driver(self) -> str:
        return "bigquery"

    def _build_sqlalchemy_dsn(self, raw_dsn: str) -> str:
        """BigQuery SQLAlchemy uses ``bigquery://`` prefix."""
        if not raw_dsn.startswith("bigquery://"):
            return f"bigquery://{self.project_id or ''}"
        return raw_dsn
