---
type: Wiki Overview
title: 'TASK-1005: Implement WebHumanTool'
id: doc:sdd-tasks-completed-task-1005-webhumantool-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: This task implements `WebHumanTool`, a subclass of `HumanTool` that auto-resolves
  the HITL manager and the current web session at invocation time (§3 Module 2 in
  the spec). It mirrors the lazy-resolution pattern used by `TelegramHumanTool`, but
  uses the `current_web_session` Cont
relates_to:
- concept: mod:parrot.handlers.web_hitl
  rel: mentions
- concept: mod:parrot.human
  rel: mentions
---

# TASK-1005: Implement WebHumanTool

**Feature**: FEAT-146 — web-hitl-and-demo-agent
**Spec**: `sdd/specs/web-hitl-and-demo-agent.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S
**Depends-on**: TASK-1003, TASK-1004
**Assigned-to**: unassigned

---

## Context

This task implements `WebHumanTool`, a subclass of `HumanTool` that auto-resolves the HITL manager and the current web session at invocation time (§3 Module 2 in the spec). It mirrors the lazy-resolution pattern used by `TelegramHumanTool`, but uses the `current_web_session` ContextVar instead of a Telegram-specific context.

This tool is used by agents running in the web handler to ask questions and hand off to humans. The demo agent (TASK-1010) and any user agent can instantiate this tool.

---

## Scope

- Implement `WebHumanTool` class in `parrot/handlers/web_hitl.py` (same file as TASK-1004).
- `WebHumanTool` extends `HumanTool`.
- Constructor accepts optional `default_targets`, `source_agent`, and `**kwargs` (does NOT accept `manager` param — always resolves lazily).
- Override `_execute` method to:
  - Lazily resolve `manager` from `get_default_human_manager()` if not already set in `__init__`.
  - Lazily resolve `target_humans` from the ContextVar (`get_current_web_session()`) when neither the call's kwargs nor the tool's `default_targets` supplied one.
  - Set default channel to `"web"`.
  - Delegate to `super()._execute(**kwargs)` with resolved values.
- Add Google-style docstrings.

**NOT in scope**:
- Endpoint handler — belongs to TASK-1006.
- Bootstrap — belongs to TASK-1007.
- AgentTalk wiring — belongs to TASK-1008.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/handlers/web_hitl.py` | MODIFY | Add `WebHumanTool` class. |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
from parrot.human import (                                                      # parrot/human/__init__.py:9-43
    HumanTool,
    HumanInteractionManager,
    set_default_human_manager,
    get_default_human_manager,
)
from parrot.handlers.web_hitl import (                                          # (created in TASK-1004)
    get_current_web_session,
    set_current_web_session,
    reset_current_web_session,
)
from typing import Any, List, Optional
import logging
```

### Existing Signatures to Use

```python
# parrot/human/tool.py:98
class HumanTool(AbstractTool):
    name: str = "ask_human"                                                     # line 112
    args_schema: Type[BaseModel] = HumanToolInput                               # line 124

    def __init__(                                                               # line 126
        self,
        manager: Any = None,
        *,
        default_channel: str = "telegram",
        default_targets: Optional[List[str]] = None,
        source_agent: Optional[str] = None,
        **kwargs: Any,
    ) -> None: ...

    async def _execute(self, **kwargs: Any) -> Any: ...                         # line 141

# parrot/human/__init__.py
def get_default_human_manager() -> Optional[HumanInteractionManager]: ...       # line 40
def set_default_human_manager(manager: HumanInteractionManager) -> None: ...    # line 34

# parrot/integrations/telegram/human_tool.py (REFERENCE PATTERN)
class TelegramHumanTool(HumanTool):                                              # line 20
    def __init__(
        self, *, default_channel: Optional[str] = None,
        default_targets: Optional[List[str]] = None,
        source_agent: Optional[str] = None,
        **kwargs: Any,
    ) -> None: ...
    async def _execute(self, **kwargs: Any) -> Any: ...
```

### Does NOT Exist

- ~~`WebHumanTool`~~ — to be created in this task.
- ~~`HumanTool.target_humans` attribute~~ — does not exist as a class attribute. The list lives on `default_targets` (init kwarg) and on per-call `kwargs["target_humans"]` inside `_execute`.

---

## Implementation Notes

### Pattern to Follow

Mirror `TelegramHumanTool` at `parrot/integrations/telegram/human_tool.py:20`:
- Constructor does NOT accept a `manager` parameter — always None in the parent.
- In `_execute`, check if `self.manager` was set; if None, call `get_default_human_manager()`.
- Check if `target_humans` was provided in `kwargs` or `self.default_targets`; if not, read from ContextVar.
- If ContextVar is empty and no `default_targets`, raise a clear error.
- Default channel is `"web"`.

### Key Constraints

- `WebHumanTool()` constructor does NOT accept `manager=...` — only `default_targets`, `source_agent`, and `**kwargs`.
- The `_execute` method must be `async`.
- Logging at INFO level when resolving manager/target, WARNING if ContextVar is empty.

---

## Acceptance Criteria

- [ ] `WebHumanTool` class exists in `parrot/handlers/web_hitl.py`.
- [ ] Constructor signature matches the brief: no `manager` param, only `default_targets`, `source_agent`, `**kwargs`.
- [ ] `_execute` method is async.
- [ ] `_execute` resolves `self.manager` from `get_default_human_manager()` when None.
- [ ] `_execute` resolves `target_humans` from ContextVar when neither the call nor `default_targets` supplied one.
- [ ] Default channel is `"web"`.
- [ ] All tests pass: `pytest packages/ai-parrot/tests/handlers/test_web_hitl.py::test_web_human_tool -v`
- [ ] No linting errors: `ruff check packages/ai-parrot/src/parrot/handlers/web_hitl.py`

---

## Test Specification

```python
# packages/ai-parrot/tests/handlers/test_web_hitl.py
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from parrot.handlers.web_hitl import (
    WebHumanTool,
    set_current_web_session,
    reset_current_web_session,
)
from parrot.human import get_default_human_manager, set_default_human_manager


@pytest.fixture
def mock_manager():
    """Mock HumanInteractionManager."""
    manager = AsyncMock()
    manager.request_human_input = AsyncMock(return_value="user_response")
    return manager


@pytest.fixture(autouse=True)
def reset_default_manager():
    """Reset the default manager between tests."""
    original = get_default_human_manager()
    yield
    if original:
        set_default_human_manager(original)
    else:
        set_default_human_manager(None)


class TestWebHumanTool:
    async def test_web_human_tool_resolves_manager_lazily(self, mock_manager):
        """WebHumanTool resolves manager from get_default_human_manager() when not provided."""
        set_default_human_manager(mock_manager)
        token = set_current_web_session("sess-123")
        try:
            tool = WebHumanTool(source_agent="test_agent")
            result = await tool._execute(
                interaction_type="approval",
                question="Test?",
            )
            # If lazy resolution worked, the manager was called
            assert mock_manager.request_human_input.called
        finally:
            reset_current_web_session(token)

    async def test_web_human_tool_target_from_contextvar(self, mock_manager):
        """WebHumanTool reads target_humans from ContextVar when not provided."""
        set_default_human_manager(mock_manager)
        token = set_current_web_session("sess-456")
        try:
            tool = WebHumanTool(source_agent="test_agent")
            await tool._execute(
                interaction_type="free_text",
                question="Name?",
            )
            # Assert the call included target_humans
            assert mock_manager.request_human_input.called
            call_kwargs = mock_manager.request_human_input.call_args[1]
            # The interaction should have been passed with the target
            interaction = mock_manager.request_human_input.call_args[0][0]
            # Verify target_humans was set (either in interaction or passed separately)
            # The exact structure depends on the parent HumanTool implementation
        finally:
            reset_current_web_session(token)

    async def test_web_human_tool_explicit_targets_win(self, mock_manager):
        """WebHumanTool ignores ContextVar when LLM provides target_humans."""
        set_default_human_manager(mock_manager)
        token = set_current_web_session("sess-from-context")
        try:
            tool = WebHumanTool(source_agent="test_agent")
            # Explicitly pass target_humans in kwargs
            result = await tool._execute(
                interaction_type="approval",
                question="Approve?",
                target_humans=["explicit-target"],
            )
            # The explicit target should be used, not the ContextVar
            assert mock_manager.request_human_input.called
        finally:
            reset_current_web_session(token)

    async def test_web_human_tool_error_when_no_target(self, mock_manager):
        """WebHumanTool raises when no target_humans and ContextVar is empty."""
        set_default_human_manager(mock_manager)
        tool = WebHumanTool(source_agent="test_agent")
        # ContextVar is not set, no default_targets, no kwargs target_humans
        with pytest.raises((ValueError, RuntimeError)):
            await tool._execute(
                interaction_type="approval",
                question="Approve?",
            )
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/web-hitl-and-demo-agent.spec.md` for full context
2. **Check dependencies** — verify TASK-1003 (WebHumanChannel) and TASK-1004 (ContextVar) are in `tasks/completed/`
3. **Verify the Codebase Contract** — confirm imports, particularly `HumanTool` signature and `TelegramHumanTool` pattern
4. **Update status** in `tasks/.index.json` → `"in-progress"` with your session ID
5. **Implement** following the scope and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `tasks/completed/TASK-1005-webhumantool.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
