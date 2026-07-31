---
type: Wiki Overview
title: 'TASK-1395: Read-only operator commands (/context, /memory, /model, /mission)'
id: doc:sdd-tasks-completed-task-1395-readonly-operator-commands-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: 'from aiogram.types import Message # verified: wrapper.py:22'
---

# TASK-1395: Read-only operator commands (/context, /memory, /model, /mission)

**Feature**: FEAT-210 — Telegram Operator Commands
**Spec**: `sdd/specs/FEAT-210-telegram-operator-commands.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1394
**Assigned-to**: unassigned

---

## Context

> Spec Module 2. Implements the four read-only operator commands that
> project local state (conversation memory, agent model) without consuming
> external features (FEAT-208/209). These commands form the self-contained
> core of the operator surface — they work immediately without needing
> heartbeat or sub-agent infrastructure.

---

## Scope

- Create `operator_commands.py` with an `OperatorCommandsMixin` class.
- Implement four handler methods on the mixin:
  - `handle_context(self, message)` — shows the conversation's shaping/system context.
  - `handle_memory(self, message)` — shows recent conversation turns (read-only, limited to N).
  - `handle_model(self, message)` — shows the agent's model name and use_llm (read-only, no mutation).
  - `handle_mission(self, message)` — shows the heartbeat mission (read-only); degrades if heartbeat absent.
- Each handler: checks `_is_operator(chat_id)` → rejects non-operators → projects data via `_send_safe_message`.
- Add formatting helpers: `_format_memory()`, `_format_context()`.
- `/memory` must truncate to a configurable limit (default 10 recent turns).
- `/mission` degrades elegantly if `HeartbeatManager` is not wired.
- Write unit tests for each handler.

**NOT in scope**: `/health`, `/status` (TASK-1396), `/thread` (TASK-1397), wiring/registration (TASK-1398).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-integrations/src/parrot/integrations/telegram/operator_commands.py` | CREATE | OperatorCommandsMixin with handle_context, handle_memory, handle_model, handle_mission |
| `packages/ai-parrot-integrations/tests/integrations/telegram/test_operator_commands_readonly.py` | CREATE | Unit tests for the 4 read-only commands |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: This section contains VERIFIED code references from the actual codebase.

### Verified Imports
```python
from aiogram.types import Message                          # verified: wrapper.py:22
from aiogram.filters import Command                        # verified: wrapper.py:32
```

### Existing Signatures to Use
```python
# packages/ai-parrot-integrations/src/parrot/integrations/telegram/wrapper.py:60
class TelegramAgentWrapper:
    self.agent          # line 87 — AbstractBot; has .model, .use_llm attributes
    self.config         # line 89 — TelegramAgentConfig
    self.conversations  # line 96 — Dict[int, "ConversationMemory"]
    self.router         # line 95 — aiogram Router

    def _is_operator(self, chat_id: int) -> bool:          # TASK-1394 creates this
    def _get_or_create_memory(self, chat_id: int):         # line 922 — returns ConversationMemory
    async def _send_safe_message(self, message, text, parse_mode=None):  # line 2579

    # Handler pattern to mirror (handle_help, line 1479):
    async def handle_help(self, message: Message) -> None:
        chat_id = message.chat.id
        if not self._is_authorized(chat_id):
            await message.answer("⛔ ...")
            return
        # ... build text ...
        await self._send_safe_message(message, text)
```

### Does NOT Exist
- ~~`operator_commands.py`~~ — does not exist yet; this task creates it
- ~~`OperatorCommandsMixin`~~ — does not exist yet; this task creates it
- ~~`self.memory`~~ — conversation state is `self.conversations: Dict[int, ConversationMemory]`, NOT `self.memory`
- ~~`self.agent.mission`~~ — mission lives on HeartbeatManager (FEAT-209), NOT on the agent
- ~~`HeartbeatManager`~~ — FEAT-209, not yet merged; import must be guarded (try/except)
- ~~`TelegramAgentConfig.model`~~ — the model info is on `self.agent` (`.model`, `.use_llm`), NOT on config

---

## Implementation Notes

### Pattern to Follow
```python
# operator_commands.py
class OperatorCommandsMixin:
    """Operator-only Telegram commands for the autonomous harness."""

    async def handle_model(self, message: Message) -> None:
        chat_id = message.chat.id
        if not self._is_operator(chat_id):
            await message.answer("⛔ Operator-only command.")
            return
        model = getattr(self.agent, 'model', 'unknown')
        use_llm = getattr(self.agent, 'use_llm', 'unknown')
        text = f"🤖 **Model**: `{model}`\n**Provider**: `{use_llm}`"
        await self._send_safe_message(message, text)
```

### Key Constraints
- All handlers are async, use `_is_operator` gate (from TASK-1394), reply via `_send_safe_message`
- `/memory`: limit output to N recent turns to avoid Telegram message size limits (4096 chars)
- `/mission`: guard import of HeartbeatManager with try/except ImportError → degrade message
- `/model` and `/mission` are strictly read-only — no setters, no mutation
- Use `getattr(self.agent, ...)` for safe attribute access on the agent

### References in Codebase
- `wrapper.py:1479` — `handle_help()` (handler pattern)
- `wrapper.py:1558` — `handle_whoami()` (simple projection pattern)
- `wrapper.py:922` — `_get_or_create_memory()` (conversation access)
- `wrapper.py:2579` — `_send_safe_message()` (safe reply)

---

## Acceptance Criteria

- [ ] `operator_commands.py` created with `OperatorCommandsMixin`
- [ ] `/context` projects conversation shaping context for the chat (read-only)
- [ ] `/memory` projects recent turns (limited, read-only, no mutation)
- [ ] `/model` shows `self.agent.model` and `self.agent.use_llm` (read-only)
- [ ] `/mission` shows heartbeat mission if available; degrades if HeartbeatManager absent
- [ ] Non-operator chat_ids are rejected by all 4 handlers
- [ ] Tests pass: `pytest packages/ai-parrot-integrations/tests/integrations/telegram/test_operator_commands_readonly.py -v`

---

## Test Specification

```python
# packages/ai-parrot-integrations/tests/integrations/telegram/test_operator_commands_readonly.py
import pytest
from unittest.mock import MagicMock, AsyncMock


class TestHandleMemory:
    async def test_readonly_projects_turns(self, op_wrapper):
        """Shows recent conversation turns without mutating."""
        ...

    async def test_truncates_to_limit(self, op_wrapper):
        """Long conversation is truncated to N recent turns."""
        ...

    async def test_non_operator_blocked(self, op_wrapper):
        """Non-operator gets rejection message."""
        ...


class TestHandleModel:
    async def test_readonly_shows_model(self, op_wrapper):
        """Shows agent model and use_llm."""
        ...

    async def test_no_mutation(self, op_wrapper):
        """Agent attributes unchanged after /model."""
        ...


class TestHandleContext:
    async def test_shows_context(self, op_wrapper):
        """Projects conversation context for the chat."""
        ...


class TestHandleMission:
    async def test_degrades_without_heartbeat(self, op_wrapper):
        """No HeartbeatManager → 'not configured' message."""
        ...

    async def test_shows_mission_with_heartbeat(self, op_wrapper):
        """With HeartbeatManager → projects mission text."""
        ...
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/FEAT-210-telegram-operator-commands.spec.md` for full context
2. **Check dependencies** — verify TASK-1394 is in `sdd/tasks/completed/`
3. **Verify the Codebase Contract** — before writing ANY code:
   - Confirm `_is_operator` exists on the wrapper (added by TASK-1394)
   - Confirm `_get_or_create_memory` at `wrapper.py:922`
   - Confirm `_send_safe_message` at `wrapper.py:2579`
   - Confirm `self.agent` has `.model` and `.use_llm` attributes
4. **Update status** in `sdd/tasks/index/telegram-operator-commands.json` → `"in-progress"`
5. **Implement** following the scope, codebase contract, and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-1395-readonly-operator-commands.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none | describe if any
