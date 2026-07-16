---
type: Wiki Overview
title: 'TASK-1201: ContextVar Infrastructure in helpers.py'
id: doc:sdd-tasks-completed-task-1201-contextvar-infrastructure-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: This is the foundation task. It adds the `_current_ctx` ContextVar and
relates_to:
- concept: mod:parrot.utils.helpers
  rel: mentions
---

# TASK-1201: ContextVar Infrastructure in helpers.py

**Feature**: FEAT-175 — Migrate RequestBot to ContextVar-based RequestContext
**Spec**: `sdd/specs/migrate-requestbot-contextvars.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

This is the foundation task. It adds the `_current_ctx` ContextVar and
`current_context()` accessor to `parrot/utils/helpers.py`, and removes the
`RequestBot` class. All subsequent tasks depend on this.

Implements Spec §3 Module 1.

---

## Scope

- Add `_current_ctx: ContextVar[Optional[RequestContext]]` module-level variable
  with `default=None`
- Add `current_context()` function that returns `_current_ctx.get()`
- Remove the entire `RequestBot` class (lines 43-77)
- Remove the `import inspect` statement (only used by RequestBot)
- Keep `RequestContext` class unchanged

**NOT in scope**: modifying `abstract.py`, handlers, or any other file.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/utils/helpers.py` | MODIFY | Add ContextVar + accessor, remove RequestBot |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from typing import Any, Optional, Union           # verified: parrot/utils/helpers.py:1
import inspect                                      # verified: parrot/utils/helpers.py:2 — TO BE REMOVED
from aiohttp import web                            # verified: parrot/utils/helpers.py:3
```

### Existing Signatures to Use
```python
# parrot/utils/helpers.py:5
class RequestContext:
    def __init__(
        self,
        request: web.Request = None,          # line 21
        app: Optional[Any] = None,            # line 22
        llm: Optional[Any] = None,            # line 23
        user_id: Union[str, int] = None,      # line 24
        session_id: str = None,               # line 25
        **kwargs                              # line 26
    ): ...
    async def __aenter__(self): return self    # line 36
    async def __aexit__(self, ...): pass       # line 39
```

### Does NOT Exist
- ~~`parrot.utils.helpers._current_ctx`~~ — does not exist yet; this task creates it
- ~~`parrot.utils.helpers.current_context`~~ — does not exist yet; this task creates it
- ~~`RequestContext` in `parrot/utils/__init__.py`~~ — NOT exported from `__init__.py`

---

## Implementation Notes

### Pattern to Follow
```python
# parrot/handlers/web_hitl.py:52 — exact same ContextVar pattern
from contextvars import ContextVar

current_web_session: ContextVar[Optional[str]] = ContextVar(
    "current_web_session", default=None
)

def get_current_web_session() -> Optional[str]:
    return current_web_session.get()
```

### Key Constraints
- The ContextVar must be module-level (not inside a class)
- `default=None` so `current_context()` returns None outside any session
- Keep `RequestContext` completely unchanged — only add new code and remove `RequestBot`
- `import inspect` can be removed since only `RequestBot.__getattr__` used it

---

## Acceptance Criteria

- [ ] `_current_ctx` ContextVar exists in `helpers.py`
- [ ] `current_context()` function exists and returns `_current_ctx.get()`
- [ ] `RequestBot` class is completely removed
- [ ] `import inspect` is removed
- [ ] `RequestContext` class is unchanged
- [ ] `ruff check packages/ai-parrot/src/parrot/utils/helpers.py` passes

---

## Test Specification

```python
# tests/bots/test_session_contextvar.py
import pytest
from parrot.utils.helpers import RequestContext, current_context, _current_ctx


class TestContextVarInfrastructure:
    def test_current_context_default_none(self):
        """current_context() returns None when no session is active."""
        assert current_context() is None

    def test_current_context_after_set(self):
        """current_context() returns the set RequestContext."""
        ctx = RequestContext(user_id="test-user")
        token = _current_ctx.set(ctx)
        try:
            assert current_context() is ctx
            assert current_context().user_id == "test-user"
        finally:
            _current_ctx.reset(token)

    def test_current_context_reset(self):
        """current_context() returns None after reset."""
        ctx = RequestContext()
        token = _current_ctx.set(ctx)
        _current_ctx.reset(token)
        assert current_context() is None

    def test_requestbot_removed(self):
        """RequestBot class no longer exists in helpers module."""
        import parrot.utils.helpers as helpers
        assert not hasattr(helpers, 'RequestBot')
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/migrate-requestbot-contextvars.spec.md`
2. **Check dependencies** — none; this is the first task
3. **Verify the Codebase Contract** — confirm `helpers.py` still has RequestBot at line 43
4. **Implement** the changes in `helpers.py`
5. **Run tests**: `pytest tests/bots/test_session_contextvar.py -v`
6. **Run lint**: `ruff check packages/ai-parrot/src/parrot/utils/helpers.py`
7. **Commit** with message: `feat(FEAT-175): add ContextVar infrastructure, remove RequestBot`

---

## Completion Note

Implemented as specified. Added `_current_ctx: ContextVar[Optional[RequestContext]]` module-level variable with `default=None`, and `current_context()` accessor function. Removed `RequestBot` class and `import inspect` (only used by RequestBot.__getattr__). `RequestContext` class is completely unchanged. Lint passes clean.
