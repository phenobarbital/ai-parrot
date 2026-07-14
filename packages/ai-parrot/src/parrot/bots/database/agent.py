"""DatabaseAgent — LLM-backed unified agent with structured output.

Inherits from BasicAgent, delegates all database operations to toolkits,
and uses QueryResponse structured output for every ask() call.
"""
from __future__ import annotations

import logging
import re
import uuid
import warnings
from typing import Any, Dict, FrozenSet, List, Optional, Set, Tuple, Union

from ...models import AIMessage, CompletionUsage
from ...models.outputs import OutputMode, StructuredOutputConfig
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


# Matches the schema part of a ``schema.table`` reference. Conservative:
# unicode-aware via ``\w`` would be too permissive (matches Spanish accents
# we don't want flowing into identifier checks); ASCII identifiers cover
# every Postgres schema we've seen in practice.
_QUALIFIED_REF_RE = re.compile(r"\b([A-Za-z_][A-Za-z0-9_]*)\.[A-Za-z_][A-Za-z0-9_]*\b")

# FEAT-172: Pattern for a valid, identifier-safe tool_prefix.
# Must start with an ASCII letter; may contain letters, digits, and underscores.
# Checked at configure() time before any toolkit tool-name is resolved.
_TOOL_PREFIX_PATTERN = re.compile(r"^[A-Za-z][A-Za-z0-9_]*$")


# ---------------------------------------------------------------------------
# Component → tool name mappings (FEAT-171: prefix-aware two-map split)
# ---------------------------------------------------------------------------

# Internal helper tools that live in DatabaseAgentToolkit.
# Resolved via getattr(self._internal_toolkit, name) — no prefix logic.
# These names do NOT carry any toolkit prefix.
_INTERNAL_TOOLS_BY_COMPONENT: Dict[OutputComponent, Set[str]] = {
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

# External database-toolkit tools.  Names here are LOGICAL — they carry
# no hardcoded prefix.  At resolution time each attached toolkit applies
# its own ``tool_prefix`` via
#   full_name = f"{tk.tool_prefix}{tk.prefix_separator}{logical_name}"
# and the tool is fetched with ``tk.get_tool(full_name)``.
#
# This decouples ``DatabaseAgent`` from any hardcoded toolkit prefix:
# a ``BigQueryToolkit(tool_prefix="bq")`` exposes ``bq_search_schema``,
# a ``PostgresToolkit(tool_prefix="db")`` exposes ``db_search_schema``,
# and both are surfaced correctly without any change here.
_TOOLKIT_TOOLS_BY_COMPONENT: Dict[OutputComponent, Set[str]] = {
    OutputComponent.SQL_QUERY: {"generate_query", "validate_query", "explain_query"},
    OutputComponent.EXECUTION_PLAN: set(),
    OutputComponent.SCHEMA_CONTEXT: {"search_schema", "describe_table"},
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
        cache_ttl_by_completeness: Optional[Dict[int, int]] = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(name=name, **kwargs)
        # Ensure logger is always available (parent stubs may omit it)
        if not hasattr(self, "logger"):
            self.logger = logging.getLogger(f"{name}.DatabaseAgent")
        self.toolkits: List[DatabaseToolkit] = toolkits or []
        self.default_user_role = default_user_role
        self.retry_config = retry_config
        self._cache_ttl_by_completeness = cache_ttl_by_completeness
        self.cache_manager = CacheManager(
            redis_url=redis_url, vector_store=vector_store
        )
        self.query_router: Optional[SchemaQueryRouter] = None
        self._toolkit_map: Dict[str, DatabaseToolkit] = {}
        self._internal_toolkit: Optional[DatabaseAgentToolkit] = None
        # Collision deduplication: each entry is (full_name, frozenset of
        # toolkit class names) so the same collision is logged at most once
        # per agent lifetime (FEAT-171).
        self._logged_collisions: Set[Tuple[str, FrozenSet[str]]] = set()
        # Deprecation deduplication: tracks id(tk) for toolkits whose
        # tool_prefix=None fallback has already fired a DeprecationWarning.
        self._warned_none_prefix: Set[int] = set()

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def configure(self, app: Any = None) -> None:
        """Configure the agent: create cache partitions, start toolkits,
        register tools with the router, and instantiate the internal toolkit.

        Validation steps (FEAT-172) run after all toolkits are started but
        before ``self._internal_toolkit`` is assigned:

        1. **Prefix presence** — raises ``ValueError`` if any toolkit's
           ``tool_prefix`` is ``None`` or ``""``; every database toolkit
           must declare a non-empty prefix.
        2. **Prefix shape** — raises ``ValueError`` if any toolkit's
           ``tool_prefix`` does not match ``^[A-Za-z][A-Za-z0-9_]*$``;
           a non-identifier-safe prefix would produce tool names rejected
           by LLM providers.
        3. **Collision detection** — raises ``ValueError`` if two toolkits
           expose the same fully-qualified tool name (detected via
           ``list_tool_names()``); the error names both conflicting classes.

        On any validation failure ``self._internal_toolkit`` remains ``None``.
        Callers must construct a fresh ``DatabaseAgent`` instance after a
        ``ValueError`` — a failed agent must not be re-used.

        Args:
            app: Optional application context (unused, for API compatibility).

        Raises:
            ValueError: If a toolkit's ``tool_prefix`` is empty or ``None``.
            ValueError: If a toolkit's ``tool_prefix`` is not identifier-safe.
            ValueError: If two toolkits register the same fully-qualified tool
                name.
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
                config_kwargs: Dict[str, Any] = {
                    "namespace": tk_id,
                    "lru_maxsize": 500,
                    "lru_ttl": 1800,
                }
                if self._cache_ttl_by_completeness is not None:
                    config_kwargs["ttl_by_completeness"] = self._cache_ttl_by_completeness
                partition = self.cache_manager.create_partition(
                    CachePartitionConfig(**config_kwargs)
                )
                tk.cache_partition = partition

            self.query_router.register_database(tk.database_type, tk_id)

            try:
                await tk.start()
                self.logger.info("Started toolkit: %s", tk_id)
            except Exception as exc:
                self.logger.warning("Failed to start toolkit %s: %s", tk_id, exc)

        # --- FEAT-172 Pass A: prefix presence ---
        # Every database toolkit must declare a non-empty tool_prefix.
        for tk in self.toolkits:
            if not tk.tool_prefix:
                raise ValueError(
                    f"DatabaseToolkit subclasses must declare a non-empty "
                    f"tool_prefix; {type(tk).__name__} has tool_prefix={tk.tool_prefix!r}. "
                    f"Set `tool_prefix` on the toolkit class (e.g. \"db\", \"bq\")."
                )

        # --- FEAT-172 Pass B: identifier-safe prefix shape ---
        # The prefix is embedded in LLM-visible tool names; providers
        # (OpenAI / Anthropic) reject names containing dashes, spaces, or
        # non-ASCII characters.
        for tk in self.toolkits:
            if not _TOOL_PREFIX_PATTERN.fullmatch(tk.tool_prefix):
                raise ValueError(
                    f"DatabaseToolkit subclasses must declare an identifier-safe "
                    f"tool_prefix matching {_TOOL_PREFIX_PATTERN.pattern!r}; "
                    f"{type(tk).__name__} has tool_prefix={tk.tool_prefix!r}. "
                    f"Use only ASCII letters, digits, and underscores, starting "
                    f"with a letter."
                )

        # --- FEAT-172 Pass C: collision detection ---
        # Walk every toolkit's fully-qualified tool names; raise on first
        # duplicate.  list_tool_names() triggers _generate_tools() lazily
        # here — the warm cache benefits _compute_active_tools later.
        fully_qualified_owners: Dict[str, type] = {}
        for tk in self.toolkits:
            for full_name in tk.list_tool_names():
                if full_name in fully_qualified_owners:
                    prior_owner = fully_qualified_owners[full_name]
                    raise ValueError(
                        f"Tool name collision while configuring DatabaseAgent: "
                        f"{full_name!r} is exposed by both {prior_owner.__name__} and "
                        f"{type(tk).__name__}. Two toolkits must not register the same "
                        f"fully-qualified tool name. Change one toolkit's tool_prefix or "
                        f"remove the duplicate from one of the toolkits."
                    )
                fully_qualified_owners[full_name] = type(tk)

        self._internal_toolkit = DatabaseAgentToolkit()

        self.logger.info(
            "DatabaseAgent configured with %d toolkits: %s",
            len(self.toolkits),
            list(self._toolkit_map.keys()),
        )

        # Delegate to BasicAgent/Chatbot/AbstractBot.configure() so LLM,
        # prompt builder, vector store, KB selector, post_configure, and
        # the ``_configured = True`` flag all run. Without this chain
        # ``self._configured`` stays False forever, and any host that
        # gates on ``is_configured`` (e.g. ``BotManager.get_bot()``)
        # re-enters configure() on the next request — re-registering
        # toolkits and raising ``ToolNameCollisionError``.
        await super().configure(app=app)

    async def cleanup(self) -> None:
        """Stop all toolkits, close the cache manager, then run base cleanup.

        The database-specific resources (toolkit asyncdb pools + the
        ``CacheManager``'s Redis pool and owned vector-store engine) are torn
        down first, then ``super().cleanup()`` releases the resources owned by
        the base agent — LLM client/session, ``self.store``, knowledge bases,
        and MCP client sessions. Each phase is isolated so a failure in one
        does not prevent the others from running (teardown must not raise).
        """
        for tk in self.toolkits:
            try:
                await tk.stop()
            except Exception as exc:
                self.logger.debug("Error stopping toolkit: %s", exc)
        try:
            await self.cache_manager.close()
        except Exception as exc:
            self.logger.debug("Error closing cache manager: %s", exc)
        # Chain base-agent cleanup (LLM, self.store, KBs, MCP). Guarded because
        # test stubs may substitute a base class without an async ``cleanup``.
        parent_cleanup = getattr(super(), "cleanup", None)
        if callable(parent_cleanup):
            try:
                await parent_cleanup()
            except Exception as exc:
                self.logger.debug("Error during base agent cleanup: %s", exc)

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
        question: str,
        user_role: Optional[UserRole] = None,
        database: Optional[str] = None,
        context: Optional[str] = None,
        output_components: Optional[Union[str, OutputComponent]] = None,
        output_format: Optional[Any] = None,
        session_id: Optional[str] = None,
        user_id: Optional[str] = None,
        structured_output: Optional[Any] = None,
        output_mode: Optional[OutputMode] = None,
        **kwargs: Any,
    ) -> AIMessage:
        """Process a database query using registered toolkits and the LLM.

        Role resolution (three-tier):
          1. Explicit ``user_role`` parameter
          2. Inferred from query intent by the router
          3. ``default_user_role`` fallback

        Args:
            question: Natural-language query or SQL. Named ``question`` to honor
                the universal ``AbstractBot.ask`` contract (the HTTP handler and
                every sibling bot call ``ask(question=...)``); aliased internally
                to ``query`` for the SQL-centric logic below.
            user_role: Explicit role override (highest priority).
            database: Explicit toolkit identifier.
            context: Additional context string injected into the prompt.
            output_components: Desired output components (flags or comma-separated string).
            output_format: Unused; reserved for future formatting options.
            session_id: Session identifier for memory tracking.
            user_id: User identifier.
            structured_output: Override the default ``QueryResponse`` structured output.
            output_mode: Override the default ``OutputMode.SQL_ANALYSIS`` envelope mode.
                Pass ``OutputMode.STRUCTURED_TABLE`` to route the ``QueryDataset``
                and ``QueryResponse.explanation`` through ``StructuredTableRenderer``
                instead of the SQL artifact card path.
            **kwargs: Forwarded to the LLM client.

        Returns:
            ``AIMessage`` with the formatted response and unpacked ``QueryResponse``.
        """
        # Internal alias: the parameter is named ``question`` to match the
        # universal ask() contract, but the SQL-routing logic below reads
        # ``query``.
        query = question
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

        target_toolkit = self._select_toolkit(route.target_database)

        # Infer which schemas are "active" for this turn — used both as a
        # hint in ``schema_summary`` and to scope the LLM's search calls.
        # Heuristic: qualified ``schema.table`` references in the user's
        # prompt or in the editor SQL piped via ``context``. We deliberately
        # do NOT match bare schema names (too many false positives with
        # short / common names like ``hr``, ``next``, ``apple``); when no
        # qualified ref is present the frontend is expected to surface the
        # list explicitly inside ``context`` (the LLM reads that block).
        allowed = (
            list(target_toolkit.allowed_schemas)
            if target_toolkit is not None
            else []
        )
        active_schemas = self._infer_active_schemas(query, context, allowed)

        # Build schema_summary. When the frontend pipes its own schema
        # block inside ``context`` it serves as the authoritative list;
        # this hint only adds a short focus line for the LLM. We keep it
        # empty when there's no signal — the previous behaviour ran an
        # ILIKE prefetch on the full user prompt which never matched and
        # cost a DB round-trip per turn.
        schema_summary = (
            f"Active schemas (inferred from this turn): {', '.join(active_schemas)}.\n"
            "When you need schema details, prefer these before searching other schemas."
            if active_schemas
            else ""
        )

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
            # Skip execution when the LLM returned no SQL — this is the
            # legitimate "meta-question" path (e.g. "do we have a table
            # called X?" → answer is just prose). The previous check only
            # caught ``None``; an empty/whitespace string fell through to
            # ``execute_query`` and tripped the "Empty query" safety rule,
            # emitting a misleading warning.
            if (
                qr_check is None
                or qr_check.query is None
                or not qr_check.query.strip()
                or target_toolkit is None
            ):
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
            response.data = self._materialise_query_dataset(qr.data)
            if output_mode == OutputMode.STRUCTURED_TABLE:
                # FEAT-218: caller requested STRUCTURED_TABLE.
                # response.response (qr.explanation) and response.data
                # (materialised QueryDataset) are already set above; the
                # StructuredTableRenderer will consume them deterministically.
                # We signal the mode so the formatter dispatches correctly.
                response.output_mode = OutputMode.STRUCTURED_TABLE
            else:
                # Default: signal to the HTTP layer that this AIMessage carries a
                # structured QueryResponse the frontend should render as a SQL
                # artifact card (explanation + dedicated SQL block) rather than
                # plain markdown.
                response.output_mode = OutputMode.SQL_ANALYSIS
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

    @staticmethod
    def _infer_active_schemas(
        user_query: str,
        context: Optional[str],
        allowed: List[str],
    ) -> List[str]:
        """Return the schemas most likely "active" for this turn.

        Two sources, in priority order:
          1. Qualified ``schema.table`` references in the **user prompt**.
          2. Qualified refs in the **context** string (typically the SQL
             being edited, piped by the frontend).

        Bare schema-name matching is intentionally NOT done — short
        schema names (``hr``, ``pe``, ``next``, ``apple``) collide with
        common Spanish/English words and produce false positives. The
        frontend is expected to surface a schema/table inventory inside
        ``context`` for the cases where qualified refs are absent.

        Returns an ordered, deduped list. Empty when no signal — the
        caller should fall back to the toolkit's full ``allowed_schemas``.
        """
        if not allowed:
            return []
        allowed_lower = {s.lower() for s in allowed}

        def _qualified(text: str) -> List[str]:
            if not text:
                return []
            seen: List[str] = []
            for match in _QUALIFIED_REF_RE.finditer(text):
                schema = match.group(1).lower()
                if schema in allowed_lower and schema not in seen:
                    seen.append(schema)
            return seen

        result = _qualified(user_query)
        if result:
            return result
        return _qualified(context or "")

    @staticmethod
    def _materialise_query_dataset(dataset: Any) -> Any:
        """Convert a ``QueryDataset.data`` (``PandasTable``) into a DataFrame.

        ``PandasTable`` is a Pydantic model holding ``columns`` + ``rows``;
        the previous implementation called ``dataset.data.to_dataframe()``
        but that method lives on ``PandasAgentResponse`` (the outer
        wrapper) — ``PandasTable`` itself has no ``to_dataframe``. We
        build the DataFrame inline. Returns ``None`` when there is no
        tabular payload so the caller can short-circuit.
        """
        if dataset is None:
            return None
        table = getattr(dataset, "data", None)
        if table is None:
            return None
        columns = getattr(table, "columns", None)
        rows = getattr(table, "rows", None)
        if not columns and not rows:
            return None
        # Local import keeps pandas out of the import-time cost on agents
        # that never produce tabular data.
        import pandas as pd
        return pd.DataFrame(rows or [], columns=columns or [])

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
        """Return the subset of tools relevant to ``components``.

        Collects two kinds of tools, both gated by component maps:

        1. **Pass 1 — Internal helpers** from ``_internal_toolkit`` (string
           manipulation, formatting) — returned as bound methods carrying
           ``_is_tool=True``.  Resolved via ``getattr`` against the internal
           toolkit; no prefix logic applies here (FEAT-173 will migrate
           the internal toolkit to a prefix when ready).

        2. **Pass 2 — External toolkit tools** from every registered
           ``self.toolkits[i]``.  Names in
           ``_TOOLKIT_TOOLS_BY_COMPONENT`` are *logical* (no prefix).
           Each toolkit applies its own ``tool_prefix`` at resolution time::

               full_name = f"{tk.tool_prefix}{tk.prefix_separator}{logical_name}"
               tool = tk.get_tool(full_name)

           This means a ``PostgresToolkit(tool_prefix="db")`` exposes
           ``db_search_schema``, a ``BigQueryToolkit(tool_prefix="bq")``
           exposes ``bq_search_schema``, and both surface correctly.

        **Collision handling**: when two toolkits would expose the same
        fully-qualified name, the first one wins.  A ``WARNING`` is logged
        once per ``(full_name, toolkit-pair)`` combination per agent
        lifetime (de-duplicated via ``self._logged_collisions``).  The
        message includes the current ``OutputComponent`` flag so operators
        can diagnose which component triggered the collision.

        **Legacy ``tool_prefix=None``**: toolkits that have not yet
        declared a prefix fall back to resolving by the logical name
        directly.  A one-time ``DeprecationWarning`` is emitted (tracked
        via ``self._warned_none_prefix``), pointing at FEAT-172 where the
        escape-hatch will be removed.

        Args:
            components: Active output component flags for the current request.

        Returns:
            List of tool objects accepted by ``ToolManager.register_tool``
            (mix of decorated bound methods and ``AbstractTool`` instances).
        """
        if self._internal_toolkit is None:
            return []

        tools: List[Any] = []
        seen: Set[str] = set()

        # ------------------------------------------------------------------
        # Pass 1 — internal helper tools (no prefix, getattr path)
        # ------------------------------------------------------------------
        for flag, tool_names in _INTERNAL_TOOLS_BY_COMPONENT.items():
            if flag not in components:
                continue
            for name in tool_names:
                if name in seen:
                    continue
                attr = getattr(self._internal_toolkit, name, None)
                if attr is not None and getattr(attr, "_is_tool", False):
                    tools.append(attr)
                    seen.add(name)

        # ------------------------------------------------------------------
        # Pass 2 — external toolkit tools (prefix-aware resolution)
        # ------------------------------------------------------------------
        # first_owner tracks which toolkit first exposed a given full_name,
        # used to construct informative collision-warning messages.
        first_owner: Dict[str, Any] = {}

        for component in OutputComponent:
            if component not in components:
                continue
            logical_names = _TOOLKIT_TOOLS_BY_COMPONENT.get(component, set())
            for logical_name in logical_names:
                for tk in self.toolkits:
                    get_tool = getattr(tk, "get_tool", None)
                    if get_tool is None:
                        continue

                    # Build the fully-qualified tool name, honouring each
                    # toolkit's declared prefix and separator.
                    if tk.tool_prefix is None:
                        if id(tk) not in self._warned_none_prefix:
                            self._warned_none_prefix.add(id(tk))
                            warnings.warn(
                                f"{type(tk).__name__} has tool_prefix=None; "
                                f"resolving tools by logical name. This is a "
                                f"transitional escape hatch and will be "
                                f"rejected at configure() time once "
                                f"FEAT-172 ships.",
                                DeprecationWarning,
                                stacklevel=2,
                            )
                        full_name = logical_name
                    else:
                        full_name = (
                            f"{tk.tool_prefix}"
                            f"{tk.prefix_separator}"
                            f"{logical_name}"
                        )

                    tk_tool = get_tool(full_name)
                    if tk_tool is None:
                        continue

                    if full_name in seen:
                        owner_cls = type(first_owner[full_name]).__name__
                        this_cls = type(tk).__name__
                        key: Tuple[str, FrozenSet[str]] = (
                            full_name,
                            frozenset({owner_cls, this_cls}),
                        )
                        if key not in self._logged_collisions:
                            self._logged_collisions.add(key)
                            self.logger.warning(
                                "Toolkit tool name collision: %r already "
                                "exposed by %s; skipping duplicate from %s "
                                "(component=%s). Toolkit order in "
                                "self.toolkits determines first-wins; "
                                "reorder if needed. "
                                "This should have been caught at configure() time "
                                "— please file a bug.",
                                full_name,
                                owner_cls,
                                this_cls,
                                component.name,
                            )
                        continue

                    tools.append(tk_tool)
                    seen.add(full_name)
                    first_owner[full_name] = tk

        return tools
