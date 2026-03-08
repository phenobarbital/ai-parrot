from typing import Optional, List
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from datetime import datetime
from .abstract import AbstractSchemaManagerTool
from .models import TableMetadata
from ..abstract import ToolResult


class BQSchemaSearchTool(AbstractSchemaManagerTool):
    """BigQuery-specific schema manager tool."""

    name = "BQSchemaSearchTool"
    description = "Schema management for BigQuery databases"

    def __init__(self, credentials: dict = None, **kwargs):
        """Initialize BQSchemaSearchTool with BigQuery credentials.

        Args:
            credentials: Optional dict with 'credentials' (path to service account JSON)
                and 'project_id' keys. Falls back to navconfig/env vars.
            **kwargs: Passed to AbstractSchemaManagerTool.
        """
        creds = credentials or {}
        try:
            from navconfig import config
        except ImportError:
            config = None

        self._bq_credentials_path = creds.get("credentials")
        if self._bq_credentials_path is None and config is not None:
            self._bq_credentials_path = config.get("BIGQUERY_CREDENTIALS_PATH")

        self._bq_project_id = creds.get("project_id")
        if self._bq_project_id is None and config is not None:
            self._bq_project_id = config.get("BIGQUERY_PROJECT_ID")

        # Force database_type for BQ
        kwargs["database_type"] = "bigquery"
        super().__init__(**kwargs)

    def _get_engine(self, dsn: str, search_path: str):
        """Create a BigQuery-compatible engine via sqlalchemy-bigquery.

        Args:
            dsn: BigQuery DSN string (e.g. ``bigquery://project_id``).
            search_path: Ignored for BigQuery.

        Returns:
            An AsyncEngine wrapping the synchronous BigQuery engine.

        Raises:
            ImportError: If ``sqlalchemy-bigquery`` or ``google-auth`` is not installed.
        """
        try:
            from sqlalchemy import create_engine
        except ImportError as exc:
            raise ImportError(
                "sqlalchemy is required for BQSchemaSearchTool"
            ) from exc

        try:
            import sqlalchemy_bigquery  # noqa: F401
        except ImportError as exc:
            raise ImportError(
                "sqlalchemy-bigquery is required for BQSchemaSearchTool. "
                "Install it with: uv pip install sqlalchemy-bigquery"
            ) from exc

        from sqlalchemy.ext.asyncio import AsyncEngine

        if self._bq_credentials_path:
            try:
                from google.oauth2 import service_account
            except ImportError as exc:
                raise ImportError(
                    "google-auth is required for BQSchemaSearchTool when using "
                    "service account credentials. Install it with: "
                    "uv pip install google-auth"
                ) from exc

            credentials = service_account.Credentials.from_service_account_file(
                str(self._bq_credentials_path),
                scopes=["https://www.googleapis.com/auth/bigquery.readonly"],
            )
            sync_engine = create_engine(
                f"bigquery://{self._bq_project_id or ''}",
                credentials_base=credentials,
            )
        else:
            # Application Default Credentials
            sync_engine = create_engine(
                f"bigquery://{self._bq_project_id or ''}"
            )

        # Wrap sync engine for async use
        return AsyncEngine(sync_engine)

    async def _execute(
        self,
        search_term: str,
        schema_name: Optional[str] = None,
        table_name: Optional[str] = None,
        search_type: str = "all",
        limit: int = 10
    ) -> ToolResult:
        """Execute schema search with cache-first → database-fallback strategy."""
        try:
            target_schemas = [schema_name] if schema_name else self.allowed_schemas

            # Step 1: Try cache first
            self.logger.debug(
                f"Searching cache for '{search_term}' in schemas: {target_schemas}"
            )
            cache_results = await self._search_in_cache(
                search_term=search_term,
                schema_name=schema_name,
                table_name=table_name,
                search_type=search_type,
                limit=limit
            )

            # Step 2: If cache is empty, search database
            if not cache_results:
                self.logger.info(
                    f"Cache miss for '{search_term}', searching BigQuery..."
                )
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
                self.logger.info(
                    f"Cache hit for '{search_term}': {len(cache_results)} results"
                )
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
            self.logger.error(f"BigQuery schema search failed: {e}")
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
        """Search in cache first."""
        if schema_name and table_name:
            table_meta = await self.metadata_cache.get_table_metadata(
                schema_name, table_name
            )
            return [table_meta] if table_meta else []

        target_schemas = [schema_name] if schema_name else self.allowed_schemas
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
        """Search directly in BigQuery INFORMATION_SCHEMA when cache is empty."""
        async with self.session_maker() as session:
            target_schemas = [schema_name] if schema_name else self.allowed_schemas
            results = []

            for schema in target_schemas:
                try:
                    if table_name:
                        # Specific table lookup
                        query_str = (
                            f"SELECT table_catalog, table_schema, table_name, table_type "
                            f"FROM `{schema}.INFORMATION_SCHEMA.TABLES` "
                            f"WHERE table_type IN ('BASE TABLE', 'VIEW') "
                            f"AND table_name = :table_name "
                            f"LIMIT 1"
                        )
                        params = {"table_name": table_name}
                    else:
                        # Pattern search
                        query_str = (
                            f"SELECT table_catalog, table_schema, table_name, table_type "
                            f"FROM `{schema}.INFORMATION_SCHEMA.TABLES` "
                            f"WHERE table_type IN ('BASE TABLE', 'VIEW') "
                            f"AND LOWER(table_name) LIKE LOWER(:term) "
                            f"LIMIT :limit"
                        )
                        params = {"term": f"%{search_term}%", "limit": limit}

                    result = await session.execute(text(query_str), params)
                    rows = result.fetchall()

                    for row in rows:
                        try:
                            metadata = await self.analyze_table(
                                session,
                                row.table_schema,
                                row.table_name,
                                row.table_type,
                                None
                            )
                            await self.metadata_cache.store_table_metadata(metadata)
                            results.append(metadata)
                        except Exception as e:
                            self.logger.warning(
                                f"Failed to analyze table "
                                f"{row.table_schema}.{row.table_name}: {e}"
                            )
                except Exception as e:
                    self.logger.warning(
                        f"Failed to search schema {schema}: {e}"
                    )

            return results

    async def analyze_schema(self, schema_name: str) -> int:
        """Analyze individual BigQuery schema (dataset) and return table count."""
        async with self.session_maker() as session:
            try:
                query_str = (
                    f"SELECT table_name, table_type "
                    f"FROM `{schema_name}.INFORMATION_SCHEMA.TABLES` "
                    f"WHERE table_type IN ('BASE TABLE', 'VIEW')"
                )

                result = await session.execute(text(query_str))
                tables_data = result.fetchall()

                for table_row in tables_data:
                    table_name = table_row.table_name
                    table_type = table_row.table_type

                    try:
                        table_metadata = await self.analyze_table(
                            session, schema_name, table_name, table_type, None
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
            except Exception:
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
