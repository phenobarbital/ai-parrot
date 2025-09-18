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

from abc import ABC
from typing import Dict, Any, List, Optional, Union, Tuple
from datetime import datetime
from string import Template
import re
import uuid
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy import text
import pandas as pd
from ...tools.manager import ToolManager
from ...stores.abstract import AbstractStore
from ..abstract import AbstractBot
from ...models import AIMessage, CompletionUsage
from .cache import SchemaMetadataCache
from .router import SchemaQueryRouter
from .models import (
    UserRole,
    QueryIntent,
    RouteDecision,
    TableMetadata,
    QueryExecutionResponse,
    OutputComponent,
    DatabaseResponse,
    get_default_components,
    customize_components,
    components_from_string
)
from .prompts import DB_AGENT_PROMPT
from .retries import QueryRetryConfig, SQLRetryHandler
from .tools import SchemaSearchTool
from ...memory import ConversationTurn


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
        client_id: Optional[str] = None,
        database_type: str = "postgresql",
        system_prompt_template: Optional[str] = None,
        **kwargs
    ):
        super().__init__(name=name, **kwargs)
        self.enable_tools = True  # Enable tools by default
        self.role = kwargs.get(
            'role', 'Database Analysis Assistant'
        )
        self.goal = kwargs.get(
            'goal', 'Help users interact with databases using natural language'
        )
        self.backstory = kwargs.get(
            'backstory',
            """
- Help users query, analyze, and understand database information
- Generate accurate SQL queries based on available schema metadata
- Provide data insights and recommendations
- Maintain conversation context for better user experience.
            """
        )
        # System Prompt Template:
        self.system_prompt_template = system_prompt_template or DB_AGENT_PROMPT

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
        self.database_type = database_type

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

        # Vector Store:
        self.knowledge_store = vector_store

        self.query_router = SchemaQueryRouter(
            primary_schema=self.primary_schema,
            allowed_schemas=self.allowed_schemas
        )

        # Schema analysis flag
        self.schema_analyzed = False
        self.auto_analyze_schema = auto_analyze_schema


    async def configure(self, app=None) -> None:
        """Configure agent with proper tool sharing."""
        await super().configure(app)

        # Connect to database
        await self.connect_database()

        # Register tools
        self._register_database_tools()

        # Share tools with LLM
        await self._share_tools_with_llm()

        # Auto-analyze schema if enabled
        if self.auto_analyze_schema and not self.schema_analyzed:
            await self.analyze_schema()

    def _register_database_tools(self):
        """Register database-specific tools."""
        self.schema_tool = SchemaSearchTool(
            engine=self.engine,
            metadata_cache=self.metadata_cache,
            allowed_schemas=self.allowed_schemas.copy(),
            session_maker=self.session_maker
        )
        self.tool_manager.add_tool(self.schema_tool)
        self.logger.debug(
            f"Registered SchemaSearchTool with {len(self.allowed_schemas)} schemas"
        )

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

        self.logger.info(
            f"Shared {len(tools)} tools with LLM Client"
        )

    def _ensure_async_driver(self, dsn: str) -> str:
        return dsn

    async def connect_database(self) -> None:
        """Connect to SQL database using SQLAlchemy async."""
        if not self.dsn:
            raise ValueError("Connection string is required")

        try:
            # Ensure async driver
            connection_string = self._ensure_async_driver(self.dsn)
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

    async def analyze_schema(self) -> None:
        """Analyze all allowed schemas and populate metadata cache."""
        try:
            self.logger.notice(
                f"Analyzing schemas: {self.allowed_schemas} (primary: {self.primary_schema})"
            )

            # Delegate to schema manager tool
            analysis_results = await self.schema_tool.analyze_all_schemas()

            # Log results
            total_tables = sum(analysis_results.values())
            for schema_name, table_count in analysis_results.items():
                if table_count > 0:
                    self.logger.info(f"Schema '{schema_name}': {table_count} tables/views")
                else:
                    self.logger.warning(f"Schema '{schema_name}': Analysis failed or no tables found")

            self.schema_analyzed = True
            self.logger.info(f"Schema analysis completed. Total: {total_tables} tables/views")

        except Exception as e:
            self.logger.error(f"Schema analysis failed: {e}")
            raise

    async def get_table_metadata(self, schema: str, tablename: str) -> Optional[TableMetadata]:
        """Get table metadata - delegates to schema tool."""
        if not self.schema_tool:
            raise RuntimeError("Schema tool not initialized. Call configure() first.")

        return await self.schema_tool.get_table_details(schema, tablename)

    async def get_schema_overview(self, schema_name: str) -> Optional[Dict[str, Any]]:
        """Get schema overview - delegates to schema Tool."""
        if not self.schema_tool:
            raise RuntimeError("Schema Tool not initialized. Call configure() first.")

        return await self.schema_tool.get_schema_overview(schema_name)

    async def create_system_prompt(
        self,
        user_context: str = "",
        context: str = "",
        vector_context: str = "",
        conversation_context: str = "",
        metadata_context: str = "",
        vector_metadata: Optional[Dict[str, Any]] = None,
        route: Optional[RouteDecision] = None,
        **kwargs
    ) -> str:
        """
        Create the complete system prompt using template substitution.

        Args:
            user_context: User-specific context for database interaction
            context: Additional context for the request
            vector_context: Context from vector store similarity search
            conversation_context: Previous conversation context
            metadata_context: Schema metadata context
            vector_metadata: Metadata from vector search
            route: Query route decision for specialized instructions
            **kwargs: Additional template variables

        Returns:
            Complete system prompt string
        """
        # Build context sections
        context_parts = []

        # User context section
        if user_context:
            user_section = f"""
**User Context:**
{user_context}

*Instructions: Tailor your response to the user's role, expertise level, and objectives described above.*
"""
            context_parts.append(user_section)

        # Additional context
        if context:
            context_parts.append(f"**Additional Context:**\n{context}")

        # Database context from schema metadata
        database_context_parts = []
        if metadata_context:
            database_context_parts.append(
                f"**Available Schema Information:**\n{metadata_context}"
            )

        # Add current database info
        db_info = f"""**Database Configuration:**
- Primary Schema: {self.primary_schema}
- Allowed Schemas: {', '.join(self.allowed_schemas)}
- Database Type: {self.database_type}
- Total Schemas: {len(self.allowed_schemas)}"""
        database_context_parts.append(db_info)

        # Vector context from knowledge store
        vector_section = ""
        if vector_context:
            vector_section = f"""**Relevant Knowledge Base Context:**
{vector_context}
"""
            if vector_metadata and vector_metadata.get('tables_referenced'):
                referenced_tables = [t for t in vector_metadata['tables_referenced'] if t]
                if referenced_tables:
                    vector_section += f"\n*Referenced Tables: {', '.join(set(referenced_tables))}*"

        # Conversation history section
        chat_section = ""
        if conversation_context:
            chat_section = f"""**Previous Conversation:**
{conversation_context}

*Note: Consider previous context when formulating your response.*
"""

        # Route-specific instructions
        route_instructions = ""
        if route:
            if route.intent == QueryIntent.SHOW_DATA:
                route_instructions = "\n**Current Task**: Generate and execute SQL to retrieve and display data."
            elif route.intent == QueryIntent.GENERATE_QUERY:
                route_instructions = "\n**Current Task**: Generate SQL query based on user request and available schema."
            elif route.intent == QueryIntent.ANALYZE_DATA:
                route_instructions = "\n**Current Task**: Analyze data and provide insights with supporting queries."
            elif route.intent == QueryIntent.EXPLORE_SCHEMA:
                route_instructions = "\n**Current Task**: Help user explore and understand the database schema."

        # Template substitution
        template = Template(self.system_prompt_template)

        try:
            system_prompt = template.safe_substitute(
                user_context=user_section if user_context else "",
                database_context="\n\n".join(database_context_parts),
                context="\n\n".join(context_parts) if context_parts else "",
                vector_context=vector_section,
                chat_history=chat_section,
                route_instructions=route_instructions,
                database_type=self.database_type,
                **kwargs
            )

            return system_prompt

        except Exception as e:
            self.logger.error(f"Error in template substitution: {e}")
            # Fallback to basic prompt
            return f"""You are a database assistant for {self.database_type} databases.
Primary Schema: {self.primary_schema}
Available Schemas: {', '.join(self.allowed_schemas)}

{user_context if user_context else ''}
{context if context else ''}

Please help the user with their database query using available tools."""


    def _parse_components(
        self,
        user_role: UserRole,
        output_components: Optional[Union[str, OutputComponent]],
        add_components: Optional[Union[str, OutputComponent]],
        remove_components: Optional[Union[str, OutputComponent]]
    ) -> OutputComponent:
        """Parse and combine output components from various inputs."""

        if output_components is not None:
            # Explicit override
            if isinstance(output_components, str):
                final_components = components_from_string(output_components)
            else:
                final_components = output_components
        else:
            # Start with role defaults
            final_components = get_default_components(user_role)

        # Apply additions
        if add_components:
            if isinstance(add_components, str):
                add_comp = components_from_string(add_components)
            else:
                add_comp = add_components
            final_components |= add_comp

        # Apply removals
        if remove_components:
            if isinstance(remove_components, str):
                remove_comp = components_from_string(remove_components)
            else:
                remove_comp = remove_components
            final_components &= ~remove_comp

        return final_components

    async def ask(
        self,
        query: str,
        context: Optional[str] = None,
        user_role: UserRole = UserRole.DATA_ANALYST,
        user_context: Optional[str] = None,
        output_components: Optional[Union[str, OutputComponent]] = None,
        output_format: Optional[str] = None,  # "markdown", "json", "dataframe"
        session_id: Optional[str] = None,
        user_id: Optional[str] = None,
        use_conversation_history: bool = True,
        # Component customization
        add_components: Optional[Union[str, OutputComponent]] = None,
        remove_components: Optional[Union[str, OutputComponent]] = None,
        enable_retry: bool = True,
        **kwargs
    ) -> AIMessage:
        """
        Ask method with role-based component responses.

        Args:
            query: The user's question about the database
            user_role: User role determining default response components
            output_components: Override default components (string or OutputComponent flags)
            output_format: Output format preference ("markdown", "json", "dataframe")
            add_components: Additional components to include (string or OutputComponent flags)
            remove_components: Components to exclude (string or OutputComponent flags)
            context: Additional context for the request
            user_context: User-specific context
            enable_retry: Whether to enable query retry on errors
            session_id: Session identifier for conversation history
            user_id: User identifier
            use_conversation_history: Whether to use conversation history
            **kwargs: Additional arguments for LLM

        Returns:
            AIMessage: Enhanced response with role-appropriate components

        Examples:
            # Business user wants all inventory data
            response = await agent.ask(
                "Show me all inventory items",
                user_role=UserRole.BUSINESS_USER
            )

            # Developer wants table metadata in markdown
            response = await agent.ask(
                "Return in markdown format the metadata of table inventory in schema hisense",
                user_role=UserRole.DEVELOPER,
                output_format="markdown"
            )

            # Data scientist wants DataFrame output
            response = await agent.ask(
                "Get sales data for analysis",
                user_role=UserRole.DATA_SCIENTIST
            )

            # DBA wants performance analysis
            response = await agent.ask(
                "Analyze slow queries on user table",
                user_role=UserRole.DATABASE_ADMIN
            )

            # Custom component combination
            response = await agent.ask(
                "Get user data",
                user_role=UserRole.DATA_ANALYST,
                add_components="performance,optimize"
            )
        """
        # Parse user role
        if isinstance(user_role, str):
            user_role = UserRole(user_role.lower())

        # Add retry configuration to kwargs
        retry_config = kwargs.pop('retry_config', QueryRetryConfig())

        # Override temperature to ensure consistent database operations
        kwargs['temperature'] = kwargs.get('temperature', self._default_temperature)

        # Generate session ID if not provided
        if not session_id:
            session_id = f"db_session_{hash(query + str(user_id))}"

        # Parse output components
        _components = self._parse_components(
            user_role, output_components, add_components, remove_components
        )

        try:
            # Step 1: Get conversation context
            conversation_history = None
            conversation_context = ""

            if use_conversation_history and self.conversation_memory:
                try:
                    conversation_history = await self.get_conversation_history(user_id, session_id)
                    if not conversation_history:
                        conversation_history = await self.create_conversation_history(user_id, session_id)
                    conversation_context = self.build_conversation_context(conversation_history)
                except Exception as e:
                    self.logger.warning(f"Failed to load conversation history: {e}")

            # Step 2: Get vector context from knowledge store
            vector_context = ""
            vector_metadata = {}
            if self.knowledge_store:
                try:
                    search_results = await self.knowledge_store.similarity_search(query, k=5)
                    if search_results:
                        vector_context = "\n\n".join(
                            [doc.page_content for doc in search_results]
                        )
                        vector_metadata = {
                            'sources': [doc.metadata.get('source', 'unknown') for doc in search_results],
                            'tables_referenced': [
                                doc.metadata.get('table_name')
                                for doc in search_results
                                if doc.metadata.get('table_name')
                            ]
                        }
                        self.logger.debug(
                            f"Retrieved vector context from {len(search_results)} sources"
                        )
                except Exception as e:
                    self.logger.warning(f"Error retrieving vector context: {e}")
        except Exception as e:
            self.logger.warning(f"Error preparing context: {e}")
            conversation_context = ""
            vector_context = ""
            vector_metadata = {}

        try:
            # Step 3: Route the query
            route: RouteDecision = await self.query_router.route(
                query=query,
                user_role=user_role,
                output_components=_components
            )

            self.logger.info(
                f"Query Routed: intent={route.intent.value}, "
                f"schema={route.primary_schema}, "
                f"role={route.user_role.value}, components={route.components}"
            )

            # Step 4: Discover metadata (if needed)
            metadata_context = ""
            discovered_tables = []
            if route.needs_metadata_discovery or route.intent in [QueryIntent.EXPLORE_SCHEMA, QueryIntent.EXPLAIN_METADATA]:
                self.logger.debug("🔍 Starting metadata discovery...")
                metadata_context, discovered_tables = await self._discover_metadata(query)
                self.logger.info(
                    f"✅ DISCOVERED: {len(discovered_tables)} tables with context length: {len(metadata_context)}"
                )

            # Step 6: Make the LLM call with tools enabled
            self.logger.info(
                f"Processing database query: use_tools=True, "
                f"available_tools={len(self.tool_manager.get_tools())}"
            )

            # Step 7: Generate/validate query (if needed)
            db_response, llm_response = await self._process_query(
                query=query,
                route=route,
                metadata_context=metadata_context,
                discovered_tables=discovered_tables,
                conversation_context=conversation_context,
                vector_context=vector_context,
                user_context=user_context,
                enable_retry=enable_retry,
                retry_config=retry_config,
                **kwargs
            )

            # Step 9: Format response
            return await self._format_response(
                query=query,
                db_response=db_response,
                route=route,
                llm_response=llm_response,
                output_format=output_format,
                discovered_tables=discovered_tables,
                **kwargs
            )

        except Exception as e:
            self.logger.error(
                f"Error in enhanced ask method: {e}"
            )
            return self._create_error_response(query, e, user_role)

    async def _use_schema_search_tool(self, user_query: str) -> Optional[str]:
        """Use schema search tool to discover relevant metadata."""
        try:
            # Direct call to schema tool
            search_results = await self.schema_tool.search_schema(
                search_term=user_query,
                search_type="all",
                limit=5
            )

            if search_results:
                self.logger.info(
                    f"Found {len(search_results)} tables via schema tool"
                )
                metadata_parts = []
                for table in search_results:
                    metadata_parts.append(table.to_yaml_context())
                return "\n---\n".join(metadata_parts)

        except Exception as e:
            self.logger.error(
                f"Schema tool failed: {e}"
            )

        return None

    async def _discover_metadata(self, query: str) -> Tuple[str, List[TableMetadata]]:
        """
        Discover relevant metadata for the query across allowed schemas.

        Returns:
            Tuple[str, List[TableMetadata]]: (metadata_context, discovered_tables)
        """
        self.logger.debug(
            f"🔍 DISCOVERY: Starting metadata discovery for query: '{query}'"
        )

        discovered_tables = []
        metadata_parts = []

        # Step 1: Direct schema search using table name extraction
        table_name = self._extract_table_name_from_query(query)
        if table_name:
            self.logger.debug(f"📋 Extracted table name: {table_name}")

            # Search for exact table match first
            for schema in self.allowed_schemas:
                table_metadata = await self.metadata_cache.get_table_metadata(schema, table_name)
                if table_metadata:
                    self.logger.info(f"✅ EXACT MATCH: Found {schema}.{table_name}")
                    discovered_tables.append(table_metadata)
                    metadata_parts.append(table_metadata.to_yaml_context())
                    break

        # Step 2: Fuzzy search if no exact match
        if not discovered_tables:
            self.logger.debug("🔄 No exact match, performing fuzzy search...")
            similar_tables = await self.schema_tool.search_schema(
                search_term=query,
                search_type="all",
                limit=5
            )

            if similar_tables:
                self.logger.info(f"🎯 FUZZY SEARCH: Found {len(similar_tables)} similar tables")
                discovered_tables.extend(similar_tables)
                for table in similar_tables:
                    metadata_parts.append(table.to_yaml_context())

        # Step 3: Fallback to hot tables if still no results
        if not discovered_tables:
            self.logger.warning("⚠️  No specific tables found, using hot tables fallback")
            hot_tables = self.metadata_cache.get_hot_tables(self.allowed_schemas, limit=3)

            for schema_name, table_name, access_count in hot_tables:
                table_meta = await self.metadata_cache.get_table_metadata(schema_name, table_name)
                if table_meta:
                    discovered_tables.append(table_meta)
                    metadata_parts.append(table_meta.to_yaml_context())

        # Combine metadata context
        metadata_context = "\n---\n".join(metadata_parts) if metadata_parts else ""

        if not metadata_context:
            # Absolute fallback
            metadata_context = f"Available schemas: {', '.join(self.allowed_schemas)} (primary: {self.primary_schema})"
            self.logger.warning("⚠️  Using minimal fallback context")

        self.logger.info(
            f"🏁 DISCOVERY COMPLETE: {len(discovered_tables)} tables, "
            f"context length: {len(metadata_context)} chars"
        )

        return metadata_context, discovered_tables

    def _extract_table_name_from_query(self, query: str) -> Optional[str]:
        """Extract table name from user query."""
        # Common patterns for table name extraction
        patterns = [
            r'table\s+(\w+)',           # "table inventory"
            r'metadata\s+of\s+table\s+(\w+)',   # "metadata of table inventory"
            r'metadata\s+of\s+(\w+)',   # "metadata of inventory"
            r'describe\s+(\w+)',        # "describe inventory"
            r'structure\s+of\s+(\w+)',  # "structure of inventory"
            r'information\s+about\s+(\w+)', # "information about inventory"
            r'details\s+of\s+(\w+)',    # "details of inventory"
            r'schema\s+(\w+)',          # "schema inventory"
            r'\b(\w+)\s+table\b',       # "inventory table"
        ]

        query_lower = query.lower()
        for pattern in patterns:
            match = re.search(pattern, query_lower)
            if match:
                table_name = match.group(1)
                # Avoid common false positives
                if table_name not in ['the', 'in', 'from', 'with', 'for', 'about', 'format', 'return']:
                    self.logger.debug(f"📋 Extracted table name: '{table_name}' using pattern: {pattern}")
                    return table_name

        return None

    async def _generate_schema(
        self,
        query: str,
        metadata_context: str,
        schema_name: str
    ) -> str:
        """
        Generate explanation for schema exploration queries.

        Used when users ask about table metadata, schema structure, etc.
        """

        # Extract table name if mentioned in query
        table_name = self._extract_table_name_from_query(query)

        if table_name:
            # Get specific table metadata
            table_metadata = await self.get_table_metadata(schema_name, table_name)
            if table_metadata:
                explanation = f"**Table: `{table_metadata.full_name}`**\n\n"
                explanation += table_metadata.to_yaml_context()
                return explanation

        # General schema information
        if metadata_context:
            explanation = f"**Schema Information for `{schema_name}`:**\n\n"
            explanation += metadata_context
            return explanation

        # Fallback
        return f"Schema `{schema_name}` information. Use schema exploration tools for detailed structure."

    async def _query_generation(
        self,
        query: str,
        route: RouteDecision,
        metadata_context: str,
        **kwargs
    ) -> Tuple[str, str, AIMessage]:
        """Generate SQL query using LLM based on user request and metadata."""
        self.logger.debug(
            f"🔍 QUERY GEN: Generating SQL for intent '{route.intent.value}' "
            f"with components {route.components}"
        )
        system_prompt = f"""
You are a PostgreSQL query expert for multi-schema databases.

**Database Context:**
**Primary Schema:** {self.primary_schema}
**Allowed Schemas:** {', '.join(self.allowed_schemas)}

**Available Tables and Structure:**
{metadata_context}

**Instructions:**
1. Generate PostgreSQL queries using only these schemas: {', '.join([f'"{schema}"' for schema in self.allowed_schemas])}
2. If you can generate a query using the available tables/columns, return ONLY the SQL query in a ```sql code block
3. NEVER invent table names - only use tables from the metadata above
4. If metadata is insufficient, use schema exploration tools
5. If you CANNOT generate a query (missing tables, columns, etc.), explain WHY in plain text - do NOT use code blocks
6. For "show me" queries, generate simple SELECT statements
7. Always include appropriate LIMIT clauses
8. Prefer primary schema "{self.primary_schema}" unless user specifies otherwise

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

Analyze the request and either generate a valid PostgreSQL query OR explain why it cannot be fulfilled.
Apply semantic understanding to map user concepts to available columns.

**Your Task:** Analyze the user request and provide either a SQL query OR a clear explanation.
    """
        # Call LLM for query generation
        llm_response = await self._llm.ask(
            prompt=f"User request: {query}",
            system_prompt=system_prompt,
            **kwargs
        )

        # Extract SQL and explanation
        response_text = str(llm_response.output) if llm_response.output else str(llm_response.response)
        # 🔍 DEBUG: Log what LLM actually said
        self.logger.info(f"🤖 LLM RESPONSE: {response_text[:200]}...")
        sql_query = self._extract_sql_from_response(response_text)

        if not sql_query:
            if self._is_explanatory_response(response_text):
                self.logger.info(f"🔍 LLM PROVIDED EXPLANATION: No SQL generated, but explanation available")
                return None, response_text, llm_response
            else:  # ← FIX: Move the else inside the if not sql_query block
                self.logger.warning(f"🔍 LLM RESPONSE UNCLEAR: No SQL found and doesn't look like explanation")

        return sql_query, response_text, llm_response

    def _is_explanatory_response(self, response_text: str) -> bool:
        """Detect if the LLM response is an explanation rather than SQL."""

        # Clean the response for analysis
        cleaned_text = response_text.strip().lower()

        # Patterns that indicate explanatory responses
        explanation_patterns = [
            "i cannot",
            "i'm sorry",
            "i am sorry",
            "unable to",
            "cannot fulfill",
            "cannot generate",
            "cannot create",
            "the table",
            "the metadata",
            "does not contain",
            "missing",
            "not found",
            "no table",
            "no column",
            "not available",
            "insufficient information",
            "please provide",
            "you need to"
        ]

        # Check if response contains explanatory language
        contains_explanation = any(pattern in cleaned_text for pattern in explanation_patterns)

        # Check if response lacks SQL patterns
        sql_patterns = ['select', 'from', 'where', 'order by', 'group by', 'insert', 'update', 'delete']
        contains_sql = any(pattern in cleaned_text for pattern in sql_patterns)

        # It's explanatory if it has explanation patterns but no SQL
        is_explanatory = contains_explanation and not contains_sql

        self.logger.debug(
            f"🔍 EXPLANATION CHECK: explanation_patterns={contains_explanation}, sql_patterns={contains_sql}, is_explanatory={is_explanatory}"
        )
        return is_explanatory

    async def _generate_query(
        self,
        query: str,
        route: RouteDecision,
        metadata_context: str,
        conversation_context: str,
        vector_context: str,
        user_context: Optional[str],
        **kwargs
    ) -> Tuple[Optional[str], Optional[str], Optional[AIMessage]]:
        """
        Generate SQL query based on user request and context.

        Adapts the existing _process_query_generation method to work with components.
        """

        # For schema exploration, don't generate SQL - use schema tools
        if route.intent.value in ['explore_schema', 'explain_metadata']:
            explanation = await self._generate_schema(
                query, metadata_context, route.primary_schema
            )
            return None, explanation, None

        elif route.intent.value == 'validate_query':
            # User provided SQL, validate it
            sql_query = query.strip()
            explanation, llm_response = await self._validate_user_sql(
                sql_query, metadata_context
            )
            return sql_query, explanation, llm_response

        else:
            # Generate new SQL query using the EXISTING method from your code
            sql_query, explanation, llm_response = await self._query_generation(
                query, route, metadata_context, **kwargs
            )
            return sql_query, explanation, llm_response

    async def _process_query(
        self,
        query: str,
        route: RouteDecision,
        metadata_context: str,
        discovered_tables: List[TableMetadata],
        conversation_context: str,
        vector_context: str,
        user_context: Optional[str],
        enable_retry: bool,
        retry_config: Optional[QueryRetryConfig] = None,
        **kwargs
    ) -> Tuple[DatabaseResponse, AIMessage]:
        """Process query generation with LLM."""

        db_response = DatabaseResponse(components_included=route.components)
        llm_response = None

        is_documentation_request = (
            'metadata' in query.lower() or
            'documentation' in query.lower() or
            'describe' in query.lower() or
            'structure' in query.lower() or
            route.intent in [QueryIntent.EXPLORE_SCHEMA, QueryIntent.EXPLAIN_METADATA]
        )
        db_response.is_documentation = True

        # Generate SQL query (if needed)
        if route.needs_query_generation and OutputComponent.SQL_QUERY in route.components:
            sql_query, explanation, llm_response = await self._generate_query(
                query, route, metadata_context, conversation_context,
                vector_context, user_context, **kwargs
            )
            db_response.query = sql_query

            # Store explanation for documentation component
            if OutputComponent.DOCUMENTATION in route.components:
                db_response.documentation = explanation

        # Execute query (if needed)
        if route.needs_execution and db_response.query:
            exec_result = await self._execute_query(
                db_response.query, route, enable_retry, retry_config
            )

            if exec_result.success:
                # Handle data conversion based on components
                if OutputComponent.DATAFRAME_OUTPUT in route.components:
                    if exec_result.data:
                        db_response.data = pd.DataFrame(exec_result.data)
                elif OutputComponent.DATA_RESULTS in route.components:
                    db_response.data = exec_result.data

                db_response.row_count = exec_result.row_count
                db_response.execution_time_ms = exec_result.execution_time_ms

                # Sample data for context
                if OutputComponent.SAMPLE_DATA in route.components and exec_result.data:
                    db_response.sample_data = exec_result.data[:5]  # First 5 rows

            # Execution plan analysis
            if exec_result.query_plan and OutputComponent.EXECUTION_PLAN in route.components:
                db_response.execution_plan = exec_result.query_plan

                # Generate performance metrics
                if OutputComponent.PERFORMANCE_METRICS in route.components:
                    db_response.performance_metrics = self._extract_performance_metrics(
                        exec_result.query_plan, exec_result.execution_time_ms
                    )

                # Generate LLM-based optimization tips
                if OutputComponent.OPTIMIZATION_TIPS in route.components:
                    db_response.optimization_tips, llm_response = await self._generate_optimization_tips(
                        db_response.query, exec_result.query_plan, metadata_context
                    )

        # FIXED: For documentation requests, format discovered table metadata instead of examples
        if OutputComponent.DOCUMENTATION in route.components or is_documentation_request:
            if discovered_tables:
                # Generate detailed documentation for discovered tables
                db_response.documentation = await self._format_table_documentation(
                    discovered_tables, route.user_role, query
                )

        # Generate examples only if NOT a documentation request
        if OutputComponent.EXAMPLES in route.components and not is_documentation_request:
            db_response.examples = await self._generate_examples(
                query, metadata_context, discovered_tables, route.primary_schema
            )

        # Schema context (if requested)
        if OutputComponent.SCHEMA_CONTEXT in route.components:
            db_response.schema_context = await self._build_schema_context(
                route.primary_schema, route.allowed_schemas
            )

        return db_response, llm_response

    async def _format_table_documentation(
        self,
        discovered_tables: List[TableMetadata],
        user_role: UserRole,
        original_query: str
    ) -> str:
        """
        FIXED: Format discovered table metadata as proper documentation.

        This replaces the generic examples with actual table documentation.
        """
        if not discovered_tables:
            return "No table metadata found for documentation."

        documentation_parts = []

        for table in discovered_tables:
            # Table header
            table_doc = [f"# Table: `{table.full_name}`\n"]

            # Table information
            if table.comment:
                table_doc.append(f"**Description:** {table.comment}\n")

            table_doc.append(f"**Schema:** {table.schema}")
            table_doc.append(f"**Table Name:** {table.tablename}")
            table_doc.append(f"**Type:** {table.table_type}")
            table_doc.append(f"**Row Count:** {table.row_count:,}" if table.row_count else "**Row Count:** Unknown")

            # Column documentation
            if table.columns:
                table_doc.append("\n## Columns\n")

                # Create markdown table for columns
                table_doc.append("| Column Name | Data Type | Nullable | Default | Comment |")
                table_doc.append("|-------------|-----------|----------|---------|---------|")

                for col in table.columns:
                    nullable = "Yes" if col.get('nullable', True) else "No"
                    default_val = col.get('default', '') or ''
                    comment = col.get('comment', '') or ''
                    data_type = col.get('type', 'unknown')

                    # Handle max_length for varchar types
                    if col.get('max_length') and 'character' in data_type.lower():
                        data_type = f"{data_type}({col['max_length']})"

                    table_doc.append(
                        f"| `{col['name']}` | {data_type} | {nullable} | {default_val} | {comment} |"
                    )

            # Primary keys
            if hasattr(table, 'primary_keys') and table.primary_keys:
                table_doc.append(f"\n**Primary Keys:** {', '.join([f'`{pk}`' for pk in table.primary_keys])}")

            # Foreign keys
            if hasattr(table, 'foreign_keys') and table.foreign_keys:
                table_doc.append("\n**Foreign Keys:**")
                for fk in table.foreign_keys:
                    if isinstance(fk, dict):
                        table_doc.append(f"- `{fk.get('column')}` -> `{fk.get('referenced_table')}.{fk.get('referenced_column')}`")

            # Indexes
            if hasattr(table, 'indexes') and table.indexes:
                table_doc.append(f"\n**Indexes:** {len(table.indexes)} indexes defined")

            # CREATE TABLE statement for developers
            if user_role == UserRole.DEVELOPER:
                create_statement = self._generate_create_table_statement(table)
                if create_statement:
                    table_doc.append(f"\n## CREATE TABLE Statement\n\n```sql\n{create_statement}\n```")

            # Sample data (if available and requested)
            if hasattr(table, 'sample_data') and table.sample_data and len(table.sample_data) > 0:
                table_doc.append("\n## Sample Data\n")
                # Show first 3 rows as example
                sample_rows = table.sample_data[:3]
                if sample_rows:
                    # Get column headers
                    headers = list(sample_rows[0].keys()) if sample_rows else []
                    if headers:
                        # Create sample data table
                        table_doc.append("| " + " | ".join(headers) + " |")
                        table_doc.append("| " + " | ".join(['---'] * len(headers)) + " |")

                        for row in sample_rows:
                            values = [str(row.get(h, '')) for h in headers]
                            # Truncate long values
                            values = [v[:50] + '...' if len(str(v)) > 50 else str(v) for v in values]
                            table_doc.append("| " + " | ".join(values) + " |")

            # Access statistics
            if hasattr(table, 'last_accessed') and table.last_accessed:
                table_doc.append(f"\n**Last Accessed:** {table.last_accessed}")
            if hasattr(table, 'access_frequency') and table.access_frequency:
                table_doc.append(f"**Access Frequency:** {table.access_frequency}")

            documentation_parts.append("\n".join(table_doc))

        return "\n\n---\n\n".join(documentation_parts)

    def _generate_create_table_statement(self, table: TableMetadata) -> str:
        """Generate CREATE TABLE statement from table metadata."""
        if not table.columns:
            return ""

        create_parts = [f'CREATE TABLE {table.full_name} (']

        column_definitions = []
        for col in table.columns:
            col_def = f'    "{col["name"]}" {col["type"]}'

            # Add NOT NULL constraint
            if not col.get('nullable', True):
                col_def += ' NOT NULL'

            # Add DEFAULT value
            if col.get('default'):
                default_val = col['default']
                # Handle different default value types
                if default_val.lower() in ['now()', 'current_timestamp', 'current_date']:
                    col_def += f' DEFAULT {default_val}'
                elif default_val.replace("'", "").replace('"', '').isdigit():
                    col_def += f' DEFAULT {default_val}'
                else:
                    col_def += f" DEFAULT '{default_val}'"

            column_definitions.append(col_def)

        # Add primary key constraint
        if hasattr(table, 'primary_keys') and table.primary_keys:
            pk_cols = ', '.join([f'"{pk}"' for pk in table.primary_keys])
            column_definitions.append(f'    PRIMARY KEY ({pk_cols})')

        create_parts.append(',\n'.join(column_definitions))
        create_parts.append(');')

        # Add table comment if exists
        if table.comment:
            create_parts.append(f"\n\nCOMMENT ON TABLE {table.full_name} IS '{table.comment}';")

        # Add column comments
        for col in table.columns:
            if col.get('comment'):
                create_parts.append(
                    f'COMMENT ON COLUMN {table.full_name}."{col["name"]}" IS \'{col["comment"]}\';'
                )

        return '\n'.join(create_parts)

    async def _build_schema_context(
        self,
        primary_schema: str,
        allowed_schemas: List[str]
    ) -> str:
        """
        Build comprehensive schema context for the user.

        Provides information about available tables, relationships, and schema structure.
        """

        context_parts = []

        # Schema overview
        context_parts.append(
            f"**Database Schema Information:**"
        )
        context_parts.append(f"- Primary Schema: `{primary_schema}`")
        context_parts.append(
            f"- Accessible Schemas: {', '.join([f'`{s}`' for s in allowed_schemas])}"
        )

        # Get table counts per schema
        schema_table_counts = {}
        for schema_name in allowed_schemas:
            try:
                overview = await self.get_schema_overview(schema_name)
                if overview:
                    table_count = overview.get('table_count', 0)
                    view_count = overview.get('view_count', 0)
                    schema_table_counts[schema_name] = {
                        'tables': table_count,
                        'views': view_count
                    }
            except Exception as e:
                self.logger.warning(f"Could not get overview for schema {schema_name}: {e}")
                schema_table_counts[schema_name] = {'tables': 0, 'views': 0}

        # Add schema details
        if schema_table_counts:
            context_parts.append(f"\n**Schema Details:**")
            for schema_name, counts in schema_table_counts.items():
                context_parts.append(
                    f"- `{schema_name}`: {counts['tables']} tables, {counts['views']} views"
                )

        # Get hot tables (most accessed)
        hot_tables = self.metadata_cache.get_hot_tables(allowed_schemas, limit=5)
        if hot_tables:
            context_parts.append(f"\n**Frequently Used Tables:**")
            for schema_name, table_name, access_count in hot_tables:
                context_parts.append(f"- `{schema_name}.{table_name}` (accessed {access_count} times)")

        # Add usage tips
        context_parts.append(f"\n**Usage Tips:**")
        context_parts.append(f"- Use schema-qualified names: `{primary_schema}.table_name`")
        context_parts.append(f"- Search for tables with: 'What tables contain [keyword]?'")
        context_parts.append(f"- Get table structure with: 'Describe table [table_name]'")

        return "\n".join(context_parts)

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
        route: RouteDecision,
        enable_retry: bool = True,
        retry_config: Optional[QueryRetryConfig] = None
    ) -> QueryExecutionResponse:
        """Execute SQL query with schema security."""

        start_time = datetime.now()
        # Configure execution options based on components
        options = dict(route.execution_options)

        # Component-specific configuration
        if OutputComponent.EXECUTION_PLAN in route.components:
            options['explain_analyze'] = True

        # Apply data limits based on role and components
        if route.include_full_data:
            options['limit'] = None  # No limit for business users
        elif route.data_limit:
            options['limit'] = route.data_limit

        if route.user_role.value == 'database_admin':
            options['timeout'] = 60
        else:
            options.setdefault('timeout', 30)

        # Retry Handler when enable_retry is True
        if enable_retry:
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
            execution_time = (datetime.now() - start_time).total_seconds() * 1000
            return QueryExecutionResponse(
                success=False,
                data=None,
                row_count=0,
                execution_time_ms=execution_time,
                schema_used=self.primary_schema,
                error_message=f"Query failed after {retry_count} retries. Last error: {last_error}",
                query_plan=None,
                metadata={
                    "retry_count": retry_count,
                    "query_history": query_history,
                    "last_error_type": type(last_error).__name__ if last_error else None
                }
            )
        else:
            # No retry, single attempt with error handling
            return await self._execute_query_safe(sql_query, options)

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
        sql_patterns = [
            r'```sql\s*(.*?)\s*```',  # ```sql with optional whitespace
            r'```SQL\s*(.*?)\s*```',  # ```SQL (uppercase)
            r'```\s*(SELECT.*?(?:;|\Z))',  # ``` with SELECT (no sql label)
            r'```\s*(WITH.*?(?:;|\Z))',   # ``` with WITH (no sql label)
        ]

        for pattern in sql_patterns:
            matches = re.findall(pattern, response_text, re.DOTALL | re.IGNORECASE)
            if matches:
                sql = matches[0].strip()
                if sql:
                    self.logger.debug(f"SQL EXTRACTED via pattern: {pattern[:20]}...")
                    return sql

        lines = response_text.split('\n')
        sql_lines = []
        in_sql = False

        for line in lines:
            line_stripped = line.strip()
            line_upper = line_stripped.upper()

            # Start collecting SQL when we see a SQL keyword
            if any(line_upper.startswith(kw) for kw in ['SELECT', 'WITH', 'INSERT', 'UPDATE', 'DELETE']):
                in_sql = True
                sql_lines.append(line_stripped)
            elif in_sql:
                # Continue collecting until we hit a terminator or empty line
                if line_stripped.endswith(';'):
                    sql_lines.append(line_stripped)
                    break
                elif not line_stripped:
                    break
                elif line_stripped.startswith('**') or line_stripped.startswith('#'):
                    # Stop at markdown headers or emphasis
                    break
                else:
                    sql_lines.append(line_stripped)

        if sql_lines:
            sql_query = '\n'.join(sql_lines)
            self.logger.debug(f"SQL EXTRACTED via fallback parsing")
            return sql_query

        # Last resort: return original if it contains SQL keywords
        if any(kw in response_text.upper() for kw in ['SELECT', 'FROM', 'WHERE']):
            self.logger.warning("Using entire response as SQL (last resort)")
            return response_text.strip()

        self.logger.warning("No SQL found in response")
        return ""

    def _format_as_text(
        self,
        db_response: DatabaseResponse,
        user_role: UserRole,
        discovered_tables: List[TableMetadata]
    ) -> str:
        """Format response as readable text based on user role."""
        sections = []
        if db_response.documentation and len(db_response.documentation) > 100:
            return db_response.documentation

        # Role-specific formatting preferences
        if user_role == UserRole.BUSINESS_USER:
            # Simple, data-focused format
            if db_response.data is not None:
                if isinstance(db_response.data, pd.DataFrame):
                    sections.append(
                        f"**Results:** {len(db_response.data)} records found"
                    )
                else:
                    sections.append(
                        f"**Results:** {db_response.row_count} records found"
                    )

        elif user_role == UserRole.DEVELOPER:
            # For developers requesting metadata, prioritize documentation
            if db_response.documentation:
                sections.append(db_response.documentation)
            elif discovered_tables:
                # Fallback to basic table info if no documentation generated
                for table in discovered_tables[:1]:  # Show first table
                    sections.append(f"**Table Found:** {table.full_name}")
                    sections.append(f"**Columns:** {len(table.columns)} columns")
                    if table.columns:
                        col_list = ', '.join([f"`{col['name']}`" for col in table.columns[:5]])
                        if len(table.columns) > 5:
                            col_list += f", ... and {len(table.columns) - 5} more"
                        sections.append(f"**Column Names:** {col_list}")

            # Technical focus with examples ONLY if no documentation
            if not db_response.documentation:
                if db_response.query:
                    sections.append(f"**SQL Query:**\n```sql\n{db_response.query}\n```")
                if db_response.examples:
                    examples_text = "\n".join([f"```sql\n{ex}\n```" for ex in db_response.examples])
                    sections.append(f"**Usage Examples:**\n{examples_text}")

        elif user_role == UserRole.DATABASE_ADMIN:
            # Performance and optimization focus
            if discovered_tables:
                sections.append(f"**Analyzed Tables:** {len(discovered_tables)} tables discovered")

            if db_response.documentation:
                sections.append(db_response.documentation)
            if db_response.query:
                sections.append(f"**Query:**\n```sql\n{db_response.query}\n```")
            if db_response.execution_plan:
                sections.append(f"**Execution Plan:**\n```\n{db_response.execution_plan}\n```")
            if db_response.performance_metrics:
                metrics = "\n".join([f"- {k}: {v}" for k, v in db_response.performance_metrics.items()])
                sections.append(f"**Performance Metrics:**\n{metrics}")
            if db_response.optimization_tips:
                tips = "\n".join([f"- {tip}" for tip in db_response.optimization_tips])
                sections.append(f"**Optimization Suggestions:**\n{tips}")
        elif user_role in [UserRole.DATA_ANALYST, UserRole.DATA_SCIENTIST]:
            # Comprehensive format with data focus
            if db_response.query:
                sections.append(f"**SQL Query:**\n```sql\n{db_response.query}\n```")
            if db_response.data is not None:
                if isinstance(db_response.data, pd.DataFrame):
                    sections.append(f"**Results:** {len(db_response.data)} records found")
                else:
                    sections.append(f"**Results:** {db_response.row_count} records found")
            if db_response.documentation:
                sections.append(f"**Documentation:**\n{db_response.documentation}")
            if db_response.examples:
                examples_text = "\n".join([f"```sql\n{ex}\n```" for ex in db_response.examples])
                sections.append(f"**Usage Examples:**\n{examples_text}")
            if db_response.execution_plan:
                sections.append(f"**Execution Plan:**\n```\n{db_response.execution_plan}\n```")
            if db_response.performance_metrics:
                metrics = "\n".join([f"- {k}: {v}" for k, v in db_response.performance_metrics.items()])
                sections.append(f"**Performance Metrics:**\n{metrics}")
            if db_response.optimization_tips:
                tips = "\n".join([f"- {tip}" for tip in db_response.optimization_tips])
                sections.append(f"**Optimization Suggestions:**\n{tips}")
        else:
            # Default comprehensive format for DATA_ANALYST and DATA_SCIENTIST
            if discovered_tables:
                sections.append(
                    f"**Schema Analysis:** Found {len(discovered_tables)} relevant tables"
                )
            return db_response.to_markdown()

        return "\n\n".join(sections)

    async def _format_response(
        self,
        query: str,
        db_response: DatabaseResponse,
        llm_response: Optional[AIMessage],
        route: RouteDecision,
        output_format: Optional[str],
        discovered_tables: List[TableMetadata],
        **kwargs
    ) -> AIMessage:
        """Format final response based on route decision."""

        if db_response.is_documentation and discovered_tables and not db_response.documentation:
            # Generate documentation on the fly
            db_response.documentation = await self._format_table_documentation(
                discovered_tables, route.user_role, query
            )

        # Generate response text based on format preference
        if output_format == "markdown":
            response_text = db_response.to_markdown()
        elif output_format == "json":
            response_text = db_response.to_json()
        else:
            response_text = self._format_as_text(
                db_response,
                route.user_role,
                discovered_tables
            )

        # Prepare output data
        output_data = None
        if OutputComponent.DATAFRAME_OUTPUT in route.components and isinstance(db_response.data, pd.DataFrame):
            output_data = db_response.data
        elif OutputComponent.DATA_RESULTS in route.components:
            output_data = db_response.data

        # Extract usage information from LLM response
        usage_info = CompletionUsage(prompt_tokens=0, completion_tokens=0, total_tokens=0)
        if llm_response and hasattr(llm_response, 'usage') and llm_response.usage:
            usage_info = llm_response.usage

        # Extract model and provider info from LLM response if available
        model_name = getattr(self, '_llm_model', 'unknown')
        provider_name = str(getattr(self, '_llm', 'unknown'))

        if llm_response:
            if hasattr(llm_response, 'model') and llm_response.model:
                model_name = llm_response.model
            if hasattr(llm_response, 'provider') and llm_response.provider:
                provider_name = str(llm_response.provider)

        return AIMessage(
            input=query,
            response=response_text,
            output=output_data,
            model=model_name,
            provider=provider_name,
            metadata={
                "user_role": route.user_role.value,
                "components_included": [comp.name for comp in OutputComponent if comp in route.components],
                "intent": route.intent.value,
                "primary_schema": route.primary_schema,
                "sql_query": db_response.query,
                "row_count": db_response.row_count,
                "execution_time_ms": db_response.execution_time_ms,
                "has_dataframe": isinstance(db_response.data, pd.DataFrame),
                "data_format": "dataframe" if isinstance(db_response.data, pd.DataFrame) else "dict_list",
                "discovered_tables": [t.full_name for t in discovered_tables],
                "is_documentation": db_response.is_documentation,
                "llm_used": getattr(self, '_llm_model', 'unknown'),
            },
            usage=usage_info
        )

    def _extract_performance_metrics(
        self,
        query_plan: str,
        execution_time: float
    ) -> Dict[str, Any]:
        """Extract performance metrics from query execution plan."""

        metrics = {
            "execution_time_ms": execution_time,
            "estimated_cost": "N/A",
            "rows_examined": "N/A",
            "index_usage": "Unknown",
            "scan_types": [],
            "join_types": []
        }

        if not query_plan:
            return metrics

        lines = query_plan.split('\n')

        for line in lines:
            line_lower = line.lower()

            # Extract cost information
            if 'cost=' in line_lower:
                cost_match = re.search(r'cost=[\d.]+\.\.([\d.]+)', line)
                if cost_match:
                    metrics["estimated_cost"] = float(cost_match.group(1))

            # Extract row information
            if 'rows=' in line_lower:
                rows_match = re.search(r'rows=(\d+)', line)
                if rows_match:
                    metrics["rows_examined"] = int(rows_match.group(1))

            # Detect scan types
            if 'seq scan' in line_lower:
                metrics["scan_types"].append("Sequential Scan")
                metrics["index_usage"] = "No indexes used"
            elif 'index scan' in line_lower:
                metrics["scan_types"].append("Index Scan")
                metrics["index_usage"] = "Indexes used"
            elif 'index only scan' in line_lower:
                metrics["scan_types"].append("Index Only Scan")
                metrics["index_usage"] = "Index-only access"
            elif 'bitmap heap scan' in line_lower:
                metrics["scan_types"].append("Bitmap Heap Scan")
                metrics["index_usage"] = "Bitmap index used"

            # Detect join types
            if 'nested loop' in line_lower:
                metrics["join_types"].append("Nested Loop")
            elif 'hash join' in line_lower:
                metrics["join_types"].append("Hash Join")
            elif 'merge join' in line_lower:
                metrics["join_types"].append("Merge Join")

        # Remove duplicates
        metrics["scan_types"] = list(set(metrics["scan_types"]))
        metrics["join_types"] = list(set(metrics["join_types"]))

        return metrics

    async def _generate_optimization_tips(
        self,
        sql_query: str,
        query_plan: str,
        metadata_context: str
    ) -> Union[List[str], AIMessage]:
        """
        LLM-based optimization tips instead of manual pattern matching.

        This uses the LLM to analyze execution plans and provide intelligent
        optimization recommendations.
        """
        if not query_plan:
            return ["Enable query plan analysis for optimization suggestions"]

        self.logger.debug("🔧 Generating LLM-based optimization tips...")

        # Create optimization analysis prompt
        optimization_prompt = f"""
You are a database performance expert analyzing a PostgreSQL query execution plan.

**SQL Query:**
```sql
{sql_query}
```

**Execution Plan:**
```
{query_plan}
```

**Available Schema Context:**
{metadata_context[:1000]}...

**Task:** Analyze this execution plan and provide 3-5 specific, actionable optimization recommendations.

**Focus on:**
1. Index recommendations (specific column combinations)
2. Query restructuring suggestions
3. Join optimization opportunities
4. Performance bottlenecks identification
5. Memory/work_mem tuning suggestions

**Format:** Return each tip as a bullet point starting with an appropriate emoji (⚡, 📈, 🔗, 💾, etc.)

**Example good tips:**
- ⚡ Add composite index on (column1, column2) to eliminate sequential scan
- 📈 Consider partitioning table by date_column for better performance
- 🔗 Rewrite EXISTS subquery as LEFT JOIN for better performance

Provide specific, actionable recommendations based on the actual execution plan:
"""
        try:
            # Call LLM for optimization analysis
            llm_response = await self._llm.ask(
                prompt=optimization_prompt,
                temperature=0.1,  # Low temperature for consistent technical advice
                max_tokens=800
            )

            response_text = str(llm_response.output) if llm_response.output else str(llm_response.response)

            # Extract bullet points from LLM response
            tips = []
            for line in response_text.split('\n'):
                line = line.strip()
                if line and (line.startswith('-') or line.startswith('•') or any(emoji in line[:3] for emoji in ['⚡', '📈', '🔗', '💾', '🔧', '📊'])):
                    # Clean up the formatting
                    tip = line.lstrip('- •').strip()
                    if tip:
                        tips.append(tip)

            if tips:
                self.logger.info(f"✅ Generated {len(tips)} LLM-based optimization tips")
                return tips[:5], llm_response  # Limit to 5 tips

        except Exception as e:
            self.logger.error(f"❌ LLM optimization analysis failed: {e}")

        # Fallback to basic analysis if LLM fails
        return self._generate_basic_optimization_tips(sql_query, query_plan), None

    def _generate_basic_optimization_tips(self, sql_query: str, query_plan: str) -> List[str]:
        """Fallback basic optimization tips using pattern matching."""
        tips = []
        plan_lower = query_plan.lower()
        query_lower = sql_query.lower() if sql_query else ""

        # Sequential scan detection
        if 'seq scan' in plan_lower:
            tips.append("⚡ Consider adding indexes on frequently filtered columns to avoid sequential scans")

        # Large sort operations
        if 'sort' in plan_lower:
            tips.append("📈 Large sort operation detected - consider adding indexes for ORDER BY columns")

        # Nested loop joins
        if 'nested loop' in plan_lower and 'join' in query_lower:
            tips.append("🔗 Nested loop joins detected - ensure join columns are indexed")

        # Query structure tips
        if query_lower:
            if 'select *' in query_lower:
                tips.append("📝 Avoid SELECT * - specify only needed columns for better performance")

        return tips or ["✅ Query appears to be well-optimized"]

    def _extract_table_names_from_metadata(self, metadata_context: str) -> List[str]:
        """Extract table names from metadata context."""
        if not metadata_context:
            return []

        # Look for table references in YAML context
        table_matches = re.findall(r'table:\s+\w+\.(\w+)', metadata_context)
        return list(set(table_matches))[:5]  # Limit to 5 unique tables

    async def _generate_examples(
        self,
        query: str,
        metadata_context: str,
        discovered_tables: List[TableMetadata],
        schema_name: str
    ) -> List[str]:
        """Generate usage examples based on available schema metadata."""

        examples = []

        if discovered_tables:
            # Generate examples for each discovered table (limit to 2 for brevity)
            for i, table in enumerate(discovered_tables[:2]):
                table_examples = [
                    f"-- Examples for table: {table.full_name}",
                    f"SELECT * FROM {table.full_name} LIMIT 10;",
                    "",
                    f"SELECT COUNT(*) FROM {table.full_name};",
                    ""
                ]
                # Add column-specific examples if columns are available
                if table.columns:
                    # Find interesting columns (non-id, non-timestamp)
                    interesting_cols = [
                        col['name'] for col in table.columns
                        if not col['name'].lower().endswith(('_id', 'id'))
                        and col['type'].lower() not in ('timestamp', 'timestamptz')
                    ][:5]  # Limit to 5 columns
                    if interesting_cols:
                        col_list = ', '.join(interesting_cols)
                        table_examples.extend([
                            f"SELECT {col_list} FROM {table.full_name} WHERE {interesting_cols[0]} IS NOT NULL LIMIT 2;",
                            ""
                        ])
                examples.extend(table_examples)
            # Add schema exploration examples
            examples.extend([
                "-- Schema exploration",
                f"SELECT table_name FROM information_schema.tables WHERE table_schema = '{schema_name}';",
                "",
                "-- Find tables with specific column patterns",
                f"SELECT table_name, column_name FROM information_schema.columns "
                f"WHERE table_schema = '{schema_name}' AND column_name LIKE '%name%';"
            ])
            return ["\n".join(examples)]

        # Extract table names from metadata context
        tables = self._extract_table_names_from_metadata(metadata_context)

        if not tables:
            # Fallback examples
            return [
                f"SELECT * FROM {schema_name}.table_name LIMIT 10;",
                f"SELECT COUNT(*) FROM {schema_name}.table_name;",
                f"DESCRIBE {schema_name}.table_name;"
            ]

        # Generate examples for available tables
        for table in tables[:2]:  # Limit to 2 tables to avoid clutter
            table_examples = [
                f"-- Basic data retrieval from {table}",
                f"SELECT * FROM {schema_name}.{table} LIMIT 10;",
                f"",
                f"-- Count records in {table}",
                f"SELECT COUNT(*) FROM {schema_name}.{table};",
                f"",
                f"-- Get table structure",
                f"\\d {schema_name}.{table};"
            ]
            examples.extend(table_examples)

        # Add schema exploration examples
        examples.extend([
            "",
            "-- List all tables in schema",
            f"SELECT table_name FROM information_schema.tables WHERE table_schema = '{schema_name}';",
            "",
            "-- Find tables containing specific column",
            f"SELECT table_name FROM information_schema.columns WHERE table_schema = '{schema_name}' AND column_name LIKE '%name%';"
        ])

        return ["\n".join(examples)]

    def _create_error_response(
        self,
        query: str,
        error: Exception,
        user_role
    ) -> 'AIMessage':
        """Create enhanced error response with role-appropriate information."""
        error_msg = f"Error processing database query: {str(error)}"

        # Role-specific error information
        if user_role.value == 'developer':
            error_msg += f"\n\n**Debug Information:**"
            error_msg += f"\n- Error Type: {type(error).__name__}"
            error_msg += f"\n- Primary Schema: {self.primary_schema}"
            error_msg += f"\n- Allowed Schemas: {', '.join(self.allowed_schemas)}"
            error_msg += f"\n- Tools Available: {len(self.tool_manager.get_tools())}"

        elif user_role.value == 'database_admin':
            error_msg += f"\n\n**Technical Details:**"
            error_msg += f"\n- Error: {type(error).__name__}: {str(error)}"
            error_msg += f"\n- Schema Context: {self.primary_schema}"

        else:
            # Simplified error for business users and analysts
            error_msg = f"Unable to process your request. Please try rephrasing your query or contact support."

        return AIMessage(
            input=query,
            response=error_msg,
            output=None,
            model="error_handler",
            provider="system",
            metadata={
                "error_type": type(error).__name__,
                "error_message": str(error),
                "user_role": user_role.value,
                "primary_schema": self.primary_schema
            },
            usage=CompletionUsage(
                prompt_tokens=0,
                completion_tokens=0,
                total_tokens=0
            )
        )

    async def _update_conversation_memory(
        self,
        user_id: str,
        session_id: str,
        user_prompt: str,
        response: AIMessage,
        user_context: Optional[str],
        vector_metadata: Dict[str, Any],
        conversation_history
    ):
        """Update conversation memory with the current interaction."""
        if not self.conversation_memory or not conversation_history:
            return

        try:
            assistant_content = str(response.output) if response.output is not None else (response.response or "")

            # Extract tools used
            tools_used = []
            if hasattr(response, 'tool_calls') and response.tool_calls:
                tools_used = [tool_call.name for tool_call in response.tool_calls]

            turn = ConversationTurn(
                turn_id=str(uuid.uuid4()),
                user_id=user_id,
                user_message=user_prompt,
                assistant_response=assistant_content,
                metadata={
                    'user_context': user_context,
                    'tools_used': tools_used,
                    'primary_schema': self.primary_schema,
                    'tables_referenced': vector_metadata.get('tables_referenced', []),
                    'sources_used': vector_metadata.get('sources', []),
                    'has_sql_execution': bool(response.metadata and response.metadata.get('sql_executed')),
                    'execution_success': response.metadata.get('execution_success') if response.metadata else None
                }
            )

            await self.conversation_memory.add_turn(user_id, session_id, turn)
            self.logger.debug(
                f"Updated conversation memory for session {session_id}"
            )

        except Exception as e:
            self.logger.error(
                f"Failed to update conversation memory: {e}"
            )

    async def cleanup(self) -> None:
        """Cleanup resources."""
        if self.engine:
            await self.engine.dispose()
