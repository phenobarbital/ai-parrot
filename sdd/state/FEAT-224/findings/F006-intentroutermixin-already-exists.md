---
id: F006
query_id: Q006
type: grep
intent: Confirm mixins dir and discover that IntentRouterMixin already exists (name collision).
executed_at: 2026-06-05T13:10:00Z
duration_ms: 180
parent_id: null
depth: 0
---

# F006 — `IntentRouterMixin` already exists (name + concept collision)

## Summary

The proposed class name **already exists and is actively maintained**. There is
a fully-implemented `IntentRouterMixin` at
`parrot/bots/mixins/intent_router.py`, but it solves a *different* problem: it
does **pre-RAG retrieval-strategy routing** (decide whether to hit
dataset/vector/graph/tool/free-LLM and inject the retrieved context), hooking
**`conversation()`**, using a **keyword fast-path + LLM `invoke()`** decision.
This is the very "keyword + LLM call" approach the new brainstorm wants to
avoid, and it routes *retrieval*, not *output mode*. The new brainstorm's
"deterministic embedding-similarity output-mode router" is genuinely absent.

## Citations

- path: `parrot/bots/mixins/intent_router.py`
  lines: 118-130
  symbol: `IntentRouterMixin`
  excerpt: |
    class IntentRouterMixin:
        """Mixin that adds intent-based routing to any Bot or Agent.
            class MyAgent(IntentRouterMixin, BasicAgent): ...
        The mixin's ``conversation()`` intercepts calls when active and routes
        through strategy discovery → candidate retrieval → decision → execution.

- path: `parrot/bots/mixins/intent_router.py`
  lines: 166-196
  symbol: `IntentRouterMixin.conversation`
  excerpt: |
    async def conversation(self, prompt: str, **kwargs: Any) -> Any:
        if not self._router_active:
            return await super().conversation(prompt, **kwargs)
        context, decision, trace = await self._route(prompt)
        ...
        if context: kwargs["injected_context"] = context

- path: `parrot/bots/mixins/intent_router.py`
  lines: 52-105, 332-369
  symbol: `_KEYWORD_STRATEGY_MAP`, `_fast_path`
  excerpt: |
    # keyword scan fast path (regex/keyword approach the new brainstorm rejects)

- path: `parrot/bots/mixins/intent_router.py`
  lines: 373-434
  symbol: `_llm_route`
  excerpt: |
    invoke = getattr(self, "invoke", None)   # LLM decision via self.invoke()

- path: `parrot/bots/mixins/__init__.py`
  lines: 4-8
  symbol: exports
  excerpt: |
    - IntentRouterMixin: pre-RAG query routing with strategy cascade and HITL support.
    from .intent_router import IntentRouterMixin

## Notes

Config object is `IntentRouterConfig` (`registry/capabilities/models.py:149`);
activation is via `configure_router(config, registry)` — NOT the base
`configure()`. Integration point in the base bot consumes the injected context:
`bots/base.py:236` ("IntentRouterMixin pre-fetched context — skip RAG
retrieval."). **This is the load-bearing finding for the whole proposal.**
Cross-ref F007 (output_mode contract), F010 (ask vs conversation).
