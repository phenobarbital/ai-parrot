"""OntologyRAGMixin — agent mixin for ontological graph RAG.

Agents opt-in to ontology-enriched RAG by inheriting this mixin.
The mixin hooks into the agent's ask() flow, intercepting queries
before standard RAG processing to enrich context with structural
graph data.

Usage::

    class MyAgent(OntologyRAGMixin, BasicAgent):
        pass

Return Type
-----------
``ontology_process`` now returns a ``ContextEnvelope`` wrapping an optional
``EnrichedContext``. Callers must read ``result.context`` instead of accessing
``EnrichedContext`` fields directly.  The full state set is:

- ``"ok"``               — happy path; ``result.context`` is populated.
- ``"ambiguous"``        — entity resolver found multiple candidates;
                           ``result.clarification`` carries ``rule``, ``mention``,
                           and ``candidates`` for the chat layer to ask the user.
- ``"entity_not_found"`` — resolver found no match for a required rule.
- ``"denied"``           — ``AuthorizationChecker`` denied the request;
                           ``result.denial_reason`` describes why.
- ``"auth_required"``    — ``ToolCallDispatcher`` raised
                           ``AuthorizationRequired``; ``result.auth_prompt``
                           contains ``auth_url``, ``provider``, and ``scopes``.
- ``"render_error"``     — Jinja2 template rendering failed; ``result.error``
                           has the diagnostic message.
- ``"vector_only"``      — returned as an ``ok``-ish fallback when graph
                           processing is skipped (no pattern match, graph
                           unavailable, etc.).
- ``"disabled"``         — ontology RAG is globally disabled.
- ``"not_configured"``   — ``tenant_manager`` was not provided to the mixin.

AQL Bind-Key Convention
-----------------------
When entity extraction resolves a rule named ``target_employee``, the
resolved ``_id`` is injected into ``intent.params`` under the key
``target_employee_id`` (rule name + ``"_id"`` suffix).  Pattern authors must
declare their AQL ``@target_employee_id`` bind parameter accordingly.

4-Level Degradation Chain (FEAT-159)
-------------------------------------
For the ``authoritative_doc_for_topic`` pattern the traversal section runs a
4-level degradation chain.  For all other patterns only levels 3-4 (vector
fallback) are added on top of the existing single-traversal logic.

``context.source`` values produced by the chain:

- ``"graph:primary"``   — primary-authority graph traversal succeeded.
- ``"graph:secondary"`` — secondary-authority graph traversal succeeded.
- ``"vector:filtered"`` — similarity_search with doc_type filter succeeded.
- ``"vector:plain"``    — unfiltered similarity_search succeeded.
- ``"ontology"``        — normal (non-authority) graph traversal succeeded.
- ``"vector_only"``     — all graph paths were empty/unavailable; falls back
                          to vector store without graph context.
"""
from __future__ import annotations

import logging
from typing import Any

from parrot.auth.exceptions import AuthorizationRequired

from .authorization import AuthorizationChecker
from .cache import OntologyCache
from .entity_resolver import EntityAmbiguityError, EntityNotFoundError, EntityResolver
from .graph_store import OntologyGraphStore
from .intent import OntologyIntentResolver
from .schema import ContextEnvelope, EnrichedContext, ResolvedIntent
from .tenant import TenantOntologyManager
from .tool_dispatcher import RenderError, ToolCallDispatcher

logger = logging.getLogger("Parrot.Ontology.Mixin")


class OntologyRAGMixin:
    """Mixin that adds Ontological Graph RAG capabilities to any agent.

    The mixin orchestrates the full ontology pipeline:

        1. Resolve tenant → merged ontology.
        2. Resolve intent (fast path or LLM path).
        3. **[NEW]** Extract + resolve named entities from the query.
        4. **[NEW]** Evaluate declarative authorization rules.
        5. Execute graph traversal if needed (existing).
        6. Apply post-action (vector_search, tool_call, or none).
        7. Cache the result.

    Graceful degradation: if ArangoDB is unavailable, logs a warning
    and returns ``ContextEnvelope(state="ok", context=EnrichedContext(source="vector_only"))``
    without raising.

    Args:
        tenant_manager: TenantOntologyManager instance.
        graph_store: OntologyGraphStore instance.
        vector_store: Existing PgVector store for post-action vector search.
        cache: OntologyCache instance (Redis-backed).
        llm_client: LLM client for intent resolver's LLM path.
        tool_manager: ToolManager instance for ToolCallDispatcher resolution.
    """

    def __init__(
        self,
        tenant_manager: TenantOntologyManager | None = None,
        graph_store: OntologyGraphStore | None = None,
        vector_store: Any = None,
        cache: OntologyCache | None = None,
        llm_client: Any = None,
        tool_manager: Any = None,
        **kwargs: Any,
    ) -> None:
        # Pass remaining kwargs to next class in MRO (cooperative inheritance)
        super().__init__(**kwargs)
        self._ont_tenant_manager = tenant_manager
        self._ont_graph_store = graph_store
        self._ont_vector_store = vector_store
        self._ont_cache = cache or OntologyCache()
        self._ont_llm_client = llm_client
        self._ont_tool_manager = tool_manager

    # ------------------------------------------------------------------
    # Public hook — concrete agents override to surface session data
    # ------------------------------------------------------------------

    def _get_permission_context(self) -> dict[str, Any]:
        """Return the current session's permission context as a plain dict.

        Default returns an empty dict.  Concrete agents should override this
        to surface ``user_id``, ``channel``, ``department``, ``roles``,
        ``manager_id``, etc. so that ``AuthorizationChecker`` rules have
        access to the full session.

        Returns:
            A dict conforming to the ``user_context`` shape expected by
            ``EntityResolver``, ``AuthorizationChecker``, and
            ``ToolCallDispatcher``.
        """
        return {}

    # ------------------------------------------------------------------
    # Main pipeline
    # ------------------------------------------------------------------

    async def ontology_process(
        self,
        query: str,
        user_context: dict[str, Any],
        tenant_id: str,
        domain: str | None = None,
    ) -> ContextEnvelope:
        """Process a query through the ontology pipeline.

        Merges ``user_context`` with ``_get_permission_context()`` so that
        agent subclasses can inject extra session data without modifying the
        call site.

        AQL Bind-Key Convention:
            For each resolved entity rule ``rule_name``, the resolved
            ``_id`` is bound into ``intent.params`` as
            ``intent.params["{rule_name}_id"]``.  Pattern YAML must declare
            the AQL placeholder accordingly, e.g.::

                FILTER e._id == @target_employee_id

        Args:
            query: The user's natural language query.
            user_context: Session data (user_id, channel, roles, …).
            tenant_id: Tenant identifier.
            domain: Optional domain for ontology resolution.

        Returns:
            ContextEnvelope describing the pipeline outcome. Always one of:
            ``"ok"``, ``"ambiguous"``, ``"entity_not_found"``, ``"denied"``,
            ``"auth_required"``, ``"render_error"``, ``"vector_only"``,
            ``"disabled"``, or ``"not_configured"``.
        """
        # Merge permission context (subclass hook) into user_context
        pctx = self._get_permission_context()
        # NOTE: user_context wins on conflict intentionally — callers supply
        # request-scoped overrides (e.g. impersonation) that must take precedence
        # over the session hook's defaults. Security-sensitive fields (roles, tenant_id)
        # are validated downstream by AuthorizationChecker, not here.
        merged_ctx: dict[str, Any] = {**pctx, **user_context}

        # Check global enable flag
        if not self._is_ontology_enabled():
            return ContextEnvelope(state="disabled")

        if not self._ont_tenant_manager:
            logger.warning("OntologyRAGMixin: no tenant_manager configured")
            return ContextEnvelope(state="not_configured")

        # 1. Resolve tenant
        try:
            tenant_ctx = self._ont_tenant_manager.resolve(
                tenant_id, domain=domain,
            )
        except FileNotFoundError as e:
            logger.warning("Ontology not found for tenant '%s': %s", tenant_id, e)
            return ContextEnvelope(
                state="ok",
                context=EnrichedContext(source="vector_only"),
            )

        # 2. Resolve intent
        resolver = OntologyIntentResolver(
            ontology=tenant_ctx.ontology,
            llm_client=self._ont_llm_client,
        )
        try:
            intent = await resolver.resolve(query, merged_ctx)
        except Exception as e:
            logger.warning("Intent resolution failed: %s", e)
            return ContextEnvelope(
                state="ok",
                context=EnrichedContext(source="vector_only"),
            )

        if intent.action == "vector_only":
            return ContextEnvelope(
                state="ok",
                context=EnrichedContext(source="vector_only", intent=intent),
            )

        # Retrieve the matched TraversalPattern
        pattern = tenant_ctx.ontology.traversal_patterns.get(intent.pattern or "")

        # 3. Entity extraction (if the pattern declares entity_extraction rules)
        resolved_entities: dict[str, str] = {}
        if pattern is not None and pattern.entity_extraction:
            entity_resolver = EntityResolver(
                graph_store=self._ont_graph_store,
                ontology=tenant_ctx.ontology,
                llm_client=self._ont_llm_client,
                vector_store=self._ont_vector_store,        # required for hybrid stage 2
                concept_instances=list(                     # required for hybrid stage 1
                    getattr(
                        tenant_ctx.ontology.entities.get("Concept"),
                        "instances", None,
                    ) or []
                ),
            )
            try:
                resolved_entities = await entity_resolver.extract_and_resolve(
                    pattern, query, merged_ctx, tenant_id,
                )
            except EntityAmbiguityError as exc:
                logger.info(
                    "Ontology pipeline: ambiguous entity rule=%s mention=%s "
                    "candidates=%d tenant=%s",
                    exc.rule_name, exc.mention, len(exc.candidates), tenant_id,
                )
                return ContextEnvelope(
                    state="ambiguous",
                    clarification={
                        "rule": exc.rule_name,
                        "mention": exc.mention,
                        "candidates": exc.candidates,
                    },
                )
            except EntityNotFoundError as exc:
                logger.info(
                    "Ontology pipeline: entity_not_found rule=%s tenant=%s",
                    exc.rule_name, tenant_id,
                )
                return ContextEnvelope(
                    state="entity_not_found",
                    error=f"{exc.rule_name} not found",
                )
            # Bind resolved IDs into AQL params using the
            # "{rule_name}_id" convention so pattern YAML can reference
            # @target_employee_id etc.
            for rule_name, _id in resolved_entities.items():
                intent.params[f"{rule_name}_id"] = _id

        # 4. Authorization check
        if pattern is not None and pattern.authorization is not None:
            auth_checker = AuthorizationChecker(graph_store=self._ont_graph_store)
            allowed, reason = await auth_checker.check(
                pattern.authorization, merged_ctx, resolved_entities, tenant_id,
            )
            if not allowed:
                logger.info(
                    "Ontology pipeline: denied reason=%r tenant=%s user=%s",
                    reason, tenant_id, merged_ctx.get("user_id"),
                )
                return ContextEnvelope(state="denied", denial_reason=reason)

        # 5. Check cache (uses resolved_entities for key isolation)
        user_id = merged_ctx.get("user_id", "anonymous")
        pattern_name = intent.pattern or "unknown"
        cache_key = OntologyCache.build_key(
            tenant_id, user_id, pattern_name,
            resolved_entities=resolved_entities,
        )

        cached = await self._ont_cache.get(cache_key)
        if cached is not None:
            logger.debug("Cache hit for %s", cache_key)
            return ContextEnvelope(state="ok", context=cached)

        # 6. Execute graph traversal — 4-level degradation chain (FEAT-159)
        #
        # For the ``authoritative_doc_for_topic`` pattern we run a 2-step
        # authority traversal (primary → secondary) before falling back to
        # vector RAG.  All other patterns keep the existing single-traversal
        # behaviour and then fall through to the vector fallback levels.
        if not self._ont_graph_store:
            logger.warning("OntologyRAGMixin: no graph_store configured")
            # Skip straight to vector levels (3 & 4)
            graph_result = None
            graph_source = None
        else:
            is_authority_pattern = (intent.pattern == "authoritative_doc_for_topic")
            graph_result = None
            graph_source = None

            if is_authority_pattern:
                # Level 1 — primary authority traversal
                primary_params = {**intent.params, "authority_level": "primary"}
                try:
                    primary_result = await self._ont_graph_store.execute_traversal(
                        ctx=tenant_ctx,
                        aql=intent.aql,
                        bind_vars=primary_params,
                        collection_binds=intent.collection_binds,
                    )
                    if primary_result:
                        graph_result = primary_result
                        graph_source = "graph:primary"
                        logger.debug(
                            "Degradation Level 1 hit (primary): tenant=%s pattern=%s rows=%d",
                            tenant_id, intent.pattern, len(graph_result),
                        )
                except Exception as exc:
                    logger.warning(
                        "Level 1 (primary) traversal failed, trying secondary: %s", exc,
                    )

                if not graph_result:
                    # Level 2 — secondary authority traversal
                    secondary_params = {**intent.params, "authority_level": "secondary"}
                    try:
                        secondary_result = await self._ont_graph_store.execute_traversal(
                            ctx=tenant_ctx,
                            aql=intent.aql,
                            bind_vars=secondary_params,
                            collection_binds=intent.collection_binds,
                        )
                        if secondary_result:
                            graph_result = secondary_result
                            graph_source = "graph:secondary"
                            logger.debug(
                                "Degradation Level 2 hit (secondary): tenant=%s pattern=%s rows=%d",
                                tenant_id, intent.pattern, len(graph_result),
                            )
                    except Exception as exc:
                        logger.warning(
                            "Level 2 (secondary) traversal failed, degrading to vector: %s", exc,
                        )
            else:
                # Standard single traversal for non-authority patterns
                try:
                    single_result = await self._ont_graph_store.execute_traversal(
                        ctx=tenant_ctx,
                        aql=intent.aql,
                        bind_vars=intent.params,
                        collection_binds=intent.collection_binds,
                    )
                    if single_result:
                        graph_result = single_result
                        graph_source = "ontology"
                except Exception as exc:
                    logger.warning(
                        "Graph traversal failed (degrading to vector_only): %s", exc,
                    )

        # If we have graph results, proceed to post-action and tool dispatch
        if graph_result and graph_source:
            return await self._build_and_dispatch(
                query=query,
                intent=intent,
                pattern=pattern,
                tenant_id=tenant_id,
                tenant_ctx=tenant_ctx,
                merged_ctx=merged_ctx,
                graph_result=graph_result,
                graph_source=graph_source,
                cache_key=cache_key,
            )

        # Level 3 — filtered vector RAG (policy/manual doc_type filter)
        if self._ont_vector_store is not None:
            try:
                filtered_results = await self._ont_vector_store.similarity_search(
                    query=query,
                    metadata_filters={"doc_type": ["policy", "manual"]},
                )
                if filtered_results:
                    logger.debug(
                        "Degradation Level 3 hit (vector:filtered): tenant=%s pattern=%s rows=%d",
                        tenant_id, intent.pattern, len(filtered_results),
                    )
                    enriched = EnrichedContext(
                        source="vector:filtered",
                        vector_context=filtered_results,
                        intent=intent,
                        metadata={
                            "pattern": intent.pattern,
                            "source": intent.source,
                            "tenant": tenant_id,
                        },
                    )
                    await self._ont_cache.set(cache_key, enriched)
                    return ContextEnvelope(state="ok", context=enriched)
            except Exception as exc:
                logger.warning("Level 3 (vector:filtered) search failed: %s", exc)

            # Level 4 — plain vector RAG (no filter)
            try:
                plain_results = await self._ont_vector_store.similarity_search(query=query)
                if plain_results:
                    logger.debug(
                        "Degradation Level 4 hit (vector:plain): tenant=%s pattern=%s rows=%d",
                        tenant_id, intent.pattern, len(plain_results),
                    )
                    enriched = EnrichedContext(
                        source="vector:plain",
                        vector_context=plain_results,
                        intent=intent,
                        metadata={
                            "pattern": intent.pattern,
                            "source": intent.source,
                            "tenant": tenant_id,
                        },
                    )
                    await self._ont_cache.set(cache_key, enriched)
                    return ContextEnvelope(state="ok", context=enriched)
            except Exception as exc:
                logger.warning("Level 4 (vector:plain) search failed: %s", exc)

        # All levels exhausted — return vector_only shell
        logger.info(
            "All degradation levels exhausted: tenant='%s', pattern='%s'",
            tenant_id, intent.pattern,
        )
        return ContextEnvelope(
            state="ok",
            context=EnrichedContext(source="vector_only", intent=intent),
        )

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    async def _build_and_dispatch(
        self,
        *,
        query: str,
        intent: Any,
        pattern: Any,
        tenant_id: str,
        tenant_ctx: Any,
        merged_ctx: dict[str, Any],
        graph_result: list[dict[str, Any]],
        graph_source: str,
        cache_key: str,
    ) -> ContextEnvelope:
        """Build EnrichedContext and dispatch tool call (if configured).

        Extracted from the main pipeline to be shared between normal-traversal
        and degradation-chain code paths.

        Args:
            query: Original user query (used for vector fallback context).
            intent: Resolved intent from the pipeline.
            pattern: Matched TraversalPattern (may be None).
            tenant_id: Tenant identifier for logging.
            tenant_ctx: Full TenantContext including pgvector schema.
            merged_ctx: Merged user/permission context dict.
            graph_result: Non-empty list of rows from graph traversal.
            graph_source: Provenance label (``"graph:primary"``,
                ``"graph:secondary"``, or ``"ontology"``).
            cache_key: Redis key for caching the result.

        Returns:
            ContextEnvelope with state="ok" on success, or an error envelope
            (auth_required, render_error, tool_failed) if tool dispatch fails.
        """
        # Post-action routing
        vector_result = None
        tool_hint = None

        if intent.post_action == "vector_search" and graph_result:
            vector_result = await self._do_vector_search(
                graph_result, intent, tenant_ctx.pgvector_schema,
            )
        elif intent.post_action == "tool_call" and graph_result:
            # Only build a lightweight hint if there is no full ToolCallSpec.
            # When pattern.tool_call is set, the dispatcher below produces the
            # richer tool_result.
            if pattern is None or pattern.tool_call is None:
                tool_hint = self._build_tool_hint(graph_result)

        # Build enriched context
        enriched = EnrichedContext(
            source=graph_source,
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

        # Tool dispatch (if pattern carries an explicit ToolCallSpec)
        tool_result: dict[str, Any] | None = None
        if intent.post_action == "tool_call" and pattern is not None and pattern.tool_call is not None:
            if self._ont_tool_manager is None:
                logger.warning(
                    "OntologyRAGMixin: tool_call post-action requested but "
                    "no tool_manager configured; falling back to tool_hint"
                )
            else:
                dispatcher = ToolCallDispatcher(tool_manager=self._ont_tool_manager)
                try:
                    tool_result = await dispatcher.dispatch(
                        pattern.tool_call, graph_result, merged_ctx,
                    )
                except AuthorizationRequired as exc:
                    logger.info(
                        "Ontology pipeline: auth_required provider=%s tenant=%s",
                        exc.provider, tenant_id,
                    )
                    return ContextEnvelope(
                        state="auth_required",
                        auth_prompt={
                            "auth_url": exc.auth_url,
                            "provider": exc.provider,
                            "scopes": list(exc.scopes or []),
                        },
                    )
                except RenderError as exc:
                    logger.warning(
                        "Ontology pipeline: render_error field=%s tenant=%s: %s",
                        exc.field, tenant_id, exc.message,
                    )
                    return ContextEnvelope(state="render_error", error=str(exc))
                except Exception as exc:
                    logger.warning(
                        "Ontology: tool_failed tenant=%s: %s", tenant_id, exc
                    )
                    return ContextEnvelope(state="tool_failed", error=str(exc))

        # Cache the enriched context
        await self._ont_cache.set(cache_key, enriched)

        logger.info(
            "Ontology pipeline complete: tenant='%s', pattern='%s', "
            "graph_results=%d, source='%s', tool_result=%s",
            tenant_id, intent.pattern,
            len(graph_result) if graph_result else 0,
            graph_source,
            bool(tool_result),
        )
        return ContextEnvelope(state="ok", context=enriched, tool_result=tool_result)

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
