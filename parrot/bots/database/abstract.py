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
import inspect
from typing import Dict, Any, List, Optional, Union, Tuple, Type, get_origin, get_args
from dataclasses import is_dataclass
from datetime import datetime
from string import Template
import re
import uuid
from pydantic import BaseModel
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

    def _is_structured_output_format(self, output_format) -> bool:
        """Check if output_format is a BaseModel or dataclass."""
        if output_format is None or isinstance(output_format, str):
            return False
        # Check if it's a Pydantic BaseModel class
        try:
            if inspect.isclass(output_format) and issubclass(output_format, BaseModel):
                return True
        except (TypeError, ImportError):
            pass
        # Check if it's a dataclass
        try:
            if inspect.isclass(output_format) and is_dataclass(output_format):
                return True
        except (TypeError, ImportError):
            pass

        return False

    async def ask(
        self,
        query: str,
        context: Optional[str] = None,
        user_role: UserRole = UserRole.DATA_ANALYST,
        user_context: Optional[str] = None,
        output_components: Optional[Union[str, OutputComponent]] = None,
        output_format: Optional[Union[str, Type[BaseModel], Type]] = None,  # "markdown", "json", "dataframe"
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
        Ask method with role-based component responses and structured output support.

        Args:
            query: The user's question about the database
            user_role: User role determining default response components
            output_components: Override default components (string or OutputComponent flags)
            output_format: Output format preference:
                - String: "markdown", "json", "dataframe"
                - BaseModel: Pydantic model class for structured output
                - Dataclass: Dataclass for structured output
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

            # Structured output with dataclass
            @dataclass
            class QueryAnalysis:
                sql_query: str
                execution_plan: str
                performance_metrics: Dict[str, Any]
                optimization_tips: List[str]

            response = await agent.ask("Analyze query performance",
                                    user_role=UserRole.QUERY_DEVELOPER,
                                    output_format=QueryAnalysis)
        """
        # Detect if output_format is a structured type
        is_structured_output = self._is_structured_output_format(output_format)
        structured_output_class = output_format if is_structured_output else None

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

            self.logger.info(
                f"Processing database query: use_tools=True, "
                f"available_tools={len(self.tool_manager.get_tools())}"
            )

            # Step 5: Generate/validate query (if needed)
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
                context=context,
                **kwargs
            )

            # Step 6: Format Final response, with response output
            return await self._format_response(
                query=query,
                db_response=db_response,
                is_structured_output=is_structured_output,
                structured_output_class=structured_output_class,
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
            self.logger.debug(
                f"📋 Extracted table name: {table_name}"
            )
            # Search for exact table match first
            for schema in self.allowed_schemas:
                table_metadata = await self.metadata_cache.get_table_metadata(
                    schema,
                    table_name
                )
                if table_metadata:
                    self.logger.info(f"✅ EXACT MATCH: Found {schema}.{table_name}")
                    discovered_tables.append(table_metadata)
                    metadata_parts.append(table_metadata.to_yaml_context())
                    break

        # Step 2: If no exact match, try more precise fuzzy search
        if not discovered_tables and table_name:
            self.logger.debug("🔄 No exact match, performing targeted fuzzy search...")

            # Search specifically for the table name, not the entire query
            similar_tables = await self.schema_tool.search_schema(
                search_term=table_name,  # Use ONLY the table name, not entire query
                search_type="table_name",  # Focus on table names only
                limit=3  # Reduce limit to avoid noise
            )

            if similar_tables:
                self.logger.info(f"🎯 FUZZY SEARCH: Found {len(similar_tables)} similar tables")
                discovered_tables.extend(similar_tables)
                for table in similar_tables:
                    metadata_parts.append(table.to_yaml_context())
            else:
                # If still no results, be explicit about missing table
                self.logger.warning(
                    f"❌ TABLE NOT FOUND: '{table_name}' not found in any schema"
                )
                return self._create_table_not_found_response(table_name, query), []

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
            self.logger.warning(
                "⚠️  Using minimal fallback context"
            )

        self.logger.info(
            f"🏁 DISCOVERY COMPLETE: {len(discovered_tables)} tables, "
            f"context length: {len(metadata_context)} chars"
        )

        return metadata_context, discovered_tables

    def _create_table_not_found_response(self, table_name: str, original_query: str) -> str:
        """Create a clear response when table doesn't exist."""
        return f"""**Table Not Found**: `{table_name}`
The table `{table_name}` does not exist in any of the available schemas: {', '.join(self.allowed_schemas)}

**Available options:**
1. Check table name spelling
2. Use: "show tables" to list available tables
3. Search for similar tables: "find tables like {table_name[:5]}"

**Available schemas:** {', '.join([f'`{s}`' for s in self.allowed_schemas])}
"""

    def _extract_table_name_from_query(self, query: str) -> Optional[str]:
        """Extract table name with better precision."""
        # Enhanced patterns with word boundaries and more specific matching
        patterns = [
            r'\bfrom\s+(?:[\w.]+\.)?(\w+)',          # "from schema.table" or "from table"
            r'\btable\s+(?:[\w.]+\.)?(\w+)',         # "table schema.table" or "table name"
            r'\bmetadata\s+of\s+(?:table\s+)?(?:[\w.]+\.)?(\w+)',  # "metadata of table X"
            r'\bdescribe\s+(?:table\s+)?(?:[\w.]+\.)?(\w+)',       # "describe table X"
            r'\bstructure\s+of\s+(?:[\w.]+\.)?(\w+)', # "structure of table"
            r'\binformation\s+about\s+(?:[\w.]+\.)?(\w+)', # "information about table"
            r'\bdetails\s+of\s+(?:[\w.]+\.)?(\w+)',  # "details of table"
            r'(?:[\w.]+\.)?(\w+)\s+table\b',         # "inventory table"
            # Be more specific about "records from" pattern
            r'\brecords?\s+from\s+(?:[\w.]+\.)?(\w+)',    # "records from table"
            r'\bdata\s+from\s+(?:[\w.]+\.)?(\w+)',        # "data from table"
        ]

        query_lower = query.lower()
        for pattern in patterns:
            match = re.search(pattern, query_lower)
            if match:
                table_name = match.group(1)
                # Filter out common false positives and SQL keywords
                false_positives = {
                    'the', 'in', 'from', 'with', 'for', 'about', 'format',
                    'return', 'select', 'where', 'order', 'group', 'by',
                    'limit', 'offset', 'having', 'distinct'
                }
                if table_name not in false_positives:
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
        context: Optional[str] = None,
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

**Context Information:**
{context}

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
        async with self._llm as client:
            llm_response = await client.ask(
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

    async def _execute_query_explain(
        self,
        sql_query: str,
    ) -> QueryExecutionResponse:
        """Execute query with EXPLAIN ANALYZE for performance analysis."""

        start_time = datetime.now()

        try:
            async with self.session_maker() as session:
                # Set search path for security
                search_path = ','.join(self.allowed_schemas)
                await session.execute(text(f"SET search_path = '{search_path}'"))

                # Execute EXPLAIN ANALYZE first
                explain_query = f"EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) {sql_query}"

                try:
                    plan_result = await session.execute(text(explain_query))
                    query_plan_json = plan_result.fetchone()[0]

                    # Convert JSON plan to readable format
                    query_plan = self._format_explain_plan(query_plan_json)

                    print('FORMAT PLAN > ', query_plan)

                    execution_time = (datetime.now() - start_time).total_seconds() * 1000

                    return QueryExecutionResponse(
                        success=True,
                        data=None,  # EXPLAIN doesn't return data
                        row_count=0,
                        execution_time_ms=execution_time,
                        query_plan=query_plan,
                        schema_used=self.primary_schema,
                        metadata={
                            "plan_json": query_plan_json,  # Store JSON for metrics extraction
                            "query_type": "explain_analyze"
                        }
                    )

                except Exception as e:
                    # If EXPLAIN fails, the query has syntax/table issues
                    execution_time = (datetime.now() - start_time).total_seconds() * 1000

                    return QueryExecutionResponse(
                        success=False,
                        data=None,
                        row_count=0,
                        execution_time_ms=execution_time,
                        error_message=str(e),
                        schema_used=self.primary_schema
                    )

        except Exception as e:
            execution_time = (datetime.now() - start_time).total_seconds() * 1000

            return QueryExecutionResponse(
                success=False,
                data=None,
                row_count=0,
                execution_time_ms=execution_time,
                error_message=f"Database connection error: {str(e)}",
                schema_used=self.primary_schema
            )

    def _format_explain_plan(self, plan_json) -> str:
        """Format EXPLAIN ANALYZE JSON output to comprehensive readable text for developers."""
        if not plan_json or not isinstance(plan_json, list):
            return "No execution plan available"

        try:
            plan_data = plan_json[0]
            main_plan = plan_data.get("Plan", {})

            # Build comprehensive formatted output
            lines = []

            # Header with overall timing
            lines.append("=" * 60)
            lines.append("POSTGRESQL EXECUTION PLAN ANALYSIS")
            lines.append("=" * 60)

            # Overall execution statistics
            if "Execution Time" in plan_data:
                lines.append(f"📊 **Overall Execution Time:** {plan_data['Execution Time']:.3f}ms")
            if "Planning Time" in plan_data:
                lines.append(f"🧠 **Planning Time:** {plan_data['Planning Time']:.3f}ms")

            lines.append("")
            lines.append("🔍 **Detailed Node Analysis:**")
            lines.append("-" * 40)

            def format_node_detailed(node, level=0):
                indent = "  " * level
                node_type = node.get("Node Type", "Unknown")
                node_lines = []

                # Main node header
                node_lines.append(f"{indent}{'└─' if level > 0 else '▶'} **{node_type}**")

                # Cost analysis (startup vs total)
                startup_cost = node.get("Startup Cost", 0)
                total_cost = node.get("Total Cost", 0)
                if startup_cost or total_cost:
                    node_lines.append(f"{indent}   💰 Cost: {startup_cost:.2f}..{total_cost:.2f}")

                # Timing details (startup vs total)
                startup_time = node.get("Actual Startup Time")
                total_time = node.get("Actual Total Time")
                if startup_time is not None and total_time is not None:
                    node_lines.append(f"{indent}   ⏱️  Time: {startup_time:.3f}ms..{total_time:.3f}ms")

                # Row estimates vs actual
                plan_rows = node.get("Plan Rows")
                actual_rows = node.get("Actual Rows")
                if plan_rows is not None or actual_rows is not None:
                    estimate_accuracy = ""
                    if plan_rows and actual_rows:
                        ratio = actual_rows / plan_rows if plan_rows > 0 else float('inf')
                        if ratio > 2 or ratio < 0.5:
                            estimate_accuracy = f" ⚠️ {'Over' if ratio > 1 else 'Under'}estimated by {ratio:.1f}x"

                    node_lines.append(f"{indent}   📊 Rows: {plan_rows or 'N/A'} planned → {actual_rows or 'N/A'} actual{estimate_accuracy}")

                # Loop information
                loops = node.get("Actual Loops", 1)
                if loops > 1:
                    node_lines.append(f"{indent}   🔄 Loops: {loops}")

                # Width (average row size)
                if "Plan Width" in node:
                    node_lines.append(f"{indent}   📏 Avg Row Size: {node['Plan Width']} bytes")

                # Table/relation information
                if "Relation Name" in node:
                    table_info = f"{indent}   🗂️  Table: {node['Relation Name']}"
                    if "Alias" in node and node["Alias"] != node["Relation Name"]:
                        table_info += f" (as {node['Alias']})"
                    node_lines.append(table_info)

                # Index information
                if "Index Name" in node:
                    index_info = f"{indent}   🔑 Index: {node['Index Name']}"
                    if "Scan Direction" in node:
                        index_info += f" ({node['Scan Direction']} scan)"
                    node_lines.append(index_info)

                # Join/Filter conditions
                if "Hash Cond" in node:
                    node_lines.append(f"{indent}   🔗 Hash Condition: {node['Hash Cond']}")
                if "Index Cond" in node:
                    node_lines.append(f"{indent}   🎯 Index Condition: {node['Index Cond']}")
                if "Filter" in node:
                    node_lines.append(f"{indent}   🔍 Filter: {node['Filter']}")
                    if "Rows Removed by Filter" in node:
                        node_lines.append(f"{indent}       ❌ Filtered out: {node['Rows Removed by Filter']} rows")

                # Sort information
                if "Sort Key" in node:
                    node_lines.append(f"{indent}   🔤 Sort Key: {', '.join(node['Sort Key'])}")
                if "Sort Method" in node:
                    sort_info = f"{indent}   📈 Sort Method: {node['Sort Method']}"
                    if "Sort Space Used" in node and "Sort Space Type" in node:
                        sort_info += f" ({node['Sort Space Used']}kB {node['Sort Space Type']})"
                    node_lines.append(sort_info)

                # Buffer usage (I/O statistics)
                buffer_info = []
                buffer_fields = [
                    ("Shared Hit Blocks", "💾 Shared Hit"),
                    ("Shared Read Blocks", "💿 Shared Read"),
                    ("Shared Dirtied Blocks", "✏️ Shared Dirty"),
                    ("Shared Written Blocks", "💾 Shared Write"),
                    ("Temp Read Blocks", "🌡️ Temp Read"),
                    ("Temp Written Blocks", "🌡️ Temp Write")
                ]

                for field, label in buffer_fields:
                    if field in node and node[field] > 0:
                        buffer_info.append(f"{label}: {node[field]}")

                if buffer_info:
                    node_lines.append(f"{indent}   📊 Buffers: {' | '.join(buffer_info)}")

                # Parallelism information
                if node.get("Parallel Aware") and "Workers Planned" in node:
                    parallel_info = f"{indent}   ⚡ Parallel: {node.get('Workers Planned', 0)} workers planned"
                    if "Workers Launched" in node:
                        parallel_info += f", {node['Workers Launched']} launched"
                    node_lines.append(parallel_info)

                # Memory usage
                if "Hash Buckets" in node:
                    memory_info = f"{indent}   🧠 Hash: {node['Hash Buckets']} buckets"
                    if "Hash Batches" in node:
                        memory_info += f", {node['Hash Batches']} batches"
                    if "Peak Memory Usage" in node:
                        memory_info += f", {node['Peak Memory Usage']}kB peak"
                    node_lines.append(memory_info)

                # Add blank line after each major node
                node_lines.append("")

                # Process child nodes recursively
                if "Plans" in node and node["Plans"]:
                    for child in node["Plans"]:
                        node_lines.extend(format_node_detailed(child, level + 1))

                return node_lines

            # Format the main execution tree
            formatted_lines = format_node_detailed(main_plan)
            lines.extend(formatted_lines)

            # Overall statistics summary
            lines.append("=" * 40)
            lines.append("📈 **EXECUTION SUMMARY**")
            lines.append("=" * 40)

            def extract_totals(node, totals=None):
                if totals is None:
                    totals = {
                        'total_cost': 0,
                        'total_time': 0,
                        'total_rows': 0,
                        'seq_scans': 0,
                        'index_scans': 0,
                        'sorts': 0,
                        'joins': 0
                    }

                # Accumulate costs and times
                totals['total_cost'] += node.get('Total Cost', 0)
                totals['total_time'] += node.get('Actual Total Time', 0)
                totals['total_rows'] += node.get('Actual Rows', 0)

                # Count operation types
                node_type = node.get('Node Type', '').lower()
                if 'seq scan' in node_type:
                    totals['seq_scans'] += 1
                elif 'index scan' in node_type or 'index only scan' in node_type:
                    totals['index_scans'] += 1
                elif 'sort' in node_type:
                    totals['sorts'] += 1
                elif 'join' in node_type:
                    totals['joins'] += 1

                # Recurse into child plans
                if 'Plans' in node:
                    for child in node['Plans']:
                        extract_totals(child, totals)

                return totals

            totals = extract_totals(main_plan)

            lines.append(f"• Total Estimated Cost: {totals['total_cost']:.2f}")
            lines.append(f"• Sequential Scans: {totals['seq_scans']}")
            lines.append(f"• Index Scans: {totals['index_scans']}")
            lines.append(f"• Sort Operations: {totals['sorts']}")
            lines.append(f"• Join Operations: {totals['joins']}")

            # Performance indicators
            lines.append("\n🎯 **PERFORMANCE INDICATORS:**")
            performance_notes = []

            if totals['seq_scans'] > 0:
                performance_notes.append("⚠️ Sequential scans detected - consider indexing")
            if totals['sorts'] > 1:
                performance_notes.append("📈 Multiple sorts - check ORDER BY optimization")
            if totals['total_cost'] > 1000:
                performance_notes.append("💰 High cost query - review for optimization opportunities")

            if performance_notes:
                lines.extend([f"• {note}" for note in performance_notes])
            else:
                lines.append("• ✅ No obvious performance issues detected")

            return "\n".join(lines)

        except Exception as e:
            return f"Error formatting execution plan: {str(e)}\n\nRaw JSON: {str(plan_json)[:500]}..."

    async def _generate_query(
        self,
        query: str,
        route: RouteDecision,
        metadata_context: str,
        conversation_context: str,
        vector_context: str,
        user_context: Optional[str],
        context: Optional[str] = None,
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
                sql_query=sql_query,
                metadata_context=metadata_context,
                context=context
            )
            return sql_query, explanation, llm_response

        else:
            # Generate new SQL query using the EXISTING method from your code
            sql_query, explanation, llm_response = await self._query_generation(
                query=query,
                route=route,
                metadata_context=metadata_context,
                context=context,
                **kwargs
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
        context: Optional[str] = None,
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
            route.intent in [QueryIntent.EXPLAIN_METADATA, QueryIntent.EXPLORE_SCHEMA] and
            route.user_role != UserRole.QUERY_DEVELOPER
        )
        if is_documentation_request:
            db_response.is_documentation = True

        if route.user_role == UserRole.QUERY_DEVELOPER:
            # Developers always get raw SQL and data results
            if OutputComponent.SQL_QUERY in route.components:
                sql_query, explanation, llm_response = await self._generate_query(
                    query=query,
                    route=route,
                    metadata_context=metadata_context,
                    conversation_context=conversation_context,
                    vector_context=vector_context,
                    user_context=user_context,
                    context=context,
                    **kwargs
                )
                db_response.query = sql_query
                # Store the generation attempt explanation
                if explanation:
                    db_response.documentation = explanation

            if db_response.query and OutputComponent.EXECUTION_PLAN in route.components:
                self.logger.info(
                    f"🔧 QUERY_DEVELOPER: Attempting execution with EXPLAIN ANALYZE"
                )
                # Try to execute with EXPLAIN ANALYZE
                exec_result = await self._execute_query_explain(db_response.query)

                if exec_result.success:
                    # Extract execution plan
                    if exec_result.query_plan:
                        db_response.execution_plan = exec_result.query_plan

                    # Extract JSON plan data from metadata
                    plan_json = None
                    if exec_result.metadata and "plan_json" in exec_result.metadata:
                        plan_json = exec_result.metadata["plan_json"]

                    # Extract performance metrics with JSON data
                    if OutputComponent.PERFORMANCE_METRICS in route.components:
                        db_response.performance_metrics = self._extract_performance_metrics(
                            exec_result.query_plan,
                            exec_result.execution_time_ms,
                            plan_json=plan_json  # Pass JSON data
                        )

                    # Generate optimization tips with JSON data
                    if OutputComponent.OPTIMIZATION_TIPS in route.components:
                        db_response.optimization_tips, opt_llm_response = await self._generate_optimization_tips(
                            sql_query=db_response.query,
                            query_plan=exec_result.query_plan,
                            metadata_context=metadata_context,
                            context=context,
                            plan_json=plan_json  # Pass JSON data
                        )
                        if opt_llm_response and not llm_response:
                            llm_response = opt_llm_response
                else:
                    # Query failed - provide analysis of why it failed
                    db_response.documentation = f"""**Query Execution Failed**
**Generated SQL:**
```sql
{db_response.query}
```

**Error:** {exec_result.error_message}

**Analysis:** The query could not be executed. This could be due to:
- Table/column name issues
- Syntax errors
- Permission problems
- Schema access restrictions

**Recommendations:**
1. Verify the table exists in the specified schema
2. Check column names and data types
3. Ensure proper schema permissions
        """
                    # Still provide basic optimization tips for the failed query
                    if OutputComponent.OPTIMIZATION_TIPS in route.components:
                        db_response.optimization_tips = [
                            "🔍 Verify table name exists in available schemas",
                            "📋 Use 'SHOW TABLES' to list available tables",
                            "🔧 Check table name spelling and case sensitivity",
                            "📊 Ensure proper schema permissions are granted"
                        ]

            # Always provide schema context for QUERY_DEVELOPER
            if OutputComponent.SCHEMA_CONTEXT in route.components:
                db_response.schema_context = await self._build_schema_context(
                    route.primary_schema,
                    route.allowed_schemas,
                    discovered_tables=discovered_tables
                )

            return db_response, llm_response

        # Generate SQL query (if needed)
        if route.needs_query_generation and OutputComponent.SQL_QUERY in route.components:
            sql_query, explanation, llm_response = await self._generate_query(
                query=query,
                route=route,
                metadata_context=metadata_context,
                conversation_context=conversation_context,
                vector_context=vector_context,
                user_context=user_context,
                context=context,
                **kwargs
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
                        sql_query=db_response.query,
                        query_plan=exec_result.query_plan,
                        metadata_context=metadata_context,
                        context=context
                    )

        # For documentation requests, format discovered table metadata instead of examples
        if (OutputComponent.DOCUMENTATION in route.components or is_documentation_request) and \
        route.user_role != UserRole.QUERY_DEVELOPER:
            if discovered_tables:
                # Generate detailed documentation for discovered tables
                db_response.documentation = await self._format_table_documentation(
                    discovered_tables, route.user_role, query
                )

        # Generate examples only if NOT a documentation request
        if OutputComponent.EXAMPLES in route.components and not is_documentation_request and \
        route.user_role != UserRole.QUERY_DEVELOPER:
            db_response.examples = await self._generate_examples(
                query, metadata_context, discovered_tables, route.primary_schema
            )

        # Schema context (if requested)
        if OutputComponent.SCHEMA_CONTEXT in route.components:
            db_response.schema_context = await self._build_schema_context(
                route.primary_schema,
                route.allowed_schemas,
                discovered_tables=discovered_tables
            )

        return db_response, llm_response

    async def _format_table_documentation(
        self,
        discovered_tables: List[TableMetadata],
        user_role: UserRole,
        original_query: str
    ) -> str:
        """
        Format discovered table metadata as proper documentation.

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
        allowed_schemas: List[str],
        discovered_tables: List[TableMetadata] = None
    ) -> str:
        """
        Build schema context showing metadata of tables involved in the query.

        Args:
            primary_schema: Primary schema name (for context)
            allowed_schemas: Allowed schemas (for context)
            discovered_tables: List of tables discovered for this query

        Returns:
            Formatted metadata context of the involved tables
        """

        if not discovered_tables:
            return f"""**Query Context:**
No specific tables identified for this query.

**Available Schemas:** {', '.join([f'`{s}`' for s in allowed_schemas])}
**Primary Schema:** `{primary_schema}`

*Use table discovery tools to identify relevant tables for your query.*"""

        context_parts = []

        # Header
        context_parts.append("**TABLES INVOLVED IN QUERY**")
        context_parts.append("=" * 50)

        for i, table in enumerate(discovered_tables, 1):
            # Table header
            context_parts.append(f"\n**{i}. {table.full_name}**")
            context_parts.append(f"   Type: {table.table_type}")
            if table.row_count is not None and table.row_count >= 0:
                context_parts.append(f"   Rows: {table.row_count:,}")
            if table.comment:
                context_parts.append(f"   Description: {table.comment}")

            # Column information in compact format
            if table.columns:
                context_parts.append(f"\n   **Columns ({len(table.columns)}):**")

                # Group columns by type for better readability
                column_groups = {}
                for col in table.columns:
                    col_type = col.get('type', 'unknown')
                    # Simplify type names for readability
                    simple_type = self._simplify_column_type(col_type)
                    if simple_type not in column_groups:
                        column_groups[simple_type] = []
                    column_groups[simple_type].append(col)

                # Display columns by type
                for type_name, cols in column_groups.items():
                    col_names = []
                    for col in cols:
                        name = col['name']
                        # Add indicators for special columns
                        if not col.get('nullable', True):
                            name += "*"  # Required field
                        if col.get('default'):
                            name += "°"  # Has default
                        col_names.append(name)

                    context_parts.append(f"   • {type_name}: {', '.join(col_names)}")

            # Primary key
            if hasattr(table, 'primary_keys') and table.primary_keys:
                pk_list = ', '.join(table.primary_keys)
                context_parts.append(f"   **Primary Key:** {pk_list}")

            # Foreign keys (relationships)
            if hasattr(table, 'foreign_keys') and table.foreign_keys:
                context_parts.append(f"   **Relationships:**")
                for fk in table.foreign_keys[:3]:  # Limit to first 3 to avoid clutter
                    if isinstance(fk, dict):
                        ref_table = fk.get('referenced_table', 'unknown')
                        ref_col = fk.get('referenced_column', 'unknown')
                        fk_col = fk.get('column', 'unknown')
                        context_parts.append(f"   • {fk_col} → {ref_table}.{ref_col}")

                if len(table.foreign_keys) > 3:
                    context_parts.append(f"   • ... and {len(table.foreign_keys) - 3} more")

            # Indexes (for performance context)
            if hasattr(table, 'indexes') and table.indexes:
                idx_count = len(table.indexes)
                context_parts.append(f"   **Indexes:** {idx_count} defined")

                # Show a few key indexes
                key_indexes = []
                for idx in table.indexes[:2]:  # Show first 2
                    if isinstance(idx, dict):
                        idx_name = idx.get('name', 'unnamed')
                        idx_cols = idx.get('columns', [])
                        if idx_cols:
                            key_indexes.append(f"{idx_name}({', '.join(idx_cols)})")

                if key_indexes:
                    context_parts.append(f"   • Key indexes: {', '.join(key_indexes)}")

        # Add usage legend
        context_parts.append("\n" + "=" * 50)
        context_parts.append("**LEGEND:**")
        context_parts.append("• Column* = Required (NOT NULL)")
        context_parts.append("• Column° = Has default value")
        context_parts.append("• Relationships show foreign key connections")

        # Query development tips specific to these tables
        context_parts.append("\n**QUERY DEVELOPMENT TIPS:**")

        # Generate contextual tips based on discovered tables
        tips = self._generate_table_specific_tips(discovered_tables)
        context_parts.extend([f"• {tip}" for tip in tips])

        return "\n".join(context_parts)

    def _simplify_column_type(self, col_type: str) -> str:
        """Simplify PostgreSQL column types for readable grouping."""
        col_type = col_type.lower()

        # Group similar types
        if 'varchar' in col_type or 'character varying' in col_type or 'text' in col_type:
            return 'Text'
        elif 'int' in col_type or 'serial' in col_type:
            return 'Integer'
        elif 'numeric' in col_type or 'decimal' in col_type or 'float' in col_type or 'double' in col_type:
            return 'Number'
        elif 'timestamp' in col_type or 'date' in col_type or 'time' in col_type:
            return 'DateTime'
        elif 'boolean' in col_type:
            return 'Boolean'
        elif 'uuid' in col_type:
            return 'UUID'
        elif 'json' in col_type:
            return 'JSON'
        elif 'array' in col_type:
            return 'Array'
        else:
            return col_type.title()

    def _generate_table_specific_tips(self, discovered_tables: List[TableMetadata]) -> List[str]:
        """Generate query development tips specific to the discovered tables."""
        tips = []

        if not discovered_tables:
            return ["No tables discovered for specific tips"]

        # Analyze the tables for specific tips
        table_names = [table.tablename for table in discovered_tables]
        total_columns = sum(len(table.columns) for table in discovered_tables if table.columns)

        # Tip about table joining
        if len(discovered_tables) > 1:
            tips.append(f"Multiple tables detected - consider JOIN relationships between {', '.join(table_names)}")

        # Tip about column selection
        if total_columns > 20:
            tips.append("Many columns available - use SELECT specific_columns instead of SELECT * for better performance")

        # Tip about primary keys for efficient queries
        pk_tables = [t.tablename for t in discovered_tables if hasattr(t, 'primary_keys') and t.primary_keys]
        if pk_tables:
            tips.append(f"Use primary keys for efficient lookups: {', '.join(pk_tables)}")

        # Tip about large tables
        large_tables = [t.tablename for t in discovered_tables if t.row_count and t.row_count > 100000]
        if large_tables:
            tips.append(f"Large tables detected ({', '.join(large_tables)}) - consider LIMIT clauses and WHERE filtering")

        # Tip about indexes
        indexed_tables = [t.tablename for t in discovered_tables if hasattr(t, 'indexes') and t.indexes]
        if indexed_tables:
            tips.append(f"Indexed tables available - leverage existing indexes for optimal performance")

        # Default tip if no specific tips generated
        if not tips:
            tips.append(
                f"Focus on the {len(discovered_tables)} table(s) structure above for efficient query design"
            )

        return tips[:4]  # Limit to 4 tips

    async def _get_schema_counts_direct(self, schema_name: str) -> Tuple[int, int]:
        """Get table and view counts directly from information_schema."""
        try:
            async with self.session_maker() as session:
                # Count tables
                table_query = text("""
                    SELECT COUNT(*)
                    FROM information_schema.tables
                    WHERE table_schema = :schema_name
                    AND table_type = 'BASE TABLE'
                """)
                table_result = await session.execute(table_query, {"schema_name": schema_name})
                table_count = table_result.scalar() or 0

                # Count views
                view_query = text("""
                    SELECT COUNT(*)
                    FROM information_schema.views
                    WHERE table_schema = :schema_name
                """)
                view_result = await session.execute(view_query, {"schema_name": schema_name})
                view_count = view_result.scalar() or 0

                return table_count, view_count

        except Exception as e:
            self.logger.error(f"Direct schema count failed for {schema_name}: {e}")
            return 0, 0

    async def _validate_user_sql(self, sql_query: str, metadata_context: str, context: Optional[str] = None) -> tuple[str, AIMessage]:
        """Validate user-provided SQL."""

        system_prompt = f"""
You are validating SQL for multi-schema access.

```sql
{sql_query}
```

**Context Information:**
{context}

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
        async with self._llm as client:
            llm_response = await client.ask(
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
        is_structured_output: bool,
        structured_output_class: Optional[Type[BaseModel]],
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

        # Check if we have data to transform
        has_data = (
            OutputComponent.DATA_RESULTS in route.components or
            OutputComponent.DATAFRAME_OUTPUT in route.components
        ) and db_response.data

        if has_data and is_structured_output:
            # Handle DataFrame input
            output_data = self._to_structured_format(
                db_response.data,
                structured_output_class
            )
            response_text = ""
        # Generate response text based on format preference
        elif output_format == "markdown":
            response_text = db_response.to_markdown()
            if OutputComponent.DATAFRAME_OUTPUT in route.components and isinstance(db_response.data, pd.DataFrame):
                output_data = db_response.data
            elif OutputComponent.DATA_RESULTS in route.components:
                output_data = db_response.data
        elif output_format == "json":
            response_text = db_response.to_json()
            if OutputComponent.DATAFRAME_OUTPUT in route.components and isinstance(db_response.data, pd.DataFrame):
                output_data = db_response.data
            elif OutputComponent.DATA_RESULTS in route.components:
                output_data = db_response.data
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

    def _to_structured_format(self, data, output_format: Type) -> Union[List, object]:
        """Convert data to structured format using Pydantic model."""
        if not output_format:
            return data

        try:
            if isinstance(data, pd.DataFrame):
                data = data.to_dict('records')

            if isinstance(data, list):
                return [
                    output_format(**item) if isinstance(item, dict) else item for item in data
                ]
            elif isinstance(data, dict):
                return output_format(**data)
            else:
                self.logger.warning(
                    "Data is neither list nor dict; returning as-is."
                )
                return data
        except Exception as e:
            self.logger.error(f"Unexpected error during structuring: {e}")
            return data

    def _extract_performance_metrics(
        self,
        query_plan: str,
        execution_time: float,
        plan_json: Optional[List[Dict]] = None
    ) -> Dict[str, Any]:
        """Extract performance metrics from query execution plan."""

        metrics = {
            "execution_time_ms": execution_time,
            "estimated_cost": "N/A",
            "rows_examined": "N/A",
            "rows_planned": "N/A",
            "index_usage": "Unknown",
            "scan_types": [],
            "join_types": [],
            "buffer_metrics": {},
            "planning_time_ms": "N/A"
        }

        # If we have JSON plan, extract from there (more accurate)
        if plan_json and isinstance(plan_json, list) and len(plan_json) > 0:
            try:
                plan_data = plan_json[0]

                # Planning time
                if "Planning Time" in plan_data:
                    metrics["planning_time_ms"] = plan_data["Planning Time"]

                # Extract from main plan
                main_plan = plan_data.get("Plan", {})

                # Cost information
                if "Total Cost" in main_plan:
                    metrics["estimated_cost"] = main_plan["Total Cost"]

                # Row information
                if "Actual Rows" in main_plan:
                    metrics["rows_examined"] = main_plan["Actual Rows"]
                if "Plan Rows" in main_plan:
                    metrics["rows_planned"] = main_plan["Plan Rows"]

                # Buffer statistics
                buffer_stats = {}
                for key in ["Shared Hit Blocks", "Shared Read Blocks", "Temp Read Blocks", "Temp Written Blocks"]:
                    if key in main_plan:
                        buffer_stats[key.lower().replace(" ", "_")] = main_plan[key]
                if buffer_stats:
                    metrics["buffer_metrics"] = buffer_stats

                # Recursively analyze all nodes for scan/join types
                def analyze_node(node):
                    node_type = node.get("Node Type", "")

                    # Scan types
                    if "scan" in node_type.lower():
                        scan_type = node_type
                        metrics["scan_types"].append(scan_type)

                        # Index usage detection
                        if "index" in node_type.lower():
                            if "index only" in node_type.lower():
                                metrics["index_usage"] = "Index-only scan"
                            elif "bitmap" in node_type.lower():
                                metrics["index_usage"] = "Bitmap index scan"
                            else:
                                metrics["index_usage"] = "Index scan"
                        elif "seq" in node_type.lower():
                            metrics["index_usage"] = "Sequential scan (no indexes)"

                    # Join types
                    if "join" in node_type.lower():
                        metrics["join_types"].append(node_type)

                    # Process child plans
                    if "Plans" in node:
                        for child_plan in node["Plans"]:
                            analyze_node(child_plan)

                analyze_node(main_plan)

                # Remove duplicates
                metrics["scan_types"] = list(set(metrics["scan_types"]))
                metrics["join_types"] = list(set(metrics["join_types"]))

                return metrics

            except Exception as e:
                self.logger.error(f"Error extracting metrics from JSON plan: {e}")
                # Fall back to text parsing

        # Fallback: Extract from text plan
        if not query_plan:
            return metrics

        lines = query_plan.split('\n')
        for line in lines:
            line_lower = line.lower()

            # Extract cost information
            if 'cost:' in line_lower:
                cost_match = re.search(r'cost:\s*([\d.]+)', line)
                if cost_match:
                    metrics["estimated_cost"] = float(cost_match.group(1))

            # Extract row information
            if 'rows:' in line_lower:
                rows_match = re.search(r'rows:\s*(\d+)', line)
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
        metadata_context: str,
        context: Optional[str] = None,
        plan_json: Optional[List[Dict]] = None  # Add JSON plan data
    ) -> Tuple[List[str], Optional[AIMessage]]:
        """
        LLM-based optimization tips with better parsing.
        """
        if not query_plan:
            return ["Enable query plan analysis for optimization suggestions"], None

        self.logger.debug("🔧 Generating LLM-based optimization tips...")

        # Enhanced prompt with better formatting instructions
        optimization_prompt = f"""
You are a PostgreSQL performance tutor helping developers understand and fix query performance issues.

**SQL Query:**
```sql
{sql_query}
```

**Execution Plan:**
```
{query_plan}
```
* If available, here is the JSON representation of the execution plan for more accurate analysis: *
```json
{plan_json}
```

**Available Schema Context:**
{metadata_context[:1000] if metadata_context else 'No schema context available'}

{context}

**EDUCATIONAL MISSION:**
Your goal is to teach PostgreSQL optimization concepts while providing actionable solutions. Each recommendation should:
1. EXPLAIN the underlying PostgreSQL concept (why this matters)
2. IDENTIFY the specific issue in this query
3. PROVIDE the exact SQL commands to fix it
4. EXPLAIN what the fix accomplishes

**RESPONSE FORMAT:**
- Start each tip with an emoji and descriptive title
- Include a brief explanation of the PostgreSQL concept
- Provide specific SQL commands with actual table/column names from the query
- Explain the expected performance impact

**EXAMPLE GOOD TIP:**
📊 **Update Table Statistics for Better Query Planning**

**What's happening:** PostgreSQL's query planner uses table statistics to estimate how many rows operations will return. When these statistics are outdated, the planner makes poor decisions (like choosing slow sequential scans over fast index scans).

**The issue:** Your execution plan shows estimated 42M rows but actual 5 rows - this massive discrepancy indicates stale statistics on the `form_data` table.

**Fix this with:**
```sql
-- Update statistics for the specific table
ANALYZE hisense.form_data;

-- Or update all tables in the schema
ANALYZE;

-- Check when statistics were last updated
SELECT schemaname, tablename, last_analyze, last_autoanalyze
FROM pg_stat_user_tables
WHERE tablename = 'form_data';
```

**Why this helps:** Fresh statistics allow PostgreSQL to choose optimal execution paths, potentially changing sequential scans to index scans and improving query performance by orders of magnitude.

**FOCUS AREAS FOR THIS QUERY:**
Based on the execution plan, prioritize recommendations about:
- Statistics accuracy (row estimate discrepancies)
- Index usage and creation with specific column combinations
- Query structure improvements with rewritten SQL examples
- Buffer usage and I/O optimization
- Join strategy improvements (if applicable)

**IMPORTANT REQUIREMENTS:**
- Always include the actual SQL commands to implement your suggestions
- Use the real table and column names from the provided query
- Explain PostgreSQL concepts in accessible terms
- Focus on the most impactful optimizations first (biggest performance gains)
- Limit to 3-4 high-impact recommendations

Provide specific, educational recommendations with concrete implementation steps:
"""
        try:
            # Call LLM for optimization analysis
            async with self._llm as client:
                llm_response = await client.ask(
                    prompt=optimization_prompt,
                    temperature=0.1,
                    max_tokens=4096,
                    max_retries=2,
                    use_tools=False,
                    stateless=True
                )

            response_text = str(llm_response.output) if llm_response.output else str(llm_response.response)
            self.logger.debug(f"🔧 LLM Optimization Response: {response_text[:200]}...")

            # Enhanced parsing logic
            tips = []
            tips = self._parse_tips(response_text)
            if tips:
                self.logger.info(f"✅ Generated {len(tips)} optimization tips")
                return tips, llm_response
        except Exception as e:
            self.logger.error(f"LLM Optimization Tips Error: {e}")

        # Fallback to basic analysis if LLM fails
        return self._generate_basic_optimization_tips(
            sql_query,
            query_plan
        ), None

    def _parse_tips(self, response_text: str) -> List[str]:
        """Parse performance tips with multi-line content."""
        tips = []
        current_tip = []
        in_tip = False

        lines = response_text.split('\n')

        for line in lines:
            line = line.strip()

            # Start of a new tip (emoji + title)
            if (line and any(emoji in line[:10] for emoji in ['📊', '⚡', '🔗', '💾', '🔧', '📈', '🎯', '🔍'])
                and ('**' in line or line.startswith(('📊', '⚡', '🔗', '💾', '🔧', '📈', '🎯', '🔍')))):

                # Save previous tip if exists
                if current_tip:
                    tip_text = '\n'.join(current_tip).strip()
                    if len(tip_text) > 50:  # Only keep substantial tips
                        tips.append(tip_text)

                # Start new tip
                current_tip = [line]
                in_tip = True

            elif in_tip and line:
                # Continue building current tip - KEEP ALL CONTENT
                current_tip.append(line)

            elif in_tip and not line:
                # Empty line - add it to preserve formatting
                current_tip.append('')

        # Add the last tip
        if current_tip:
            tip_text = '\n'.join(current_tip).strip()
            if len(tip_text) > 50:
                tips.append(tip_text)

        # Return all tips without truncation - developers need complete information
        return tips

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

            chatbot_key = getattr(self, 'chatbot_id', None)
            if chatbot_key is not None:
                chatbot_key = str(chatbot_key)
            await self.conversation_memory.add_turn(
                user_id,
                session_id,
                turn,
                chatbot_id=chatbot_key
            )
            self.logger.debug(
                f"Updated conversation memory for session {session_id}"
            )

        except Exception as e:
            self.logger.error(
                f"Failed to update conversation memory: {e}"
            )

    async def cleanup(self) -> None:
        """Cleanup database and parent resources."""
        try:
            # Close database engine
            if self.engine:
                await self.engine.dispose()
                self.logger.debug("Database engine disposed")
        except Exception as e:
            self.logger.error(f"Error during DB agent cleanup: {e}")
