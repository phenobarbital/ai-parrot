"""
Unified Database Tool for AI-Parrot

Consolidates schema extraction, knowledge base building, query generation,
validation, and execution into a single, powerful database interface.
"""

import asyncio
import json
import hashlib
from typing import Dict, List, Optional, Any, Union, Literal, Tuple
from datetime import datetime, timedelta
from pathlib import Path
from enum import Enum
import pandas as pd
from pydantic import BaseModel, Field, field_validator

from asyncdb import AsyncDB
from .abstract import AbstractTool, ToolResult, AbstractToolArgsSchema
from ..stores.abstract import AbstractStore


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
        "query_execute", "full_pipeline"
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

    @field_validator('natural_language_query', 'sql_query')
    @classmethod
    def validate_query_input(cls, v, values):
        # Ensure at least one query type is provided for query operations
        if values.get('operation') in ['query_generate', 'query_execute', 'full_pipeline']:
            if not v and not values.get('sql_query') and not values.get('natural_language_query'):
                raise ValueError("Either natural_language_query or sql_query must be provided")
        return v


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
        **kwargs
    ):
        """
        Initialize the unified database tool.

        Args:
            knowledge_store: Vector store for schema metadata and RAG
            default_connection_params: Default connection parameters per database type
            enable_query_caching: Whether to cache query results
        """
        super().__init__(**kwargs)

        self.knowledge_store = knowledge_store
        self.default_connection_params = default_connection_params or {}
        self.enable_query_caching = enable_query_caching

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
            # Route to specific operations
            if operation == "schema_extract":
                return await self._extract_schema_operation(
                    database_flavor, connection_params, schema_names,
                    update_knowledge_base, cache_duration_hours
                )
            elif operation == "query_generate":
                return await self._query_generation_operation(
                    natural_language_query, database_flavor, connection_params, schema_names
                )
            elif operation == "query_validate":
                return await self._query_validation_operation(
                    sql_query or natural_language_query, database_flavor, connection_params
                )
            elif operation == "query_execute":
                return await self._query_execution_operation(
                    sql_query, database_flavor, connection_params,
                    max_rows, timeout_seconds, output_format, structured_output_schema
                )
            elif operation == "full_pipeline":
                return await self._full_pipeline_operation(
                    natural_language_query, sql_query, database_flavor, connection_params,
                    schema_names, max_rows, timeout_seconds, dry_run,
                    output_format, structured_output_schema, update_knowledge_base, cache_duration_hours
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
                    "timestamp": datetime.utcnow().isoformat()
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
        # Implementation would use your existing AsyncDB setup
        # This is where you'd leverage your current DatabaseQueryTool logic
        pass

    async def _extract_database_schema(
        self,
        db_connection: AsyncDB,
        database_flavor: DatabaseFlavor,
        schema_names: List[str]
    ) -> SchemaMetadata:
        """Extract comprehensive schema metadata from the database."""
        # This would use your existing SchemaTool logic
        # but adapted to work with the unified interface
        pass

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
                cached_schema = SchemaMetadata(**schema_result.result)

            # Use database-specific query generator
            generator = self._query_generators.get(database_flavor)
            if not generator:
                raise ValueError(f"No query generator available for {database_flavor.value}")

            # Build rich context for LLM query generation
            schema_context = self._build_schema_context_for_llm(cached_schema, natural_language_query)

            # Generate the SQL query
            generated_sql = await generator(natural_language_query, schema_context)

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
            return await asyncio.wait_for(
                db_connection.fetch(sql_query),
                timeout=timeout_seconds
            )

        except asyncio.TimeoutError:
            raise Exception(f"Query execution timed out after {timeout_seconds} seconds")
        except Exception as e:
            raise Exception(f"Database execution error: {str(e)}")

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
        generated_query = await self._call_llm_for_query_generation(prompt)

        return generated_query

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
