---
id: F016
query_id: Q026
type: grep
intent: Locate IntentRouterMixin for the v2 automatic-router follow-up
executed_at: 2026-08-23T02:20:00Z
depth: 0
---
# F016 — IntentRouterMixin exists in bots/mixins (v2 candidate, out of v1 scope)

## Summary
`class IntentRouterMixin` at `parrot/bots/mixins/intent_router.py:123`. It is a bot mixin
(depends on the agent framework), not importable from the dependency-light wiki CLI path
(F009) — a v2 router would live in the toolkit/agent layer, not in `wikitoolkit`.

## Citations
- path: `packages/ai-parrot/src/parrot/bots/mixins/intent_router.py`
  lines: 123
  symbol: `IntentRouterMixin`
