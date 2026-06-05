---
id: F004
query_id: Q004
type: grep
intent: Resolve the BLOCKING question — does a named RequestContext carrier exist?
executed_at: 2026-06-05T13:09:00Z
duration_ms: 210
parent_id: null
depth: 0
---

# F004 — `RequestContext` carrier exists (blocking question RESOLVED)

## Summary

A named `RequestContext` exists at `utils/helpers.py:7`, bound per-asyncio-task
via the `_current_ctx` ContextVar and reachable anywhere through
`current_context()`. It is a **plain (non-Pydantic) class** with fields
`request, app, llm, user_id, session_id, kwargs`. It does **not** currently
carry `output_mode` / `intent_score`. So the blocking design question is
answered: a carrier exists and is contextvar-bound, but the proposed
`output_mode`/`intent_score` fields would be NEW, and (per F007) the mode
contract today lives on the response/ask-kwarg, not on this carrier.

## Citations

- path: `parrot/utils/helpers.py`
  lines: 7-36
  symbol: `RequestContext`
  excerpt: |
    class RequestContext:
        def __init__(self, request=None, app=None, llm=None,
                     user_id=None, session_id=None, **kwargs):
            self.request = request; self.app = app; self.llm = llm
            self.user_id = user_id; self.session_id = session_id
            self.kwargs = kwargs

- path: `parrot/utils/helpers.py`
  lines: 47-59
  symbol: `_current_ctx`, `current_context`
  excerpt: |
    _current_ctx: ContextVar[Optional[RequestContext]] = ContextVar(
        "parrot_request_ctx", default=None)
    def current_context() -> Optional[RequestContext]: return _current_ctx.get()

- path: `parrot/bots/abstract.py`
  lines: 3271-3312
  symbol: `AbstractBot.session()` (binds ctx)
  excerpt: |
    """Bind a RequestContext to the current asyncio task ..."""
    ctx = RequestContext(...)

## Notes

`ask()` (abstract.py:3660) and `conversation()` (abstract.py:3107) both accept
`ctx: Optional[RequestContext] = None`. Cross-ref F007, F010.
