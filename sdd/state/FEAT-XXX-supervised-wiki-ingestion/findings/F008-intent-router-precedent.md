# F008 — `IntentRouterMixin`: in-repo precedent for cascade routing

- `packages/ai-parrot/src/parrot/bots/mixins/intent_router.py:1-60` —
  pre-RAG router that intercepts queries and routes them; uses a
  `_KEYWORD_STRATEGY_MAP` fast path (:59) before any LLM call, LLM fallback
  after, plus `RoutingDecision`/`RoutingTrace` models from
  `parrot.registry.capabilities.models`.
- It routes *queries*, not *documents*, so it is a **pattern** to mirror
  (cheap-first cascade, typed decision + trace), not a component to reuse
  directly. Naming the new component `IngestTriageRouter` avoids confusion.

Method: read of module header + grep.
