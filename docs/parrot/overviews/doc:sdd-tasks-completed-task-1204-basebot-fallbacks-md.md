---
type: Wiki Overview
title: 'TASK-1204: BaseBot Concrete ContextVar Fallbacks'
id: doc:sdd-tasks-completed-task-1204-basebot-fallbacks-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: BaseBot's concrete implementations of `ask()`, `ask_stream()`, and
relates_to:
- concept: mod:parrot.utils.helpers
  rel: mentions
---

# TASK-1204: BaseBot Concrete ContextVar Fallbacks

**Feature**: FEAT-175 — Migrate RequestBot to ContextVar-based RequestContext
**Spec**: `sdd/specs/migrate-requestbot-contextvars.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-1201
**Assigned-to**: unassigned

---

## Context

BaseBot's concrete implementations of `ask()`, `ask_stream()`, and
`conversation()` accept `ctx` as a parameter and forward it to
`_build_kb_context()`. This task adds the ContextVar fallback at the top
of each method so that when `ctx=None` (the default), the ambient context
from `session()` is used automatically.

Implements Spec §3 Module 4.

---

## Scope

- Add `if ctx is None: ctx = _current_ctx.get()` at the top of:
  - `BaseBot.ask()` (line 653, body starts ~line 700)
  - `BaseBot.ask_stream()` (line 1157, body starts ~line 1178)
  - `BaseBot.conversation()` (line 115, body starts ~line 136)
- Add import of `_current_ctx` from `..utils.helpers`
- Check if `BaseBot.invoke()` exists as a concrete method — if so, add the same fallback

**NOT in scope**: modifying abstract.py (TASK-1202), modifying handlers (TASK-1203).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/bots/base.py` | MODIFY | Add ContextVar fallback in 3-4 methods, add import |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# parrot/bots/base.py:20
from ..utils.helpers import RequestContext
```

New import needed:
```python
from ..utils.helpers import RequestContext, _current_ctx
```

### Existing Signatures to Use

```python
# parrot/bots/base.py:653 — ask()
async def ask(
    self,
    question: str,
    ...
    ctx: Optional[RequestContext] = None,   # line 666
    ...
) -> AIMessage:
    # Body starts at line 700
    session_id = session_id or str(uuid.uuid4())  # line 700
    user_id = user_id or "anonymous"               # line 701
    ...
    # ctx forwarded to _build_kb_context at line 826:
    kb_context, kb_meta = await self._build_kb_context(
        question, user_id=user_id, session_id=session_id, ctx=ctx,
    )

# parrot/bots/base.py:1157 — ask_stream()
async def ask_stream(
    self,
    question: str,
    ...
    ctx: Optional[RequestContext] = None,   # line 1170
    ...
) -> AsyncIterator[Union[str, AIMessage]]:
    # Body starts at line 1178
    session_id = session_id or str(uuid.uuid4())  # line 1178
    ...
    # ctx forwarded to _build_kb_context at line 1257

# parrot/bots/base.py:115 — conversation()
async def conversation(
    self,
    question: str,
    ...
    ctx: Optional[RequestContext] = None,   # line 130
    ...
) -> AIMessage:
    # ctx forwarded to _build_kb_context at line 235
```

### Does NOT Exist
- ~~`BaseBot.invoke()` concrete method~~ — verify before implementing; may only exist on AbstractBot
- ~~`BaseBot.ctx` attribute~~ — no instance attribute

---

## Implementation Notes

### Exact Change Pattern

At the very top of each method body, before any other logic:

```python
async def ask(self, ..., ctx: Optional[RequestContext] = None, ...) -> AIMessage:
    if ctx is None:
        ctx = _current_ctx.get()
    # ... rest of existing body unchanged
    session_id = session_id or str(uuid.uuid4())
    ...
```

### Key Constraints
- The fallback line MUST come before any code that uses `ctx`
- The rest of the method body is completely unchanged
- `_build_kb_context(ctx=ctx)` calls work as before — ctx is either the
  explicit argument, the ContextVar value, or None (when outside any session)

---

## Acceptance Criteria

- [ ] `BaseBot.ask()` falls back to `_current_ctx.get()` when `ctx is None`
- [ ] `BaseBot.ask_stream()` falls back to `_current_ctx.get()` when `ctx is None`
- [ ] `BaseBot.conversation()` falls back to `_current_ctx.get()` when `ctx is None`
- [ ] `_current_ctx` is imported from `..utils.helpers`
- [ ] `ruff check packages/ai-parrot/src/parrot/bots/base.py` passes

---

## Test Specification

```python
# tests/bots/test_session_contextvar.py (append to existing)
import pytest
from unittest.mock import MagicMock, AsyncMock, patch
from parrot.utils.helpers import RequestContext, _current_ctx


class TestBaseBotFallback:
    @pytest.mark.asyncio
    async def test_ask_explicit_ctx_wins(self, configured_bot):
        """ask(ctx=explicit) uses the explicit ctx, not the ContextVar."""
        ambient = RequestContext(user_id="ambient")
        explicit = RequestContext(user_id="explicit")
        token = _current_ctx.set(ambient)
        try:
            # The bot's ask() should use "explicit", not "ambient"
            # Verify by checking what ctx is passed to _build_kb_context
            with patch.object(configured_bot, '_build_kb_context',
                            new_callable=AsyncMock, return_value=("", {})):
                await configured_bot.ask("test", ctx=explicit)
                call_kwargs = configured_bot._build_kb_context.call_args
                assert call_kwargs.kwargs.get('ctx') is explicit
        finally:
            _current_ctx.reset(token)

    @pytest.mark.asyncio
    async def test_ask_falls_back_to_contextvar(self, configured_bot):
        """ask() without ctx= reads from ContextVar when inside session()."""
        ambient = RequestContext(user_id="ambient")
        token = _current_ctx.set(ambient)
        try:
            with patch.object(configured_bot, '_build_kb_context',
                            new_callable=AsyncMock, return_value=("", {})):
                await configured_bot.ask("test")
                call_kwargs = configured_bot._build_kb_context.call_args
                assert call_kwargs.kwargs.get('ctx') is ambient
        finally:
            _current_ctx.reset(token)
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/migrate-requestbot-contextvars.spec.md`
2. **Check dependencies** — TASK-1201 must be complete (verify `_current_ctx` exists in helpers.py)
3. **Read `base.py`** to find the exact start of each method body
4. **Check if `invoke()` exists** as a concrete method in BaseBot
5. **Add the one-line fallback** at the top of each method
6. **Run lint**: `ruff check packages/ai-parrot/src/parrot/bots/base.py`
7. **Commit** with message: `feat(FEAT-175): add ContextVar fallback in BaseBot entry points`

---

## Completion Note

Added `if ctx is None: ctx = _current_ctx.get()` at the start of conversation() (line 169), invoke() (line 515), ask() (line 762), and ask_stream() (line 1293). Import updated: `from ..utils.helpers import RequestContext, _current_ctx`. All 4 fallbacks confirmed present. Lint: 5 pre-existing violations only, no new issues.
