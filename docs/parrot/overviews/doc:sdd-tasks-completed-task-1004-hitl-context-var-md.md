---
type: Wiki Overview
title: 'TASK-1004: Add `current_web_session` ContextVar helpers'
id: doc:sdd-tasks-completed-task-1004-hitl-context-var-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: 'This task implements the `current_web_session` ContextVar and its three
  helper functions in `parrot/handlers/web_hitl.py`. The ContextVar allows `WebHumanTool`
  to lazily resolve the active web session (channel ID) at request time without being
  explicitly passed by the caller (§3 '
relates_to:
- concept: mod:parrot.handlers.web_hitl
  rel: mentions
---

# TASK-1004: Add `current_web_session` ContextVar helpers

**Feature**: FEAT-146 — web-hitl-and-demo-agent
**Spec**: `sdd/specs/web-hitl-and-demo-agent.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

This task implements the `current_web_session` ContextVar and its three helper functions in `parrot/handlers/web_hitl.py`. The ContextVar allows `WebHumanTool` to lazily resolve the active web session (channel ID) at request time without being explicitly passed by the caller (§3 Module 2 in the spec).

This is the second module in the stack; `WebHumanTool` (TASK-1005) depends on it.

---

## Scope

- Create `parrot/handlers/web_hitl.py` (new file).
- Define `current_web_session: ContextVar[Optional[str]]`.
- Implement three helper functions:
  - `get_current_web_session() -> Optional[str]` — read the ContextVar.
  - `set_current_web_session(session: Optional[str]) -> Token` — set the ContextVar and return the token.
  - `reset_current_web_session(token: Token) -> None` — reset using the token.
- Add Google-style docstrings to all three functions.
- Add module-level docstring explaining the purpose.

**NOT in scope**:
- `WebHumanTool` class — belongs to TASK-1005.
- `HITLResponseHandler` — belongs to TASK-1006.
- `setup_web_hitl` bootstrap — belongs to TASK-1007.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/handlers/web_hitl.py` | CREATE | ContextVar and helper functions. |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
from contextvars import ContextVar, Token                                       # Python stdlib
from typing import Optional
```

### Existing Signatures to Use

```python
# Python contextvars module (standard library)
from contextvars import ContextVar
# ContextVar supports:
#   var = ContextVar('name', default=None)
#   var.get() -> value or raises LookupError if no default
#   var.set(value) -> Token
#   var.reset(token) -> None
```

### Does NOT Exist

- ~~`current_web_session` ContextVar~~ — to be created in this task.
- ~~Helper functions~~ — to be created.

---

## Implementation Notes

### Pattern to Follow

Mirror the ContextVar pattern from `parrot/integrations/telegram/context.py:30` (which implements `get_current_telegram_chat_id`). The same Token-based reset approach ensures clean isolation under concurrent requests.

### Key Constraints

- Default value for the ContextVar should be `None`.
- Helper functions are module-level (not class methods).
- The Token return type from `set_current_web_session` must be the actual `contextvars.Token` object so `reset_current_web_session` can use it.
- All functions should have Google-style docstrings.

---

## Acceptance Criteria

- [ ] `parrot/handlers/web_hitl.py` exists with module docstring.
- [ ] `current_web_session: ContextVar[Optional[str]]` is defined with default `None`.
- [ ] `get_current_web_session()` returns `Optional[str]`.
- [ ] `set_current_web_session(session: Optional[str])` returns `Token` and updates the ContextVar.
- [ ] `reset_current_web_session(token: Token)` resets to the previous value.
- [ ] All three functions have Google-style docstrings.
- [ ] No linting errors: `ruff check packages/ai-parrot/src/parrot/handlers/web_hitl.py`

---

## Test Specification

```python
# packages/ai-parrot/tests/handlers/test_web_hitl.py
import pytest
import asyncio
from parrot.handlers.web_hitl import (
    current_web_session,
    get_current_web_session,
    set_current_web_session,
    reset_current_web_session,
)


class TestContextVar:
    def test_context_var_default(self):
        """get_current_web_session returns None by default."""
        value = get_current_web_session()
        assert value is None

    def test_context_var_set_and_get(self):
        """set_current_web_session updates the ContextVar."""
        token = set_current_web_session("sess-123")
        assert get_current_web_session() == "sess-123"
        reset_current_web_session(token)

    def test_context_var_reset(self):
        """reset_current_web_session restores the previous value."""
        # Set initial value
        token1 = set_current_web_session("sess-1")
        assert get_current_web_session() == "sess-1"
        
        # Set a new value and get a token
        token2 = set_current_web_session("sess-2")
        assert get_current_web_session() == "sess-2"
        
        # Reset to the previous value
        reset_current_web_session(token2)
        assert get_current_web_session() == "sess-1"
        
        # Reset to the original
        reset_current_web_session(token1)
        assert get_current_web_session() is None

    @pytest.mark.asyncio
    async def test_context_var_isolation(self):
        """ContextVar values are isolated between concurrent tasks."""
        async def set_and_read(value):
            token = set_current_web_session(value)
            # Simulate some async work
            await asyncio.sleep(0.01)
            result = get_current_web_session()
            reset_current_web_session(token)
            return result

        results = await asyncio.gather(
            set_and_read("sess-a"),
            set_and_read("sess-b"),
            set_and_read("sess-c"),
        )
        assert results == ["sess-a", "sess-b", "sess-c"]
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/web-hitl-and-demo-agent.spec.md` for full context
2. **Check dependencies** — none, this is independent
3. **Verify the Codebase Contract** — confirm ContextVar API matches Python stdlib
4. **Update status** in `tasks/.index.json` → `"in-progress"` with your session ID
5. **Implement** following the scope and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `tasks/completed/TASK-1004-hitl-context-var.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
