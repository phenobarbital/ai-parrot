"""DatabaseAgent — unified agent with multi-toolkit support.

Thin orchestration layer that delegates all database operations to toolkits.
Handles LLM interaction, system prompt generation, response formatting,
conversation memory, and three-tier role resolution.
"""
from __future__ import annotations

import json
from string import Template
from typing import Any, Dict, List, Optional, Type, Union

from pydantic import BaseModel

from ...models import AIMessage, CompletionUsage
from ...stores.abstract import AbstractStore
from ..abstract import AbstractBot
from .cache import CacheManager, CachePartitionConfig
from .models import (
    DatabaseResponse,
    OutputComponent,
    QueryIntent,
    RouteDecision,
    UserRole,
    get_default_components,
)
from .prompts import DB_AGENT_PROMPT
from .retries import QueryRetryConfig
from .router import SchemaQueryRouter
from .toolkits.base import DatabaseToolkit


class DatabaseAgent(AbstractBot):
    """Unified database agent with multi-toolkit support.

    Delegates all database-specific operations to registered
    ``DatabaseToolkit`` instances.  Provides three-tier role resolution,
    hybrid database routing, and dynamic system prompt generation.

    Args:
        name: Agent display name.
        toolkits: List of ``DatabaseToolkit`` instances.
        default_user_role: Fallback role when none is provided/inferred.
        vector_store: Optional vector store for cache similarity search.
        redis_url: Optional Redis URL for cache persistence.
        system_prompt_template: Custom system prompt (uses default if ``None``).
        **kwargs: Passed through to ``AbstractBot``.
    """

    _default_temperature: float = 0.0
    max_tokens: int = 8192
    system_prompt_template = DB_AGENT_PROMPT

    def __init__(
        self,
        name: str = "DatabaseAgent",
        toolkits: Optional[List[DatabaseToolkit]] = None,
        default_user_role: UserRole = UserRole.DATA_ANALYST,
        vector_store: Optional[AbstractStore] = None,
        redis_url: Optional[str] = None,
        system_prompt_template: Optional[str] = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(name=name, **kwargs)
        self.toolkits: List[DatabaseToolkit] = toolkits or []
        self.default_user_role = default_user_role

        # Cache manager (shared across all toolkits)
        self.cache_manager = CacheManager(
            redis_url=redis_url, vector_store=vector_store
        )

        # Router (initialised during configure())
        self.query_router: Optional[SchemaQueryRouter] = None

        # Override prompt if provided
        if system_prompt_template:
            self.system_prompt_template = system_prompt_template

        # Toolkit name → toolkit map
        self._toolkit_map: Dict[str, DatabaseToolkit] = {}

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def configure(self, app: Any = None) -> None:
        """Configure the agent: create cache partitions, start toolkits,
        register tools, and build the router.

        Args:
            app: Optional application context (passed to ``super().configure``).
        """
        # 1. Determine router parameters from first toolkit
        primary_schema = "public"
        allowed_schemas: List[str] = []
        for tk in self.toolkits:
            if not allowed_schemas:
                primary_schema = tk.primary_schema
            allowed_schemas.extend(tk.allowed_schemas)
        allowed_schemas = list(dict.fromkeys(allowed_schemas))  # dedupe

        self.query_router = SchemaQueryRouter(
            primary_schema=primary_schema,
            allowed_schemas=allowed_schemas,
        )

        # 2. Create cache partitions & start toolkits
        for tk in self.toolkits:
            # Unique identifier for this toolkit
            tk_id = f"{tk.database_type}_{tk.primary_schema}"
            self._toolkit_map[tk_id] = tk

            # Create cache partition if toolkit doesn't already have one
            if tk.cache_partition is None:
                partition = self.cache_manager.create_partition(
                    CachePartitionConfig(
                        namespace=tk_id,
                        lru_maxsize=500,
                        lru_ttl=1800,
                    )
                )
                tk.cache_partition = partition

            # Register database identifiers with router
            self.query_router.register_database(tk.database_type, tk_id)

            # Start toolkit (connect to database)
            try:
                await tk.start()
                self.logger.info("Started toolkit: %s", tk_id)
            except Exception as exc:
                self.logger.warning("Failed to start toolkit %s: %s", tk_id, exc)

        self.logger.info(
            "DatabaseAgent configured with %d toolkits: %s",
            len(self.toolkits),
            list(self._toolkit_map.keys()),
        )

    async def cleanup(self) -> None:
        """Stop all toolkits and close the cache manager."""
        for tk in self.toolkits:
            try:
                await tk.stop()
            except Exception as exc:
                self.logger.debug("Error stopping toolkit: %s", exc)
        await self.cache_manager.close()

    # ------------------------------------------------------------------
    # Main API
    # ------------------------------------------------------------------

    async def ask(
        self,
        query: str,
        user_role: Optional[UserRole] = None,
        database: Optional[str] = None,
        context: Optional[str] = None,
        output_components: Optional[Union[str, OutputComponent]] = None,
        output_format: Optional[Union[str, Type[BaseModel]]] = None,
        session_id: Optional[str] = None,
        user_id: Optional[str] = None,
        enable_retry: bool = True,
        **kwargs: Any,
    ) -> AIMessage:
        """Process a database query using registered toolkits.

        Role resolution (three-tier):
          1. Explicit ``user_role`` parameter
          2. Inferred from query intent by the router
          3. ``default_user_role`` fallback

        Args:
            query: Natural-language query or raw SQL.
            user_role: Explicit role override (highest priority).
            database: Explicit toolkit identifier.
            context: Additional context string.
            output_components: Desired output components.
            output_format: Desired response format.
            session_id: Session identifier for memory.
            user_id: User identifier.
            enable_retry: Whether to retry on errors.
            **kwargs: Additional options.

        Returns:
            ``AIMessage`` with the formatted response.
        """
        if self.query_router is None:
            return self._make_message(
                "Agent not configured. Call configure() first.", query
            )

        # 1. Parse output components
        components = self._resolve_components(output_components)

        # 2. Route query (intent + role + database)
        route = await self.query_router.route(
            query=query,
            user_role=user_role,
            output_components=components,
            database=database,
        )

        # Apply default role if router didn't resolve one
        if route.role_source == "default":
            route.user_role = self.default_user_role

        # 3. Select target toolkit
        target_toolkit = self._select_toolkit(route.target_database)

        # 4. Build system prompt
        system_prompt = self._build_system_prompt(route, context)

        # 5. Build the response
        db_response = DatabaseResponse()

        try:
            # Schema search if needed
            if route.needs_metadata_discovery and target_toolkit:
                tables = await target_toolkit.search_schema(query, limit=5)
                if tables:
                    schema_ctx = "\n".join(t.to_yaml_context() for t in tables)
                    db_response.schema_context = schema_ctx

            # Query execution if needed
            if route.needs_execution and target_toolkit:
                # For raw SQL or validated queries
                if route.intent in (QueryIntent.VALIDATE_QUERY, QueryIntent.SHOW_DATA):
                    exec_result = await target_toolkit.execute_query(
                        query,
                        limit=route.data_limit or 1000,
                    )
                    if exec_result.success:
                        db_response.query = query
                        db_response.data = exec_result.data
                    else:
                        db_response.documentation = f"Query failed: {exec_result.error_message}"

        except Exception as exc:
            self.logger.error("Error processing query: %s", exc)
            db_response.documentation = f"Error: {exc}"

        # 6. Format response
        content = self._format_db_response(db_response, route)

        return self._make_message(content, query)

    # ------------------------------------------------------------------
    # Abstract method implementations required by AbstractBot
    # ------------------------------------------------------------------

    async def conversation(self, question: str, **kwargs: Any) -> AIMessage:
        """Conversation method — delegates to ``ask()``."""
        return await self.ask(question, **kwargs)

    async def invoke(self, question: str, **kwargs: Any) -> AIMessage:
        """Invoke method — delegates to ``ask()``."""
        return await self.ask(question, **kwargs)

    async def ask_stream(self, question: str, **kwargs: Any):
        """Streaming ask — not yet implemented; yields single response."""
        result = await self.ask(question, **kwargs)
        yield result

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _make_message(self, content: str, query: str = "") -> AIMessage:
        """Create a properly initialised ``AIMessage``."""
        return AIMessage(
            content=content,
            input=query,
            output=content,
            model="database-agent",
            provider="parrot",
            usage=CompletionUsage(
                prompt_tokens=0, completion_tokens=0, total_tokens=0
            ),
        )

    def _resolve_components(
        self,
        output_components: Optional[Union[str, OutputComponent]],
    ) -> Optional[OutputComponent]:
        """Resolve output components from string or enum."""
        if output_components is None:
            return None
        if isinstance(output_components, OutputComponent):
            return output_components
        if isinstance(output_components, str):
            from .models import components_from_string
            return components_from_string(output_components)
        return None

    def _select_toolkit(
        self, target_database: Optional[str]
    ) -> Optional[DatabaseToolkit]:
        """Select the toolkit to handle the request.

        Args:
            target_database: Toolkit identifier from routing.

        Returns:
            The matching toolkit, or the first one, or ``None``.
        """
        if target_database and target_database in self._toolkit_map:
            return self._toolkit_map[target_database]
        # Fallback: first available toolkit
        if self.toolkits:
            return self.toolkits[0]
        return None

    def _build_system_prompt(
        self,
        route: RouteDecision,
        context: Optional[str] = None,
    ) -> str:
        """Build the system prompt dynamically from registered toolkits."""
        # Describe available databases
        db_descriptions: list[str] = []
        for tk_id, tk in self._toolkit_map.items():
            schemas = ", ".join(tk.allowed_schemas)
            db_descriptions.append(
                f"- {tk_id} ({tk.database_type}): schemas [{schemas}]"
            )
        database_context = (
            "**Available databases:**\n" + "\n".join(db_descriptions)
            if db_descriptions
            else ""
        )

        # Role description
        role_map = {
            UserRole.BUSINESS_USER: "business data analyst",
            UserRole.DATA_ANALYST: "data analyst",
            UserRole.DATA_SCIENTIST: "data scientist",
            UserRole.DATABASE_ADMIN: "database administrator",
            UserRole.DEVELOPER: "software developer",
            UserRole.QUERY_DEVELOPER: "query developer",
        }
        role = role_map.get(route.user_role, "data analyst")

        try:
            return Template(self.system_prompt_template).safe_substitute(
                role=role,
                backstory=f"You are serving as a {role}.",
                user_context=context or "",
                database_context=database_context,
                context="",
                vector_context="",
                chat_history="",
                database_type=", ".join(
                    tk.database_type for tk in self.toolkits
                ),
            )
        except Exception:
            return self.system_prompt_template

    def _format_db_response(
        self,
        db_response: DatabaseResponse,
        route: RouteDecision,
    ) -> str:
        """Format a ``DatabaseResponse`` into a text string for the user.

        Args:
            db_response: The assembled response components.
            route: The routing decision (for component flags).

        Returns:
            Formatted text string.
        """
        parts: list[str] = []

        if db_response.query and OutputComponent.SQL_QUERY in route.components:
            parts.append(f"**Query:**\n```sql\n{db_response.query}\n```")

        if db_response.data and OutputComponent.DATA_RESULTS in route.components:
            if isinstance(db_response.data, list):
                if len(db_response.data) <= 20:
                    parts.append(f"**Results** ({len(db_response.data)} rows):\n```json\n{json.dumps(db_response.data, indent=2, default=str)}\n```")
                else:
                    parts.append(f"**Results:** {len(db_response.data)} rows returned.")
            else:
                parts.append(f"**Results:**\n{db_response.data}")

        if db_response.schema_context and OutputComponent.SCHEMA_CONTEXT in route.components:
            parts.append(f"**Schema Context:**\n{db_response.schema_context}")

        if db_response.documentation and OutputComponent.DOCUMENTATION in route.components:
            parts.append(f"**Documentation:**\n{db_response.documentation}")

        if db_response.execution_plan and OutputComponent.EXECUTION_PLAN in route.components:
            parts.append(f"**Execution Plan:**\n{db_response.execution_plan}")

        if db_response.optimization_tips and OutputComponent.OPTIMIZATION_TIPS in route.components:
            tips = "\n".join(f"- {t}" for t in db_response.optimization_tips)
            parts.append(f"**Optimization Tips:**\n{tips}")

        if db_response.examples and OutputComponent.EXAMPLES in route.components:
            examples = "\n".join(f"- {e}" for e in db_response.examples)
            parts.append(f"**Examples:**\n{examples}")

        if not parts:
            # Fallback: include any non-None field
            if db_response.documentation:
                parts.append(db_response.documentation)
            elif db_response.schema_context:
                parts.append(db_response.schema_context)
            else:
                parts.append("No results available.")

        return "\n\n".join(parts)
