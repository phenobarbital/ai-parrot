---
id: F004
query: "ask/ask_stream/conversation/invoke signatures"
type: read
file: packages/ai-parrot/src/parrot/bots/abstract.py
lines: 2943-3546
---

All four entry points accept `ctx: Optional[RequestContext] = None`:
- ask()         line 3474
- ask_stream()  line 3521
- conversation() line 2943
- invoke()      line 3218

These are abstract methods. The ContextVar fallback (`if ctx is None: ctx = _current_ctx.get()`)
can be added at either the abstract or concrete level.
