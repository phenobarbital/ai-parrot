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
from navconfig import config, BASE_DIR
# from querysource.conf import default_dsn, INFLUX_TOKEN
from .abstract import AbstractTool


class QueryLanguage(str, Enum):
    """Supported query languages."""
    SQL = "sql"
    FLUX = "flux"  # InfluxDB
    MQL = "mql"    # MongoDB Query Language
    CYPHER = "cypher"  # Neo4j
    JSON = "json"  # Elasticsearch/OpenSearch JSON DSL
    AQL = "aql"  # ArangoDB Query Language


class DriverInfo:
    """Information about database drivers and their characteristics."""

    DRIVER_MAP = {
        # SQL-based databases
        'pg': {
            'name': 'PostgreSQL',
            'query_language': QueryLanguage.SQL,
            'description': 'PostgreSQL database',
            'aliases': ['postgres', 'postgresql'],
            'asyncdb_driver': 'pg'
        },
        'mysql': {
            'name': 'MySQL',
            'query_language': QueryLanguage.SQL,
            'description': 'MySQL/MariaDB database',
            'aliases': ['mariadb'],
            'asyncdb_driver': 'mysql'
        },
        'bigquery': {
            'name': 'Google BigQuery',
            'query_language': QueryLanguage.SQL,
            'description': 'Google BigQuery data warehouse',
            'aliases': ['bq'],
            'asyncdb_driver': 'bigquery'
        },
        'sqlite': {
            'name': 'SQLite',
            'query_language': QueryLanguage.SQL,
            'description': 'SQLite embedded database',
            'aliases': [],
            'asyncdb_driver': 'sqlite'
        },
        'oracle': {
            'name': 'Oracle Database',
            'query_language': QueryLanguage.SQL,
            'description': 'Oracle Database',
            'aliases': [],
            'asyncdb_driver': 'oracle'
        },
        'mssql': {
            'name': 'Microsoft SQL Server',
            'query_language': QueryLanguage.SQL,
            'description': 'Microsoft SQL Server database',
            'aliases': ['sqlserver'],
            'asyncdb_driver': 'mssql'
        },
        'clickhouse': {
            'name': 'ClickHouse',
            'query_language': QueryLanguage.SQL,
            'description': 'ClickHouse OLAP database',
            'aliases': [],
            'asyncdb_driver': 'clickhouse'
        },
        'duckdb': {
            'name': 'DuckDB',
            'query_language': QueryLanguage.SQL,
            'description': 'DuckDB embedded analytical database',
            'aliases': [],
            'asyncdb_driver': 'duckdb'
        },
        # Non-SQL databases
        'influx': {
            'name': 'InfluxDB',
            'query_language': QueryLanguage.FLUX,
            'description': 'InfluxDB time-series database (uses Flux query language)',
            'aliases': ['influxdb'],
            'asyncdb_driver': 'influx'
        },
        # MongoDB and compatible databases (both use 'mongo' driver in asyncdb)
        'mongo': {
            'name': 'MongoDB',
            'query_language': QueryLanguage.MQL,
            'description': 'MongoDB document-oriented database',
            'aliases': ['mongo'],
            'asyncdb_driver': 'mongo',
            'dbtype': 'mongodb'
        },
        'atlas': {
            'name': 'MongoDB Atlas',
            'query_language': QueryLanguage.MQL,
            'description': 'MongoDB Atlas cloud database',
            'aliases': [],
            'asyncdb_driver': 'mongo',
            'dbtype': 'atlas'
        },
        'documentdb': {
            'name': 'DocumentDB',
            'query_language': QueryLanguage.MQL,
            'description': 'AWS DocumentDB (MongoDB-compatible) document database',
            'aliases': [],
            'asyncdb_driver': 'mongo',  # Uses mongo driver with dbtype parameter
            'dbtype': 'documentdb'
        },
        # Elasticsearch:
        'elastic': {
            'name': 'Elasticsearch/OpenSearch',
            'query_language': QueryLanguage.JSON,
            'supports_limit': True
        },
        'elasticsearch': {
            'name': 'Elasticsearch',
            'query_language': QueryLanguage.JSON,
            'supports_limit': True
        },
        'opensearch': {
            'name': 'OpenSearch',
            'query_language': QueryLanguage.JSON,
            'supports_limit': True
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
    def get_asyncdb_driver(cls, driver: str) -> str:
        """Get the actual asyncdb driver name."""
        driver = cls.normalize_driver(driver)
        driver_info = cls.DRIVER_MAP.get(driver, {})
        return driver_info.get('asyncdb_driver', driver)

    @classmethod
    def get_dbtype(cls, driver: str) -> Optional[str]:
        """Get the dbtype parameter for drivers that need it (mongo-based)."""
        driver = cls.normalize_driver(driver)
        driver_info = cls.DRIVER_MAP.get(driver, {})
        return driver_info.get('dbtype')

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
            'aliases': [],
            'asyncdb_driver': driver
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
            "Document-based: 'mongo' (MongoDB), 'atlas' (MongoDB Atlas), 'documentdb' (AWS DocumentDB)\n"
            "Note: Query syntax must match the driver's query language."
        )
    )
    query: Union[str, Dict[str, Any]] = Field(
        ...,
        description=(
            "Query to execute for data retrieval. Query syntax depends on the driver:\n\n"
            "SQL drivers (pg, mysql, bigquery, etc.):\n"
            "  Use SQL SELECT statements, e.g.: SELECT * FROM users WHERE age > 25\n\n"
            "InfluxDB (influx):\n"
            "  Use Flux query language, e.g.: from(bucket:\"my-bucket\") |> range(start: -1h)\n\n"
            "MongoDB/DocumentDB (mongo, atlas, documentdb):\n"
            "  Provide the MongoDB query filter as JSON.\n"
            "  The collection_name must be specified in the 'credentials' parameter, OR in the query.\n"
            "  Examples:\n"
            "    - Filter only: {\"status\": \"active\"}\n"
            "    - Command style: { \"find\": \"users\", \"filter\": {\"status\": \"active\"}, \"limit\": 10, \"sort\": {\"created_at\": -1} }\n\n"
            "Only data retrieval queries are allowed - no DDL or DML operations."
        )
    )
    credentials: Optional[Dict[str, Any]] = Field(
        default=None,
        description=(
            "Dictionary containing database connection credentials (optional if defaults available).\n\n"
            "For SQL databases:\n"
            "  {'host': 'localhost', 'port': 5432, 'database': 'mydb', 'user': 'admin', 'password': 'secret'}\n\n"
            "For MongoDB/DocumentDB (mongo, atlas, documentdb):\n"
            "  REQUIRED: 'collection_name' - The collection to query\n"
            "  Example: {\n"
            "    'host': 'cluster.docdb.amazonaws.com',\n"
            "    'port': 27017,\n"
            "    'database': 'mydb',\n"
            "    'collection_name': 'users',  # REQUIRED for mongo-based drivers\n"
            "    'username': 'admin',\n"
            "    'password': 'secret',\n"
            "    'ssl': True,  # For DocumentDB\n"
            "    'tlsCAFile': '/path/to/cert.pem'  # For DocumentDB\n"
            "  }"
        )
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
            print(f"DEBUG: Query validation failed. Cleaned query: '{query_cleaned[:100]}...'")
            return {
                'is_safe': False,
                'message': "SQL query should start with SELECT, WITH, SHOW, DESCRIBE, or EXPLAIN",
                'suggestions': [
                    "Start queries with SELECT for data retrieval",
                    "Use WITH clauses for complex queries with CTEs",
                    "Use EXPLAIN for query analysis"
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
        elif query_language == QueryLanguage.JSON:
            return cls.validate_elasticsearch_query(query)
        else:
            # For unknown query languages, do minimal validation
            return {
                'is_safe': True,
                'message': f'Basic validation passed for {query_language.value}'
            }

    @staticmethod
    def validate_elasticsearch_query(query: str) -> Dict[str, Any]:
        """Validate Elasticsearch query (JSON DSL format)."""
        try:
            # Parse the query to ensure it's valid JSON
            query_dict = json.loads(query) if isinstance(query, str) else query

            # Basic validation
            if not isinstance(query_dict, dict):
                return {
                    'is_safe': False,
                    'message': 'Query must be a valid JSON object',
                    'suggestions': ['Ensure query is a valid JSON object']
                }
            # Check for unsafe operations (if needed)
            # For now, we allow all queries as Elasticsearch is primarily read-only
            return {
                'is_safe': True,
                'message': 'Elasticsearch query validation passed'
            }
        except json.JSONDecodeError as e:
            return {
                'is_safe': False,
                'message': f'Invalid JSON: {str(e)}',
                'suggestions': ['Fix JSON syntax errors']
            }
        except Exception as e:
            return {
                'is_safe': False,
                'message': f'Query validation failed: {str(e)}',
                'suggestions': []
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
    - DocumentDB: DocumentDB (documentdb) - document-oriented database

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
    - 'documentdb' → DocumentDB (MongoDB-compatible)
    - 'elastic' → Elasticsearch (Elasticsearch/OpenSearch)

    QUERY LANGUAGE EXAMPLES:

    SQL (pg, mysql, bigquery, etc.):
        SELECT column1, column2 FROM table WHERE condition

    Flux (influx):
        from(bucket: "my-bucket")
        |> range(start: -12h)
        |> filter(fn: (r) => r["_measurement"] == "temperature")
        |> filter(fn: (r) => r["location"] == "room1")

    DocumentDB:
        { find: "collection", filter: { field: "value" } }


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
        "Execute queries on various databases for data retrieval. "
        "Supports SQL (PostgreSQL, MySQL, BigQuery, etc.), InfluxDB (Flux), "
        "and MongoDB/DocumentDB (MQL). For MongoDB/DocumentDB: provide collection_name "
        "in credentials and only the query filter in the query parameter. "
        "Returns pandas DataFrame or JSON. Read-only operations only."
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
        driver: str,
        provided_credentials: Optional[Dict[str, Any]] = None
    ) -> Tuple[Dict[str, Any], Optional[str]]:
        """
        Get default credentials for the specified database driver.
        Handles mongo-based drivers (mongodb, atlas, documentdb) correctly.
        """
        from querysource.conf import default_dsn, INFLUX_TOKEN
        dsn = None
        normalized_driver = DriverInfo.normalize_driver(driver)
        if driver == 'postgresql':
            driver = 'pg'
        if driver == 'pg':
            dsn = default_dsn

        # Get dbtype for mongo-based drivers
        dbtype = DriverInfo.get_dbtype(normalized_driver)
        default_credentials = {
            'bigquery': {
                'credentials': Path(config.get('BIGQUERY_CREDENTIALS_PATH')).resolve(),
                'project_id': config.get('BIGQUERY_PROJECT_ID'),
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
            },
            # MongoDB - standard configuration
            'mongo': {
                'driver': 'mongo',
                'host': config.get('MONGODB_HOST', fallback='localhost'),
                'port': config.get('MONGODB_PORT', fallback='27017'),
                'database': config.get('MONGODB_DATABASE', fallback='test'),
                'username': config.get('MONGODB_USER'),
                'password': config.get('MONGODB_PASSWORD'),
                'dbtype': 'mongodb'
            },
            # MongoDB Atlas - cloud configuration
            'atlas': {
                'driver': 'mongo',
                'host': config.get('ATLAS_HOST'),
                'port': config.get('ATLAS_PORT', fallback='27017'),
                'database': config.get('ATLAS_DATABASE', fallback='test'),
                'username': config.get('ATLAS_USER'),
                'password': config.get('ATLAS_PASSWORD'),
                'dbtype': 'atlas'
            },
            # AWS DocumentDB - MongoDB-compatible with SSL
            'documentdb': {
                'driver': 'mongo',
                'host': config.get('DOCUMENTDB_HOSTNAME', fallback='localhost'),
                'port': config.get('DOCUMENTDB_PORT', fallback='27017'),
                'database': config.get('DOCUMENTDB_DATABASE', fallback='test'),
                'username': config.get('DOCUMENTDB_USERNAME'),
                'password': config.get('DOCUMENTDB_PASSWORD'),
                'tlsCAFile': BASE_DIR.joinpath('env', "global-bundle.pem"),
                'ssl': config.get('DOCUMENTDB_USE_SSL', fallback=True),
                'collection_name': config.get('DOCUMENTDB_COLLECTION', fallback='mycollection'),
                'dbtype': 'documentdb'
            },
            # Elasticsearch/OpenSearch
            'elastic': {
                'host': config.get('ELASTICSEARCH_HOST', fallback='localhost'),
                'port': config.get('ELASTICSEARCH_PORT', fallback='9200'),
                'db': config.get('ELASTICSEARCH_INDEX', fallback='logstash-*'),
                'user': config.get('ELASTICSEARCH_USER'),
                'password': config.get('ELASTICSEARCH_PASSWORD'),
                'protocol': config.get('ELASTICSEARCH_PROTOCOL', fallback='http'),
                'client_type': config.get('ELASTICSEARCH_CLIENT_TYPE', fallback='auto')
            },
            'elasticsearch': {
                'host': config.get('ELASTICSEARCH_HOST', fallback='localhost'),
                'port': config.get('ELASTICSEARCH_PORT', fallback='9200'),
                'db': config.get('ELASTICSEARCH_INDEX', fallback='logstash-*'),
                'user': config.get('ELASTICSEARCH_USER'),
                'password': config.get('ELASTICSEARCH_PASSWORD'),
                'protocol': config.get('ELASTICSEARCH_PROTOCOL', fallback='http'),
                'client_type': config.get('ELASTICSEARCH_CLIENT_TYPE', fallback='elasticsearch')
            },
            'opensearch': {
                'host': config.get('ELASTICSEARCH_HOST', fallback='localhost'),
                'port': config.get('ELASTICSEARCH_PORT', fallback='9200'),
                'db': config.get('ELASTICSEARCH_INDEX', fallback='logstash-*'),
                'user': config.get('ELASTICSEARCH_USER'),
                'password': config.get('ELASTICSEARCH_PASSWORD'),
                'protocol': config.get('ELASTICSEARCH_PROTOCOL', fallback='http'),
                'client_type': 'opensearch'
            },
        }

        if normalized_driver not in default_credentials:
            raise ValueError(
                f"No default credentials configured for database driver: {normalized_driver}"
            )

        creds = default_credentials[normalized_driver].copy()

        # Override with provided credentials if any
        if provided_credentials:
            creds.update(provided_credentials)

        # Remove None values
        creds = {k: v for k, v in creds.items() if v is not None}
        return creds, dsn

    def _get_credentials(
        self,
        driver: str,
        provided_credentials: Optional[Dict[str, Any]]
    ) -> Tuple[Dict[str, Any], str]:
        """Get database credentials, either provided or default."""

        try:
            default_creds, dsn = self._get_default_credentials(driver, provided_credentials)
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
            if not isinstance(query, str):
                return query

            # Check if LIMIT is already present
            if re.search(r'\bLIMIT\b', query, re.IGNORECASE):
                return query

            # Regex to identify the "tail" consisting of semicolons, whitespace, and comments
            # We strip this tail from the end of the string.
            tail_pattern = r'(?:\s+|;|--[^\n]*|/\*[\s\S]*?\*/)*$'
            clean_query = re.sub(tail_pattern, '', query)

            if not clean_query:
                return query

            return f"{clean_query} LIMIT {max_rows}"

        elif query_language == QueryLanguage.FLUX:
            if not isinstance(query, str):
                return query
            # For Flux, add limit() to the pipeline if not present
            if '|> limit(' not in query.lower():
                return f"{query.rstrip()} |> limit(n: {max_rows})"
            return query

        elif query_language == QueryLanguage.JSON:
            # For Elasticsearch/OpenSearch JSON DSL
            try:
                query_dict = json.loads(query) if isinstance(query, str) else query
                # Add size parameter if not present
                if 'size' not in query_dict or query_dict['size'] > max_rows:
                    query_dict['size'] = max_rows

                return json.dumps(query_dict)
            except Exception:
                # If parsing fails, return original query
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
            db = AsyncDB(driver, dsn=dsn) if dsn else AsyncDB(driver, params=credentials)

            async with await db.connection() as conn:  # pylint: disable=E1101 # noqa
                # Set output format
                conn.output_format(output_format)
                # For mongo-based drivers, ensure we're using the correct database
                if driver == 'mongo':
                    if database_name := credentials.get('database'):
                        await conn.use(database_name)

                # Add row limit to query if specified and not already present
                modified_query = self._add_row_limit(query, max_rows, driver)

                if isinstance(modified_query, str):
                    self.logger.info(
                        f"Executing query on {driver}: {modified_query[:100]}..."
                    )
                else:
                    self.logger.info(
                        f"Executing query on {driver}: {modified_query}..."
                    )

                # Execute query with timeout
                if driver == 'influx':
                    # InfluxDB requires a different method to execute Flux queries
                    result, errors = await asyncio.wait_for(
                        conn.query(modified_query, frmt='recordset'),
                        timeout=timeout
                    )
                elif driver == 'mongo':
                    # For mongo-based drivers:
                    # 1. collection_name MUST be in credentials
                    # 2. query parameter contains ONLY the MongoDB filter (JSON)
                    # For mongo-based drivers:
                    # Support both standard JSON filter and {find:..., filter:...} command style

                    collection_name = credentials.get('collection_name')
                    query_dict = {}
                    possible_limit = None
                    mongo_kwargs = {}

                    # 1. Parsing logic
                    if modified_query:
                        # Handle legacy 'collection::json_query' format first
                        if isinstance(modified_query, str) and '::' in modified_query:
                             self.logger.warning(
                                "Detected '::' format in query. For MongoDB/DocumentDB, "
                                "please provide collection_name in credentials or use the "
                                "{'find': 'collection', 'filter': {...}} syntax."
                             )
                             c_name, json_query = modified_query.split('::', 1)
                             collection_name = c_name.strip()
                             try:
                                query_dict = json.loads(json_query.strip()) if json_query.strip() else {}
                             except Exception:
                                query_dict = {}

                        else:
                            # Parse JSON if string
                            if isinstance(modified_query, str):
                                try:
                                    query_dict = json.loads(modified_query.strip())
                                except Exception:
                                    # Fallback if not valid JSON, though it should be
                                    query_dict = {}
                            elif isinstance(modified_query, dict):
                                query_dict = modified_query
                            else:
                                query_dict = {}

                    # 2. Extract structured command components
                    # Check if it's a command object with 'filter' or 'find'
                    if isinstance(query_dict, dict) and ('filter' in query_dict or 'find' in query_dict):
                        if 'find' in query_dict and isinstance(query_dict['find'], str):
                            collection_name = query_dict['find']

                        # Extract limit/sort/projection
                        if 'limit' in query_dict:
                            possible_limit = query_dict['limit']
                        if 'sort' in query_dict:
                            mongo_kwargs['sort'] = query_dict['sort']
                        if 'projection' in query_dict:
                            mongo_kwargs['projection'] = query_dict['projection']

                        # The actual query is the filter
                        query_dict = query_dict.get('filter', {})

                    # 3. Validation
                    if not collection_name:
                        raise ValueError(
                            "For MongoDB/DocumentDB queries, 'collection_name' must be "
                            "provided in the 'credentials', or in the query as "
                            "{'find': 'collection_name', ...}."
                        )

                    if not isinstance(query_dict, dict):
                         query_dict = {}

                    self.logger.info(
                        f"Querying collection '{collection_name}' with filter: {query_dict}"
                    )

                    # 4. Enforce Limits
                    # Baseline hard limit
                    final_max_rows = 20

                    # Consider user-provided max_rows
                    if max_rows and max_rows > 0:
                        final_max_rows = min(final_max_rows, max_rows)

                    # Consider query-embedded limit
                    if possible_limit is not None and isinstance(possible_limit, int):
                         final_max_rows = min(final_max_rows, possible_limit)

                    result, errors = await conn.query(
                        collection_name=collection_name,
                        query=query_dict,
                        limit=final_max_rows,
                        **mongo_kwargs
                    )
                elif driver in ('elastic', 'elasticsearch', 'opensearch'):
                    # Handle index parameter for Elastic/OpenSearch
                    query_obj = None
                    is_json_str = False

                    if isinstance(modified_query, str):
                        try:
                            query_obj = json.loads(modified_query)
                            is_json_str = True
                        except Exception:
                            pass
                    elif isinstance(modified_query, dict):
                        query_obj = modified_query

                    if isinstance(query_obj, dict):
                        # Extract index if present
                        if 'index' in query_obj:
                            target_index = query_obj.pop('index')
                            if target_index:
                                await conn.use(target_index)
                                self.logger.info(f"Switched to index: {target_index}")

                        # Update modified_query
                        if is_json_str:
                             modified_query = json.dumps(query_obj)
                        else:
                             modified_query = query_obj

                    result, errors = await asyncio.wait_for(
                        conn.query(modified_query),
                        timeout=timeout
                    )
                else:
                    result, errors = await asyncio.wait_for(
                        conn.query(modified_query),
                        timeout=timeout
                    )

                # Handle "Empty Data" error from asyncdb's pandas serializer
                # This is NOT a real error for Elasticsearch/OpenSearch - it just means
                # the query returned 0 hits, which is a valid result
                if errors:
                    error_str = str(errors)
                    if "Empty Data" in error_str and driver in ('elastic', 'elasticsearch', 'opensearch'):
                        self.logger.info(
                            f"OpenSearch/Elasticsearch query returned 0 hits (empty result)"
                        )
                        # Return an empty DataFrame or empty JSON instead of raising an error
                        if output_format == 'pandas':
                            return pd.DataFrame()
                        else:
                            return "[]"
                    else:
                        raise RuntimeError(
                            f"Database query errors: {errors}"
                        )

                # Return the actual result based on format
                if output_format == 'pandas':
                    if result is None:
                        return pd.DataFrame()
                    if not isinstance(result, pd.DataFrame):
                        raise RuntimeError(
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

        except asyncio.TimeoutError as e:
            raise RuntimeError(
                f"Query execution exceeded {timeout} seconds"
            ) from e
        except Exception as e:
            raise RuntimeError(
                f"Database query failed: {str(e)}"
            ) from e

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
            if 'driver' in creds:
                driver = creds.pop('driver')

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
