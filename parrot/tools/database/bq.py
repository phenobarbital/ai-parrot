from typing import Optional, List
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from datetime import datetime
from .abstract import AbstractSchemaManagerTool
from .models import TableMetadata

class BQSchemaSearchTool(AbstractSchemaManagerTool):
    """BigQuery-specific schema manager tool."""

    name = "BQSchemaSearchTool"
    description = "Schema management for BigQuery databases"

    async def analyze_schema(self, schema_name: str) -> int:
        """Analyze individual BigQuery schema (dataset) and return table count."""
        async with self.session_maker() as session:
            try:
                # Query INFORMATION_SCHEMA.TABLES for the dataset
                query_str = f"SELECT table_name, table_type FROM `{schema_name}.INFORMATION_SCHEMA.TABLES` WHERE table_type IN ('BASE TABLE', 'VIEW')"

                result = await session.execute(text(query_str))
                tables_data = result.fetchall()

                for table_row in tables_data:
                    table_name = table_row.table_name
                    table_type = table_row.table_type
                    comment = None

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
            except Exception as e:
                self.logger.error(f"Error accessing schema {schema_name}: {e}")
                return 0

    async def analyze_table(
        self,
        session: AsyncSession,
        schema_name: str,
        table_name: str,
        table_type: str,
        comment: Optional[str]
    ) -> TableMetadata:
        """Analyze individual BigQuery table metadata."""

        # Get columns
        columns_query = f"""
            SELECT
                column_name,
                data_type,
                is_nullable,
                NULL as column_default,
                NULL as character_maximum_length,
                NULL as comment
            FROM `{schema_name}.INFORMATION_SCHEMA.COLUMNS`
            WHERE table_name = :table_name
            ORDER BY ordinal_position
        """

        result = await session.execute(
            text(columns_query),
            {"table_name": table_name}
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

        # Primary keys are generally not as critical/available in standard BQ metadata queries
        # in the same way as Postgres, so leaving empty for now.
        primary_keys = []

        row_count = None

        sample_data = []
        if table_type == 'BASE TABLE':
            try:
                sample_query = f'SELECT * FROM `{schema_name}.{table_name}` LIMIT 3'
                sample_result = await session.execute(text(sample_query))
                rows = sample_result.fetchall()
                if rows:
                    column_names = list(sample_result.keys())
                    sample_data = [dict(zip(column_names, row)) for row in rows]
            except Exception as e:
                pass

        return TableMetadata(
            schema=schema_name,
            tablename=table_name,
            table_type=table_type,
            full_name=f'`{schema_name}.{table_name}`',
            comment=comment,
            columns=columns,
            primary_keys=primary_keys,
            foreign_keys=[],
            indexes=[],
            row_count=row_count,
            sample_data=sample_data,
            last_accessed=datetime.now()
        )
