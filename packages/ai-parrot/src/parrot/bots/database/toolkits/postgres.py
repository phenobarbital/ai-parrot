"""PostgresToolkit — PostgreSQL-specific overrides of ``SQLToolkit``.

Provides PG-specific EXPLAIN format, ``pg_class``/``pg_namespace``
introspection, column comments via ``col_description()``, and
``postgresql+asyncpg://`` DSN mapping.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from ..models import TableMetadata
from .sql import SQLToolkit


class PostgresToolkit(SQLToolkit):
    """PostgreSQL-specific toolkit.

    Overrides dialect hooks for PostgreSQL's richer introspection and
    EXPLAIN output.
    """

    def __init__(
        self,
        dsn: str,
        allowed_schemas: Optional[List[str]] = None,
        primary_schema: Optional[str] = None,
        backend: str = "asyncdb",
        **kwargs: Any,
    ) -> None:
        super().__init__(
            dsn=dsn,
            allowed_schemas=allowed_schemas,
            primary_schema=primary_schema,
            backend=backend,
            database_type="postgresql",
            **kwargs,
        )

    # ------------------------------------------------------------------
    # Dialect hooks
    # ------------------------------------------------------------------

    def _get_explain_prefix(self) -> str:
        return "EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)"

    def _get_information_schema_query(
        self,
        search_term: str,
        schemas: List[str],
    ) -> tuple[str, Dict[str, Any]]:
        """Use ``pg_class``/``pg_namespace`` joins for comment support."""
        sql = """
            SELECT DISTINCT
                ist.table_schema,
                ist.table_name,
                ist.table_type,
                obj_description(pgc.oid) AS comment
            FROM information_schema.tables ist
            LEFT JOIN pg_namespace pgn ON pgn.nspname = ist.table_schema
            LEFT JOIN pg_class pgc ON pgc.relname = ist.table_name
                AND pgc.relnamespace = pgn.oid
            WHERE ist.table_schema = ANY(:schemas)
            AND (
                ist.table_name ILIKE :term
                OR (ist.table_schema || '.' || ist.table_name) ILIKE :term
            )
            AND ist.table_type IN ('BASE TABLE', 'VIEW')
            ORDER BY ist.table_name
            LIMIT :limit
        """
        return sql, {
            "schemas": schemas,
            "term": f"%{search_term}%",
            "limit": 20,
        }

    def _get_columns_query(
        self, schema: str, table: str
    ) -> tuple[str, Dict[str, Any]]:
        """Include ``col_description()`` for column comments."""
        sql = """
            SELECT
                c.column_name,
                c.data_type,
                c.is_nullable,
                c.column_default,
                c.ordinal_position,
                col_description(
                    (SELECT oid FROM pg_class WHERE relname = :table
                     AND relnamespace = (SELECT oid FROM pg_namespace WHERE nspname = :schema)),
                    c.ordinal_position
                ) AS column_comment
            FROM information_schema.columns c
            WHERE c.table_schema = :schema AND c.table_name = :table
            ORDER BY c.ordinal_position
        """
        return sql, {"schema": schema, "table": table}

    def _build_sqlalchemy_dsn(self, raw_dsn: str) -> str:
        """Ensure ``postgresql+asyncpg://`` prefix."""
        if raw_dsn.startswith("postgresql://"):
            return raw_dsn.replace("postgresql://", "postgresql+asyncpg://", 1)
        if raw_dsn.startswith("postgres://"):
            return raw_dsn.replace("postgres://", "postgresql+asyncpg://", 1)
        return raw_dsn

    def _get_asyncdb_driver(self) -> str:
        return "pg"
