"""OntologyRAGMixin — agent mixin for ontological graph RAG.

Agents opt-in to ontology-enriched RAG by inheriting this mixin.
The mixin hooks into the agent's ask() flow, intercepting queries
before standard RAG processing to enrich context with structural
graph data.

Usage::

    class MyAgent(OntologyRAGMixin, BasicAgent):
        pass
"""
from __future__ import annotations

import logging
from typing import Any

from .cache import OntologyCache
from .graph_store import OntologyGraphStore
from .intent import OntologyIntentResolver
from .schema import EnrichedContext, ResolvedIntent
from .tenant import TenantOntologyManager

logger = logging.getLogger("Parrot.Ontology.Mixin")


class OntologyRAGMixin:
    """Mixin that adds Ontological Graph RAG capabilities to any agent.

    The mixin orchestrates the full ontology pipeline:
        1. Resolve tenant → merged ontology.
        2. Resolve intent (fast path or LLM path).
        3. Execute graph traversal if needed.
        4. Apply post-action (vector_search, tool_call, or none).
        5. Cache the result.

    Graceful degradation: if ArangoDB is unavailable, logs a warning
    and returns vector_only without raising.

    Args:
        tenant_manager: TenantOntologyManager instance.
        graph_store: OntologyGraphStore instance.
        vector_store: Existing PgVector store for post-action vector search.
        cache: OntologyCache instance (Redis-backed).
        llm_client: LLM client for intent resolver's LLM path.
    """

    def __init__(
        self,
        tenant_manager: TenantOntologyManager | None = None,
        graph_store: OntologyGraphStore | None = None,
        vector_store: Any = None,
        cache: OntologyCache | None = None,
        llm_client: Any = None,
        **kwargs: Any,
    ) -> None:
        # Pass remaining kwargs to next class in MRO (cooperative inheritance)
        super().__init__(**kwargs)
        self._ont_tenant_manager = tenant_manager
        self._ont_graph_store = graph_store
        self._ont_vector_store = vector_store
        self._ont_cache = cache or OntologyCache()
        self._ont_llm_client = llm_client

    async def ontology_process(
        self,
        query: str,
        user_context: dict[str, Any],
        tenant_id: str,
        domain: str | None = None,
    ) -> EnrichedContext:
        """Process a query through the ontology pipeline.

        Args:
            query: The user's natural language query.
            user_context: Session data (user_id, etc.).
            tenant_id: Tenant identifier.
            domain: Optional domain for ontology resolution.

        Returns:
            EnrichedContext with graph + vector + tool hint data.
        """
        # Check global enable flag
        if not self._is_ontology_enabled():
            return EnrichedContext(source="disabled")

        if not self._ont_tenant_manager:
            logger.warning("OntologyRAGMixin: no tenant_manager configured")
            return EnrichedContext(source="not_configured")

        # 1. Resolve tenant
        try:
            tenant_ctx = self._ont_tenant_manager.resolve(
                tenant_id, domain=domain,
            )
        except FileNotFoundError as e:
            logger.warning("Ontology not found for tenant '%s': %s", tenant_id, e)
            return EnrichedContext(source="vector_only")

        # 2. Resolve intent
        resolver = OntologyIntentResolver(
            ontology=tenant_ctx.ontology,
            llm_client=self._ont_llm_client,
        )
        try:
            intent = await resolver.resolve(query, user_context)
        except Exception as e:
            logger.warning("Intent resolution failed: %s", e)
            return EnrichedContext(source="vector_only")

        if intent.action == "vector_only":
            return EnrichedContext(source="vector_only", intent=intent)

        # 3. Check cache
        user_id = user_context.get("user_id", "anonymous")
        pattern_name = intent.pattern or "unknown"
        cache_key = OntologyCache.build_key(tenant_id, user_id, pattern_name)

        cached = await self._ont_cache.get(cache_key)
        if cached is not None:
            logger.debug("Cache hit for %s", cache_key)
            return cached

        # 4. Execute graph traversal
        if not self._ont_graph_store:
            logger.warning("OntologyRAGMixin: no graph_store configured")
            return EnrichedContext(source="vector_only", intent=intent)

        try:
            graph_result = await self._ont_graph_store.execute_traversal(
                ctx=tenant_ctx,
                aql=intent.aql,
                bind_vars=intent.params,
                collection_binds=intent.collection_binds,
            )
        except Exception as e:
            logger.warning(
                "Graph traversal failed (degrading to vector_only): %s", e,
            )
            return EnrichedContext(source="vector_only", intent=intent)

        # 5. Post-action routing
        vector_result = None
        tool_hint = None

        if intent.post_action == "vector_search" and graph_result:
            vector_result = await self._do_vector_search(
                graph_result, intent, tenant_ctx.pgvector_schema,
            )
        elif intent.post_action == "tool_call" and graph_result:
            tool_hint = self._build_tool_hint(graph_result)

        # 6. Build enriched context
        enriched = EnrichedContext(
            source="ontology",
            graph_context=graph_result,
            vector_context=vector_result,
            tool_hint=tool_hint,
            intent=intent,
            metadata={
                "pattern": intent.pattern,
                "source": intent.source,
                "tenant": tenant_id,
            },
        )

        # 7. Cache the result
        await self._ont_cache.set(cache_key, enriched)

        logger.info(
            "Ontology pipeline complete: tenant='%s', pattern='%s', "
            "graph_results=%d, source='%s'",
            tenant_id, intent.pattern,
            len(graph_result) if graph_result else 0,
            intent.source,
        )
        return enriched

    async def _do_vector_search(
        self,
        graph_result: list[dict[str, Any]],
        intent: ResolvedIntent,
        pgvector_schema: str,
    ) -> list[dict[str, Any]] | None:
        """Execute post-action vector search using graph context.

        Args:
            graph_result: Results from graph traversal.
            intent: Resolved intent with post_query field.
            pgvector_schema: PgVector schema for this tenant.

        Returns:
            Vector search results, or None.
        """
        if not self._ont_vector_store:
            return None

        # Extract search query from graph result
        search_query = self._extract_post_query(graph_result, intent.post_query)
        if not search_query:
            return None

        try:
            results = await self._ont_vector_store.search(
                query=search_query,
                schema=pgvector_schema,
            )
            return results if isinstance(results, list) else [results]
        except Exception as e:
            logger.warning("Post-action vector search failed: %s", e)
            return None

    @staticmethod
    def _extract_post_query(
        graph_result: list[dict[str, Any]],
        post_query_field: str | None,
    ) -> str | None:
        """Extract a search query string from graph traversal results.

        Args:
            graph_result: List of result dicts from traversal.
            post_query_field: Field name to extract from results.

        Returns:
            Extracted string value, or None.
        """
        if not post_query_field or not graph_result:
            return None
        for result in graph_result:
            val = result.get(post_query_field)
            if val:
                return str(val)
        return None

    @staticmethod
    def _build_tool_hint(graph_result: list[dict[str, Any]]) -> str:
        """Build a tool execution hint from graph context.

        Args:
            graph_result: Results from graph traversal.

        Returns:
            Hint string for the agent's tool manager.
        """
        summary_parts = []
        for r in graph_result[:5]:  # Limit to 5 items
            if isinstance(r, dict):
                # Pick the most informative fields
                name = r.get("name", r.get("_key", ""))
                if name:
                    summary_parts.append(str(name))
        summary = ", ".join(summary_parts) if summary_parts else "graph data available"
        return (
            f"Graph context is available. The user is associated with: "
            f"{summary}. Use available tools to enrich the response."
        )

    @staticmethod
    def _is_ontology_enabled() -> bool:
        """Check if ontology RAG is globally enabled.

        Returns:
            True if ENABLE_ONTOLOGY_RAG is True.
        """
        try:
            from parrot.conf import ENABLE_ONTOLOGY_RAG
            return bool(ENABLE_ONTOLOGY_RAG)
        except (ImportError, AttributeError):
            return False
