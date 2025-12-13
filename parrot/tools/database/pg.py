from typing import Optional, List
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from parrot.bots.database.models import TableMetadata
from datetime import datetime
from .abstract import AbstractSchemaManagerTool

class PgSchemaSearchTool(AbstractSchemaManagerTool):
    """PostgreSQL-specific schema manager tool."""

    name = "PgSchemaSearchTool"
    description = "Schema management for PostgreSQL databases"

    async def analyze_schema(self, schema_name: str) -> int:
        """Analyze individual PostgreSQL schema and return table count."""
        async with self.session_maker() as session:
            # Get all tables and views in schema
            tables_query = """
                SELECT
                    table_name,
                    table_type,
                    obj_description(pgc.oid) as comment
                FROM information_schema.tables ist
                LEFT JOIN pg_class pgc ON pgc.relname = ist.table_name
                LEFT JOIN pg_namespace pgn ON pgn.oid = pgc.relnamespace
                WHERE table_schema = :schema_name
                AND table_type IN ('BASE TABLE', 'VIEW')
                ORDER BY table_name
            """

            result = await session.execute(
                text(tables_query),
                {"schema_name": schema_name}
            )
            tables_data = result.fetchall()

            # Analyze each table
            for table_row in tables_data:
                table_name = table_row.table_name
                table_type = table_row.table_type
                comment = table_row.comment

                try:
                    table_metadata = await self.analyze_table(
                        session, schema_name, table_name, table_type, comment
                    )
                    await self.metadata_cache.store_table_metadata(table_metadata)
                except Exception as e:
                    self.logger.warning(
                        f"Failed to analyze table {schema_name}.{table_name}: {e}"
                    )

            return len(tables_data)

    async def analyze_table(
        self,
        session: AsyncSession,
        schema_name: str,
        table_name: str,
        table_type: str,
        comment: Optional[str]
    ) -> TableMetadata:
        """Analyze individual PostgreSQL table metadata."""

        # Get column information
        columns_query = """
            SELECT
                column_name,
                data_type,
                is_nullable,
                column_default,
                character_maximum_length,
                col_description(pgc.oid, ordinal_position) as comment
            FROM information_schema.columns isc
            LEFT JOIN pg_class pgc ON pgc.relname = isc.table_name
            LEFT JOIN pg_namespace pgn ON pgn.oid = pgc.relnamespace
            WHERE table_schema = :schema_name
            AND table_name = :table_name
            ORDER BY ordinal_position
        """

        result = await session.execute(
            text(columns_query),
            {"schema_name": schema_name, "table_name": table_name}
        )

        columns = []
        for col_row in result.fetchall():
            columns.append({
                "name": col_row.column_name,
                "type": col_row.data_type,
                "nullable": col_row.is_nullable == "YES",
                "default": col_row.column_default,
                "max_length": col_row.character_maximum_length,
                "comment": col_row.comment
            })

        # Get primary keys
        pk_query = """
            SELECT column_name
            FROM information_schema.key_column_usage kcu
            JOIN information_schema.table_constraints tc
                ON kcu.constraint_name = tc.constraint_name
                AND kcu.table_schema = tc.table_schema
            WHERE tc.constraint_type = 'PRIMARY KEY'
            AND kcu.table_schema = :schema_name
            AND kcu.table_name = :table_name
            ORDER BY ordinal_position
        """

        pk_result = await session.execute(
            text(pk_query),
            {"schema_name": schema_name, "table_name": table_name}
        )
        primary_keys = [row.column_name for row in pk_result.fetchall()]

        # Get row count estimate
        row_count = None
        if table_type == 'BASE TABLE':
            try:
                count_query = 'SELECT reltuples::bigint FROM pg_class WHERE relname = :table_name'
                count_result = await session.execute(text(count_query), {"table_name": table_name})
                row_count = count_result.scalar()
            except Exception:
                pass

        # Get sample data
        sample_data = []
        if table_type == 'BASE TABLE' and row_count and row_count < 1000000:
            try:
                sample_query = f'SELECT * FROM "{schema_name}"."{table_name}" LIMIT 3'
                sample_result = await session.execute(text(sample_query))
                rows = sample_result.fetchall()
                if rows:
                    column_names = list(sample_result.keys())
                    sample_data = [dict(zip(column_names, row)) for row in rows]
            except Exception:
                pass

        return TableMetadata(
            schema=schema_name,
            tablename=table_name,
            table_type=table_type,
            full_name=f'"{schema_name}"."{table_name}"',
            comment=comment,
            columns=columns,
            primary_keys=primary_keys,
            foreign_keys=[],
            indexes=[],
            row_count=row_count,
            sample_data=sample_data,
            last_accessed=datetime.now()
        )
