---
id: F010
query_id: Q008
type: read
intent: Determine the relationship between ask() and conversation() and where the hook belongs.
executed_at: 2026-06-05T13:12:00Z
duration_ms: 130
parent_id: F006
depth: 1
---

# F010 — `ask()` and `conversation()` are distinct entrypoints

## Summary

`ask()` (abstract.py:3660) and `conversation()` (abstract.py:3107) are separate
public methods, both accepting `ctx: Optional[RequestContext] = None`. The
existing `IntentRouterMixin` only intercepts `conversation()`. Subclasses like
`DataAgent` override `ask()` directly (data.py:1294) with their own
`output_mode` kwarg and logic, and `ask()` does not uniformly funnel through
`conversation()`. Consequently, routing wired only into `conversation()` does
**not** cover the `ask()` entrypoint — confirming the user's requirement that
the router must hook **both** `ask()` and `conversation()` to be effective.

## Citations

- path: `parrot/bots/abstract.py`
  lines: 3107, 3660, 3715
  symbol: `conversation`, `ask`, `ask_stream`
  excerpt: |
    async def conversation(self, ..., ctx: Optional[RequestContext] = None): ...
    async def ask(self, ..., ctx: Optional[RequestContext] = None): ...

- path: `parrot/bots/data.py`
  lines: 1294-1306
  symbol: `DataAgent.ask` (independent override)
  excerpt: |
    async def ask(self, question, ..., output_mode=None, ...): ...

- path: `parrot/bots/mixins/intent_router.py`
  lines: 166
  symbol: `IntentRouterMixin.conversation` (only conversation hooked today)
  excerpt: |
    async def conversation(self, prompt: str, **kwargs): ...

## Notes

A shared private hook (e.g. `_resolve_output_mode(query, ctx)`) called from
BOTH `ask()` and `conversation()` avoids duplicating routing logic and matches
the brainstorm's template-method (A3) recommendation. Cross-ref F006, F007.
