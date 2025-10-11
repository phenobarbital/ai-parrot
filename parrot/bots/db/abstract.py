"""
Database Agent Architecture for AI-Parrot.

This module provides an abstract base for database introspection agents
that can analyze database schemas and generate queries from natural language.
"""

from abc import abstractmethod
from typing import Dict, Any, List, Optional, Union
import uuid
import json
import asyncio
from string import Template
from sqlalchemy.ext.asyncio import AsyncEngine
from ..abstract import AbstractBot
from ...tools.manager import (
    ToolManager,
)
from ...stores.abstract import AbstractStore
from .prompts import DB_AGENT_PROMPT, BASIC_HUMAN_PROMPT
from .tools import (
    SchemaSearchTool,
    QueryGenerationTool,
    DatabaseSchema,
    TableMetadata,
)
from ...models import AIMessage
from ...tools.databasequery import DatabaseQueryTool
from .cache import SchemaCache
from ...memory import ConversationTurn

class AbstractDBAgent(AbstractBot):
    """
    Abstract base class for database introspection agents.

    This agent analyzes database schemas, stores metadata in a knowledge base,
    and generates queries from natural language descriptions.
    """
    system_prompt_template: str = DB_AGENT_PROMPT
    human_prompt_template = BASIC_HUMAN_PROMPT
    _default_temperature: float = 0.0
    # _default_llm: str = 'openai'
    # LLM:
    # llm_client: str = 'openai'
    # default_model: str = 'gpt-4o'
    max_tokens: int = 8192

    def __init__(
        self,
        name: str = "DatabaseAgent",
        credentials: Union[str, Dict[str, Any]] = None,
        schema_name: Optional[str] = None,
        knowledge_store: AbstractStore = None,
        auto_analyze_schema: bool = True,
        cache_ttl: int = 3600,  # Cache TTL in seconds
        **kwargs
    ):
        """
        Initialize the database agent.

        Args:
            name: Agent name
            credentials: Database connection credentials
            schema_name: Target schema name (optional)
            knowledge_store: Vector store for schema metadata
            auto_analyze_schema: Whether to automatically analyze schema on init
        """
        kwargs.setdefault('temperature', self._default_temperature)
        super().__init__(name=name, **kwargs)
        self.role = kwargs.get(
            'role', 'Database Analysis Assistant')
        self.goal = kwargs.get(
            'goal', 'Help users interact with databases using natural language'
        )
        self.capabilities = kwargs.get(
            'capabilities',
            'Database schema analysis, query generation, and data retrieval'
        )
        self.backstory = kwargs.get(
            'backstory',
            'Expert database assistant with deep knowledge of SQL and data analysis'
        )

        self.credentials = credentials
        self.schema_name = schema_name
        self.knowledge_store = knowledge_store
        # Schema cache for metadata
        self.cache = SchemaCache(ttl=cache_ttl)
        self.auto_analyze_schema = auto_analyze_schema

        # Initialize database-specific components
        self.engine: Optional[AsyncEngine] = None
        self.schema_metadata: Optional[DatabaseSchema] = None

        # Initialize tool manager
        self.tool_manager = ToolManager(
            logger=self.logger,
            debug=self._debug
        )

        # Add database-specific tools
        self._setup_database_tools()
        try:
            self.loop = asyncio.get_running_loop()
        except RuntimeError:
            raise RuntimeError(
                "An event loop is required to initialize the AbstractDBAgent."
            )
        asyncio.set_event_loop(self.loop)

    def default_rationale(self) -> str:
        # TODO: read rationale from a file
        return (
            "** Your Style: **\n"
            "- When responding to user queries, ensure that you provide accurate and up-to-date information.\n"  # noqa: C0301
            "- Providing precise and helpful database interactions.\n"
            "- Remember: You operate with zero temperature for consistent, precise database operations."
        )

    async def initialize_schema(self):
        """Initialize database connection and analyze schema."""
        try:
            await self.connect_database()
            self.schema_metadata = await self.extract_schema_metadata()

            if self.knowledge_store:
                await self.store_schema_in_knowledge_base()

        except Exception as e:
            self.logger.error(
                f"Failed to initialize schema: {e}"
            )
            raise

    def _setup_database_tools(self):
        """Setup database-specific tools."""
        # Add schema search tool
        schema_search_tool = SchemaSearchTool(agent=self)
        self.tool_manager.register_tool(schema_search_tool)

        # Add query generation tool
        query_gen_tool = QueryGenerationTool(agent=self)
        self.tool_manager.register_tool(query_gen_tool)

        # Add database query tool
        db_query_tool = DatabaseQueryTool(agent=self)
        self.tool_manager.register_tool(db_query_tool)

    async def configure(self, app=None) -> None:
        """Configure the database agent."""
        await super().configure(app)
        await self.initialize_schema()

    def _define_prompt(self, config: Optional[dict] = None, **kwargs):
        """
        Define the System Prompt and replace variables.
        """
        # setup the prompt variables:
        if config:
            for key, val in config.items():
                setattr(self, key, val)

        tmpl = Template(self.system_prompt_template)
        final_prompt = tmpl.safe_substitute(
            name=self.name,
            role=getattr(self, 'role', 'Database Analysis Assistant'),
            goal=getattr(self, 'goal', 'Help users interact with databases using natural language'),
            capabilities=getattr(self, 'capabilities', 'Database schema analysis, query generation, and data retrieval'),
            backstory=getattr(self, 'backstory', 'Expert database assistant with deep knowledge of SQL and data analysis'),
            rationale=getattr(self, 'rationale', 'Providing precise and helpful database interactions'),
            **kwargs
        )
        self.system_prompt_template = final_prompt

    async def create_system_prompt(
        self,
        user_context: str = "",
        context: str = "",
        vector_context: str = "",
        pre_context: str = "",
        conversation_context: str = "",
        metadata: Optional[Dict[str, Any]] = None,
        **kwargs
    ) -> str:
        """
        Create the complete system prompt for the LLM with user context support.

        Args:
            user_context: User-specific context for the database interaction
            vector_context: Vector store context
            conversation_context: Previous conversation context
            metadata: Additional metadata
            **kwargs: Additional template variables
        """
        # Process contexts
        context_parts = []

        # Add user context if provided
        if user_context:
            context_parts.append(f"""
Use the following information about user's data to guide your responses:
**User Context:**
{user_context}
Based on the user context above, please tailor your response to their specific:
- Role and responsibilities
- Technical expertise level
- Business objectives
- Preferred communication style
            """)
        if context:
            context_parts.append(f"**Additional Context:**\n{context}")

        # Add vector context
        if vector_context:
            context_parts.append(f"**Database Context:**\n{vector_context}")

        # Add metadata
        if metadata:
            metadata_text = "**Database Metadata:**\n"
            for key, value in metadata.items():
                if key == 'sources' and isinstance(value, list):
                    metadata_text += f"- {key}: {', '.join(value[:3])}{'...' if len(value) > 3 else ''}\n"
                else:
                    metadata_text += f"- {key}: {value}\n"
            context_parts.append(metadata_text)

        # Format conversation context
        chat_history_section = ""
        if conversation_context:
            chat_history_section = f"**Conversation History:**\n{conversation_context}"

        # Database-specific context
        db_context_parts = []
        if self.schema_metadata:
            db_info = f"**Database Information:**\n"
            db_info += f"- Database: {self.schema_metadata.database_name}\n"
            db_info += f"- Type: {self.schema_metadata.database_type}\n"
            db_info += f"- Tables: {len(self.schema_metadata.tables)}\n"
            db_info += f"- Views: {len(self.schema_metadata.views)}\n"
            db_context_parts.append(db_info)

        # Apply template substitution
        tmpl = Template(self.system_prompt_template)
        system_prompt = tmpl.safe_substitute(
            user_context=user_context,
            pre_context=pre_context,
            context="\n\n".join(context_parts) if context_parts else "No additional context available.",
            database_context="\n\n".join(db_context_parts) if db_context_parts else "",
            chat_history=chat_history_section,
            **kwargs
        )
        return system_prompt

    async def cleanup(self) -> None:
        """Cleanup resources including cache connections."""
        await self.cache.close()
        await super().cleanup() if hasattr(super(), 'cleanup') else None

    @abstractmethod
    async def connect_database(self) -> None:
        """Connect to the database. Must be implemented by subclasses."""
        pass

    @abstractmethod
    async def extract_schema_metadata(self) -> DatabaseSchema:
        """
        Extract complete schema metadata from the database.
        Must be implemented by subclasses based on database type.
        """
        pass

    @abstractmethod
    async def generate_query(
        self,
        natural_language_query: str,
        target_tables: Optional[List[str]] = None,
        query_type: str = "SELECT"
    ) -> Dict[str, Any]:
        """
        Generate database query from natural language.
        Must be implemented by subclasses based on database type.
        """
        pass

    @abstractmethod
    async def execute_query(self, query: str) -> Dict[str, Any]:
        """
        Execute a query against the database.
        Must be implemented by subclasses based on database type.
        """
        pass

    async def store_schema_in_knowledge_base(self) -> None:
        """Store schema metadata in the knowledge base for retrieval."""
        if not self.knowledge_store or not self.schema_metadata:
            return

        documents = []

        # Store table metadata
        for table in self.schema_metadata.tables:
            table_doc = {
                "content": self._format_table_for_storage(table),
                "metadata": {
                    "type": "table_schema",
                    "database": self.schema_metadata.database_name,
                    "schema": table.schema,
                    "tablename": table.tablename,
                    "database_type": self.schema_metadata.database_type
                }
            }
            documents.append(table_doc)

        # Store view metadata
        for view in self.schema_metadata.views:
            view_doc = {
                "content": self._format_table_for_storage(view, is_view=True),
                "metadata": {
                    "type": "view_schema",
                    "database": self.schema_metadata.database_name,
                    "schema": view.schema,
                    "view_name": view.tablename,
                    "database_type": self.schema_metadata.database_type
                }
            }
            documents.append(view_doc)

        # Store in knowledge base
        await self.knowledge_store.add_documents(documents)

    def _format_table_for_storage(self, table: TableMetadata, is_view: bool = False) -> str:
        """Format table metadata for storage in knowledge base."""
        object_type = "VIEW" if is_view else "TABLE"

        content = f"""
{object_type}: {table.schema}.{table.tablename}
Description: {table.description or 'No description available'}

Columns:
"""
        for col in table.columns:
            nullable = "NULL" if col.get('nullable', True) else "NOT NULL"
            default = f" DEFAULT {col['default']}" if col.get('default') else ""
            content += f"  - {col['name']}: {col['type']} {nullable}{default}\n"
            if col.get('description'):
                content += f"    Description: {col['description']}\n"

        if table.primary_keys:
            content += f"\nPrimary Keys: {', '.join(table.primary_keys)}\n"

        if table.foreign_keys:
            content += "\nForeign Keys:\n"
            for fk in table.foreign_keys:
                content += f"  - {fk['column']} -> {fk['referenced_table']}.{fk['referenced_column']}\n"

        if table.indexes:
            content += "\nIndexes:\n"
            for idx in table.indexes:
                content += f"  - {idx['name']}: {', '.join(idx['columns'])}\n"

        if table.sample_data:
            content += "\nSample Data:\n"
            for i, row in enumerate(table.sample_data[:3]):  # Limit to 3 rows
                content += f"  Row {i+1}: {json.dumps(row, default=str)}\n"

        return content

    async def ask(
        self,
        prompt: str,
        user_context: Optional[str] = None,
        context: Optional[str] = None,
        session_id: Optional[str] = None,
        user_id: Optional[str] = None,
        use_conversation_history: bool = True,
        **kwargs
    ) -> AIMessage:
        """
        Database-specific ask method with user context support and agentic mode.

        Args:
            prompt: The user's question about the database
            user_context: User-specific context for database interaction
            session_id: Session identifier for conversation history
            user_id: User identifier
            use_conversation_history: Whether to use conversation history
            **kwargs: Additional arguments for LLM

        Returns:
            AIMessage: The response from the LLM
        """
        # Force agentic mode for database operations
        effective_mode = "agentic"

        # Override temperature to ensure consistent database operations
        kwargs['temperature'] = kwargs.get('temperature', self._default_temperature)

        # Generate session ID if not provided
        if not session_id:
            session_id = f"db_session_{hash(prompt + str(user_id))}"

        try:
            # Get conversation history if enabled
            conversation_history = None
            conversation_context = ""

            if use_conversation_history and self.conversation_memory:
                conversation_history = await self.get_conversation_history(user_id, session_id)
                if not conversation_history:
                    conversation_history = await self.create_conversation_history(
                        user_id, session_id
                    )
                conversation_context = self.build_conversation_context(conversation_history)

            # Get vector context from knowledge store if available
            vector_context = ""
            vector_metadata = {}
            if self.knowledge_store:
                try:
                    # Search for relevant schema information
                    search_results = await self.knowledge_store.similarity_search(
                        prompt, k=5
                    )
                    if search_results:
                        vector_context = "\n\n".join([doc.page_content for doc in search_results])
                        vector_metadata = {
                            'sources': [doc.metadata.get('source', 'unknown') for doc in search_results],
                            'tables_referenced': [doc.metadata.get('table_name') for doc in search_results if doc.metadata.get('table_name')]
                        }
                except Exception as e:
                    self.logger.warning(f"Error retrieving vector context: {e}")

            # Create system prompt with user context
            system_prompt = await self.create_system_prompt(
                user_context=user_context,
                context=context or "",
                vector_context=vector_context,
                conversation_context=conversation_context,
                metadata=vector_metadata,
                **kwargs
            )

            # Log the operation
            self.logger.info(
                f"Database query in agentic mode: use_tools=True, "
                f"effective_mode={effective_mode}, available_tools={len(self.tools)}"
            )

            # Make the LLM call with tools enabled
            async with self._llm as client:
                response = await client.ask(
                    prompt=prompt,
                    model=kwargs.get('model', self._llm_model),
                    system_prompt=system_prompt,
                    user_id=user_id,
                    session_id=session_id,
                    temperature=kwargs.get('temperature', self._default_temperature),
                    tools=self.tools if self.tools else None,
                    **{k: v for k, v in kwargs.items() if k not in ['model', 'temperature']}
                )

            # Update conversation memory
            if use_conversation_history and conversation_history:
                assistant_content = str(response.output) if response.output is not None else (response.response or "")

                turn = ConversationTurn(
                    turn_id=str(uuid.uuid4()),
                    user_id=user_id,
                    user_message=prompt,
                    assistant_response=assistant_content,
                    metadata={
                        'user_context': user_context,
                        'effective_mode': effective_mode,
                        'tools_used': [tool.name for tool in response.tool_calls] if response.tool_calls else []
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

            return response

        except Exception as e:
            self.logger.error(
                f"Error in database ask method: {e}"
            )
            raise
