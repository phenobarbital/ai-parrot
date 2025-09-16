"""
Schema-Centric AbstractDbAgent for Multi-Tenant Architecture
===========================================================

Designed for:
- 96+ schemas with ~50 tables each (~4,800+ total tables)
- Per-client schema isolation
- LRU + Vector store caching (no Redis)
- Dual execution paths: natural language generation + direct SQL tools
- "Show me" = data retrieval pattern recognition
"""

from abc import ABC, abstractmethod
from typing import Dict, Any, List, Optional, Union
from datetime import datetime
import re
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy import text
from ...tools.manager import ToolManager
from ...tools.asdb import DatabaseQueryTool
from ...stores.abstract import AbstractStore
from ..abstract import AbstractBot
from ...models import AIMessage, CompletionUsage
from .cache import SchemaMetadataCache
from .router import SchemaQueryRouter
from .models import (
    UserRole,
    QueryIntent,
    ReturnFormat,
    RouteDecision,
    TableMetadata,
    QueryExecutionResponse
)
from .prompts import DB_AGENT_PROMPT, BASIC_HUMAN_PROMPT
from .retries import QueryRetryConfig, SQLRetryHandler


# ============================================================================
# SCHEMA-CENTRIC ABSTRACT DB AGENT
# ============================================================================

class AbstractDBAgent(AbstractBot, ABC):
    """Schema-centric AbstractDBAgent for multi-tenant architecture."""
    _default_temperature: float = 0.0
    max_tokens: int = 8192

    def __init__(
        self,
        name: str = "DBAgent",
        dsn: str = None,
        allowed_schemas: Union[str, List[str]] = "public",
        primary_schema: Optional[str] = None,
        vector_store: Optional[AbstractStore] = None,
        auto_analyze_schema: bool = True,
        client_id: Optional[str] = None,  # For per-client agents
        **kwargs
    ):
        super().__init__(name=name, **kwargs)
        self.enable_tools = True  # Enable tools by default

        # Multi-schema configuration
        if isinstance(allowed_schemas, str):
            self.allowed_schemas = [allowed_schemas]
        else:
            self.allowed_schemas = allowed_schemas

        # Primary schema is the main focus, defaults to first allowed schema
        self.primary_schema = primary_schema or self.allowed_schemas[0]

        # Ensure primary schema is in allowed list
        if self.primary_schema not in self.allowed_schemas:
            self.allowed_schemas.insert(0, self.primary_schema)

        self.client_id = client_id or self.primary_schema
        self.dsn = dsn

        # Database components
        self.engine: Optional[AsyncEngine] = None
        self.session_maker: Optional[sessionmaker] = None

        # Per-agent ToolManager
        self.tool_manager = ToolManager(
            logger=self.logger,
            debug=getattr(self, '_debug', False)
        )

        # Schema-aware components
        self.metadata_cache = SchemaMetadataCache(
            vector_store=vector_store,  # Optional - can be None
            lru_maxsize=500,  # Large cache for many tables
            lru_ttl=1800     # 30 minutes
        )

        self.query_router = SchemaQueryRouter(
            primary_schema=self.primary_schema,
            allowed_schemas=self.allowed_schemas
        )

        # Register tools
        self._register_database_tools()

        # Schema analysis flag
        self.auto_analyze_schema = auto_analyze_schema
        self.schema_analyzed = False

    async def configure(self, app=None) -> None:
        """Configure agent with proper tool sharing."""
        await super().configure(app)

        # Connect to database
        await self.connect_database()

        # Share tools with LLM
        await self._share_tools_with_llm()

        # Auto-analyze schema if enabled
        if self.auto_analyze_schema and not self.schema_analyzed:
            await self.analyze_schema()

    async def connect_database(self) -> None:
        """Connect to PostgreSQL database using SQLAlchemy async."""
        if not self.dsn:
            raise ValueError("Connection string is required")

        try:
            # Ensure async driver
            if '+asyncpg' not in self.dsn:
                connection_string = self.dsn.replace(
                    'postgresql://', 'postgresql+asyncpg://'
                )
            else:
                connection_string = self.dsn

            # Build search path from allowed schemas
            search_path = ','.join(self.allowed_schemas)

            self.engine = create_async_engine(
                connection_string,
                echo=False,
                pool_pre_ping=True,
                pool_recycle=3600,
                # Multi-schema search path
                connect_args={
                    "server_settings": {
                        "search_path": search_path
                    }
                }
            )

            self.session_maker = sessionmaker(
                self.engine,
                class_=AsyncSession,
                expire_on_commit=False
            )

            # Test connection
            async with self.engine.begin() as conn:
                result = await conn.execute(text("SELECT current_schema()"))
                current_schema = result.scalar()
                self.logger.info(
                    f"Connected to database. Current schema: {current_schema}, "
                    f"Search path: {search_path}"
                )

        except Exception as e:
            self.logger.error(f"Failed to connect to database: {e}")
            raise

    # @abstractmethod
    def _register_database_tools(self):
        """Register database-specific tools. Must be implemented by subclasses."""
        pass

    async def _share_tools_with_llm(self):
        """Share ToolManager tools with LLM Client."""
        if not hasattr(self, '_llm') or not self._llm:
            self.logger.warning("LLM client not initialized, cannot share tools")
            return

        if not hasattr(self._llm, 'tool_manager'):
            self.logger.warning("LLM client has no tool_manager")
            return

        tools = list(self.tool_manager.get_tools())
        for tool in tools:
            self._llm.tool_manager.add_tool(tool)

        self.logger.info(f"Shared {len(tools)} tools with LLM Client")

    async def analyze_schema(self) -> None:
        """Analyze all allowed schemas and populate metadata cache."""
        try:
            self.logger.info(f"Analyzing schemas: {self.allowed_schemas} (primary: {self.primary_schema})")

            total_tables = 0

            for schema_name in self.allowed_schemas:
                try:
                    schema_table_count = await self._analyze_single_schema(schema_name)
                    total_tables += schema_table_count
                    self.logger.info(f"Schema '{schema_name}': {schema_table_count} tables/views analyzed")

                except Exception as e:
                    self.logger.warning(f"Failed to analyze schema '{schema_name}': {e}")
                    # Continue with other schemas
                    continue

            self.schema_analyzed = True
            self.logger.info(
                f"Schema analysis completed. Total: {total_tables} tables/views across "
                f"{len(self.allowed_schemas)} schemas"
            )

        except Exception as e:
            self.logger.error(f"Schema analysis failed: {e}")
            raise

    async def _analyze_single_schema(self, schema_name: str) -> int:
        """Analyze individual schema and return table count."""

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
                    # Get detailed table metadata
                    table_metadata = await self._analyze_table(
                        session, schema_name, table_name, table_type, comment
                    )

                    # Store in cache
                    await self.metadata_cache.store_table_metadata(table_metadata)

                except Exception as e:
                    self.logger.warning(f"Failed to analyze table {schema_name}.{table_name}: {e}")

            return len(tables_data)

    async def _analyze_table(
        self,
        session: AsyncSession,
        schema_name: str,
        table_name: str,
        table_type: str,
        comment: Optional[str]
    ) -> TableMetadata:
        """Analyze individual table metadata."""

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
                count_query = f'SELECT reltuples::bigint FROM pg_class WHERE relname = :table_name'
                count_result = await session.execute(text(count_query), {"table_name": table_name})
                row_count = count_result.scalar()
            except:
                pass  # Skip if estimate fails

        # Get sample data (only for tables, not views, and only if reasonable size)
        sample_data = []
        if table_type == 'BASE TABLE' and row_count and row_count < 1000000:  # Only for < 1M rows
            try:
                sample_query = f'SELECT * FROM "{schema_name}"."{table_name}" LIMIT 3'
                sample_result = await session.execute(text(sample_query))
                rows = sample_result.fetchall()
                if rows:
                    columns_names = list(sample_result.keys())
                    sample_data = [dict(zip(columns_names, row)) for row in rows]
            except:
                pass  # Skip if sample fails

        return TableMetadata(
            schema_name=schema_name,
            table_name=table_name,
            table_type=table_type,
            full_name=f'"{schema_name}"."{table_name}"',
            comment=comment,
            columns=columns,
            primary_keys=primary_keys,
            foreign_keys=[],  # Could be implemented
            indexes=[],       # Could be implemented
            row_count=row_count,
            sample_data=sample_data,
            last_accessed=datetime.now()
        )

    async def ask(
        self,
        query: str,
        user_role: UserRole = UserRole.DATA_ANALYST,
        return_format: Optional[ReturnFormat] = None,
        enable_retry: bool = True,
        **kwargs
    ) -> AIMessage:
        """
        Main query processing with schema-centric 3-step pipeline.
        """
        # Add retry configuration to kwargs
        retry_config = kwargs.pop('retry_config', QueryRetryConfig())

        try:
            # Step 1: Route the query
            route: RouteDecision = await self.query_router.route(
                query=query,
                user_role=user_role,
                return_format=return_format
            )

            self.logger.info(
                f"Query routed: intent={route.intent.value}, "
                f"format={route.return_format.value}, "
                f"schema={route.primary_schema}"
            )

            # Step 2: Discover metadata (if needed)
            metadata_context = ""
            if route.needs_metadata_discovery:
                metadata_context = await self._discover_metadata(query)

            # Step 3a: Generate/validate query (if needed)
            sql_query = None
            explanation = None
            llm_response = None  # Store the original LLM response

            if route.needs_query_generation:
                sql_query, explanation, llm_response = await self._process_query_generation(
                    query, route, metadata_context
                )
            elif route.intent == QueryIntent.VALIDATE_QUERY:
                # User provided SQL, validate it
                sql_query = query.strip()
                explanation, llm_response = await self._validate_user_sql(sql_query, metadata_context)

            # Step 3b: Execute query (if needed)
            exec_result = None
            if route.needs_execution and sql_query:
                if enable_retry:
                    exec_result = await self._execute_query(
                        sql_query,
                        route.execution_options,
                        retry_config
                    )
                else:
                    exec_result = await self._execute_query_safe(
                        sql_query,
                        route.execution_options
                    )

            # Step 4: Format response
            return self._format_response(route, query, sql_query, explanation, exec_result, llm_response)

        except Exception as e:
            self.logger.error(
                f"Error in ask method: {e}"
            )
            # Return error as AIMessage
            return AIMessage(
                input=query,
                response=f"Error processing query: {str(e)}",
                output=None,
                model=getattr(self, '_llm_model', 'unknown'),
                provider=getattr(self, '_llm', 'unknown'),
                metadata={
                    "error": str(e), "schema": self.primary_schema
                },
                usage=CompletionUsage(
                    prompt_tokens=0,
                    completion_tokens=0,
                    total_tokens=0
                ),
            )

    async def _discover_metadata(self, query: str) -> str:
        """Discover relevant metadata for the query across allowed schemas."""

        # 🔍 DEBUG: Log the discovery process
        self.logger.info(f"🔍 DISCOVERY: Starting metadata discovery for query: '{query}'")
        self.logger.info(f"🔍 DISCOVERY: Allowed schemas: {self.allowed_schemas}")
        self.logger.info(f"🔍 DISCOVERY: Primary schema: {self.primary_schema}")

        # Search for similar tables across all allowed schemas
        similar_tables = await self.metadata_cache.search_similar_tables(
            schema_names=self.allowed_schemas,
            query=query,
            limit=5
        )

        if similar_tables:
            self.logger.notice(f"🔍 DISCOVERY: Found {len(similar_tables)} similar tables:")
            # Format as YAML context
            metadata_parts = []
            for table in similar_tables:
                metadata_parts.append(table.to_yaml_context())
            return "\n---\n".join(metadata_parts)
        else:
            self.logger.warning(
                f"🔍 DISCOVERY: No similar tables found for query: '{query}'"
            )

        # Fallback: get hot tables from all allowed schemas
        hot_tables = self.metadata_cache.get_hot_tables(self.allowed_schemas, limit=3)
        if hot_tables:
            self.logger.info(f"🔍 DISCOVERY: Using fallback hot tables: {hot_tables}")
            metadata_parts = []
            for schema_name, table_name, access_count in hot_tables:
                self.logger.info(f"🔍   - {schema_name}.{table_name} (accessed {access_count} times)")
                table_meta = await self.metadata_cache.get_table_metadata(
                    schema_name, table_name
                )
                if table_meta:
                    # 🔍 DEBUG: Log the columns of hot tables too
                    self.logger.info(f"🔍     Columns: {[col['name'] for col in table_meta.columns]}")
                    metadata_parts.append(table_meta.to_yaml_context())

            if metadata_parts:
                metadata_context = "\n---\n".join(metadata_parts)
                self.logger.info(f"🔍 DISCOVERY: Fallback metadata context length: {len(metadata_context)} chars")
                return metadata_context
        else:
            self.logger.warning(
                f"🔍 DISCOVERY: No hot tables found either!"
            )

        fallback_message = f"Allowed schemas: {', '.join(self.allowed_schemas)} (primary: {self.primary_schema})"
        self.logger.warning(
            f"🔍 DISCOVERY: Using minimal fallback: {fallback_message}"
        )
        return fallback_message

    async def _process_query_generation(
        self,
        query: str,
        route: RouteDecision,
        metadata_context: str,
        **kwargs
    ) -> tuple[str, str, AIMessage]:
        """Process query generation with LLM."""

        system_prompt = f"""
You are a PostgreSQL query expert for multi-schema databases.

**Primary Schema:** {self.primary_schema}
**Allowed Schemas:** {', '.join(self.allowed_schemas)}

**Available Tables and Structure:**
{metadata_context}

**Instructions:**
1. Generate PostgreSQL queries using only these schemas: {', '.join([f'"{schema}"' for schema in self.allowed_schemas])}
2. NEVER invent table names - only use tables from the metadata above
3. If metadata is insufficient, use schema exploration tools
4. For "show me" queries, generate simple SELECT statements
5. Always include appropriate LIMIT clauses
6. Prefer primary schema "{self.primary_schema}" unless user specifies otherwise

**COLUMN SELECTION STRATEGY:**
1. First, look for EXACT matches to user terms
2. Then, look for SEMANTIC matches (price → pricing)
3. Choose the most appropriate column based on context
4. If multiple columns could work, prefer the most specific one

**QUERY PROCESSING RULES:**
1. ONLY use tables and columns from the metadata above - NEVER invent names
2. When user mentions concepts like "price", find the closest actual column name
3. Generate clean, readable PostgreSQL queries
4. Always include appropriate LIMIT clauses for "top N" requests
5. Use proper schema qualification: "{self.primary_schema}".table_name

**User Intent:** {route.intent.value}
**Return Format:** {route.return_format.value}

Generate an accurate PostgreSQL query using ACTUAL column names from the metadata.
Apply semantic understanding to map user concepts to available columns.
    """

        # Call LLM for query generation
        llm_response = await self._llm.ask(
            prompt=f"User request: {query}",
            system_prompt=system_prompt,
            temperature=0.0,  # Consistent results
            **kwargs
        )

        # Extract SQL and explanation
        response_text = str(llm_response.output) if llm_response.output else str(llm_response.response)
        sql_query = self._extract_sql_from_response(response_text)

        return sql_query, response_text, llm_response

    async def _validate_user_sql(self, sql_query: str, metadata_context: str) -> tuple[str, AIMessage]:
        """Validate user-provided SQL."""

        system_prompt = f"""
You are validating SQL for multi-schema access.

**Primary Schema:** {self.primary_schema}
**Allowed Schemas:** {', '.join(self.allowed_schemas)}

**Available Schema Information:**
{metadata_context}

**Validation Tasks:**
1. Check syntax correctness
2. Verify table/column existence
3. Ensure queries only access allowed schemas: {', '.join(self.allowed_schemas)}
4. Identify potential performance issues
5. Suggest improvements

Provide detailed validation results.
"""

        llm_response = await self._llm.ask(
            prompt=f"Validate this SQL query:\n\n```sql\n{sql_query}\n```",
            system_prompt=system_prompt,
            temperature=0.0
        )

        validation_text = str(llm_response.output) if llm_response.output else str(llm_response.response)
        return validation_text, llm_response

    async def _execute_query(
        self,
        sql_query: str,
        options: Dict[str, Any],
        retry_config: Optional[QueryRetryConfig] = None
    ) -> QueryExecutionResponse:
        """Execute SQL query with schema security."""

        retry_handler = SQLRetryHandler(self, retry_config or QueryRetryConfig())
        retry_count = 0
        last_error = None
        query_history = []  # Track all attempts

        while retry_count <= retry_handler.config.max_retries:
            try:
                self.logger.debug(f"🔄 QUERY ATTEMPT {retry_count + 1}: Executing SQL")
                # Execute the query
                result = await self._execute_query_internal(sql_query, options)
                # Success!
                if retry_count > 0:
                    self.logger.info(
                        f"✅ QUERY SUCCESS: Fixed after {retry_count + 1} retries"
                    )

                return result
            except Exception as e:
                self.logger.warning(
                    f"❌ QUERY FAILED (attempt {retry_count + 1}): {e}"
                )

                query_history.append({
                    "attempt": retry_count + 1,
                    "query": sql_query,
                    "error": str(e),
                    "error_type": type(e).__name__
                })

                last_error = e

                # Check if this is a retryable error
                if not retry_handler._is_retryable_error(e):
                    self.logger.info(f"🚫 NON-RETRYABLE ERROR: {type(e).__name__}")
                    break

                # Check if we've hit max retries
                if retry_count >= retry_handler.config.max_retries:
                    self.logger.info(f"🛑 MAX RETRIES REACHED: {retry_count}")
                    break

                # Try to fix the query
                self.logger.info(
                    f"🔧 ATTEMPTING QUERY FIX: Retry {retry_count + 1}"
                )

                try:
                    fixed_query = await self._fix_query(
                        original_query=sql_query,
                        error=e,
                        retry_count=retry_count,
                        query_history=query_history
                    )
                    if fixed_query and fixed_query.strip() != sql_query.strip():
                        sql_query = fixed_query
                        retry_count += 1
                    else:
                        self.logger.warning(
                            f"🔧 NO QUERY FIX: LLM returned same or empty query"
                        )
                        break
                except Exception as fix_error:
                    self.logger.error(
                        f"🔧 QUERY FIX FAILED: {fix_error}"
                    )
                    break
        # All retries failed, return error response
        start_time = datetime.now()
        execution_time = (datetime.now() - start_time).total_seconds() * 1000

        return QueryExecutionResponse(
            success=False,
            data=None,
            row_count=0,
            execution_time_ms=execution_time,
            error_message=f"Query failed after {retry_count} retries. Last error: {last_error}",
            query_plan=None,
            metadata={
                "retry_count": retry_count,
                "query_history": query_history,
                "last_error_type": type(last_error).__name__ if last_error else None
            }
        )

    async def _execute_query_internal(
        self,
        sql_query: str,
        options: Dict[str, Any]
    ) -> QueryExecutionResponse:
        """Execute query and raise exceptions (don't catch them) for retry mechanism."""

        start_time = datetime.now()

        # Validate query targets correct schemas
        if not self._validate_schema_security(sql_query):
            raise ValueError(
                f"Query attempts to access schemas outside of allowed list: {self.allowed_schemas}"
            )

        # Execute query - LET EXCEPTIONS PROPAGATE for retry mechanism
        async with self.session_maker() as session:
            # Set search path for security
            search_path = ','.join(self.allowed_schemas)
            await session.execute(text(f"SET search_path = '{search_path}'"))

            # Add timeout
            timeout = options.get('timeout', 30)
            await session.execute(text(f"SET statement_timeout = '{timeout}s'"))

            # Execute main query
            query_plan = None
            if options.get('explain_analyze', False):
                # Get query plan first
                plan_result = await session.execute(text(f"EXPLAIN ANALYZE {sql_query}"))
                query_plan = "\n".join([row[0] for row in plan_result.fetchall()])

            # Execute actual query - DON'T CATCH EXCEPTIONS HERE
            result = await session.execute(text(sql_query))

            if sql_query.strip().upper().startswith('SELECT'):
                # Handle SELECT queries
                rows = result.fetchall()
                columns = list(result.keys()) if rows else []

                # Apply limit
                limit = options.get('limit', 1000)
                limited_rows = rows[:limit] if len(rows) > limit else rows

                # Convert to list of dicts
                data = [dict(zip(columns, row)) for row in limited_rows]
                row_count = len(rows)  # Original count
            else:
                # Handle non-SELECT queries
                data = None
                columns = []
                row_count = result.rowcount

            execution_time = (datetime.now() - start_time).total_seconds() * 1000

            return QueryExecutionResponse(
                success=True,
                data=data,
                row_count=row_count,
                execution_time_ms=execution_time,
                columns=columns,
                query_plan=query_plan,
                schema_used=self.primary_schema
            )

    async def _execute_query_safe(
        self,
        sql_query: str,
        options: Dict[str, Any]
    ) -> QueryExecutionResponse:
        """Execute query with error handling (for non-retry scenarios)."""

        start_time = datetime.now()

        try:
            # Use the internal method that raises exceptions
            return await self._execute_query_internal(sql_query, options)

        except Exception as e:
            execution_time = (datetime.now() - start_time).total_seconds() * 1000

            self.logger.error(f"Query execution failed: {e}")

            return QueryExecutionResponse(
                success=False,
                data=None,
                row_count=0,
                execution_time_ms=execution_time,
                error_message=str(e),
                schema_used=self.primary_schema
            )

    async def _fix_query(
        self,
        original_query: str,
        error: Exception,
        retry_count: int,
        query_history: List[Dict[str, Any]]
    ) -> Optional[str]:
        """Use LLM to fix a failed SQL query based on the error."""

        retry_handler = SQLRetryHandler(self)

        # Extract problematic table/column info
        table_name, column_name = retry_handler._extract_table_column_from_error(
            original_query, error
        )

        # Get sample data if possible
        sample_data = ""
        if table_name and column_name:
            sample_data = await retry_handler._get_sample_data_for_error(
                self.primary_schema, table_name, column_name
            )

        # Build error context
        error_context = f"""
**QUERY EXECUTION ERROR:**
Error Type: {type(error).__name__}
Error Message: {str(error)}

**FAILED QUERY:**
```sql
{original_query}
```

**RETRY ATTEMPT:** {retry_count + 1} of {retry_handler.config.max_retries}

{sample_data}

**PREVIOUS ATTEMPTS:**
{self._format_query_history(query_history)}
    """

        # Enhanced system prompt for query fixing
        fix_prompt = f"""
You are a PostgreSQL expert specializing in fixing SQL query errors.

**PRIMARY TASK:** Fix the failed SQL query based on the error message and sample data.

**COMMON ERROR PATTERNS & FIXES:**

💰 **Currency/Number Format Errors:**
- Error: "invalid input syntax for type numeric: '1,999.99'"
- Fix: Remove commas and currency symbols properly
- Example: `CAST(REPLACE(REPLACE(pricing, '$', ''), ',', '') AS NUMERIC)`

📝 **String/Text Conversion Issues:**
- Error: Type conversion failures
- Fix: Use proper casting with text cleaning
- Example: `CAST(TRIM(column_name) AS INTEGER)`

🔤 **Column/Table Name Issues:**
- Error: "column does not exist"
- Fix: Check exact column names from metadata, use proper quoting
- Example: Use "column_name" if names have special characters

**SCHEMA CONTEXT:**
Primary Schema: {self.primary_schema}
Available Schemas: {', '.join(self.allowed_schemas)}

{error_context}

**FIXING INSTRUCTIONS:**
1. Analyze the error message carefully
2. Look at the sample data to understand the actual format
3. Modify the query to handle the data format properly
4. Keep the same business logic (ORDER BY, LIMIT, etc.)
5. Only change what's necessary to fix the error
6. Test your logic against the sample data shown

**OUTPUT:** Return ONLY the corrected SQL query, no explanations.
    """
        try:
            response = await self._llm.ask(
                prompt="Fix the failing SQL query based on the error details above.",
                system_prompt=fix_prompt,
                temperature=0.0  # Deterministic fixes
            )

            fixed_query = self._extract_sql_from_response(
                str(response.output) if response.output else str(response.response)
            )

            if fixed_query:
                self.logger.debug(f"FIXED QUERY: {fixed_query}")
                return fixed_query
            else:
                self.logger.warning(f"LLM FIX: No SQL query found in response")
                return None

        except Exception as e:
            self.logger.error(f"LLM FIX ERROR: {e}")
            return None

    def _format_query_history(self, query_history: List[Dict[str, Any]]) -> str:
        """Format query history for LLM context."""
        if not query_history:
            return "No previous attempts."

        formatted = []
        for attempt in query_history:
            formatted.append(
                f"Attempt {attempt['attempt']}: {attempt['error_type']} - {attempt['error']}"
            )

        return "\n".join(formatted)

    def _validate_schema_security(self, sql_query: str) -> bool:
        """Ensure query only accesses authorized schemas."""
        query_upper = sql_query.upper()

        # Check for unauthorized schema references
        unauthorized_patterns = [
            r'\bFROM\s+(?!")(\w+)\.', # FROM schema.table without quotes
            r'\bJOIN\s+(?!")(\w+)\.', # JOIN schema.table without quotes
            r'\bUPDATE\s+(?!")(\w+)\.', # UPDATE schema.table without quotes
            r'\bINSERT\s+INTO\s+(?!")(\w+)\.', # INSERT INTO schema.table without quotes
        ]

        for pattern in unauthorized_patterns:
            matches = re.findall(pattern, query_upper)
            for match in matches:
                if match.upper() not in [schema.upper() for schema in self.allowed_schemas]:
                    self.logger.warning(f"Query attempts to access unauthorized schema: {match}")
                    return False

        # Additional security checks could be added here
        return True

    def _extract_sql_from_response(self, response_text: str) -> str:
        """Extract SQL query from LLM response."""
        # Look for SQL code blocks
        sql_pattern = r'```sql\n(.*?)\n```'
        matches = re.findall(sql_pattern, response_text, re.DOTALL | re.IGNORECASE)

        if matches:
            return matches[0].strip()

        # Fallback: look for SQL keywords
        lines = response_text.split('\n')
        sql_lines = []
        in_sql = False

        for line in lines:
            line_upper = line.strip().upper()
            if any(line_upper.startswith(kw) for kw in ['SELECT', 'WITH', 'INSERT', 'UPDATE', 'DELETE']):
                in_sql = True
                sql_lines.append(line)
            elif in_sql:
                if line.strip().endswith(';') or not line.strip():
                    if line.strip().endswith(';'):
                        sql_lines.append(line)
                    break
                else:
                    sql_lines.append(line)

        if sql_lines:
            return '\n'.join(sql_lines).strip()

        # Last resort: return original if it looks like SQL
        if any(kw in response_text.upper() for kw in ['SELECT', 'FROM', 'WHERE']):
            return response_text.strip()

        return ""

    def _format_response(
        self,
        route: RouteDecision,
        original_query: str,
        sql_query: Optional[str],
        explanation: Optional[str],
        exec_result: Optional[QueryExecutionResponse],
        llm_response: Optional[AIMessage] = None
    ) -> AIMessage:
        """Format final response based on route decision."""

        response_parts = []

        if route.return_format == ReturnFormat.DATA_ONLY:
            if exec_result and exec_result.success and exec_result.data:
                response_parts.append(f"Found {exec_result.row_count} rows:")
                # Data will be in output field
            elif exec_result and not exec_result.success:
                response_parts.append(f"Query failed: {exec_result.error_message}")
            else:
                response_parts.append("No data returned.")

        elif route.return_format == ReturnFormat.QUERY_ONLY:
            if sql_query:
                response_parts.append(f"Generated SQL:\n```sql\n{sql_query}\n```")
            if explanation and route.intent == QueryIntent.VALIDATE_QUERY:
                response_parts.append(f"\nValidation Results:\n{explanation}")

        elif route.return_format == ReturnFormat.QUERY_AND_DATA:
            if sql_query:
                response_parts.append(f"**SQL Query:**\n```sql\n{sql_query}\n```")

            if exec_result:
                if exec_result.success:
                    response_parts.append(f"**Results:** {exec_result.row_count} rows returned")
                else:
                    response_parts.append(f"**Error:** {exec_result.error_message}")

        elif route.return_format == ReturnFormat.QUERY_DATA_EXPLANATION:
            if sql_query:
                response_parts.append(f"**Generated SQL:**\n```sql\n{sql_query}\n```")

            if explanation:
                response_parts.append(f"**Explanation:**\n{explanation}")

            if exec_result:
                if exec_result.success:
                    response_parts.append(f"**Execution:** {exec_result.row_count} rows in {exec_result.execution_time_ms:.1f}ms")

                    if exec_result.query_plan:
                        response_parts.append(f"**Query Plan:**\n```\n{exec_result.query_plan}\n```")
                else:
                    response_parts.append(f"**Error:** {exec_result.error_message}")

        response_text = "\n\n".join(response_parts) if response_parts else "No response generated."

        if llm_response:
            model_name = llm_response.model
            provider_name = llm_response.provider or 'gemini'
            usage_info = llm_response.usage
        else:
            # Fallback for cases where no LLM was called
            model_name = getattr(self, '_llm_model', 'unknown')
            provider_name = getattr(self._llm, 'client_type', 'unknown') if hasattr(self, '_llm') else 'unknown'
            usage_info = CompletionUsage(prompt_tokens=0, completion_tokens=0, total_tokens=0)

        if hasattr(self, '_llm') and self._llm:
            if hasattr(self._llm, 'client_type'):
                provider_name = str(self._llm.client_type)
            elif hasattr(self._llm, 'provider'):
                provider_name = str(self._llm.provider)

        return AIMessage(
            input=original_query,
            response=response_text,
            output=exec_result.data if exec_result and exec_result.success else None,
            model=model_name,
            provider=provider_name,
            usage=usage_info,
            metadata={
                "primary_schema": self.primary_schema,
                "allowed_schemas": self.allowed_schemas,
                "intent": route.intent.value,
                "return_format": route.return_format.value,
                "sql_query": sql_query,
                "execution_success": exec_result.success if exec_result else None,
                "row_count": exec_result.row_count if exec_result else 0,
                "execution_time_ms": exec_result.execution_time_ms if exec_result else 0
            }
        )

    async def cleanup(self) -> None:
        """Cleanup resources."""
        if self.engine:
            await self.engine.dispose()


# ============================================================================
# USAGE EXAMPLES FOR MULTI-SCHEMA MULTI-TENANT ARCHITECTURE
# ============================================================================

"""
# Example usage for multi-tenant schema-centric agents with flexible schema access

# Example 1: EPSON client with access to multiple schemas
epson_agent = ConcreteDbAgent(
    name="EPSON_DBAgent",
    connection_string="postgresql+asyncpg://user:pass@localhost/navigator",
    allowed_schemas=["epson", "public", "navigator", "troc"],  # Multi-schema access
    primary_schema="epson",  # Main focus schema
    client_id="epson",
    vector_store=your_vector_store  # Optional - can be None
)

# Example 2: Client with only LRU cache (no vector store)
simple_client_agent = ConcreteDbAgent(
    name="SimpleClient_DBAgent",
    connection_string="postgresql+asyncpg://user:pass@localhost/navigator",
    allowed_schemas=["client_a", "public"],
    primary_schema="client_a",
    client_id="client_a",
    vector_store=None  # Only LRU cache will be used
)

# Example 3: Admin agent with access to all schemas
admin_agent = ConcreteDbAgent(
    name="Admin_DBAgent",
    connection_string="postgresql+asyncpg://user:pass@localhost/navigator",
    allowed_schemas=["public", "navigator", "troc", "epson", "client_a", "client_b"],
    primary_schema="public",
    client_id="admin",
    vector_store=your_vector_store
)

# Configure agents
await epson_agent.configure()
await simple_client_agent.configure()
await admin_agent.configure()

# Usage examples showing multi-schema capabilities

# 1. Query that might access tables from multiple schemas
response_epson = await epson_agent.ask(
    "Show me users from epson schema and reference data from navigator schema",
    user_role=UserRole.BUSINESS_USER,
    return_format=ReturnFormat.DATA_ONLY
)

# 2. Query with simple cache (no vector store)
response_simple = await simple_client_agent.ask(
    "Get username and job_code of active employees",
    user_role=UserRole.DATA_ANALYST
)

# 3. Cross-schema analysis (admin access)
response_admin = await admin_agent.ask(
    "Analyze user distribution across all client schemas",
    user_role=UserRole.DATABASE_ADMIN,
    return_format=ReturnFormat.QUERY_DATA_EXPLANATION
)

# 4. Schema exploration across multiple schemas
schema_exploration = await epson_agent.ask(
    "What tables are available across all my allowed schemas?",
    user_role=UserRole.DEVELOPER
)

# The system will:
# - Allow queries across allowed schemas: epson, public, navigator, troc
# - Prevent access to unauthorized schemas
# - Use primary schema (epson) as the main focus for metadata discovery
# - Work with or without vector store based on configuration
# - Cache metadata across all allowed schemas in LRU cache
# - Provide schema-aware query generation and validation

# Example of agent factory for dynamic client creation
def create_client_agent(
    client_id: str,
    client_schemas: List[str],
    vector_store: Optional[AbstractStore] = None
) -> ConcreteDbAgent:
    '''Create a new agent for a client with their specific schema access.'''

    # Always include public schema for shared resources
    allowed_schemas = list(set(client_schemas + ["public"]))

    # Primary schema is the client's main schema
    primary_schema = client_schemas[0] if client_schemas else "public"

    return ConcreteDbAgent(
        name=f"{client_id}_DBAgent",
        connection_string=os.getenv("DATABASE_URL"),
        allowed_schemas=allowed_schemas,
        primary_schema=primary_schema,
        client_id=client_id,
        vector_store=vector_store,
        auto_analyze_schema=True
    )

# Dynamic client agent creation
toyota_agent = create_client_agent(
    client_id="toyota",
    client_schemas=["toyota", "automotive_shared"],
    vector_store=vector_store  # Optional
)

honda_agent = create_client_agent(
    client_id="honda",
    client_schemas=["honda", "automotive_shared"],
    vector_store=None  # No vector store - LRU only
)

# Each agent automatically gets:
# - Access to their specific schemas + public
# - Schema-scoped security validation
# - Metadata caching optimized for their allowed schemas
# - Query routing aware of their schema access patterns
"""
