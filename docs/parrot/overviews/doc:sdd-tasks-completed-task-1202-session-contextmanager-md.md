---
type: Wiki Overview
title: 'TASK-1202: AbstractBot.session() Context Manager + Entry Point Fallbacks'
id: doc:sdd-tasks-completed-task-1202-session-contextmanager-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: This is the core task. It adds `session()` to AbstractBot (absorbing PBAC
  +
relates_to:
- concept: mod:parrot.utils.helpers
  rel: mentions
---

# TASK-1202: AbstractBot.session() Context Manager + Entry Point Fallbacks

**Feature**: FEAT-175 — Migrate RequestBot to ContextVar-based RequestContext
**Spec**: `sdd/specs/migrate-requestbot-contextvars.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-1201
**Assigned-to**: unassigned

---

## Context

This is the core task. It adds `session()` to AbstractBot (absorbing PBAC +
semaphore from `retrieval()`), adds ContextVar fallback in the four abstract
entry points, removes `retrieval()`, and removes the virtual subclass
registration. After this task, the bot no longer needs a proxy wrapper.

Implements Spec §3 Module 2.

---

## Scope

- Add `session()` async context manager to `AbstractBot` that:
  1. Builds `RequestContext` from params (or accepts a pre-built one)
  2. Enforces PBAC (port entire block from `retrieval()` lines 3141-3197)
  3. Sets `_current_ctx` ContextVar token
  4. Acquires `self._semaphore`
  5. Yields `self` (the real bot, not a wrapper)
  6. Resets the ContextVar token in `finally`
- Add ContextVar fallback (`if ctx is None: ctx = _current_ctx.get()`) in:
  - `ask()` (abstract, line 3473)
  - `ask_stream()` (abstract, line 3520)
  - `conversation()` (abstract, line 2942)
  - `invoke()` (abstract, line 3217)
- Remove `retrieval()` method entirely (lines 3103-3204)
- Remove `AbstractBot.register(RequestBot)` (line 3759)
- Update imports: remove `RequestBot` import, add `_current_ctx` and
  `current_context` imports from `..utils.helpers`
- Check if `followup()` accepts `ctx` — if so, add the same fallback

**NOT in scope**: modifying `base.py` concrete implementations (TASK-1204),
modifying handlers (TASK-1203), writing new tests (TASK-1205).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/bots/abstract.py` | MODIFY | Add session(), remove retrieval(), add fallbacks, update imports |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# parrot/bots/abstract.py:55
from ..utils.helpers import RequestContext, RequestBot  # RequestBot import TO BE REMOVED
```

New import needed (after TASK-1201):
```python
from ..utils.helpers import RequestContext, _current_ctx, current_context
```

### Existing Signatures to Use

```python
# parrot/bots/abstract.py:560
self._semaphore = asyncio.BoundedSemaphore(max_concurrency)

# parrot/bots/abstract.py:3096-3101
async def __aenter__(self): return self
async def __aexit__(self, exc_type, exc_value, traceback):
    with contextlib.suppress(Exception):
        await self.cleanup()

# parrot/bots/abstract.py:3103-3204 — retrieval() TO BE REPLACED
@asynccontextmanager
async def retrieval(
    self,
    request: web.Request = None,
    app: Optional[Any] = None,
    llm: Optional[Any] = None,
    **kwargs
) -> AsyncIterator["RequestBot"]:
    ctx = RequestContext(request=request, app=app, llm=llm, **kwargs)  # line 3133
    wrapper = RequestBot(delegate=self, context=ctx)                   # line 3139
    # PBAC enforcement: lines 3141-3197
    # if _PBAC_AVAILABLE: ... (entire block)
    async with self._semaphore:                                        # line 3200
        try:
            yield wrapper                                              # line 3202
        finally:
            ctx = None                                                 # line 3204

# parrot/bots/abstract.py:3473 — ask() signature
@abstractmethod
async def ask(self, question: str, ..., ctx: Optional[RequestContext] = None, ...) -> AIMessage:
    ...

# parrot/bots/abstract.py:3520 — ask_stream() signature
@abstractmethod
async def ask_stream(self, question: str, ..., ctx: Optional[RequestContext] = None, ...) -> AsyncIterator[Union[str, AIMessage]]:
    ...

# parrot/bots/abstract.py:2942 — conversation() signature
@abstractmethod
async def conversation(self, question: str, ..., ctx: Optional[RequestContext] = None, ...) -> AIMessage:
    ...

# parrot/bots/abstract.py:3217 — invoke() signature
@abstractmethod
async def invoke(self, question: str, ..., ctx: Optional[RequestContext] = None, ...) -> AIMessage:
    ...

# parrot/bots/abstract.py:3759
AbstractBot.register(RequestBot)  # TO BE REMOVED
```

### Does NOT Exist
- ~~`AbstractBot.session()`~~ — does not exist yet; this task creates it
- ~~`AbstractBot.ctx`~~ — no instance attribute for ctx on the bot
- ~~`from contextvars import ContextVar` in abstract.py~~ — not currently imported there; use the one from helpers

---

## Implementation Notes

### Pattern to Follow

The `session()` method should look like this (from spec §2 New Public Interfaces):

```python
@asynccontextmanager
async def session(
    self,
    ctx: Optional[RequestContext] = None,
    *,
    request: web.Request = None,
    app: Optional[Any] = None,
    llm: Optional[Any] = None,
    user_id: Union[str, int, None] = None,
    session_id: Optional[str] = None,
    **ctx_kwargs,
) -> AsyncIterator["AbstractBot"]:
    if ctx is None:
        ctx = RequestContext(
            request=request,
            app=app,
            llm=llm,
            user_id=user_id,
            session_id=session_id,
            **ctx_kwargs,
        )

    # --- PBAC enforcement (port from retrieval() lines 3141-3197 verbatim) ---
    # Copy the entire if _PBAC_AVAILABLE: block here
    # ...

    token = _current_ctx.set(ctx)
    try:
        async with self._semaphore:
            async with ctx:
                yield self
    finally:
        _current_ctx.reset(token)
```

### ContextVar fallback in abstract entry points

For each of the four abstract methods, add before the `...` body:

```python
@abstractmethod
async def ask(self, question: str, ..., ctx: Optional[RequestContext] = None, ...) -> AIMessage:
    # ContextVar fallback — concrete implementations inherit this
    ...
```

**IMPORTANT**: Since these are `@abstractmethod` with `...` bodies, the fallback
must be added as a comment/docstring instruction. The ACTUAL fallback code goes
in the concrete `BaseBot` implementations (TASK-1204). However, if the abstract
methods have any non-abstract pre-processing code, add the fallback there.

**Alternative**: If the abstract methods are pure stubs (just `...`), document
the fallback requirement in the docstring so TASK-1204 picks it up. Check the
actual method bodies before deciding.

### Key Constraints
- Port PBAC code EXACTLY from `retrieval()` — do not redesign
- `session()` yields `self`, NOT a wrapper
- The `async with ctx:` is needed to honor RequestContext lifecycle
- ContextVar token MUST be reset in `finally` to prevent leaks
- The semaphore wraps the yield, same as in `retrieval()`

### References in Codebase
- `parrot/bots/abstract.py:3103-3204` — `retrieval()` (source for PBAC + semaphore)
- `parrot/handlers/web_hitl.py:52` — ContextVar set/reset pattern
- `parrot/tools/dataset_manager/tool.py:41` — ContextVar isolation pattern

---

## Acceptance Criteria

- [ ] `AbstractBot.session()` context manager exists and absorbs PBAC + semaphore
- [ ] `retrieval()` method is completely removed
- [ ] `AbstractBot.register(RequestBot)` line is removed
- [ ] Import of `RequestBot` from `..utils.helpers` is removed
- [ ] `_current_ctx` is imported from `..utils.helpers`
- [ ] Entry point methods document or implement ContextVar fallback
- [ ] `ruff check packages/ai-parrot/src/parrot/bots/abstract.py` passes

---

## Test Specification

```python
# tests/bots/test_session_contextvar.py (append to file from TASK-1201)
import asyncio
import pytest
from unittest.mock import MagicMock, AsyncMock, patch
from parrot.utils.helpers import RequestContext, current_context


class TestSessionContextManager:
    @pytest.mark.asyncio
    async def test_session_yields_real_bot(self, configured_bot):
        """session() yields the bot itself, not a proxy wrapper."""
        async with configured_bot.session(request=MagicMock()) as b:
            assert b is configured_bot

    @pytest.mark.asyncio
    async def test_session_sets_contextvar(self, configured_bot):
        """current_context() returns the bound RequestContext inside session()."""
        async with configured_bot.session(
            user_id="u1", session_id="s1"
        ) as b:
            ctx = current_context()
            assert ctx is not None
            assert ctx.user_id == "u1"
            assert ctx.session_id == "s1"

    @pytest.mark.asyncio
    async def test_session_resets_contextvar(self, configured_bot):
        """current_context() returns None after session() exits."""
        async with configured_bot.session(user_id="u1") as b:
            assert current_context() is not None
        assert current_context() is None

    @pytest.mark.asyncio
    async def test_session_concurrent_isolation(self, configured_bot):
        """Two concurrent sessions on the same bot have isolated ctx."""
        results = {}

        async def worker(uid):
            async with configured_bot.session(user_id=uid) as b:
                await asyncio.sleep(0.01)
                results[uid] = current_context().user_id

        await asyncio.gather(worker("alice"), worker("bob"))
        assert results["alice"] == "alice"
        assert results["bob"] == "bob"

    @pytest.mark.asyncio
    async def test_session_accepts_prebuilt_ctx(self, configured_bot):
        """session(ctx=prebuilt) uses the provided RequestContext."""
        ctx = RequestContext(user_id="pre")
        async with configured_bot.session(ctx=ctx) as b:
            assert current_context() is ctx

    @pytest.mark.asyncio
    async def test_retrieval_removed(self, configured_bot):
        """retrieval() no longer exists on AbstractBot."""
        assert not hasattr(configured_bot, 'retrieval')
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/migrate-requestbot-contextvars.spec.md`
2. **Check dependencies** — TASK-1201 must be complete (verify `_current_ctx` exists in helpers.py)
3. **Read `abstract.py` lines 3103-3204** to understand the full PBAC block before porting
4. **Check if `followup()` accepts `ctx`** — grep for `async def followup` in abstract.py
5. **Implement** session(), remove retrieval(), add fallbacks
6. **Run lint**: `ruff check packages/ai-parrot/src/parrot/bots/abstract.py`
7. **Commit** with message: `feat(FEAT-175): add session() context manager, remove retrieval()`

---

## Completion Note

Implemented as specified. Added session() context manager with full PBAC block ported verbatim from retrieval(). session() yields self (the real bot, not a proxy). _current_ctx ContextVar set/reset around yield in finally block. semaphore wraps the yield. retrieval() method removed. AbstractBot.register(RequestBot) removed. Import updated to include _current_ctx and current_context. Lint: only pre-existing E402 violations, no new issues.
