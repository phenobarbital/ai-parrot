---
id: F005
query_id: Q005
type: grep
intent: Verify KnowledgeRouter (FEAT-200) exists with deterministic vocabulary + embedding fallback and namespaced concept_id
executed_at: 2026-08-23T00:21:23Z
depth: 0
parent_id: null
---

# F005 — No "KnowledgeRouter" symbol exists; the real router is IntentRouterMixin, and the ontology resolver it replaced is soft-deprecated

## Summary

There is no class named `KnowledgeRouter` anywhere in the repo. The capability the source
attributes to it exists under two other names. `OntologyIntentResolver`
(`knowledge/ontology/intent.py`) implements exactly the described dual-path shape — a ~0ms
keyword fast path against `trigger_intents` plus an LLM/structured-output path for ambiguous
queries — but its module docstring **soft-deprecates** it in favour of
`parrot.bots.mixins.intent_router.IntentRouterMixin`, which does unified routing across
datasets, tools, vector stores and graph sources. `ResolvedIntent` is the output contract
(`action: graph_query|vector_only`, `aql`, `params`, `collection_binds`, `source`), close to
but not the same as the source's proposed `RoutingDecision`.

## Citations

- path: `packages/ai-parrot/src/parrot/knowledge/ontology/intent.py`
  lines: 1-14
  symbol: `OntologyIntentResolver`
  excerpt: |
    """Dual-path intent resolution for ontology graph RAG.

    Resolves user queries into graph traversal intents using two paths:
        - Fast path (~0ms): keyword scan against trigger_intents.
        - LLM path (~200-800ms): structured output for ambiguous queries.

    .. deprecated::
        OntologyIntentResolver is soft-deprecated in favour of
        IntentRouterMixin, which provides unified routing across
        datasets, tools, vector stores, and graph sources.

- path: `packages/ai-parrot/src/parrot/bots/mixins/intent_router.py`
  lines: 1-20, 123
  symbol: `IntentRouterMixin`
  excerpt: |
    """IntentRouterMixin — pre-RAG query routing for AI-Parrot bots.

    Intercepts conversation() calls and routes the user query to the most
    appropriate strategy (dataset query, vector search, tool call, graph
    traversal, free LLM, etc.) before delegating to the base conversation().
    MRO note: IntentRouterMixin MUST appear before the concrete bot class.

- path: `packages/ai-parrot/src/parrot/knowledge/ontology/schema.py`
  lines: 424-456
  symbol: `ResolvedIntent`
  excerpt: |
    action: Literal["graph_query", "vector_only"]
    pattern: str | None = None
    aql: str | None = None
    collection_binds: dict[str, str] = Field(default_factory=dict)
    source: str = "none"

- path: `packages/ai-parrot/src/parrot/knowledge/ontology/concept_catalog/http.py`
  symbol: concept catalog
  excerpt: |
    Concept Catalog HTTP Routes (FEAT-159 TASK-1092).

## Notes

The source's §4.1 is architecturally right but names a symbol that does not exist. Any spec
must retarget it to IntentRouterMixin and must not build on the deprecated resolver.
