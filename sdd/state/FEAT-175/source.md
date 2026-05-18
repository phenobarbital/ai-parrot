---
kind: inline
jira_key: null
fetched_at: 2026-05-15T00:00:00Z
summary_oneline: Migrate RequestBot proxy wrapper to ContextVar-based RequestContext propagation
---

# Source: Migrate RequestBot to ContextVars

Current AbstractBot is wrapped with a RequestBot, idea is migrating to a ContextVar.
This is exactly what contextvars.ContextVar exists for, and it's how aiohttp,
FastAPI/Starlette, and SQLAlchemy async sessions solve the identical problem. You get
per-task isolation for free, you don't need an external wrapper, and a single long-lived
bot instance can serve many concurrent requests safely.

## Proposed Pattern

1. **The context variable** — module-level `_current_ctx: ContextVar[Optional[RequestContext]]`
   in `utils/helpers.py`, with a `current_context()` accessor.

2. **A scoped binder on AbstractBot** — `session()` async context manager that binds ctx
   to the ContextVar for the block's lifetime. Separate from `__aenter__/__aexit__`
   (resource lifecycle). Avoids race conditions on shared bot instances.

3. **Fallback in ask()/ask_stream()/conversation()** — `if ctx is None: ctx = _current_ctx.get()`.
   Explicit ctx= still wins.

4. **Usage in AgentTalk.POST** — replace `retrieval()` usage with `bot.session()` for the
   ask() and ask_stream() paths.
