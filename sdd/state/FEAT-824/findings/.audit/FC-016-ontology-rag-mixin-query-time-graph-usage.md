---
id: FC-016
query_id: Q016
type: read
intent: "How does the ontology RAG mixin use the graph store at query time (traversal, degradation to vector-only)?"
executed_at: 2026-11-06T13:49:00Z
duration_ms: 0
parent_id: null
depth: 0
---

# FC-016 — At query time the mixin needs exactly two store calls (`execute_pattern`, `execute_query`) and already degrades to vector-only when the graph is unavailable

## Summary

`OntologyRAGMixin` holds an injected `OntologyTraversalStore` (`self._ont_graph_store`), resolves the store's `dialect` (default `"aql"`), and runs every graph step through one helper, `_run_graph_query`: matched patterns go to `execute_pattern(tenant_ctx, pattern, params, intent.collection_binds)` "so every backend picks its own template"; dynamic LLM intents go to `execute_query(tenant_ctx, DynamicQuery(dialect=intent.dialect, text=intent.query, ...))`. Around it sits a **4-level degradation chain** (FEAT-159: primary traversal → secondary traversal → filtered vector search → plain vector search → `source="vector_only"` shell), and the class docstring states "if ArangoDB is unavailable, logs a warning and returns ... `vector_only`". Vector search goes to the tenant's `pgvector_schema`. So the query path is already insulated from the graph engine at the *call* level; what binds it to ArangoDB is the **content** it passes through (AQL templates, `collection_binds`, `_id`-shaped bind values — FC-004), not the API.

## Citations

- path: `packages/ai-parrot/src/parrot/knowledge/ontology/mixin.py`
  lines: 509-545
  symbol: `OntologyRAGMixin._run_graph_query`
  excerpt: |
    if pattern is not None:
        return await self._ont_graph_store.execute_pattern(
            tenant_ctx, pattern, params, intent.collection_binds,
        )
    return await self._ont_graph_store.execute_query(
        tenant_ctx,
        DynamicQuery(dialect=intent.dialect, text=intent.query or "", bind_vars=params,
                     collection_binds=intent.collection_binds),
    )

- path: `packages/ai-parrot/src/parrot/knowledge/ontology/mixin.py`
  lines: 494-503
  symbol: degradation-chain terminal state
  excerpt: |
    # All levels exhausted — return vector_only shell
    logger.info("All degradation levels exhausted: tenant='%s', pattern='%s'", tenant_id, intent.pattern)
    return ContextEnvelope(
        state="ok",
        context=EnrichedContext(source="vector_only", intent=intent),
    )

- path: `packages/ai-parrot/src/parrot/knowledge/ontology/mixin.py`
  lines: 103-134
  symbol: `OntologyRAGMixin.__init__` (graph_store injection)
  excerpt: |
    103:    Graceful degradation: if ArangoDB is unavailable, logs a warning
    104:    and returns ``ContextEnvelope(state="ok", context=EnrichedContext(source="vector_only"))``
    124:        graph_store: OntologyTraversalStore | None = None,
    134:        self._ont_graph_store = graph_store

- path: `packages/ai-parrot/src/parrot/knowledge/ontology/mixin.py`
  lines: 164-166
  symbol: dialect resolution
  excerpt: |
    164:        """Return the query dialect of the configured graph store (default ``aql``)."""
    166:        return dialect if isinstance(dialect, str) and dialect else "aql"

- path: `packages/ai-parrot/src/parrot/knowledge/ontology/mixin.py`
  lines: 343-422
  symbol: 4-level degradation chain
  excerpt: |
    343:        # 6. Execute graph traversal — 4-level degradation chain (FEAT-159)
    405:                            "Level 2 (secondary) traversal failed, degrading to vector: %s",
    422:                        "Graph traversal failed (degrading to vector_only): %s",

- path: `packages/ai-parrot/src/parrot/knowledge/ontology/mixin.py`
  lines: 589-694
  symbol: pgvector search on the tenant schema
  excerpt: |
    589:                tenant_ctx.pgvector_schema,
    671:        pgvector_schema: str,
    694:                schema=pgvector_schema,

## Notes

- Only L490-549 was read in full; the other line references come from `grep -nE "vector_only|_ont_graph_store *=|degrad|pgvector_schema"` on the file (758 lines).
- The mixin header (L37-42, L181-185) documents an "AQL Bind-Key Convention" (`@target_employee_id` style) tying entity-extraction rule names to AQL bind parameters.
- The draft's retrieval flow (§6: `resolve` → `expand` → `KnowledgeStore.search` with IRI filter) is a *different pipeline* from this one (intent → pattern/dynamic query → traversal rows → post_action vector search / tool call, with authorization specs). The draft does not say whether `OntologyRAGMixin`'s traversal-pattern pipeline is kept, re-targeted to another dialect, or retired.
- The other two `OntologyTraversalStore` consumers (FC-003): `authorization.py` (L224 "bounded OUTBOUND traversal along `reports_to` edges" → `is_reachable`) and `entity_resolver.py` (`find_by_field` / `search_by_name` presumably — not opened).
