from typing import Optional, List
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from datetime import datetime
from .abstract import AbstractSchemaManagerTool
from .models import TableMetadata
from ..abstract import ToolResult


class PgSchemaSearchTool(AbstractSchemaManagerTool):
    """PostgreSQL-specific schema manager tool."""

    name = "PgSchemaSearchTool"
    description = "Schema management for PostgreSQL databases. You MUST use this tool to discover and understand schema tables and their columns using 'search_term' before trying to run a query using DatabaseQueryTool."

    async def _execute(
        self,
        search_term: str,
        schema_name: Optional[str] = None,
        table_name: Optional[str] = None,
        search_type: str = "all",
        limit: int = 10
    ) -> ToolResult:
        """Execute schema search with proper cache-first strategy."""
        try:
            # Determine target schemas
            target_schemas = [schema_name] if schema_name else self.allowed_schemas
            
            # Step 1: Try cache first
            self.logger.debug(f"🔍 Searching cache for '{search_term}' in schemas: {target_schemas}")
            cache_results = await self._search_in_cache(
                search_term=search_term,
                schema_name=schema_name,
                table_name=table_name,
                search_type=search_type,
                limit=limit
            )
            
            # Step 2: If cache is empty, search database
            if not cache_results:
                self.logger.info(f"💾 Cache miss for '{search_term}', searching database...")
                db_results = await self._search_in_database(
                    search_term=search_term,
                    schema_name=schema_name,
                    table_name=table_name,
                    search_type=search_type,
                    limit=limit
                )
                results = db_results
                source = "database"
            else:
                self.logger.info(f"✅ Cache hit for '{search_term}': {len(cache_results)} results")
                results = cache_results
                source = "cache"
            
            # Step 3: Format results
            formatted_results = []
            for table in results:
                fmt = await self._format_table_result(table, search_term, search_type)
                if fmt:
                    formatted_results.append(fmt)
            
            return ToolResult(
                status="success",
                result=formatted_results,
                metadata={
                    "search_term": search_term,
                    "schema_name": schema_name,
                    "table_name": table_name,
                    "search_type": search_type,
                    "results_count": len(formatted_results),
                    "searched_schemas": target_schemas,
                    "source": source
                }
            )
        except Exception as e:
            self.logger.error(f"Schema search failed: {e}")
            return ToolResult(
                status="error",
                result=None,
                error=str(e),
                metadata={
                    "search_term": search_term,
                    "schema_name": schema_name,
                    "table_name": table_name
                }
            )

    async def _search_in_cache(
        self,
        search_term: str,
        schema_name: Optional[str] = None,
        table_name: Optional[str] = None,
        search_type: str = "all",
        limit: int = 10
    ) -> List[TableMetadata]:
        """Search in cache first - Step 1."""
        # Case 1: Specific schema and table lookup
        if schema_name and table_name:
            self.logger.debug(f"🔍 Specific lookup: {schema_name}.{table_name}")
            table_meta = await self.metadata_cache.get_table_metadata(schema_name, table_name)
            return [table_meta] if table_meta else []
        
        # Case 2: General search using cache's similarity search
        target_schemas = [schema_name] if schema_name else self.allowed_schemas
        self.logger.debug(f"🔍 General cache search in schemas: {target_schemas}")
        
        return await self.metadata_cache.search_similar_tables(
            schema_names=target_schemas,
            query=search_term,
            limit=limit
        )

    async def _search_in_database(
        self,
        search_term: str,
        schema_name: Optional[str] = None,
        table_name: Optional[str] = None,
        search_type: str = "all",
        limit: int = 10
    ) -> List[TableMetadata]:
        """Search directly in database when cache is empty - Step 2."""
        async with self.session_maker() as session:
            target_schemas = [schema_name] if schema_name else self.allowed_schemas
            
            # Case 1: Specific table lookup
            if table_name:
                self.logger.debug(f"💾 DB lookup for specific table: {table_name} in {target_schemas}")
                search_query = """
                    SELECT DISTINCT
                        ist.table_schema,
                        ist.table_name,
                        ist.table_type,
                        obj_description(pgc.oid) as comment
                    FROM information_schema.tables ist
                    LEFT JOIN pg_namespace pgn ON pgn.nspname = ist.table_schema
                    LEFT JOIN pg_class pgc ON pgc.relname = ist.table_name 
                        AND pgc.relnamespace = pgn.oid
                    WHERE ist.table_schema = ANY(:schemas)
                    AND ist.table_name = :table_name
                    AND ist.table_type IN ('BASE TABLE', 'VIEW')
                    LIMIT 1
                """
                params = {"schemas": target_schemas, "table_name": table_name}
            else:
                # Case 2: General pattern search
                self.logger.debug(f"💾 DB pattern search for '{search_term}' in {target_schemas}")
                search_query = """
                    SELECT DISTINCT
                        ist.table_schema,
                        ist.table_name,
                        ist.table_type,
                        obj_description(pgc.oid) as comment
                    FROM information_schema.tables ist
                    LEFT JOIN pg_namespace pgn ON pgn.nspname = ist.table_schema
                    LEFT JOIN pg_class pgc ON pgc.relname = ist.table_name 
                        AND pgc.relnamespace = pgn.oid
                    WHERE ist.table_schema = ANY(:schemas)
                    AND (
                        ist.table_name ILIKE :term
                        OR 
                        (ist.table_schema || '.' || ist.table_name) ILIKE :term
                    )
                    AND ist.table_type IN ('BASE TABLE', 'VIEW')
                    ORDER BY ist.table_name
                    LIMIT :limit
                """
                params = {
                    "schemas": target_schemas,
                    "term": f"%{search_term}%",
                    "limit": limit
                }
            
            result = await session.execute(text(search_query), params)
            rows = result.fetchall()
            
            results = []
            for row in rows:
                try:
                    # Analyze and get full metadata
                    metadata = await self.analyze_table(
                        session,
                        row.table_schema,
                        row.table_name,
                        row.table_type,
                        row.comment
                    )
                    
                    # Step 4: Store in cache for future use
                    await self.metadata_cache.store_table_metadata(metadata)
                    self.logger.debug(f"💾 Stored {row.table_schema}.{row.table_name} in cache")
                    
                    results.append(metadata)
                except Exception as e:
                    self.logger.warning(
                        f"Failed to analyze table {row.table_schema}.{row.table_name}: {e}"
                    )
            
            return results

    async def analyze_schema(self, schema_name: str) -> int:
        """Analyze individual PostgreSQL schema and return table count."""
        async with self.session_maker() as session:
            # Get all tables and views in schema
            tables_query = """
                SELECT DISTINCT
                    ist.table_name,
                    ist.table_type,
                    obj_description(pgc.oid) as comment
                FROM information_schema.tables ist
                LEFT JOIN pg_namespace pgn ON pgn.nspname = ist.table_schema
                LEFT JOIN pg_class pgc ON pgc.relname = ist.table_name 
                    AND pgc.relnamespace = pgn.oid
                WHERE ist.table_schema = :schema_name
                AND ist.table_type IN ('BASE TABLE', 'VIEW')
                ORDER BY ist.table_name
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
            SELECT DISTINCT
                isc.column_name,
                isc.data_type,
                isc.is_nullable,
                isc.column_default,
                isc.character_maximum_length,
                isc.ordinal_position,
                col_description(pgc.oid, isc.ordinal_position) as comment
            FROM information_schema.columns isc
            LEFT JOIN pg_namespace pgn ON pgn.nspname = isc.table_schema
            LEFT JOIN pg_class pgc ON pgc.relname = isc.table_name 
                AND pgc.relnamespace = pgn.oid
            WHERE isc.table_schema = :schema_name
            AND isc.table_name = :table_name
            ORDER BY isc.ordinal_position
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
