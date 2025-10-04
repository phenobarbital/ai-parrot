"""
Database Query Tool migrated to use AbstractTool framework.
"""
import re
import json
import os
import asyncio
from typing import Dict, Optional, Any, Tuple, Union, Literal, List
from datetime import datetime
from enum import Enum
from pathlib import Path
import pandas as pd
from pydantic import BaseModel, Field, field_validator
from asyncdb import AsyncDB
from navconfig import config
from querysource.conf import default_dsn, INFLUX_TOKEN
from .abstract import AbstractTool


class QueryLanguage(str, Enum):
    """Supported query languages."""
    SQL = "sql"
    FLUX = "flux"  # InfluxDB
    MQL = "mql"    # MongoDB Query Language (future)
    CYPHER = "cypher"  # Neo4j (future)


class DriverInfo:
    """Information about database drivers and their characteristics."""

    DRIVER_MAP = {
        # SQL-based databases
        'pg': {
            'name': 'PostgreSQL',
            'query_language': QueryLanguage.SQL,
            'description': 'PostgreSQL database',
            'aliases': ['postgres', 'postgresql']
        },
        'mysql': {
            'name': 'MySQL',
            'query_language': QueryLanguage.SQL,
            'description': 'MySQL/MariaDB database',
            'aliases': ['mariadb']
        },
        'bigquery': {
            'name': 'Google BigQuery',
            'query_language': QueryLanguage.SQL,
            'description': 'Google BigQuery data warehouse',
            'aliases': ['bq']
        },
        'sqlite': {
            'name': 'SQLite',
            'query_language': QueryLanguage.SQL,
            'description': 'SQLite embedded database',
            'aliases': []
        },
        'oracle': {
            'name': 'Oracle Database',
            'query_language': QueryLanguage.SQL,
            'description': 'Oracle Database',
            'aliases': []
        },
        'mssql': {
            'name': 'Microsoft SQL Server',
            'query_language': QueryLanguage.SQL,
            'description': 'Microsoft SQL Server database',
            'aliases': ['sqlserver']
        },
        'clickhouse': {
            'name': 'ClickHouse',
            'query_language': QueryLanguage.SQL,
            'description': 'ClickHouse OLAP database',
            'aliases': []
        },
        'duckdb': {
            'name': 'DuckDB',
            'query_language': QueryLanguage.SQL,
            'description': 'DuckDB embedded analytical database',
            'aliases': []
        },
        # Non-SQL databases
        'influx': {
            'name': 'InfluxDB',
            'query_language': QueryLanguage.FLUX,
            'description': 'InfluxDB time-series database (uses Flux query language)',
            'aliases': ['influxdb']
        },
    }

    @classmethod
    def normalize_driver(cls, driver: str) -> str:
        """Normalize driver name from aliases."""
        driver_lower = driver.lower()

        # Check if it's already a canonical name
        if driver_lower in cls.DRIVER_MAP:
            return driver_lower

        # Check aliases
        for canonical_name, info in cls.DRIVER_MAP.items():
            if driver_lower in info.get('aliases', []):
                return canonical_name

        return driver_lower

    @classmethod
    def get_query_language(cls, driver: str) -> QueryLanguage:
        """Get the query language for a driver."""
        driver = cls.normalize_driver(driver)
        driver_info = cls.DRIVER_MAP.get(driver, {})
        return driver_info.get('query_language', QueryLanguage.SQL)

    @classmethod
    def get_driver_info(cls, driver: str) -> Dict[str, Any]:
        """Get full information about a driver."""
        driver = cls.normalize_driver(driver)
        return cls.DRIVER_MAP.get(driver, {
            'name': driver,
            'query_language': QueryLanguage.SQL,
            'description': f'{driver} database',
            'aliases': []
        })

    @classmethod
    def list_drivers(cls) -> List[Dict[str, Any]]:
        """List all supported drivers with their info."""
        return [
            {
                'driver': driver,
                **info
            }
            for driver, info in cls.DRIVER_MAP.items()
        ]

class DatabaseQueryArgs(BaseModel):
    """Arguments schema for DatabaseQueryTool."""

    driver: str = Field(
        ...,
        description=(
            "Database driver to use. Supported drivers:\n"
            "SQL-based: 'pg' (PostgreSQL), 'mysql', 'bigquery', 'sqlite', 'oracle', "
            "'mssql' (Microsoft SQL Server), 'clickhouse', 'duckdb'\n"
            "Time-series: 'influx' (InfluxDB - uses Flux query language)\n"
            "Note: Query syntax must match the driver's query language."
        )
    )
    query: str = Field(
        ...,
        description=(
            "Query to execute for data retrieval. Query syntax depends on the driver:\n"
            "- SQL drivers (pg, mysql, bigquery, etc.): Use SQL SELECT statements\n"
            "- InfluxDB (influx): Use Flux query language (e.g., from(bucket:...) |> range(...))\n"
            "Only data retrieval queries are allowed - no DDL or DML operations."
        )
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
        # Normalize and validate driver
        normalized = DriverInfo.normalize_driver(v)
        if normalized not in DriverInfo.DRIVER_MAP:
            supported = list(DriverInfo.DRIVER_MAP.keys())
            raise ValueError(f"Database driver must be one of: {supported}")
        return normalized

    @field_validator('credentials', mode='before')
    @classmethod
    def validate_credentials(cls, v):
        """Ensure credentials is either None, a dict, or a DSN string."""
        if isinstance(v, str):
            v = { "dsn": v }
        return v


class QueryValidator:
    """Validates queries based on query language."""

    @staticmethod
    def validate_sql_query(query: str) -> Dict[str, Any]:
        """Validate SQL query for safety."""
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
                    'message': f"SQL query contains dangerous operation: {operation}",
                    'suggestions': [
                        "Use SELECT statements for data retrieval",
                        "Use aggregate functions (COUNT, SUM, AVG) for analysis",
                        "Use WHERE clauses to filter data"
                    ]
                }

        # Check if query starts with SELECT or other safe operations
        safe_starts = ['SELECT', 'WITH', 'SHOW', 'DESCRIBE', 'DESC', 'EXPLAIN']
        if not any(query_cleaned.startswith(safe_op) for safe_op in safe_starts):
            return {
                'is_safe': False,
                'message': "SQL query should start with SELECT, WITH, SHOW, or DESCRIBE",
                'suggestions': [
                    "Start queries with SELECT for data retrieval",
                    "Use WITH clauses for complex queries with CTEs"
                ]
            }

        return {'is_safe': True, 'message': 'SQL query validation passed'}

    @staticmethod
    def validate_flux_query(query: str) -> Dict[str, Any]:
        """Validate InfluxDB Flux query for safety."""
        query_lower = query.lower().strip()

        # Flux queries typically start with from() or import
        if not (query_lower.startswith('from(') or query_lower.startswith('import')):
            return {
                'is_safe': False,
                'message': "Flux query should typically start with from() or import",
                'suggestions': [
                    "Use from(bucket: \"...\") to query data",
                    "Chain with |> range() to specify time range",
                    "Use |> filter() to filter data"
                ]
            }

        # Check for potentially dangerous Flux operations
        # Flux write operations
        dangerous_patterns = [
            r'\bto\s*\(',  # to() function writes data
            r'\bdelete\s*\(',  # delete() function
        ]

        for pattern in dangerous_patterns:
            if re.search(pattern, query_lower):
                return {
                    'is_safe': False,
                    'message': "Flux query contains write/delete operation",
                    'suggestions': [
                        "Use queries for data retrieval only",
                        "Use from() |> range() |> filter() for reading data"
                    ]
                }

        return {'is_safe': True, 'message': 'Flux query validation passed'}

    @classmethod
    def validate_query(cls, query: str, query_language: QueryLanguage) -> Dict[str, Any]:
        """Validate query based on its language."""
        if query_language == QueryLanguage.SQL:
            return cls.validate_sql_query(query)
        elif query_language == QueryLanguage.FLUX:
            return cls.validate_flux_query(query)
        else:
            # For unknown query languages, do minimal validation
            return {
                'is_safe': True,
                'message': f'Basic validation passed for {query_language.value}'
            }

class DatabaseQueryTool(AbstractTool):
    """
    Multi-language Database Query Tool for executing queries across multiple database systems.

    This tool can execute SELECT queries on various databases including BigQuery, PostgreSQL,
    MySQL, InfluxDB, SQLite, Oracle, and others supported by asyncdb library.

    Supports multiple query languages:
    - SQL: PostgreSQL (pg), MySQL, BigQuery, SQLite, Oracle, MS SQL Server (mssql),
        ClickHouse, DuckDB
    - Flux: InfluxDB (influx) - time-series database with Flux query language

    DRIVER REFERENCE:
    - 'pg' or 'postgres' or 'postgresql' → PostgreSQL
    - 'mysql' or 'mariadb' → MySQL/MariaDB
    - 'bigquery' or 'bq' → Google BigQuery
    - 'mssql' or 'sqlserver' → Microsoft SQL Server
    - 'influx' or 'influxdb' → InfluxDB (uses Flux, not SQL)
    - 'sqlite' → SQLite
    - 'oracle' → Oracle Database
    - 'clickhouse' → ClickHouse
    - 'duckdb' → DuckDB

    QUERY LANGUAGE EXAMPLES:

    SQL (pg, mysql, bigquery, etc.):
        SELECT column1, column2 FROM table WHERE condition

    Flux (influx):
        from(bucket: "my-bucket")
        |> range(start: -12h)
        |> filter(fn: (r) => r["_measurement"] == "temperature")
        |> filter(fn: (r) => r["location"] == "room1")


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
        "Execute queries on various databases for data retrieval and analysis. "
        "Supports SQL databases (PostgreSQL/pg, MySQL, BigQuery, MS SQL Server/mssql, etc.) "
        "and InfluxDB (influx - uses Flux query language, not SQL). "
        "Query syntax must match the database driver's query language. "
        "Returns data as pandas DataFrame or JSON. Read-only operations only."
    )
    args_schema = DatabaseQueryArgs

    def __init__(self, **kwargs):
        """Initialize the Database Query tool."""
        super().__init__(**kwargs)
        self.default_credentials = {}

    def _default_output_dir(self) -> Optional[Path]:
        """Get the default output directory for database query results."""
        return self.static_dir / "database_queries" if self.static_dir else None

    def _validate_query_safety(self, query: str, driver: str) -> Dict[str, Any]:
        """Validate query safety based on driver's query language."""
        query_language = DriverInfo.get_query_language(driver)
        return QueryValidator.validate_query(query, query_language)

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
                'token': INFLUX_TOKEN,
                'org': config.get('INFLUX_ORG', fallback='my-org'),
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

    def _add_row_limit(self, query: str, max_rows: int, driver: str) -> str:
        """Add row limit to query based on query language."""
        if not max_rows or max_rows <= 0:
            return query

        query_language = DriverInfo.get_query_language(driver)

        if query_language == QueryLanguage.SQL:
            query_upper = query.upper().strip()
            # Check if LIMIT is already present
            if 'LIMIT' in query_upper:
                return query
            return f"{query.rstrip(';')} LIMIT {max_rows}"

        elif query_language == QueryLanguage.FLUX:
            # For Flux, add limit() to the pipeline if not present
            if '|> limit(' not in query.lower():
                return f"{query.rstrip()} |> limit(n: {max_rows})"
            return query

        else:
            # For unknown query languages, return as-is
            return query

    def get_driver_info_list(self) -> List[Dict[str, Any]]:
        """Get detailed information about all supported drivers."""
        return DriverInfo.list_drivers()

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
                modified_query = self._add_row_limit(query, max_rows, driver)

                self.logger.info(
                    f"Executing query on {driver}: {modified_query[:100]}..."
                )

                # Execute query with timeout
                if driver == 'influx':
                    # InfluxDB requires a different method to execute Flux queries
                    result, errors = await asyncio.wait_for(
                        conn.query(modified_query, frmt='recordset'),
                        timeout=timeout
                    )
                else:
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
        dsn: Optional[str] = None,
        output_format: str = "pandas",
        query_timeout: int = 300,
        max_rows: int = 10000,
        **kwargs
    ) -> Union[pd.DataFrame, str]:
        """
        Execute the database query with multi-language support.

        Args:
            driver: Database driver (pg, mysql, bigquery, influx, mssql, etc.)
            query: Query to execute (SQL or Flux depending on driver)
            credentials: Optional database credentials
            dsn: Optional DSN string
            output_format: Output format ('pandas' or 'json')
            query_timeout: Query timeout in seconds
            max_rows: Maximum number of rows to return
            **kwargs: Additional arguments

        Returns:
            pandas DataFrame if output_format='pandas', JSON string otherwise
        """
        start_time = datetime.now()

        try:
            # Normalize driver name
            driver = DriverInfo.normalize_driver(driver)
            driver_info = DriverInfo.get_driver_info(driver)

            self.logger.info(
                f"Starting query on {driver_info['name']} "
                f"(language: {driver_info['query_language'].value})"
            )

            # Validate query safety based on query language
            validation_result = self._validate_query_safety(query, driver)
            if not validation_result['is_safe']:
                raise ValueError(
                    f"Query validation failed: {validation_result['message']}\n"
                    f"Suggestions: {', '.join(validation_result.get('suggestions', []))}"
                )

            # Get credentials
            creds, resolved_dsn = self._get_credentials(driver, credentials)
            final_dsn = dsn or resolved_dsn

            # Add row limit if applicable
            modified_query = self._add_row_limit(query, max_rows, driver)

            # Execute query
            result = await self._execute_database_query(
                driver,
                creds,
                final_dsn,
                modified_query,
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
                    f"Retrieved {len(result)} rows, {len(result.columns)} columns "
                    f"from {driver_info['name']}."
                )
            else:
                self.logger.info(
                    f"Query executed successfully in {execution_time:.2f}s "
                    f"on {driver_info['name']}."
                )

            return {
                "status": "success",
                "result": result,
                'metadata': {
                    "query": modified_query,
                    "driver": driver_info['name'],
                    'rows_returned': len(result) if isinstance(result, pd.DataFrame) else None,
                    'columns_returned': len(result.columns) if isinstance(result, pd.DataFrame) else None,
                    'execution_time_seconds': execution_time,
                    'output_format': output_format
                }
            }

        except Exception as e:
            end_time = datetime.now()
            execution_time = (end_time - start_time).total_seconds()

            self.logger.error(
                f"Query failed on {driver} after {execution_time:.2f}s: {e}"
            )
            raise

    def get_supported_drivers(self) -> List[str]:
        """Get list of supported database drivers."""
        return [
            'bigquery', 'pg', 'postgres', 'postgresql', 'mysql', 'influx', 'sqlite',
            'oracle', 'mssql', 'clickhouse', 'snowflake'
        ]

    async def test_connection(
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

            result = await self._execute(
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
