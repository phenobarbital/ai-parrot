"""DatabaseAgent — LLM-backed unified agent with structured output.

Inherits from BasicAgent, delegates all database operations to toolkits,
and uses QueryResponse structured output for every ask() call.
"""
from __future__ import annotations

import logging
import uuid
from typing import Any, Dict, List, Optional, Set, Union

from ...models import AIMessage, CompletionUsage
from ...models.outputs import StructuredOutputConfig
from ...stores.abstract import AbstractStore
from ..agent import BasicAgent
from ..prompts.builder import PromptBuilder
from .cache import CacheManager, CachePartitionConfig
from .models import (
    OutputComponent,
    UserRole,
    components_from_string,
    get_default_components,
)
from .models import QueryResponse
from .prompts import _build_database_prompt_builder
from .retries import QueryRetryConfig, RetryContext
from .router import SchemaQueryRouter
from .toolkits import DatabaseAgentToolkit
from .toolkits.base import DatabaseToolkit


# ---------------------------------------------------------------------------
# Component → internal toolkit tool name mapping
# ---------------------------------------------------------------------------

_COMPONENT_TO_TOOL_NAMES: Dict[OutputComponent, Set[str]] = {
    OutputComponent.SQL_QUERY: {
        "extract_sql_from_response",
        "extract_table_name_from_query",
    },
    OutputComponent.OPTIMIZATION_TIPS: {
        "generate_optimization_tips",
        "generate_basic_optimization_tips",
        "generate_table_specific_tips",
        "extract_performance_metrics",
    },
    OutputComponent.EXECUTION_PLAN: {
        "format_explain_plan",
        "extract_performance_metrics",
    },
    OutputComponent.SCHEMA_CONTEXT: {
        "generate_create_table_statement",
        "simplify_column_type",
        "extract_table_names_from_metadata",
        "get_schema_counts_direct",
    },
    OutputComponent.EXAMPLES: {
        "generate_examples",
    },
    OutputComponent.DATA_RESULTS: {
        "format_query_history",
    },
    OutputComponent.DOCUMENTATION: {
        "format_as_text",
        "is_explanatory_response",
        "parse_tips",
    },
}


class DatabaseAgent(BasicAgent):
    """Unified database agent backed by BasicAgent + QueryResponse structured output.

    Inherits composable prompt layers, LLM lifecycle, and tool management
    from BasicAgent.  Database toolkits handle actual DB I/O; the internal
    DatabaseAgentToolkit exposes formatting helpers as LLM tools.

    Args:
        name: Agent display name.
        toolkits: List of ``DatabaseToolkit`` instances.
        default_user_role: Fallback role when none is provided/inferred.
        vector_store: Optional vector store for cache similarity search.
        redis_url: Optional Redis URL for cache persistence.
        retry_config: Optional query retry configuration.
        **kwargs: Forwarded to ``BasicAgent.__init__``.
    """

    _default_temperature: float = 0.0
    max_tokens: int = 8192
    _prompt_builder: PromptBuilder = _build_database_prompt_builder()

    def __init__(
        self,
        name: str = "DatabaseAgent",
        toolkits: Optional[List[DatabaseToolkit]] = None,
        default_user_role: UserRole = UserRole.DATA_ANALYST,
        vector_store: Optional[AbstractStore] = None,
        redis_url: Optional[str] = None,
        retry_config: Optional[QueryRetryConfig] = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(name=name, **kwargs)
        # Ensure logger is always available (parent stubs may omit it)
        if not hasattr(self, "logger"):
            self.logger = logging.getLogger(f"{name}.DatabaseAgent")
        self.toolkits: List[DatabaseToolkit] = toolkits or []
        self.default_user_role = default_user_role
        self.retry_config = retry_config
        self.cache_manager = CacheManager(
            redis_url=redis_url, vector_store=vector_store
        )
        self.query_router: Optional[SchemaQueryRouter] = None
        self._toolkit_map: Dict[str, DatabaseToolkit] = {}
        self._internal_toolkit: Optional[DatabaseAgentToolkit] = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def configure(self, app: Any = None) -> None:
        """Configure the agent: create cache partitions, start toolkits,
        register tools with the router, and instantiate the internal toolkit.

        Args:
            app: Optional application context (unused, for API compatibility).
        """
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

        for tk in self.toolkits:
            tk_id = f"{tk.database_type}_{tk.primary_schema}"
            self._toolkit_map[tk_id] = tk

            # Propagate agent-level retry config into the toolkit (overrides default).
            if self.retry_config is not None:
                tk.retry_config = self.retry_config

            if tk.cache_partition is None:
                partition = self.cache_manager.create_partition(
                    CachePartitionConfig(
                        namespace=tk_id,
                        lru_maxsize=500,
                        lru_ttl=1800,
                    )
                )
                tk.cache_partition = partition

            self.query_router.register_database(tk.database_type, tk_id)

            try:
                await tk.start()
                self.logger.info("Started toolkit: %s", tk_id)
            except Exception as exc:
                self.logger.warning("Failed to start toolkit %s: %s", tk_id, exc)

        self._internal_toolkit = DatabaseAgentToolkit()

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
    # Public API
    # ------------------------------------------------------------------

    async def create_system_prompt(self, **kwargs: Any) -> str:
        """Build the system prompt using the database-specific PromptBuilder layers.

        Delegates to the parent's implementation when available; otherwise builds
        the prompt directly from ``_prompt_builder`` (test-stub compatibility).

        Args:
            **kwargs: Template variables forwarded to the prompt builder
                (e.g., ``database``, ``intent``, ``schema_summary``).

        Returns:
            Rendered system prompt string.
        """
        _super = super()
        if hasattr(_super, "create_system_prompt"):
            return await _super.create_system_prompt(**kwargs)  # type: ignore[union-attr]
        # Fallback for test stubs: build directly from _prompt_builder
        context: Dict[str, Any] = {
            "knowledge_content": "",
            "user_context": kwargs.pop("user_context", ""),
            "chat_history": "",
            "output_instructions": "",
            **kwargs,
        }
        return self._prompt_builder.build(context)

    def get_default_components(self, user_role: UserRole) -> OutputComponent:
        """Return default output components for a user role.

        Delegates to the module-level helper so the result is identical.

        Args:
            user_role: The role to look up.

        Returns:
            ``OutputComponent`` flags appropriate for that role.
        """
        return get_default_components(user_role)

    async def ask(
        self,
        query: str,
        user_role: Optional[UserRole] = None,
        database: Optional[str] = None,
        context: Optional[str] = None,
        output_components: Optional[Union[str, OutputComponent]] = None,
        output_format: Optional[Any] = None,
        session_id: Optional[str] = None,
        user_id: Optional[str] = None,
        structured_output: Optional[Any] = None,
        **kwargs: Any,
    ) -> AIMessage:
        """Process a database query using registered toolkits and the LLM.

        Role resolution (three-tier):
          1. Explicit ``user_role`` parameter
          2. Inferred from query intent by the router
          3. ``default_user_role`` fallback

        Args:
            query: Natural-language query or SQL.
            user_role: Explicit role override (highest priority).
            database: Explicit toolkit identifier.
            context: Additional context string injected into the prompt.
            output_components: Desired output components (flags or comma-separated string).
            output_format: Unused; reserved for future formatting options.
            session_id: Session identifier for memory tracking.
            user_id: User identifier.
            structured_output: Override the default ``QueryResponse`` structured output.
            **kwargs: Forwarded to the LLM client.

        Returns:
            ``AIMessage`` with the formatted response and unpacked ``QueryResponse``.
        """
        session_id = session_id or str(uuid.uuid4())
        user_id = user_id or "anonymous"

        # Edge case: no toolkit → structured error without LLM call
        if not self.toolkits:
            qr = QueryResponse(
                explanation=(
                    "No database toolkit registered. "
                    "Pass at least one DatabaseToolkit when constructing DatabaseAgent."
                ),
                query=None,
                data=None,
            )
            return self._make_structured_message(qr, query=query, session_id=session_id)

        if self.query_router is None:
            qr = QueryResponse(
                explanation="Agent not configured. Call configure() first.",
                query=None,
                data=None,
            )
            return self._make_structured_message(qr, query=query, session_id=session_id)

        # Resolve output components
        components = self._resolve_components(output_components)

        # Route query (intent + role + database selection)
        route = await self.query_router.route(
            query=query,
            user_role=user_role,
            output_components=components,
            database=database,
        )

        if route.role_source == "default":
            route.user_role = self.default_user_role

        # When the caller omitted ``output_components``, the router has
        # already merged the role baseline with intent-specific flags
        # (see ``SchemaQueryRouter.route``). Use that result directly,
        # otherwise intent-specific components (e.g. ``OPTIMIZATION_TIPS``
        # for ``OPTIMIZE_QUERY``) get silently dropped from tool gating
        # and the prompt.
        if components is None:
            components = route.components

        # Schema summary from target toolkit (best-effort)
        schema_summary = ""
        target_toolkit = self._select_toolkit(route.target_database)
        if target_toolkit is not None:
            try:
                tables = await target_toolkit.search_schema(query, limit=5)
                if tables:
                    schema_summary = "\n".join(t.to_yaml_context() for t in tables)
            except Exception as exc:
                self.logger.debug("Schema search failed: %s", exc)

        # Build system prompt via PromptBuilder layers
        db_name = route.target_database or (
            self.toolkits[0].database_type if self.toolkits else "unknown"
        )
        intent_str = (
            route.intent.value if hasattr(route.intent, "value") else str(route.intent)
        )
        system_prompt = await self.create_system_prompt(
            database=db_name,
            intent=intent_str,
            output_components=str(components),
            schema_summary=schema_summary,
            user_context=context or "",
        )

        # Compute tool subset gated by active output components
        active_tools = self._compute_active_tools(components)

        # LLM call parameters
        llm_kwargs: Dict[str, Any] = {
            "prompt": query,
            "system_prompt": system_prompt,
            "use_tools": True,
            "tools": active_tools,
            "user_id": user_id,
            "session_id": session_id,
            "temperature": kwargs.pop("temperature", self._default_temperature),
        }
        if self.max_tokens is not None:
            llm_kwargs["max_tokens"] = self.max_tokens

        # Structured output: caller override or default QueryResponse
        if structured_output is not None:
            llm_kwargs["structured_output"] = structured_output
        else:
            llm_kwargs["structured_output"] = StructuredOutputConfig(
                output_type=QueryResponse
            )

        # Invoke LLM with retry loop — re-ask up to retry_config.max_retries times
        # when the toolkit returns a RetryContext (retryable query failure).
        max_attempts = (self.retry_config.max_retries if self.retry_config else 0) + 1
        attempt = 0
        last_retry_ctx: Optional[RetryContext] = None
        response: Optional[AIMessage] = None

        while attempt < max_attempts:
            call_kwargs: Dict[str, Any] = dict(llm_kwargs)
            if last_retry_ctx is not None:
                retry_section = (
                    f"\n\n[Retry {last_retry_ctx.attempt}] Previous SQL query failed.\n"
                    f"Query: {last_retry_ctx.query}\n"
                    f"Error: {last_retry_ctx.error}"
                )
                if last_retry_ctx.sample_data:
                    retry_section += f"\nSample data: {last_retry_ctx.sample_data}"
                retry_section += "\nPlease generate a corrected SQL query."
                call_kwargs["prompt"] = query + retry_section

            response = await self._llm.ask(**call_kwargs)

            qr_check: Optional[QueryResponse] = (
                response.output if isinstance(response.output, QueryResponse) else None
            )
            if qr_check is None or qr_check.query is None or target_toolkit is None:
                break

            try:
                exec_result = await target_toolkit.execute_query(qr_check.query)
            except Exception as exec_exc:
                # Non-retryable error re-raised by execute_query when
                # ``retry_config`` is set. Surface as a failure
                # QueryResponse so the caller cannot mistake it for a
                # successful run.
                self.logger.error(
                    "Query execution raised non-retryable error: %s", exec_exc
                )
                response.output = QueryResponse(
                    explanation=(
                        f"Query execution failed with a non-retryable error: "
                        f"{exec_exc}"
                    ),
                    query=qr_check.query,
                    data=None,
                )
                break

            if not isinstance(exec_result, RetryContext):
                break

            last_retry_ctx = exec_result
            attempt += 1

        if last_retry_ctx is not None and attempt >= max_attempts:
            self.logger.warning(
                "Retry exhausted after %s attempts; surfacing last error.", attempt
            )

        # Unpack structured output into AIMessage fields.
        # The while loop always runs at least once (max_attempts >= 1), so
        # ``response`` is set on every code path. We use an explicit guard
        # here rather than ``assert`` because production deployments may
        # run with -O, which strips assertions.
        if response is None:  # pragma: no cover — defensive
            raise RuntimeError(
                "LLM response not generated (retry loop must run at least once)"
            )
        qr: Optional[QueryResponse] = (
            response.output if isinstance(response.output, QueryResponse) else None
        )
        if qr is not None:
            response.is_structured = True
            response.response = qr.explanation
            response.data = (
                qr.data.data.to_dataframe()
                if qr.data and qr.data.data
                else None
            )
        else:
            # Free-text fallback
            response.is_structured = False

        response.session_id = session_id
        return response

    async def conversation(self, question: str, **kwargs: Any) -> AIMessage:
        """Conversation method — delegates to ``ask()``."""
        return await self.ask(question, **kwargs)

    async def invoke(self, question: str, **kwargs: Any) -> AIMessage:
        """Invoke method — delegates to ``ask()``."""
        return await self.ask(question, **kwargs)

    async def ask_stream(self, question: str, **kwargs: Any):
        """Streaming ask — yields single response (streaming not yet implemented)."""
        result = await self.ask(question, **kwargs)
        yield result

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _make_structured_message(
        self,
        qr: QueryResponse,
        query: str = "",
        session_id: str = "",
    ) -> AIMessage:
        """Build an AIMessage wrapping a QueryResponse without an LLM call."""
        msg = AIMessage(
            input=query,
            output=qr,
            response=qr.explanation,
            model="database-agent",
            provider="parrot",
            usage=CompletionUsage(
                prompt_tokens=0, completion_tokens=0, total_tokens=0
            ),
            is_structured=True,
            session_id=session_id or None,
        )
        return msg

    def _resolve_components(
        self,
        output_components: Optional[Union[str, OutputComponent]],
    ) -> Optional[OutputComponent]:
        """Resolve output components from string or enum.

        Args:
            output_components: Raw value from caller.

        Returns:
            Resolved ``OutputComponent`` flags, or ``None`` if not provided.
        """
        if output_components is None:
            return None
        if isinstance(output_components, OutputComponent):
            return output_components
        if isinstance(output_components, str):
            return components_from_string(output_components)
        return None

    def _select_toolkit(
        self, target_database: Optional[str]
    ) -> Optional[DatabaseToolkit]:
        """Select the toolkit to handle the request.

        Args:
            target_database: Toolkit identifier from routing.

        Returns:
            The matching toolkit, or the first available one, or ``None``.
        """
        if target_database and target_database in self._toolkit_map:
            return self._toolkit_map[target_database]
        if self.toolkits:
            return self.toolkits[0]
        return None

    def _compute_active_tools(self, components: OutputComponent) -> List[Any]:
        """Return the subset of internal toolkit tools relevant to ``components``.

        Iterates ``_COMPONENT_TO_TOOL_NAMES`` and collects tool names whose
        associated ``OutputComponent`` flag is present in ``components``, then
        returns the corresponding bound methods from ``self._internal_toolkit``.

        Args:
            components: Active output component flags for the current request.

        Returns:
            List of callable tool objects (bound methods with ``_is_tool=True``).
        """
        if self._internal_toolkit is None:
            return []

        exposed_names: Set[str] = set()
        for flag, tool_names in _COMPONENT_TO_TOOL_NAMES.items():
            if flag in components:
                exposed_names |= tool_names

        return [
            getattr(self._internal_toolkit, name)
            for name in exposed_names
            if hasattr(self._internal_toolkit, name)
            and getattr(
                getattr(self._internal_toolkit, name, None), "_is_tool", False
            )
        ]
