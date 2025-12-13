"""
Unified Database Tool for AI-Parrot

Consolidates schema extraction, knowledge base building, query generation,
validation, and execution into a single, powerful database interface.
"""
from __future__ import annotations
from typing import Dict, List, Optional, Any, Union, Literal, Tuple
import re
import asyncio
import json
import hashlib
from datetime import datetime, timedelta, timezone
from enum import Enum
import pandas as pd
from pydantic import (
    BaseModel,
    Field,
    field_validator,
    model_validator
)
from asyncdb import AsyncDB
from .abstract import (
    AbstractTool,
    ToolResult,
    AbstractToolArgsSchema
)
from ..stores.abstract import AbstractStore
from ..clients.base import AbstractClient
from ..clients.factory import LLMFactory
from ..models import AIMessage


class DatabaseFlavor(str, Enum):
    """Supported database flavors."""
    POSTGRESQL = "postgresql"
    MYSQL = "mysql"
    SQLSERVER = "sqlserver"
    BIGQUERY = "bigquery"
    INFLUXDB = "influxdb"
    CASSANDRA = "cassandra"
    MONGODB = "mongodb"
    ELASTICSEARCH = "elasticsearch"
    SQLITE = "sqlite"
    DUCKDB = "duckdb"


class QueryType(str, Enum):
    """Supported query types."""
    SELECT = "SELECT"
    INSERT = "INSERT"
    UPDATE = "UPDATE"
    DELETE = "DELETE"
    CREATE = "CREATE"
    ALTER = "ALTER"
    DROP = "DROP"


class OutputFormat(str, Enum):
    """Supported output formats."""
    PANDAS = "pandas"
    JSON = "json"
    DICT = "dict"
    CSV = "csv"
    STRUCTURED = "structured"  # Uses Pydantic models


class SchemaMetadata(BaseModel):
    """Metadata for a database schema."""
    schema_name: str
    tables: List[Dict[str, Any]]
    views: List[Dict[str, Any]]
    functions: List[Dict[str, Any]]
    procedures: List[Dict[str, Any]]
    indexes: List[Dict[str, Any]]
    constraints: List[Dict[str, Any]]
    last_updated: datetime
    database_flavor: DatabaseFlavor


class QueryValidationResult(BaseModel):
    """Result of query validation."""
    is_valid: bool
    query_type: Optional[QueryType]
    affected_tables: List[str]
    estimated_cost: Optional[float]
    warnings: List[str]
    errors: List[str]
    security_checks: Dict[str, bool]


class DatabaseToolArgs(AbstractToolArgsSchema):
    """Arguments for the unified database tool."""

    # Query specification
    natural_language_query: Optional[str] = Field(
        None, description="Natural language description of what you want to query"
    )
    sql_query: Optional[str] = Field(
        None, description="Direct SQL query to execute"
    )

    # Database connection
    database_flavor: DatabaseFlavor = Field(
        DatabaseFlavor.POSTGRESQL, description="Type of database to connect to"
    )
    connection_params: Optional[Dict[str, Any]] = Field(
        None, description="Database connection parameters"
    )
    schema_names: List[str] = Field(
        default=["public"], description="Schema names to work with"
    )

    # Operation modes
    operation: Literal[
        "schema_extract", "query_generate", "query_validate",
        "query_execute", "full_pipeline", "explain_query"
    ] = Field(
        "full_pipeline", description="What operation to perform"
    )

    # Query options
    max_rows: int = Field(1000, description="Maximum rows to return")
    timeout_seconds: int = Field(300, description="Query timeout")
    dry_run: bool = Field(False, description="Validate without executing")

    # Output options
    output_format: OutputFormat = Field(
        OutputFormat.PANDAS, description="Format for query results"
    )
    structured_output_schema: Optional[Dict[str, Any]] = Field(
        None, description="Pydantic schema for structured outputs"
    )

    # Knowledge base options
    update_knowledge_base: bool = Field(
        True, description="Whether to update schema knowledge base"
    )
    cache_duration_hours: int = Field(
        24, description="How long to cache schema metadata"
    )

    @model_validator(mode='after')
    def validate_query_input(self) -> 'DatabaseToolArgs':
        # Ensure at least one query type is provided for query operations
        if self.operation in ['query_generate', 'query_execute', 'full_pipeline', 'explain_query']:
            if not self.natural_language_query and not self.sql_query:
                raise ValueError("Either natural_language_query or sql_query must be provided")
        return self


class DatabaseTool(AbstractTool):
    """
    Unified Database Tool that handles the complete database interaction pipeline:

    1. Schema Discovery: Extract and cache table schemas from any supported database
    2. Knowledge Base Building: Store schema metadata in vector store for RAG
    3. Query Generation: Convert natural language to database-specific queries
    4. Query Validation: Syntax checking, security validation, cost estimation
    5. Query Execution: Safe execution with proper error handling
    6. Structured Output: Format results according to specified schemas

    This tool consolidates the functionality of SchemaTool, DatabaseQueryTool,
    and SQLAgent into a single, cohesive interface.
    """

    name = "database_tool"
    description = """Unified database tool for schema discovery, query generation,
                    validation, and execution across multiple database types"""
    args_schema = DatabaseToolArgs

    def __init__(
        self,
        knowledge_store: Optional[AbstractStore] = None,
        default_connection_params: Optional[Dict[DatabaseFlavor, Dict]] = None,
        enable_query_caching: bool = True,
        llm: Optional[Union[AbstractClient, str]] = None,
        **kwargs
    ):
        """
        Initialize the unified database tool.

        Args:
            knowledge_store: Vector store for schema metadata and RAG
            default_connection_params: Default connection parameters per database type
            enable_query_caching: Whether to cache query results
            llm: LLM to use for query generation and validation
        """
        super().__init__(**kwargs)

        self.knowledge_store = knowledge_store
        self.default_connection_params = default_connection_params or {}
        self.enable_query_caching = enable_query_caching

        # Initialize LLM
        if isinstance(llm, str):
            self.llm = LLMFactory.create(llm)
        else:
            self.llm = llm

        # Cache for schema metadata and database connections
        self._schema_cache: Dict[str, Tuple[SchemaMetadata, datetime]] = {}
        self._connection_cache: Dict[str, AsyncDB] = {}

        # Database-specific query generators and validators
        self._query_generators = {}
        self._query_validators = {}

        self._setup_database_handlers()

    def _setup_database_handlers(self):
        """Initialize database-specific handlers for different flavors."""
        # This would be expanded to include handlers for each database type
        self._query_generators = {
            DatabaseFlavor.POSTGRESQL: self._generate_postgresql_query,
            DatabaseFlavor.MYSQL: self._generate_mysql_query,
            DatabaseFlavor.BIGQUERY: self._generate_bigquery_query,
            # Add more database-specific generators...
        }

        self._query_validators = {
            DatabaseFlavor.POSTGRESQL: self._validate_postgresql_query,
            DatabaseFlavor.MYSQL: self._validate_mysql_query,
            DatabaseFlavor.BIGQUERY: self._validate_bigquery_query,
            # Add more database-specific validators...
        }

    def _clean_sql(self, sql_query: str) -> str:
        """Clean SQL query from markdown formatting."""
        if not sql_query:
            return ""
        # Remove markdown code blocks
        clean_query = re.sub(r'```\w*\n?', '', sql_query)
        clean_query = clean_query.replace('```', '')
        return clean_query.strip()

    async def _execute(
        self,
        natural_language_query: Optional[str] = None,
        sql_query: Optional[str] = None,
        database_flavor: DatabaseFlavor = DatabaseFlavor.POSTGRESQL,
        connection_params: Optional[Dict[str, Any]] = None,
        schema_names: List[str] = ["public"],
        operation: str = "full_pipeline",
        max_rows: int = 1000,
        timeout_seconds: int = 300,
        dry_run: bool = False,
        output_format: OutputFormat = OutputFormat.PANDAS,
        structured_output_schema: Optional[Dict[str, Any]] = None,
        update_knowledge_base: bool = True,
        cache_duration_hours: int = 24,
        **kwargs
    ) -> ToolResult:
        """
        Execute the unified database tool pipeline.

        The method routes to different sub-operations based on the operation parameter,
        or executes the full pipeline for complete query processing.
        """
        try:
            # Fallback to default connection parameters if not provided
            if connection_params is None:
                connection_params = self.default_connection_params.get(database_flavor)

            if sql_query:
                sql_query = self._clean_sql(sql_query)

            # Route to specific operations
            if operation == "schema_extract":
                return await self._extract_schema_operation(
                    database_flavor, connection_params, schema_names,
                    update_knowledge_base, cache_duration_hours
                )
            if operation == "query_generate":
                return await self._query_generation_operation(
                    natural_language_query, database_flavor, connection_params, schema_names
                )
            if operation == "query_validate":
                return await self._query_validation_operation(
                    sql_query or natural_language_query, database_flavor, connection_params
                )
            if operation == "query_execute":
                return await self._query_execution_operation(
                    sql_query, database_flavor, connection_params,
                    max_rows, timeout_seconds, output_format, structured_output_schema
                )
            if operation == "full_pipeline":
                return await self._full_pipeline_operation(
                    natural_language_query, sql_query, database_flavor, connection_params,
                    schema_names, max_rows, timeout_seconds, dry_run,
                    output_format, structured_output_schema, update_knowledge_base, cache_duration_hours
                )
            if operation == "explain_query":
                return await self._explain_query_operation(
                    sql_query or natural_language_query, database_flavor, connection_params
                )
            else:
                raise ValueError(f"Unknown operation: {operation}")

        except Exception as e:
            return ToolResult(
                status="error",
                result=None,
                error=f"Database tool execution failed: {str(e)}",
                metadata={
                    "operation": operation,
                    "database_flavor": database_flavor.value,
                    "timestamp": datetime.now(timezone.utc).isoformat()
                }
            )

    async def _full_pipeline_operation(
        self,
        natural_language_query: Optional[str],
        sql_query: Optional[str],
        database_flavor: DatabaseFlavor,
        connection_params: Optional[Dict[str, Any]],
        schema_names: List[str],
        max_rows: int,
        timeout_seconds: int,
        dry_run: bool,
        output_format: OutputFormat,
        structured_output_schema: Optional[Dict[str, Any]],
        update_knowledge_base: bool,
        cache_duration_hours: int
    ) -> ToolResult:
        """
        Execute the complete database interaction pipeline.

        This is the main orchestrator method that combines all functionality:
        schema extraction, knowledge base updates, query generation, validation, and execution.
        """
        pipeline_results = {
            "schema_extraction": None,
            "query_generation": None,
            "query_validation": None,
            "query_execution": None,
            "knowledge_base_update": None
        }

        try:
            # Step 1: Extract and cache schema metadata
            self.logger.info(f"Step 1: Extracting schema for {database_flavor.value}")
            schema_result = await self._extract_schema_operation(
                database_flavor, connection_params, schema_names,
                update_knowledge_base, cache_duration_hours
            )
            pipeline_results["schema_extraction"] = schema_result.result

            # Step 2: Generate SQL query if natural language was provided
            generated_query = sql_query
            if natural_language_query:
                self.logger.info("Step 2: Generating SQL from natural language")
                query_result = await self._query_generation_operation(
                    natural_language_query, database_flavor, connection_params, schema_names
                )
                pipeline_results["query_generation"] = query_result.result
                generated_query = query_result.result.get("sql_query")

            if not generated_query:
                raise ValueError("No valid SQL query to execute")

            # Step 3: Validate the query
            self.logger.info("Step 3: Validating SQL query")
            validation_result = await self._query_validation_operation(
                generated_query, database_flavor, connection_params
            )
            pipeline_results["query_validation"] = validation_result.result

            if not validation_result.result["is_valid"]:
                if dry_run:
                    return ToolResult(
                        status="success",
                        result={
                            "pipeline_results": pipeline_results,
                            "dry_run": True,
                            "query_valid": False
                        },
                        metadata={"operation": "full_pipeline", "dry_run": True}
                    )
                else:
                    raise ValueError(f"Query validation failed: {validation_result.result['errors']}")

            # Step 4: Execute the query (unless dry run)
            if not dry_run:
                self.logger.info("Step 4: Executing validated query")
                execution_result = await self._query_execution_operation(
                    generated_query, database_flavor, connection_params,
                    max_rows, timeout_seconds, output_format, structured_output_schema
                )
                pipeline_results["query_execution"] = execution_result.result

            # Success! Return comprehensive results
            return ToolResult(
                status="success",
                result={
                    "pipeline_results": pipeline_results,
                    "final_query": generated_query,
                    "dry_run": dry_run,
                    "execution_summary": {
                        "rows_returned": len(pipeline_results["query_execution"]["data"]) if not dry_run and pipeline_results["query_execution"] else 0,
                        "execution_time_seconds": pipeline_results["query_execution"]["execution_time"] if not dry_run and pipeline_results["query_execution"] else None,
                        "output_format": output_format.value
                    }
                },
                metadata={
                    "operation": "full_pipeline",
                    "database_flavor": database_flavor.value,
                    "schema_count": len(schema_names),
                    "natural_language_input": natural_language_query is not None,
                    "timestamp": datetime.utcnow().isoformat()
                }
            )

        except Exception as e:
            return ToolResult(
                status="error",
                result={"pipeline_results": pipeline_results},
                error=f"Pipeline failed at step: {str(e)}",
                metadata={"operation": "full_pipeline", "partial_results": True}
            )

    async def _extract_schema_operation(
        self,
        database_flavor: DatabaseFlavor,
        connection_params: Optional[Dict[str, Any]],
        schema_names: List[str],
        update_knowledge_base: bool,
        cache_duration_hours: int
    ) -> ToolResult:
        """Extract database schema metadata and optionally update knowledge base."""
        try:
            # Check cache first
            cache_key = self._generate_schema_cache_key(database_flavor, connection_params, schema_names)
            cached_schema, cache_time = self._schema_cache.get(cache_key, (None, None))

            if cached_schema and cache_time:
                cache_age = datetime.utcnow() - cache_time
                if cache_age < timedelta(hours=cache_duration_hours):
                    self.logger.info(f"Using cached schema metadata (age: {cache_age})")
                    return ToolResult(
                        status="success",
                        result=cached_schema.dict(),
                        metadata={"source": "cache", "cache_age_hours": cache_age.total_seconds() / 3600}
                    )

            # Extract fresh schema metadata
            db_connection = await self._get_database_connection(database_flavor, connection_params)
            schema_metadata = await self._extract_database_schema(db_connection, database_flavor, schema_names)

            # Cache the results
            self._schema_cache[cache_key] = (schema_metadata, datetime.utcnow())

            # Update knowledge base if requested
            if update_knowledge_base and self.knowledge_store:
                await self._update_schema_knowledge_base(schema_metadata)

            return ToolResult(
                status="success",
                result=schema_metadata.dict(),
                metadata={
                    "source": "database",
                    "schema_count": len(schema_names),
                    "table_count": len(schema_metadata.tables),
                    "view_count": len(schema_metadata.views),
                    "knowledge_base_updated": update_knowledge_base and self.knowledge_store is not None
                }
            )

        except Exception as e:
            return ToolResult(
                status="error",
                result=None,
                error=f"Schema extraction failed: {str(e)}",
                metadata={"operation": "schema_extract"}
            )

    # Additional helper methods would continue here...
    # Including _query_generation_operation, _query_validation_operation,
    # _query_execution_operation, and all the database-specific implementations

    def _generate_schema_cache_key(
        self,
        database_flavor: DatabaseFlavor,
        connection_params: Optional[Dict[str, Any]],
        schema_names: List[str]
    ) -> str:
        """Generate a unique cache key for schema metadata."""
        key_data = {
            "flavor": database_flavor.value,
            "params": connection_params or {},
            "schemas": sorted(schema_names)
        }
        return hashlib.md5(json.dumps(key_data, sort_keys=True).encode()).hexdigest()

    async def _get_database_connection(
        self,
        database_flavor: DatabaseFlavor,
        connection_params: Optional[Dict[str, Any]]
    ) -> AsyncDB:
        """Get or create a database connection using AsyncDB."""
        """Get or create a database connection using AsyncDB."""
        # Normalize connection parameters
        params = connection_params.copy() if connection_params else {}

        # Common mapping: username -> user (used by asyncpg and others)
        if 'username' in params and 'user' not in params:
            params['user'] = params.pop('username')

        driver_map = {
            DatabaseFlavor.POSTGRESQL: 'pg',
            DatabaseFlavor.MYSQL: 'mysql',
            DatabaseFlavor.SQLITE: 'sqlite',
        }
        driver = driver_map.get(database_flavor, database_flavor.value)
        return AsyncDB(driver, params=params)

    async def _extract_database_schema(
        self,
        db_connection: AsyncDB,
        database_flavor: DatabaseFlavor,
        schema_names: List[str]
    ) -> SchemaMetadata:
        """Extract comprehensive schema metadata from the database."""
        """Extract comprehensive schema metadata from the database."""
        if database_flavor == DatabaseFlavor.POSTGRESQL:
            return await self._extract_postgresql_schema(db_connection, schema_names)

        raise NotImplementedError(f"Schema extraction not implemented for {database_flavor}")

    async def _extract_postgresql_schema(
        self,
        db: AsyncDB,
        schema_names: List[str]
    ) -> SchemaMetadata:
        """Extract schema for PostgreSQL."""
        tables_data = []
        async with await db.connection() as conn:
            schemas_list = ", ".join([f"'{s}'" for s in schema_names])
            if not schemas_list:
                schemas_list = "'public'" # Default

            query = f"""
                SELECT t.table_schema, t.table_name, c.column_name, c.data_type
                FROM information_schema.tables t
                JOIN information_schema.columns c
                  ON t.table_schema = c.table_schema AND t.table_name = c.table_name
                WHERE t.table_schema IN ({schemas_list})
                ORDER BY t.table_schema, t.table_name, c.ordinal_position
            """
            try:
                rows = await conn.fetch(query) # Using fetch if available, or query
            except Exception:
                # Fallback to query if fetch not available on conn wrapper
                rows = await conn.query(query)

            # Check if rows is a list of lists (result set wrapper)
            if rows and isinstance(rows, list) and len(rows) > 0 and isinstance(rows[0], list):
                rows = rows[0]

            # Process rows
            grouped = {}
            for row in rows:
                # Handle possible dict or object access
                # asyncpg.Record supports .get() and ['key']
                if hasattr(row, 'get'):
                    s_name = row.get('table_schema')
                    t_name = row.get('table_name')
                    c_name = row.get('column_name')
                    d_type = row.get('data_type')
                elif isinstance(row, (list, tuple)) and len(row) >= 4:
                    s_name = row[0]
                    t_name = row[1]
                    c_name = row[2]
                    d_type = row[3]
                else:
                    # Attempt dict access as fallback
                    try:
                        s_name = row['table_schema']
                        t_name = row['table_name']
                        c_name = row['column_name']
                        d_type = row['data_type']
                    except (TypeError, KeyError, IndexError):
                        continue # Skip invalid rows

                k = (s_name, t_name)
                if k not in grouped:
                    grouped[k] = {
                        "schema": s_name,
                        "name": t_name,
                        "columns": []
                    }
                grouped[k]["columns"].append({"name": c_name, "type": d_type})

            tables_data = list(grouped.values())

        return SchemaMetadata(
            schema_name=",".join(schema_names),
            tables=tables_data,
            views=[],
            functions=[],
            procedures=[],
            indexes=[],
            constraints=[],
            last_updated=datetime.utcnow(),
            database_flavor=DatabaseFlavor.POSTGRESQL
        )

    async def _query_generation_operation(
        self,
        natural_language_query: str,
        database_flavor: DatabaseFlavor,
        connection_params: Optional[Dict[str, Any]],
        schema_names: List[str]
    ) -> ToolResult:
        """Generate SQL query from natural language using schema context."""
        try:
            # Get schema context for query generation
            schema_key = self._generate_schema_cache_key(database_flavor, connection_params, schema_names)
            cached_schema, _ = self._schema_cache.get(schema_key, (None, None))

            if not cached_schema:
                # If no cached schema, extract it first
                schema_result = await self._extract_schema_operation(
                    database_flavor, connection_params, schema_names, False, 24
                )
                if schema_result.status != "success" or not schema_result.result:
                    raise ValueError(f"Schema extraction failed: {schema_result.error or 'No result returned'}")

                cached_schema = SchemaMetadata(**schema_result.result)

            # Use database-specific query generator
            generator = self._query_generators.get(database_flavor)
            if not generator:
                raise ValueError(f"No query generator available for {database_flavor.value}")

            # Build rich context for LLM query generation
            schema_context = self._build_schema_context_for_llm(cached_schema, natural_language_query)

            # Generate the SQL query
            generated_sql = await generator(natural_language_query, schema_context)
            generated_sql = self._clean_sql(generated_sql)

            return ToolResult(
                status="success",
                result={
                    "natural_language_query": natural_language_query,
                    "sql_query": generated_sql,
                    "database_flavor": database_flavor.value,
                    "schema_context_used": len(schema_context.get("relevant_tables", [])),
                    "generation_timestamp": datetime.utcnow().isoformat()
                },
                metadata={
                    "operation": "query_generation",
                    "has_schema_context": bool(schema_context)
                }
            )

        except Exception as e:
            return ToolResult(
                status="error",
                result=None,
                error=f"Query generation failed: {str(e)}",
                metadata={"operation": "query_generation"}
            )

    async def _query_validation_operation(
        self,
        sql_query: str,
        database_flavor: DatabaseFlavor,
        connection_params: Optional[Dict[str, Any]]
    ) -> ToolResult:
        """Validate SQL query for syntax, security, and performance."""
        try:
            validator = self._query_validators.get(database_flavor)
            if not validator:
                raise ValueError(f"No query validator available for {database_flavor.value}")

            validation_result = await validator(sql_query)

            return ToolResult(
                status="success" if validation_result.is_valid else "warning",
                result=validation_result.dict(),
                metadata={
                    "operation": "query_validation",
                    "query_type": validation_result.query_type.value if validation_result.query_type else None
                }
            )

        except Exception as e:
            return ToolResult(
                status="error",
                result=None,
                error=f"Query validation failed: {str(e)}",
                metadata={"operation": "query_validation"}
            )

    async def _query_execution_operation(
        self,
        sql_query: str,
        database_flavor: DatabaseFlavor,
        connection_params: Optional[Dict[str, Any]],
        max_rows: int,
        timeout_seconds: int,
        output_format: OutputFormat,
        structured_output_schema: Optional[Dict[str, Any]]
    ) -> ToolResult:
        """Execute SQL query and format results according to specifications."""
        try:
            db_connection = await self._get_database_connection(database_flavor, connection_params)

            # Execute query with timeout and row limit
            start_time = datetime.utcnow()

            # This integrates your existing DatabaseQueryTool logic
            raw_results = await self._execute_query_with_asyncdb(
                db_connection, sql_query, max_rows, timeout_seconds
            )

            execution_time = (datetime.utcnow() - start_time).total_seconds()

            # Format results according to specified output format
            formatted_results = await self._format_query_results(
                raw_results, output_format, structured_output_schema
            )

            return ToolResult(
                status="success",
                result={
                    "data": formatted_results,
                    "row_count": len(raw_results) if isinstance(raw_results, list) else None,
                    "execution_time": execution_time,
                    "output_format": output_format.value,
                    "query": sql_query
                },
                metadata={
                    "operation": "query_execution",
                    "database_flavor": database_flavor.value,
                    "rows_returned": len(raw_results) if isinstance(raw_results, list) else 0
                }
            )

        except Exception as e:
            return ToolResult(
                status="error",
                result=None,
                error=f"Query execution failed: {str(e)}",
                metadata={"operation": "query_execution", "query": sql_query}
            )

    async def _explain_query_operation(
        self,
        sql_query: str,
        database_flavor: DatabaseFlavor,
        connection_params: Optional[Dict[str, Any]]
    ) -> ToolResult:
        """
        Explain query execution plan and provide LLM-based optimizations.
        """
        if not sql_query:
             return ToolResult(
                status="error",
                result=None,
                error="No SQL query provided for explanation",
                metadata={"operation": "explain_query"}
            )

        try:
            db_connection = await self._get_database_connection(database_flavor, connection_params)

            # Determine appropriate EXPLAIN command
            explain_cmd = f"EXPLAIN ANALYZE {sql_query}"
            if database_flavor == DatabaseFlavor.MYSQL:
                 # MySQL 8.0.18+ supports EXPLAIN ANALYZE, otherwise fallback to EXPLAIN
                 # For safety/compatibility we might start with EXPLAIN if ANALYZE fails or just try
                 explain_cmd = f"EXPLAIN ANALYZE {sql_query}"
            elif database_flavor == DatabaseFlavor.BIGQUERY:
                 # BigQuery doesn't support EXPLAIN ANALYZE syntax directly in this way usually
                 # It returns stats in job metadata.
                 # But we can try to use Dry Run or similar.
                 # For now, let's assume standard SQL syntax applies or let execution fail and fallback
                 pass

            # Execute explanation
            try:
                raw_plan = await self._execute_query_with_asyncdb(
                    db_connection, explain_cmd, max_rows=0, timeout_seconds=30
                )
            except Exception as e:
                # Fallback to simple EXPLAIN if ANALYZE fails (e.g. not supported or timeouts)
                self.logger.warning(f"EXPLAIN ANALYZE failed, falling back to EXPLAIN: {e}")
                explain_cmd = f"EXPLAIN {sql_query}"
                raw_plan = await self._execute_query_with_asyncdb(
                    db_connection, explain_cmd, max_rows=0, timeout_seconds=30
                )

            # Format plan into string
            plan_text = ""
            if isinstance(raw_plan, list):
                # Flatten the list of rows/dicts
                for row in raw_plan:
                    if isinstance(row, dict):
                        # Usually the first column contains the plan output
                        plan_text += list(row.values())[0] + "\n"
                    elif isinstance(row, (list, tuple)):
                        plan_text += str(row[0]) + "\n"
                    else:
                        plan_text += str(row) + "\n"
            else:
                plan_text = str(raw_plan)

            # Ask LLM to explain and optimize
            llm_explanation = "No LLM configured for explanation."
            if self.llm:
                prompt = (
                    f"You are a database performance expert. Analyze the following query plan for a {database_flavor.value} database.\n"
                    f"Query:\n```sql\n{sql_query}\n```\n\n"
                    f"Execution Plan:\n```\n{plan_text}\n```\n\n"
                    "Please provide:\n"
                    "1. A human-readable explanation of how the query is executed.\n"
                    "2. Performance bottlenecks identified in the plan.\n"
                    "3. Concrete suggestions for indexes or query rewrites to improve performance.\n"
                    "4. Rating of current query efficiency (1-10)."
                )

                response = await self.llm.ask(prompt)
                if isinstance(response, AIMessage):
                    llm_explanation = str(response.output).strip()
                elif isinstance(response, dict) and 'content' in response:
                    llm_explanation = str(response['content']).strip()
                else:
                    llm_explanation = str(response).strip()

            return ToolResult(
                status="success",
                result={
                    "query": sql_query,
                    "plan": plan_text,
                    "analysis": llm_explanation,
                    "database_flavor": database_flavor.value
                },
                metadata={
                    "operation": "explain_query",
                    "command_used": explain_cmd
                }
            )

        except Exception as e:
            return ToolResult(
                status="error",
                result=None,
                error=f"Query explanation failed: {str(e)}",
                metadata={"operation": "explain_query"}
            )

    def _build_schema_context_for_llm(
        self,
        schema_metadata: SchemaMetadata,
        natural_language_query: str
    ) -> Dict[str, Any]:
        """
        Build rich schema context for LLM query generation.

        This is a critical method that determines query generation quality.
        It intelligently selects relevant schema elements based on the natural language query.
        """
        # Use vector similarity or keyword matching to find relevant tables
        relevant_tables = self._find_relevant_tables(schema_metadata, natural_language_query)

        # Build comprehensive context including relationships, constraints, and sample data
        context = {
            "database_flavor": schema_metadata.database_flavor.value,
            "schema_name": schema_metadata.schema_name,
            "relevant_tables": relevant_tables,
            "table_relationships": self._extract_table_relationships(schema_metadata, relevant_tables),
            "common_patterns": self._get_query_patterns_for_tables(relevant_tables),
            "data_types_guide": self._get_data_type_guide(schema_metadata.database_flavor)
        }

        return context

    async def _execute_query_with_asyncdb(
        self,
        db_connection: AsyncDB,
        sql_query: str,
        max_rows: int,
        timeout_seconds: int
    ) -> Any:
        """Execute query using AsyncDB with proper error handling and limits."""
        # This integrates your existing DatabaseQueryTool execution logic
        # but with enhanced error handling and result limiting

        try:
            # Add LIMIT clause if not present and max_rows is specified
            if max_rows > 0 and "LIMIT" not in sql_query.upper():
                sql_query = f"{sql_query.rstrip(';')} LIMIT {max_rows};"

            # Execute with timeout using asyncio
            async with await db_connection.connection() as conn:
                return await asyncio.wait_for(
                    conn.fetchall(sql_query),
                    timeout=timeout_seconds
                )

        except asyncio.TimeoutError as e:
            raise TimeoutError(
                f"Query execution timed out after {timeout_seconds} seconds"
            ) from e
        except Exception as e:
            raise RuntimeError(
                f"Database execution error: {str(e)}"
            ) from e

    async def _format_query_results(
        self,
        raw_results: Any,
        output_format: OutputFormat,
        structured_output_schema: Optional[Dict[str, Any]]
    ) -> Any:
        """Format query results according to specified output format."""
        if output_format == OutputFormat.PANDAS:
            return pd.DataFrame(raw_results) if raw_results else pd.DataFrame()
        elif output_format == OutputFormat.JSON:
            return json.dumps(raw_results, default=str, indent=2)
        elif output_format == OutputFormat.DICT:
            return raw_results
        elif output_format == OutputFormat.CSV:
            df = pd.DataFrame(raw_results) if raw_results else pd.DataFrame()
            return df.to_csv(index=False)
        elif output_format == OutputFormat.STRUCTURED and structured_output_schema:
            # Convert results to Pydantic models based on provided schema
            return self._convert_to_structured_output(raw_results, structured_output_schema)
        else:
            return raw_results

    # Database-specific implementations (these would replace your current separate tools)
    async def _generate_postgresql_query(self, natural_language: str, schema_context: Dict) -> str:
        """
        Generate PostgreSQL-specific SQL from natural language.

        This method would integrate your existing SQLAgent logic but with enhanced
        schema context and PostgreSQL-specific optimizations.
        """
        # Build prompt with rich schema context
        prompt = self._build_query_generation_prompt(
            natural_language, schema_context, "postgresql"
        )

        # Use your existing LLM client to generate the query
        # This would integrate with your AI-Parrot LLM clients
        return await self._call_llm_for_query_generation(prompt)

    async def _validate_postgresql_query(self, query: str) -> QueryValidationResult:
        """
        Validate PostgreSQL query for syntax, security, and performance.

        This provides the validation layer that was missing from your current SQLAgent.
        """
        validation_result = QueryValidationResult(
            is_valid=True,
            query_type=None,
            affected_tables=[],
            estimated_cost=None,
            warnings=[],
            errors=[],
            security_checks={}
        )

        try:
            # Parse query to determine type and affected tables
            query_upper = query.strip().upper()
            if query_upper.startswith('SELECT'):
                validation_result.query_type = QueryType.SELECT
            elif query_upper.startswith('INSERT'):
                validation_result.query_type = QueryType.INSERT
            # ... other query types

            # Security checks
            validation_result.security_checks = {
                "no_sql_injection_patterns": self._check_sql_injection_patterns(query),
                "no_dangerous_operations": self._check_dangerous_operations(query),
                "proper_quoting": self._check_proper_quoting(query)
            }

            # Syntax validation (could use sqlparse or connect to database for EXPLAIN)
            syntax_valid = await self._validate_syntax_postgresql(query)
            if not syntax_valid:
                validation_result.is_valid = False
                validation_result.errors.append("Invalid SQL syntax")

            # Performance warnings
            if "SELECT *" in query_upper:
                validation_result.warnings.append("Consider specifying explicit columns instead of SELECT *")

            return validation_result

        except Exception as e:
            validation_result.is_valid = False
            validation_result.errors.append(f"Validation error: {str(e)}")
            return validation_result

    def _check_dangerous_operations(self, query: str) -> bool:
        """
        Check if query contains dangerous operations that should be blocked.

        Returns:
            True if query is SAFE (no dangerous operations)
            False if dangerous operations detected
        """
        query_upper = query.upper()

        dangerous_patterns = [
            # DDL operations
            r'\bDROP\s+(TABLE|DATABASE|SCHEMA|INDEX|VIEW|PROCEDURE|FUNCTION)\b',
            r'\bTRUNCATE\s+TABLE\b',
            r'\bALTER\s+(TABLE|DATABASE|SCHEMA)\s+.*\s+DROP\b',
            # DML without WHERE
            r'\bDELETE\s+FROM\s+\w+\s*;?\s*$',
            # Admin commands
            r'\bGRANT\b',
            r'\bREVOKE\b',
            r'\bCREATE\s+USER\b',
            r'\bDROP\s+USER\b',
            r'\bALTER\s+USER\b',
            # Command execution (PostgreSQL)
            r'\bCOPY\s+.*\s+TO\s+PROGRAM\b',
            # SQL Server
            r'\bEXEC\s*\(',
            r'\bXP_CMDSHELL\b',
            # MySQL file operations
            r'\bLOAD_FILE\b',
            r'\bINTO\s+OUTFILE\b',
            r'\bINTO\s+DUMPFILE\b',
        ]

        for pattern in dangerous_patterns:
            if re.search(pattern, query_upper, re.IGNORECASE | re.DOTALL):
                return False

        # Check DELETE/UPDATE without WHERE
        if re.search(r'\bDELETE\s+FROM\s+\w+\s*$', query_upper):
            return False

        update_match = re.search(r'\bUPDATE\s+\w+\s+SET\s+', query_upper)
        if update_match and 'WHERE' not in query_upper:
            return False

        return True

    def _check_sql_injection_patterns(self, query: str) -> bool:
        """
        Check for common SQL injection patterns.

        Returns:
            True if no injection patterns found (SAFE)
            False if potential injection detected
        """
        injection_patterns = [
            # Union/Boolean-based
            r"'\s*(OR|AND)\s+['\"0-9]",
            r"'\s*OR\s+1\s*=\s*1",
            r"'\s*OR\s+'[^']*'\s*=\s*'[^']*'",
            # Comment-based
            r";\s*--",
            r";\s*/\*",
            r"--\s*$",
            # Stacked queries
            r"'\s*;\s*(DROP|DELETE|UPDATE|INSERT|EXEC)\b",
            r";\s*(SELECT|INSERT|UPDATE|DELETE|DROP|CREATE|ALTER)\b",
            # UNION injection
            r"\bUNION\s+(ALL\s+)?SELECT\b.*\bFROM\b",
            # Time-based
            r"\bSLEEP\s*\(",
            r"\bWAITFOR\s+DELAY\b",
            r"\bBENCHMARK\s*\(",
            r"\bPG_SLEEP\s*\(",
            # Encoding attempts
            r"0x[0-9a-fA-F]+",
            r"\bCHAR\s*\(\s*\d+\s*\)",
        ]

        for pattern in injection_patterns:
            if re.search(pattern, query, re.IGNORECASE):
                return False

        return True

    def _check_proper_quoting(self, query: str) -> bool:
        """
        Check if string literals are properly quoted.

        Returns:
            True if quoting appears proper (SAFE)
            False if improper quoting detected
        """
        # Check for unbalanced quotes
        single_quotes = query.count("'") - query.count("\\'") - query.count("''")
        double_quotes = query.count('"') - query.count('\\"') - query.count('""')

        if single_quotes % 2 != 0 or double_quotes % 2 != 0:
            return False

        # Check for dangerous patterns after string literals
        dangerous_patterns = [
            r"'\s*\)\s*(OR|AND|UNION)\b",
            r"'\s*;\s*\w+",
        ]

        for pattern in dangerous_patterns:
            if re.search(pattern, query, re.IGNORECASE):
                return False

        return True

    async def _validate_syntax_postgresql(self, query: str) -> bool:
        """Validate PostgreSQL query syntax using pattern matching."""
        try:
            query_stripped = query.strip().rstrip(';')
            query_upper = query_stripped.upper()

            valid_starts = [
                'SELECT', 'INSERT', 'UPDATE', 'DELETE', 'WITH',
                'CREATE', 'ALTER', 'DROP', 'TRUNCATE',
                'BEGIN', 'COMMIT', 'ROLLBACK', 'SAVEPOINT',
                'EXPLAIN', 'ANALYZE', 'VACUUM', 'REINDEX',
                'GRANT', 'REVOKE', 'SET', 'SHOW', 'RESET',
                'COPY', 'CALL', 'DO', 'LOCK',
            ]

            first_word = query_upper.split()[0] if query_stripped else ''
            if first_word not in valid_starts:
                return False

            # Validate statement structures
            if query_upper.startswith('INSERT') and 'INTO' not in query_upper:
                return False
            if query_upper.startswith('UPDATE') and 'SET' not in query_upper:
                return False
            if query_upper.startswith('DELETE') and 'FROM' not in query_upper:
                return False

            # Check balance
            if query.count('(') != query.count(')'):
                return False
            if query.count('[') != query.count(']'):
                return False

            return True
        except Exception:
            return False

    # =========================================================================
    # MYSQL METHODS
    # =========================================================================

    async def _generate_mysql_query(
        self,
        natural_language: str,
        schema_context: Dict[str, Any]
    ) -> str:
        """Generate MySQL-specific SQL from natural language."""
        prompt = self._build_query_generation_prompt(
            natural_language, schema_context, "mysql"
        )

        mysql_instructions = """
MySQL-Specific Rules:
1. Use backticks (`) for identifier quoting
2. Use LIMIT for row limiting
3. Use IFNULL() instead of COALESCE() for two arguments
4. Use NOW() for current timestamp
5. Use DATE_FORMAT() for date formatting
6. Use CONCAT() for string concatenation
7. Boolean values are 1/0
8. Use REGEXP for regex matching
"""

        generated_query = await self._call_llm_for_query_generation(
            f"{prompt}\n\n{mysql_instructions}"
        )

        return self._ensure_mysql_compatibility(generated_query)

    def _ensure_mysql_compatibility(self, query: str) -> str:
        """Post-process query to ensure MySQL compatibility."""
        result = query

        # Replace double quotes with backticks for identifiers
        result = re.sub(r'"(\w+)"(?=\s*[,.\)\s]|$)', r'`\1`', result)

        # Replace COALESCE with two args to IFNULL
        result = re.sub(
            r'\bCOALESCE\s*\(\s*([^,]+)\s*,\s*([^,\)]+)\s*\)',
            r'IFNULL(\1, \2)',
            result,
            flags=re.IGNORECASE
        )

        # Replace TRUE/FALSE with 1/0
        result = re.sub(r'\bTRUE\b', '1', result, flags=re.IGNORECASE)
        result = re.sub(r'\bFALSE\b', '0', result, flags=re.IGNORECASE)

        return result

    async def _validate_mysql_query(self, query: str) -> QueryValidationResult:
        """Validate MySQL query for syntax, security, and performance."""
        validation_result = QueryValidationResult(
            is_valid=True,
            query_type=None,
            affected_tables=[],
            estimated_cost=None,
            warnings=[],
            errors=[],
            security_checks={}
        )

        try:
            query_upper = query.strip().upper()

            # Determine query type
            for qt in QueryType:
                if query_upper.startswith(qt.value):
                    validation_result.query_type = qt
                    break

            # Extract tables
            validation_result.affected_tables = self._extract_tables_from_query(query)

            # Security checks
            validation_result.security_checks = {
                "no_sql_injection_patterns": self._check_sql_injection_patterns(query),
                "no_dangerous_operations": self._check_dangerous_operations(query),
                "proper_quoting": self._check_proper_quoting(query)
            }

            if not all(validation_result.security_checks.values()):
                validation_result.is_valid = False
                for check, passed in validation_result.security_checks.items():
                    if not passed:
                        validation_result.errors.append(f"Security check failed: {check}")

            # Syntax validation
            if not await self._validate_syntax_mysql(query):
                validation_result.is_valid = False
                validation_result.errors.append("Invalid MySQL syntax")

            # Performance warnings
            if "SELECT *" in query_upper:
                validation_result.warnings.append("Consider specifying explicit columns")

            if re.search(r"LIKE\s*'%", query, re.IGNORECASE):
                validation_result.warnings.append("Leading wildcard may prevent index usage")

            return validation_result

        except Exception as e:
            validation_result.is_valid = False
            validation_result.errors.append(f"Validation error: {str(e)}")
            return validation_result

    async def _validate_syntax_mysql(self, query: str) -> bool:
        """Validate MySQL-specific query syntax."""
        try:
            query_stripped = query.strip().rstrip(';')
            query_upper = query_stripped.upper()

            valid_starts = [
                'SELECT', 'INSERT', 'UPDATE', 'DELETE', 'REPLACE',
                'CREATE', 'ALTER', 'DROP', 'TRUNCATE', 'RENAME',
                'START', 'BEGIN', 'COMMIT', 'ROLLBACK', 'SAVEPOINT',
                'SET', 'SHOW', 'DESCRIBE', 'DESC', 'EXPLAIN',
                'GRANT', 'REVOKE', 'LOCK', 'UNLOCK', 'USE', 'WITH',
            ]

            first_word = query_upper.split()[0] if query_stripped else ''
            if first_word not in valid_starts:
                return False

            # Validate statement structures
            if first_word in ('INSERT', 'REPLACE') and 'INTO' not in query_upper:
                return False
            if first_word == 'UPDATE' and 'SET' not in query_upper:
                return False

            # Check balance
            if query.count('(') != query.count(')'):
                return False
            if query.count('`') % 2 != 0:
                return False

            return True
        except Exception:
            return False

    # =========================================================================
    # BIGQUERY METHODS
    # =========================================================================

    async def _generate_bigquery_query(
        self,
        natural_language: str,
        schema_context: Dict[str, Any]
    ) -> str:
        """Generate BigQuery-specific SQL from natural language."""
        prompt = self._build_query_generation_prompt(
            natural_language, schema_context, "bigquery"
        )

        bigquery_instructions = """
BigQuery-Specific Rules:
1. Use backticks for table names: `project.dataset.table`
2. Use STRUCT<> and ARRAY<> for complex types
3. Use UNNEST() to flatten arrays
4. Use SAFE_DIVIDE() for division with potential zeros
5. Use FORMAT_DATE/FORMAT_TIMESTAMP for date formatting
6. Use DATE_DIFF, TIMESTAMP_DIFF for date differences
7. Use QUALIFY clause for window function filtering
8. Use Standard SQL (prefix with #standardSQL if needed)
"""

        generated_query = await self._call_llm_for_query_generation(
            f"{prompt}\n\n{bigquery_instructions}"
        )

        return self._ensure_bigquery_compatibility(generated_query)

    def _ensure_bigquery_compatibility(self, query: str) -> str:
        """Post-process query to ensure BigQuery compatibility."""
        result = query

        # Quote project.dataset.table names
        result = re.sub(
            r'(?<![`\w])(\w+)\.(\w+)\.(\w+)(?![`\w])',
            r'`\1.\2.\3`',
            result
        )

        # Replace NOW() with CURRENT_TIMESTAMP()
        result = re.sub(r'\bNOW\s*\(\s*\)', 'CURRENT_TIMESTAMP()', result, flags=re.IGNORECASE)

        # Replace GETDATE()
        result = re.sub(r'\bGETDATE\s*\(\s*\)', 'CURRENT_TIMESTAMP()', result, flags=re.IGNORECASE)

        return result

    async def _validate_bigquery_query(self, query: str) -> QueryValidationResult:
        """Validate BigQuery query for syntax, security, and performance."""
        validation_result = QueryValidationResult(
            is_valid=True,
            query_type=None,
            affected_tables=[],
            estimated_cost=None,
            warnings=[],
            errors=[],
            security_checks={}
        )

        try:
            query_upper = query.strip().upper()

            # Remove SQL dialect prefix
            if query_upper.startswith('#'):
                newline_idx = query.find('\n')
                if newline_idx > 0:
                    query_upper = query[newline_idx:].strip().upper()

            # Determine query type
            if query_upper.startswith(('SELECT', 'WITH')):
                validation_result.query_type = QueryType.SELECT
            elif query_upper.startswith('MERGE'):
                validation_result.query_type = QueryType.UPDATE
            else:
                for qt in QueryType:
                    if query_upper.startswith(qt.value):
                        validation_result.query_type = qt
                        break

            # Extract tables
            validation_result.affected_tables = self._extract_bigquery_tables(query)

            # Security checks
            validation_result.security_checks = {
                "no_sql_injection_patterns": self._check_sql_injection_patterns(query),
                "no_dangerous_operations": self._check_dangerous_bigquery_operations(query),
                "proper_quoting": self._check_proper_quoting(query)
            }

            if not all(validation_result.security_checks.values()):
                validation_result.is_valid = False
                for check, passed in validation_result.security_checks.items():
                    if not passed:
                        validation_result.errors.append(f"Security check failed: {check}")

            # Syntax validation
            if not await self._validate_syntax_bigquery(query):
                validation_result.is_valid = False
                validation_result.errors.append("Invalid BigQuery SQL syntax")

            # Performance warnings
            if "SELECT *" in query_upper:
                validation_result.warnings.append(
                    "SELECT * scans all columns - specify needed columns for cost reduction"
                )

            if 'WHERE' not in query_upper and '_PARTITIONTIME' not in query_upper:
                validation_result.warnings.append(
                    "Consider adding partition filter for cost reduction"
                )

            if query.strip().startswith('#legacySQL'):
                validation_result.warnings.append("Consider migrating to Standard SQL")

            return validation_result

        except Exception as e:
            validation_result.is_valid = False
            validation_result.errors.append(f"Validation error: {str(e)}")
            return validation_result

    def _check_dangerous_bigquery_operations(self, query: str) -> bool:
        """Check for dangerous BigQuery operations. Returns True if SAFE."""
        query_upper = query.upper()

        dangerous_patterns = [
            r'\bDROP\s+(TABLE|SCHEMA|VIEW|FUNCTION)\b',
            r'\bTRUNCATE\s+TABLE\b',
            r'\bDELETE\s+FROM\s+`[^`]+`\s*$',
            r'\bDROP\s+ALL\s+ROW\s+ACCESS\s+POLICIES\b',
        ]

        for pattern in dangerous_patterns:
            if re.search(pattern, query_upper, re.IGNORECASE | re.DOTALL):
                return False

        return True

    def _extract_bigquery_tables(self, query: str) -> List[str]:
        """Extract table names from BigQuery query."""
        tables = set()

        # Backtick-quoted fully-qualified names
        tables.update(re.findall(r'`([a-zA-Z0-9_-]+\.[a-zA-Z0-9_-]+\.[a-zA-Z0-9_-]+)`', query))
        tables.update(re.findall(r'`([a-zA-Z0-9_-]+\.[a-zA-Z0-9_-]+)`', query))

        # Standard table references
        tables.update(self._extract_tables_from_query(query))

        return list(tables)

    async def _validate_syntax_bigquery(self, query: str) -> bool:
        """Validate BigQuery-specific query syntax."""
        try:
            query_stripped = query.strip()

            if query_stripped.startswith('#'):
                newline_idx = query_stripped.find('\n')
                if newline_idx > 0:
                    query_stripped = query_stripped[newline_idx:].strip()

            query_stripped = query_stripped.rstrip(';')
            query_upper = query_stripped.upper()

            valid_starts = [
                'SELECT', 'INSERT', 'UPDATE', 'DELETE', 'MERGE',
                'CREATE', 'ALTER', 'DROP', 'TRUNCATE', 'WITH',
                'DECLARE', 'SET', 'EXECUTE', 'BEGIN', 'IF',
                'EXPORT', 'LOAD', 'GRANT', 'REVOKE', 'ASSERT',
            ]

            first_word = query_upper.split()[0] if query_stripped else ''
            if first_word not in valid_starts:
                return False

            # Check balance
            if query.count('(') != query.count(')'):
                return False
            if query.count('`') % 2 != 0:
                return False
            if query.count('[') != query.count(']'):
                return False
            if query.count('<') != query.count('>'):
                return False

            return True
        except Exception:
            return False

    # =========================================================================
    # HELPER METHODS
    # =========================================================================

    def _extract_tables_from_query(self, query: str) -> List[str]:
        """Extract table names from SQL query."""
        tables = set()

        patterns = [
            r'\bFROM\s+([`"\[]?[\w.-]+[`"\]]?)',
            r'\bJOIN\s+([`"\[]?[\w.-]+[`"\]]?)',
            r'\bINSERT\s+INTO\s+([`"\[]?[\w.-]+[`"\]]?)',
            r'\bUPDATE\s+([`"\[]?[\w.-]+[`"\]]?)',
            r'\bDELETE\s+FROM\s+([`"\[]?[\w.-]+[`"\]]?)',
        ]

        for pattern in patterns:
            for match in re.findall(pattern, query, re.IGNORECASE):
                tables.add(match.strip('`"[]'))

        return list(tables)

    def _find_relevant_tables(
        self,
        schema_metadata: SchemaMetadata,
        natural_language_query: str
    ) -> List[Dict[str, Any]]:
        """Find tables relevant to the natural language query."""
        relevant_tables = []
        query_lower = natural_language_query.lower()

        keywords = set(re.findall(r'\b\w+\b', query_lower))

        stop_words = {
            'the', 'a', 'an', 'is', 'are', 'was', 'were', 'be', 'been',
            'have', 'has', 'had', 'do', 'does', 'did', 'will', 'would',
            'could', 'should', 'may', 'might', 'must', 'shall', 'can',
            'to', 'of', 'in', 'for', 'on', 'with', 'at', 'by', 'from',
            'and', 'or', 'but', 'if', 'as', 'show', 'get', 'find', 'list',
            'give', 'tell', 'me', 'i', 'you', 'we', 'they', 'select', 'all',
        }

        keywords = keywords - stop_words

        for table in schema_metadata.tables:
            table_name = table.get('table_name', '').lower()
            columns = table.get('columns', [])

            score = 0
            matched_columns = []

            # Check table name
            table_words = set(re.findall(r'\w+', table_name))
            if table_words & keywords:
                score += 10

            for keyword in keywords:
                if keyword in table_name:
                    score += 5

            # Check columns
            for column in columns:
                col_name = column.get('column_name', '').lower()
                col_words = set(re.findall(r'\w+', col_name))

                if col_words & keywords:
                    score += 3
                    matched_columns.append(col_name)

                for keyword in keywords:
                    if keyword in col_name and col_name not in matched_columns:
                        score += 1
                        matched_columns.append(col_name)

            if score > 0:
                relevant_tables.append({
                    'table_name': table.get('table_name'),
                    'schema': table.get('schema', schema_metadata.schema_name),
                    'columns': columns,
                    'matched_columns': matched_columns,
                    'relevance_score': score,
                    'comment': table.get('comment', '')
                })

        relevant_tables.sort(key=lambda x: x['relevance_score'], reverse=True)
        return relevant_tables[:10]

    def _extract_table_relationships(
        self,
        schema_metadata: SchemaMetadata,
        relevant_tables: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """Extract relationships between relevant tables."""
        relationships = []
        relevant_table_names = {t['table_name'] for t in relevant_tables}

        # From constraints
        for constraint in schema_metadata.constraints:
            if constraint.get('constraint_type') == 'FOREIGN KEY':
                source_table = constraint.get('table_name')
                target_table = constraint.get('referenced_table')

                if source_table in relevant_table_names or target_table in relevant_table_names:
                    relationships.append({
                        'type': 'foreign_key',
                        'source_table': source_table,
                        'source_column': constraint.get('column_name'),
                        'target_table': target_table,
                        'target_column': constraint.get('referenced_column'),
                    })

        # Infer from naming conventions
        for table in relevant_tables:
            for column in table.get('columns', []):
                col_name = column.get('column_name', '')

                if col_name.endswith('_id'):
                    potential_table = col_name[:-3]
                    for pt in [potential_table, potential_table + 's', potential_table + 'es']:
                        if pt in relevant_table_names:
                            relationships.append({
                                'type': 'inferred',
                                'source_table': table['table_name'],
                                'source_column': col_name,
                                'target_table': pt,
                                'target_column': 'id',
                            })
                            break

        return relationships

    def _get_query_patterns_for_tables(
        self,
        relevant_tables: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """Generate common query patterns for relevant tables."""
        patterns = []

        for table in relevant_tables[:3]:
            table_name = table['table_name']
            columns = table.get('columns', [])

            if columns:
                col_list = ', '.join([c['column_name'] for c in columns[:5]])
                patterns.append({
                    'description': f'Select from {table_name}',
                    'pattern': f'SELECT {col_list} FROM {table_name} WHERE ...',
                })

            if numeric_cols := [
                c for c in columns if c.get('data_type', '').lower() in (
                    'integer', 'int', 'bigint', 'numeric', 'decimal', 'float'
                )
            ]:
                patterns.append({
                    'description': f'Aggregate {table_name}',
                    'pattern': f'SELECT COUNT(*), SUM({numeric_cols[0]["column_name"]}) FROM {table_name} GROUP BY ...',
                })

        return patterns

    def _get_data_type_guide(self, database_flavor: DatabaseFlavor) -> Dict[str, Any]:
        """Get data type information for database flavor."""
        guides = {
            DatabaseFlavor.POSTGRESQL: {
                'string_concat': '|| operator or CONCAT()',
                'null_handling': 'IS NULL / IS NOT NULL, COALESCE()',
                'boolean_type': 'BOOLEAN',
            },
            DatabaseFlavor.MYSQL: {
                'string_concat': 'CONCAT() function',
                'null_handling': 'IS NULL / IS NOT NULL, IFNULL()',
                'boolean_type': 'TINYINT(1)',
            },
            DatabaseFlavor.BIGQUERY: {
                'string_concat': 'CONCAT() or ||',
                'null_handling': 'IS NULL / IS NOT NULL, IFNULL(), COALESCE()',
                'boolean_type': 'BOOL',
            }
        }
        return guides.get(database_flavor, guides[DatabaseFlavor.POSTGRESQL])

    def _build_query_generation_prompt(
        self,
        natural_language: str,
        schema_context: Dict[str, Any],
        dialect: str
    ) -> str:
        """Build prompt for LLM query generation."""
        prompt_parts = [
            f"Generate a {dialect.upper()} SQL query for:",
            f"\nRequest: {natural_language}",
            f"\nDatabase: {schema_context.get('database_flavor', dialect).upper()}",
            "\n\nAvailable Tables:",
        ]

        for table in schema_context.get('relevant_tables', [])[:5]:
            prompt_parts.append(f"\n\nTable: {table.get('table_name')}")
            columns = table.get('columns', [])[:15]
            if columns:
                prompt_parts.append("\nColumns:")
                for col in columns:
                    col_info = f"  - {col.get('column_name')}: {col.get('data_type', 'unknown')}"
                    prompt_parts.append(col_info)

        relationships = schema_context.get('table_relationships', [])
        if relationships:
            prompt_parts.append("\n\nRelationships:")
            for rel in relationships[:5]:
                prompt_parts.append(
                    f"  - {rel['source_table']}.{rel['source_column']} -> "
                    f"{rel['target_table']}.{rel['target_column']}"
                )

        prompt_parts.append("\n\nGenerate only the SQL query, no explanations:")
        return '\n'.join(prompt_parts)

    async def _call_llm_for_query_generation(self, prompt: str) -> str:
        """Call LLM client to generate SQL query."""
        system_msg = "You are a SQL expert. Generate precise SQL queries. Return only the SQL, no explanations."

        if self.llm:
            response = await self.llm.ask(prompt, system_prompt=system_msg)
            if isinstance(response, AIMessage):
                return str(response.output).strip()
            # Handle possible dict response if client doesn't return AIMessage (fallback)
            elif isinstance(response, dict) and 'content' in response:
                 # Should extract text
                 return str(response['content']).strip() # Simplified fallback
            return str(response).strip()

        if hasattr(self, 'agent') and self.agent:
            response = await self.agent.llm.acomplete(prompt, system_message=system_msg)
            return response.strip()

        if hasattr(self, 'llm_client') and self.llm_client:
            response = await self.llm_client.acomplete(prompt)
            return response.strip()

        raise ValueError(
            "No LLM client configured. Provide an 'llm', 'agent' or 'llm_client' to DatabaseTool."
        )

    async def _update_schema_knowledge_base(
        self,
        schema_metadata: SchemaMetadata
    ) -> None:
        """Update knowledge store with schema metadata for RAG."""
        if not self.knowledge_store:
            return

        documents = []

        for table in schema_metadata.tables:
            table_name = table.get('table_name')
            columns = table.get('columns', [])

            column_descriptions = [
                f"{col.get('column_name')} ({col.get('data_type', 'unknown')})"
                for col in columns
            ]

            doc_text = f"""
Table: {schema_metadata.schema_name}.{table_name}
Database: {schema_metadata.database_flavor.value}
Columns: {', '.join(column_descriptions)}
"""

            documents.append({
                'content': doc_text,
                'metadata': {
                    'type': 'database_schema',
                    'schema': schema_metadata.schema_name,
                    'table': table_name,
                    'database_flavor': schema_metadata.database_flavor.value,
                }
            })

        await self.knowledge_store.add_documents(documents)

    def _convert_to_structured_output(
        self,
        raw_results: Any,
        schema: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """Convert raw query results to structured output."""
        if not raw_results:
            return []

        field_mappings = schema.get('field_mappings', {})
        structured_results = []

        for row in raw_results:
            structured_row = {}

            if isinstance(row, dict):
                if field_mappings:
                    for target, source in field_mappings.items():
                        if source in row:
                            structured_row[target] = row[source]
                        elif target in row:
                            structured_row[target] = row[target]
                else:
                    structured_row = row
            else:
                fields = schema.get('fields', [])
                for i, field in enumerate(fields):
                    if i < len(row):
                        structured_row[field] = row[i]

            structured_results.append(structured_row)

        return structured_results
