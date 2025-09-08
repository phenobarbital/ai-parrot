"""
Database Query Tool migrated to use AbstractTool framework.
"""
import re
import json
import os
import asyncio
from typing import Dict, Optional, Any, Tuple, Union, Literal, List
from datetime import datetime
from pathlib import Path
import pandas as pd
from pydantic import BaseModel, Field, field_validator
from asyncdb import AsyncDB
from navconfig import config
from querysource.conf import default_dsn
from .abstract import AbstractTool


class DatabaseQueryArgs(BaseModel):
    """Arguments schema for DatabaseQueryTool."""

    driver: str = Field(
        ...,
        description="Database driver to use (bigquery, pg, mysql, influx, sqlite, oracle, etc.)"
    )
    query: str = Field(
        ...,
        description="Query to execute (only allowing statements for data retrieval). Must match the dialect of the specified database driver."
    )
    credentials: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Dictionary containing database connection credentials (optional if default credentials available), eg. {'dsn': '...'} or {'host': '...', 'port"
    )
    dsn: Optional[str] = Field(
        default=None,
        description="Optional DSN string for database connection (overrides credentials if provided)"
    )
    output_format: Literal["pandas", "json", 'native', 'arrow'] = Field(
        "pandas",
        description="Output format for query results: 'pandas' for DataFrame, 'json' for JSON string, 'native' for native format, 'arrow' for Apache Arrow format"
    )
    query_timeout: int = Field(
        300,
        description="Query timeout in seconds (default: 300)"
    )
    max_rows: int = Field(
        10000,
        description="Maximum number of rows to return (default: 10000)"
    )

    @field_validator('query_timeout')
    @classmethod
    def validate_timeout(cls, v):
        if v <= 0:
            raise ValueError("Query timeout must be positive")
        return v

    @field_validator('max_rows')
    @classmethod
    def validate_max_rows(cls, v):
        if v <= 0:
            raise ValueError("Max rows must be positive")
        return v

    @field_validator('driver')
    @classmethod
    def validate_driver(cls, v):
        supported_drivers = [
            'bigquery', 'pg', 'postgresql', 'mysql', 'influx', 'sqlite',
            'oracle', 'mssql', 'clickhouse', 'duckdb'
        ]
        if v.lower() not in supported_drivers:
            raise ValueError(f"Database driver must be one of: {supported_drivers}")
        return v.lower()

    @field_validator('credentials', mode='before')
    @classmethod
    def validate_credentials(cls, v):
        """Ensure credentials is either None, a dict, or a DSN string."""
        if isinstance(v, str):
            v = { "dsn": v }
        return v


class DatabaseQueryTool(AbstractTool):
    """
    Database Query Tool for executing SQL queries across multiple database systems.

    This tool can execute SELECT queries on various databases including BigQuery, PostgreSQL,
    MySQL, InfluxDB, SQLite, Oracle, and others supported by asyncdb library.

    IMPORTANT: This tool is designed for data retrieval and analysis queries (SELECT statements).
    It should NOT be used for:
    - DDL operations (CREATE, ALTER, DROP tables/schemas)
    - DML operations (INSERT, UPDATE, DELETE data)
    - Administrative operations (GRANT, REVOKE permissions)
    - Database structure modifications

    Use this tool for:
    - Data exploration and analysis
    - Generating reports from existing data
    - Aggregating and summarizing information
    - Filtering and searching database records
    - Joining data from multiple tables for analysis
    """

    name = "database_query"
    description = (
        "Execute SQL queries on various databases (BigQuery, PostgreSQL, MySQL, InfluxDB, etc.) "
        "for data retrieval and analysis. Use this tool to run SELECT queries to explore data, "
        "generate reports, and perform analytics. AVOID DDL operations (CREATE, ALTER, DROP) "
        "and data modifications (INSERT, UPDATE, DELETE). Returns data as pandas DataFrame or JSON."
    )
    args_schema = DatabaseQueryArgs

    def __init__(self, **kwargs):
        """Initialize the Database Query tool."""
        super().__init__(**kwargs)
        self.default_credentials = {}

    def _default_output_dir(self) -> Optional[Path]:
        """Get the default output directory for database query results."""
        return self.static_dir / "database_queries" if self.static_dir else None

    def _validate_query_safety(self, query: str) -> Dict[str, Any]:
        """Validate that the query is safe and appropriate for this tool."""
        query_upper = query.upper().strip()

        # Remove comments and extra whitespace
        query_cleaned = re.sub(r'--.*?\n', '', query_upper)
        query_cleaned = re.sub(r'/\*.*?\*/', '', query_cleaned, flags=re.DOTALL)
        query_cleaned = ' '.join(query_cleaned.split())

        # Dangerous operations to block
        dangerous_operations = [
            'CREATE', 'ALTER', 'DROP', 'TRUNCATE',
            'INSERT', 'UPDATE', 'DELETE', 'MERGE',
            'GRANT', 'REVOKE', 'EXEC', 'EXECUTE',
            'CALL', 'DECLARE', 'SET @'
        ]

        # Check for dangerous operations
        for operation in dangerous_operations:
            if re.search(rf'\b{operation}\b', query_cleaned):
                return {
                    'is_safe': False,
                    'message': f"Query contains potentially dangerous operation: {operation}",
                    'suggestions': [
                        "Use SELECT statements for data retrieval",
                        "Use aggregate functions (COUNT, SUM, AVG) for analysis",
                        "Use WHERE clauses to filter data",
                        "Use JOIN clauses to combine data from multiple tables"
                    ]
                }

        # Check if query starts with SELECT (most common safe operation)
        if not query_cleaned.startswith('SELECT') and not query_cleaned.startswith('WITH'):
            # Allow some other safe operations
            safe_starts = ['SHOW', 'DESCRIBE', 'DESC', 'EXPLAIN']
            if not any(query_cleaned.startswith(safe_op) for safe_op in safe_starts):
                return {
                    'is_safe': False,
                    'message': "Query should typically start with SELECT for data retrieval",
                    'suggestions': [
                        "Start queries with SELECT for data retrieval",
                        "Use WITH clauses for complex queries with CTEs",
                        "Use SHOW/DESCRIBE for schema exploration"
                    ]
                }

        return {'is_safe': True, 'message': 'Query validation passed'}

    def _get_default_credentials(
        self,
        driver: str
    ) -> Tuple[Dict[str, Any], Optional[str]]:
        """
        Get default credentials for the specified database driver.
        This method should be customized based on your environment and security practices.

        TODO: using default credentials from QuerySource config.
        """
        dsn = None
        if driver == 'postgresql':
            driver = 'pg'
        if driver == 'pg':
            dsn = default_dsn
        # TODO: Add logic to fetch default credentials from secure storage or environment variables
        default_credentials = {
            'bigquery': {
                'credentials_file': config.get('GOOGLE_APPLICATION_CREDENTIALS'),
                'project_id': config.get('GOOGLE_CLOUD_PROJECT'),
            },
            'pg': {
                'host': config.get('POSTGRES_HOST', fallback='localhost'),
                'port': config.get('POSTGRES_PORT', fallback='5432'),
                'database': config.get('POSTGRES_DB', fallback='postgres'),
                'user': config.get('POSTGRES_USER', fallback='postgres'),
                'password': config.get('POSTGRES_PASSWORD'),
            },
            'mysql': {
                'host': config.get('MYSQL_HOST', fallback='localhost'),
                'port': config.get('MYSQL_PORT', fallback='3306'),
                'database': config.get('MYSQL_DATABASE', fallback='mysql'),
                'user': config.get('MYSQL_USER', fallback='root'),
                'password': config.get('MYSQL_PASSWORD'),
            },
            'sqlite': {
                'database': config.get('SQLITE_DATABASE', fallback=':memory:'),
            },
            'influx': {
                'host': config.get('INFLUX_HOST', fallback='localhost'),
                'port': config.get('INFLUX_PORT', fallback='8086'),
                'database': config.get('INFLUX_DATABASE', fallback='default'),
                'username': config.get('INFLUX_USERNAME'),
                'password': config.get('INFLUX_PASSWORD'),
            },
            'oracle': {
                'host': config.get('ORACLE_HOST', fallback='localhost'),
                'port': config.get('ORACLE_PORT', fallback='1521'),
                'service_name': config.get('ORACLE_SERVICE_NAME', fallback='xe'),
                'user': config.get('ORACLE_USER'),
                'password': config.get('ORACLE_PASSWORD'),
            },
            'mssql': {
                'host': config.get('MSSQL_HOST', fallback='localhost'),
                'port': config.get('MSSQL_PORT', fallback='1433'),
                'database': config.get('MSSQL_DATABASE', fallback='master'),
                'user': config.get('MSSQL_USER'),
                'password': config.get('MSSQL_PASSWORD'),
            }
        }

        if driver not in default_credentials:
            raise ValueError(
                f"No default credentials configured for database driver: {driver}"
            )

        creds = default_credentials[driver].copy()

        # Remove None values
        creds = {k: v for k, v in creds.items() if v is not None}

        return creds, dsn

    def _get_credentials(
        self,
        driver: str,
        provided_credentials: Optional[Dict[str, Any]]
    ) -> Tuple[Dict[str, Any], str]:
        """Get database credentials, either provided or default."""
        if provided_credentials:
            return provided_credentials, None

        try:
            default_creds, dsn = self._get_default_credentials(driver)
            return default_creds, dsn
        except Exception as e:
            raise ValueError(
                f"No credentials provided and could not get default for {driver}: {e}"
            )

    def _add_row_limit(self, query: str, max_rows: int) -> str:
        """Add row limit to query if not already present."""
        query_upper = query.upper().strip()

        # Check if LIMIT is already present
        if 'LIMIT' in query_upper:
            return query

        # Add LIMIT clause
        if max_rows and max_rows > 0:
            return f"{query.rstrip(';')} LIMIT {max_rows}"

        return query

    async def _execute_database_query(
        self,
        driver: str,
        credentials: Dict[str, Any],
        dsn: Optional[str],
        query: str,
        output_format: str,
        timeout: int,
        max_rows: int
    ) -> Union[pd.DataFrame, str]:
        """Execute the actual database query using Asyncdb."""

        # TODO: combine AsyncDB with Ibis for better abstraction.
        try:
            # Create AsyncDB instance
            if dsn:
                db = AsyncDB(driver, dsn=dsn)
            else:
                db = AsyncDB(driver, params=credentials)

            async with await db.connection() as conn:  # pylint: disable=E1101 # noqa
                # Set output format
                conn.output_format(output_format)

                # Add row limit to query if specified and not already present
                modified_query = self._add_row_limit(query, max_rows)

                self.logger.info(
                    f"Executing query on {driver}: {modified_query[:100]}..."
                )

                # Execute query with timeout
                result, errors = await asyncio.wait_for(
                    conn.query(modified_query),
                    timeout=timeout
                )

                if errors:
                    raise Exception(f"Database query errors: {errors}")

                # Return the actual result based on format
                if output_format == 'pandas':
                    if not isinstance(result, pd.DataFrame):
                        raise Exception(
                            f"Expected pandas DataFrame but got {type(result)}"
                        )
                    return result
                else:  # json
                    if isinstance(result, str):
                        return result
                    elif isinstance(result, pd.DataFrame):
                        return result.to_json(orient='records', date_format='iso')
                    else:
                        return json.dumps(result, default=str, indent=2)

        except asyncio.TimeoutError:
            raise Exception(f"Query execution exceeded {timeout} seconds")
        except Exception as e:
            raise Exception(f"Database query failed: {str(e)}")

    async def _execute(
        self,
        driver: str,
        query: str,
        credentials: Optional[Dict[str, Any]] = None,
        output_format: str = "pandas",
        query_timeout: int = 300,
        max_rows: int = 10000,
        **kwargs
    ) -> Union[pd.DataFrame, str]:
        """
        Execute the database query (AbstractTool interface).

        Args:
            driver: Database driver to use
            query: SQL query to execute
            credentials: Optional database credentials
            output_format: Output format ('pandas' or 'json')
            query_timeout: Query timeout in seconds
            max_rows: Maximum number of rows to return
            **kwargs: Additional arguments

        Returns:
            pandas DataFrame if output_format='pandas', JSON string if output_format='json'
        """
        start_time = datetime.now()

        try:
            self.logger.info(
                f"Starting database query on {driver}"
            )

            # Validate query safety
            validation_result = self._validate_query_safety(query)
            if not validation_result['is_safe']:
                raise ValueError(
                    f"Query validation failed: {validation_result['message']}"
                )

            # Get credentials
            creds, dsn = self._get_credentials(driver, credentials)

            # Execute query
            result = await self._execute_database_query(
                driver,
                creds,
                dsn,
                query,
                output_format,
                query_timeout,
                max_rows
            )

            end_time = datetime.now()
            execution_time = (end_time - start_time).total_seconds()

            # Log execution details
            if output_format == 'pandas' and isinstance(result, pd.DataFrame):
                self.logger.info(
                    f"Query executed successfully in {execution_time:.2f}s. "
                    f"Retrieved {len(result)} rows, {len(result.columns)} columns."
                )
            else:
                self.logger.info(
                    f"Query executed successfully in {execution_time:.2f}s. "
                    f"Retrieved JSON result."
                )

            return result

        except Exception as e:
            end_time = datetime.now()
            execution_time = (end_time - start_time).total_seconds()

            self.logger.error(f"Database query failed after {execution_time:.2f}s: {e}")
            raise

    def execute_sync(
        self,
        driver: str,
        query: str,
        credentials: Optional[Dict[str, Any]] = None,
        output_format: str = "pandas",
        query_timeout: int = 300,
        max_rows: int = 10000
    ) -> Union[pd.DataFrame, str]:
        """
        Execute database query synchronously.

        Args:
            driver: Database driver to use
            query: SQL query to execute
            credentials: Optional database credentials
            output_format: Output format ('pandas' or 'json')
            query_timeout: Query timeout in seconds
            max_rows: Maximum number of rows to return

        Returns:
            pandas DataFrame if output_format='pandas', JSON string if output_format='json'
        """
        try:
            loop = asyncio.get_running_loop()
            # If we're in an async context, create a task
            task = loop.create_task(self.execute(
                driver=driver,
                query=query,
                credentials=credentials,
                output_format=output_format,
                query_timeout=query_timeout,
                max_rows=max_rows
            ))
            return task
        except RuntimeError:
            # No running loop, safe to create one
            return asyncio.run(self.execute(
                driver=driver,
                query=query,
                credentials=credentials,
                output_format=output_format,
                query_timeout=query_timeout,
                max_rows=max_rows
            ))

    def get_supported_drivers(self) -> List[str]:
        """Get list of supported database drivers."""
        return [
            'bigquery', 'pg', 'postgres', 'postgresql', 'mysql', 'influx', 'sqlite',
            'oracle', 'mssql', 'clickhouse', 'snowflake'
        ]

    def test_connection(
        self,
        driver: str,
        credentials: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Test database connection.

        Args:
            driver: Database driver to test
            credentials: Optional credentials to use

        Returns:
            Dictionary with connection test results
        """
        try:
            # Simple test query
            test_query = "SELECT 1 as test_column"

            result = self.execute_sync(
                driver=driver,
                query=test_query,
                credentials=credentials,
                output_format="pandas",
                query_timeout=30,
                max_rows=1
            )

            return {
                "status": "success",
                "message": f"Successfully connected to {driver}",
                "test_result": result.to_dict('records') if isinstance(result, pd.DataFrame) else result
            }

        except Exception as e:
            return {
                "status": "error",
                "message": f"Failed to connect to {driver}: {str(e)}"
            }

    def save_query_result(
        self,
        result: Union[pd.DataFrame, str],
        filename: Optional[str] = None,
        file_format: str = "csv"
    ) -> Dict[str, Any]:
        """
        Save query result to file.

        Args:
            result: Query result to save
            filename: Optional filename
            file_format: File format ('csv', 'json', 'excel')

        Returns:
            Dictionary with file information
        """
        if not self.output_dir:
            raise ValueError("Output directory not configured")

        if not filename:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"query_result_{timestamp}"

        # Ensure output directory exists
        self.output_dir.mkdir(parents=True, exist_ok=True)

        try:
            if isinstance(result, pd.DataFrame):
                if file_format.lower() == 'csv':
                    file_path = self.output_dir / f"{filename}.csv"
                    result.to_csv(file_path, index=False)
                elif file_format.lower() == 'excel':
                    file_path = self.output_dir / f"{filename}.xlsx"
                    result.to_excel(file_path, index=False)
                elif file_format.lower() == 'json':
                    file_path = self.output_dir / f"{filename}.json"
                    result.to_json(file_path, orient='records', date_format='iso', indent=2)
                else:
                    raise ValueError(f"Unsupported file format: {file_format}")
            else:
                # Assume it's JSON string
                file_path = self.output_dir / f"{filename}.json"
                with open(file_path, 'w', encoding='utf-8') as f:
                    f.write(result)

            file_url = self.to_static_url(file_path)

            return {
                "filename": file_path.name,
                "file_path": str(file_path),
                "file_url": file_url,
                "file_size": file_path.stat().st_size,
                "format": file_format
            }

        except Exception as e:
            raise ValueError(
                f"Error saving query result: {e}"
            )
