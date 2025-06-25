import re
import json
import uuid
from pathlib import Path
from typing import Dict, Optional, Type, Any, Union, Literal
from datetime import datetime
import asyncio
import traceback
import pandas as pd

from langchain.tools import BaseTool
from pydantic import BaseModel, Field, ConfigDict
from asyncdb import AsyncDB


class DBInput(BaseModel):
    """
    Input schema for the DatabaseQueryTool. Users can supply:
    • database_driver (required): the database driver to use (bigquery, pg, mysql, influx, etc.)
    • query (required): SQL query to execute (SELECT statements recommended)
    • credentials: (Optional) dictionary with database connection credentials
    • output_format: (Optional) format for query results - "pandas" or "json" (default: "pandas")
    • query_timeout: (Optional) query timeout in seconds (default: 300)
    • max_rows: (Optional) maximum number of rows to return (default: 10000)
    """
    model_config = ConfigDict(extra='forbid', arbitrary_types_allowed=False)

    database_driver: str = Field(
        ...,
        description="Database driver to use (bigquery, pg, mysql, influx, sqlite, oracle, etc.)"
    )
    query: str = Field(
        ...,
        description="SQL query to execute (preferably SELECT statements for data retrieval)"
    )
    credentials: Optional[Dict[str, Any]] = Field(
        None,
        description="Dictionary containing database connection credentials (optional if default credentials available)"
    )
    output_format: Literal["pandas", "json"] = Field(
        "pandas",
        description="Output format for query results: 'pandas' for DataFrame or 'json' for JSON string"
    )
    query_timeout: Optional[int] = Field(
        300,
        description="Query timeout in seconds (default: 300)"
    )
    max_rows: Optional[int] = Field(
        10000,
        description="Maximum number of rows to return (default: 10000)"
    )


class DatabaseQueryTool(BaseTool):
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

    name: str = "database_query_tool"
    description: str = (
        "Execute SQL queries on various databases (BigQuery, PostgreSQL, MySQL, InfluxDB, etc.) "
        "for data retrieval and analysis. Use this tool to run SELECT queries to explore data, "
        "generate reports, and perform analytics. AVOID DDL operations (CREATE, ALTER, DROP) "
        "and data modifications (INSERT, UPDATE, DELETE). Returns data as pandas DataFrame or JSON."
    )

    args_schema: Type[BaseModel] = DBInput

    def __init__(self):
        """Initialize the Database Query tool."""
        super().__init__()

    async def _arun(self, **kwargs) -> Dict[str, Any]:
        """Async version of the run method."""
        try:
            # Validate input using Pydantic
            input_data = DBInput(**kwargs)
            return await self._execute_query(input_data)
        except Exception as e:
            print(f"❌ Error in DatabaseQueryTool._arun: {e}")
            print(traceback.format_exc())
            return {"error": str(e), "status": "error"}

    def _run(self, **kwargs) -> Dict[str, Any]:
        """Synchronous entrypoint."""
        try:
            # Validate input using Pydantic
            input_data = DBInput(**kwargs)
        except Exception as e:
            return {"error": f"Invalid input: {e}", "status": "error"}

        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                return loop.run_until_complete(self._execute_query(input_data))
            else:
                return asyncio.run(self._execute_query(input_data))
        except RuntimeError:
            return asyncio.run(self._execute_query(input_data))

    async def _execute_query(self, input_data: DBInput) -> Dict[str, Any]:
        """Execute the database query using asyncdb."""
        try:
            # Validate query safety
            validation_result = self._validate_query_safety(input_data.query)
            if not validation_result['is_safe']:
                return {
                    "status": "error",
                    "error": "Query validation failed",
                    "message": validation_result['message'],
                    "suggestions": validation_result.get('suggestions', [])
                }

            # Get credentials
            credentials = await self._get_credentials(input_data.database_driver, input_data.credentials)

            # Execute query
            result = await self._run_database_query(
                input_data.database_driver,
                credentials,
                input_data.query,
                input_data.output_format,
                input_data.query_timeout,
                input_data.max_rows
            )

            return result

        except Exception as e:
            return {
                "status": "error",
                "error": str(e),
                "message": f"Failed to execute database query: {str(e)}",
                "database_driver": input_data.database_driver,
                "query": input_data.query[:100] + "..." if len(input_data.query) > 100 else input_data.query
            }

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

    async def _get_credentials(self, database_driver: str, provided_credentials: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        """Get database credentials, either provided or default."""
        if provided_credentials:
            return provided_credentials

        # Try to get default credentials
        try:
            default_creds = await self._get_default_credentials(database_driver)
            return default_creds
        except Exception as e:
            raise Exception(f"No credentials provided and could not get default credentials for {database_driver}: {e}")

    async def _get_default_credentials(self, database_driver: str) -> Dict[str, Any]:
        """
        Get default credentials for the specified database driver.
        This method should be customized based on your environment and security practices.
        """
        # This is a placeholder implementation - customize based on your needs
        default_credentials = {
            'bigquery': {
                # For BigQuery, you might use service account key file or ADC
                'credentials_file': None,  # Path to service account JSON
                'project_id': None,       # Will be determined from credentials
            },
            'pg': {
                'host': 'localhost',
                'port': 5432,
                'database': 'postgres',
                'user': 'postgres',
                'password': None,  # Should be set via environment variable
            },
            'mysql': {
                'host': 'localhost',
                'port': 3306,
                'database': 'mysql',
                'user': 'root',
                'password': None,  # Should be set via environment variable
            },
            'sqlite': {
                'database': ':memory:',  # In-memory database
            },
            'influx': {
                'host': 'localhost',
                'port': 8086,
                'database': 'default',
                'username': None,
                'password': None,
            }
        }

        if database_driver not in default_credentials:
            raise Exception(f"No default credentials configured for database driver: {database_driver}")

        creds = default_credentials[database_driver].copy()

        # Load sensitive values from environment variables
        import os

        if database_driver == 'pg':
            creds['password'] = os.getenv('POSTGRES_PASSWORD')
            creds['host'] = os.getenv('POSTGRES_HOST', creds['host'])
            creds['database'] = os.getenv('POSTGRES_DB', creds['database'])
            creds['user'] = os.getenv('POSTGRES_USER', creds['user'])

        elif database_driver == 'mysql':
            creds['password'] = os.getenv('MYSQL_PASSWORD')
            creds['host'] = os.getenv('MYSQL_HOST', creds['host'])
            creds['database'] = os.getenv('MYSQL_DATABASE', creds['database'])
            creds['user'] = os.getenv('MYSQL_USER', creds['user'])

        elif database_driver == 'bigquery':
            creds['credentials_file'] = os.getenv('GOOGLE_APPLICATION_CREDENTIALS')
            creds['project_id'] = os.getenv('GOOGLE_CLOUD_PROJECT')

        elif database_driver == 'influx':
            creds['username'] = os.getenv('INFLUX_USERNAME')
            creds['password'] = os.getenv('INFLUX_PASSWORD')
            creds['host'] = os.getenv('INFLUX_HOST', creds['host'])
            creds['database'] = os.getenv('INFLUX_DATABASE', creds['database'])

        return creds

    async def _run_database_query(
        self,
        database_driver: str,
        credentials: Dict[str, Any],
        query: str,
        output_format: str,
        timeout: int,
        max_rows: int
    ) -> Dict[str, Any]:
        """Execute the actual database query using asyncdb."""

        start_time = datetime.now()

        try:
            # Create AsyncDB instance
            db = AsyncDB(database_driver, params=credentials)
            async with await db.connection() as conn:  # noqa
                # Set output format
                conn.output_format(output_format)

                # Add row limit to query if specified and not already present
                modified_query = self._add_row_limit(query, max_rows)

                # Execute query with timeout
                result, errors = await asyncio.wait_for(
                    conn.query(modified_query),
                    timeout=timeout
                )

                end_time = datetime.now()
                execution_time = (end_time - start_time).total_seconds()

                # Process result based on output format
                if output_format == 'pandas':
                    return self._process_pandas_result(result, errors, execution_time, modified_query, database_driver)
                else:  # json
                    return self._process_json_result(result, errors, execution_time, modified_query, database_driver)

        except asyncio.TimeoutError:
            return {
                "status": "error",
                "error": "Query timeout",
                "message": f"Query execution exceeded {timeout} seconds",
                "database_driver": database_driver,
                "execution_time": timeout
            }
        except Exception as e:
            end_time = datetime.now()
            execution_time = (end_time - start_time).total_seconds()

            return {
                "status": "error",
                "error": str(e),
                "message": f"Database query failed: {str(e)}",
                "database_driver": database_driver,
                "execution_time": execution_time
            }

    def _add_row_limit(self, query: str, max_rows: int) -> str:
        """Add row limit to query if not already present."""
        query_upper = query.upper().strip()

        # Check if LIMIT is already present
        if 'LIMIT' in query_upper:
            return query

        # Add LIMIT clause for different database types
        if max_rows and max_rows > 0:
            return f"{query.rstrip(';')} LIMIT {max_rows}"

        return query

    def _process_pandas_result(
        self,
        result: pd.DataFrame,
        errors: Any,
        execution_time: float,
        query: str,
        database_driver: str
    ) -> Dict[str, Any]:
        """Process pandas DataFrame result."""

        if errors:
            return {
                "status": "error",
                "error": str(errors),
                "message": "Query executed with errors",
                "database_driver": database_driver,
                "execution_time": execution_time
            }

        # Convert DataFrame to serializable format for the response
        response = {
            "status": "success",
            "data": result,  # This will be the actual DataFrame
            "data_info": {
                "rows": len(result),
                "columns": len(result.columns) if hasattr(result, 'columns') else 0,
                "column_names": list(result.columns) if hasattr(result, 'columns') else [],
                "data_types": result.dtypes.to_dict() if hasattr(result, 'dtypes') else {}
            },
            "execution_time": execution_time,
            "database_driver": database_driver,
            "output_format": "pandas",
            "query": query[:200] + "..." if len(query) > 200 else query,
            "message": f"Query executed successfully. Retrieved {len(result)} rows."
        }

        # Add sample data for preview
        if len(result) > 0:
            response["sample_data"] = result.head(5).to_dict('records')

        return response

    def _process_json_result(
        self,
        result: Any,
        errors: Any,
        execution_time: float,
        query: str,
        database_driver: str
    ) -> Dict[str, Any]:
        """Process JSON result."""

        if errors:
            return {
                "status": "error",
                "error": str(errors),
                "message": "Query executed with errors",
                "database_driver": database_driver,
                "execution_time": execution_time
            }

        # Convert result to JSON string if it's not already
        if isinstance(result, str):
            json_data = result
            try:
                parsed_data = json.loads(result)
                row_count = len(parsed_data) if isinstance(parsed_data, list) else 1
            except:
                row_count = 1
        else:
            try:
                json_data = json.dumps(result, default=str, indent=2)
                row_count = len(result) if hasattr(result, '__len__') else 1
            except Exception as e:
                return {
                    "status": "error",
                    "error": f"Failed to serialize result to JSON: {e}",
                    "message": "Could not convert query result to JSON format",
                    "database_driver": database_driver,
                    "execution_time": execution_time
                }

        return {
            "status": "success",
            "data": json_data,
            "data_info": {
                "rows": row_count,
                "format": "json",
                "size_bytes": len(json_data)
            },
            "execution_time": execution_time,
            "database_driver": database_driver,
            "output_format": "json",
            "query": query[:200] + "..." if len(query) > 200 else query,
            "message": f"Query executed successfully. Retrieved data in JSON format."
        }
