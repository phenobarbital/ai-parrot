---
type: Wiki Overview
title: 'TASK-1397: /thread command (fork → ephemeral sub-agent)'
id: doc:sdd-tasks-completed-task-1397-thread-command-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: 'from aiogram.types import Message # verified: wrapper.py:22'
---

# TASK-1397: /thread command (fork → ephemeral sub-agent)

**Feature**: FEAT-210 — Telegram Operator Commands
**Spec**: `sdd/specs/FEAT-210-telegram-operator-commands.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1394, TASK-1395
**Assigned-to**: unassigned

---

## Context

> Spec Module 4. Implements `/thread <task>` — the only operator command
> that mutates state by spawning an ephemeral sub-agent (FEAT-208) to
> handle a parallel task. This is the most complex individual handler
> because it involves async sub-agent lifecycle, timeout management, and
> result delivery back to the chat. Degrades if FEAT-208 spawn is not wired.

---

## Scope

- Add `handle_thread(self, message)` to `OperatorCommandsMixin`:
  - Parses `<task>` text from the message after `/thread`.
  - Spawns an ephemeral sub-agent via FEAT-208 APIs (BotManager / SpawnSubAgentTool).
  - Sends a "processing..." indicator while the sub-agent works.
  - Delivers the sub-agent result back to the operator chat.
  - Degrades to "sub-agents not available" if FEAT-208 is not wired.
- Handle timeout: if sub-agent takes too long, respond with a timeout message.
- Write unit tests with faked spawn APIs.

**NOT in scope**: `/health`, `/status` (TASK-1396), `/context`, `/memory`, `/model`, `/mission` (TASK-1395), wiring (TASK-1398).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-integrations/src/parrot/integrations/telegram/operator_commands.py` | MODIFY | Add handle_thread to OperatorCommandsMixin |
| `packages/ai-parrot-integrations/tests/integrations/telegram/test_operator_commands_thread.py` | CREATE | Unit tests for /thread with fakes |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: This section contains VERIFIED code references from the actual codebase.

### Verified Imports
```python
from aiogram.types import Message                          # verified: wrapper.py:22
```

### Existing Signatures to Use
```python
# packages/ai-parrot-integrations/src/parrot/integrations/telegram/wrapper.py:60
class TelegramAgentWrapper:
    self.agent          # line 87 — AbstractBot instance
    self.app            # line 94 — aiohttp web.Application
    self.config         # line 89 — TelegramAgentConfig
    self.router         # line 95 — aiogram Router

    def _is_operator(self, chat_id: int) -> bool:          # TASK-1394
    async def _send_safe_message(self, message, text, parse_mode=None):  # line 2579

# operator_commands.py (created by TASK-1395)
class OperatorCommandsMixin:
    # Extend with handle_thread
    ...
```

### FEAT-208 Interface (guarded import — may not exist at implementation time)
```python
# Ephemeral sub-agent spawn (FEAT-208 — NOT yet merged)
# Import MUST be guarded: try: ... except ImportError: ...
# Access pattern likely via self.app.get('bot_manager') or self.agent's tools
# SpawnSubAgentTool or BotManager.create_ephemeral_user_bot()
```

### Does NOT Exist
- ~~`self.spawn_agent()`~~ — no such method on TelegramAgentWrapper
- ~~`self.threads`~~ — no thread tracking on the wrapper
- ~~`self.bot_manager`~~ — access via `self.app.get(...)`, not a direct attribute
- ~~`SpawnSubAgentTool`~~ — FEAT-208, not yet merged; must guard imports
- ~~`self.agent.fork()`~~ — agents don't have a fork method

---

## Implementation Notes

### Pattern to Follow
```python
async def handle_thread(self, message: Message) -> None:
    chat_id = message.chat.id
    if not self._is_operator(chat_id):
        await message.answer("⛔ Operator-only command.")
        return

    task_text = message.text.split(maxsplit=1)
    if len(task_text) < 2:
        await self._send_safe_message(message, "Usage: `/thread <task description>`")
        return

    task = task_text[1]
    bot_manager = self.app.get('bot_manager') if hasattr(self, 'app') and self.app else None
    if bot_manager is None:
        await self._send_safe_message(message, "ℹ️ Sub-agents not available.")
        return

    await self._send_safe_message(message, f"🧵 Spawning sub-agent for: _{task}_")
    # ... spawn and await result ...
```

### Key Constraints
- ALL imports of FEAT-208 modules MUST be guarded (try/except ImportError)
- Use typing indicator / "processing..." message while sub-agent works
- Implement a reasonable timeout (configurable or hardcoded ~120s)
- Parse task text safely — handle empty `/thread` with usage message
- Result delivery must respect Telegram's 4096-char message limit (truncate if needed)
- async/await throughout — never block the event loop waiting for the sub-agent

### References in Codebase
- `wrapper.py:2579` — `_send_safe_message()` (safe reply with markdown fallback)
- FEAT-208 spec for sub-agent spawn interface

---

## Acceptance Criteria

- [ ] `/thread <task>` spawns a sub-agent and returns its result
- [ ] `/thread` with no arguments shows usage message
- [ ] Degrades to "sub-agents not available" when FEAT-208 is not wired
- [ ] Non-operator chat_ids rejected
- [ ] Timeout handling: responds if sub-agent exceeds time limit
- [ ] All FEAT-208 imports guarded (try/except ImportError)
- [ ] Tests pass: `pytest packages/ai-parrot-integrations/tests/integrations/telegram/test_operator_commands_thread.py -v`

---

## Test Specification

```python
# packages/ai-parrot-integrations/tests/integrations/telegram/test_operator_commands_thread.py
import pytest
from unittest.mock import MagicMock, AsyncMock


class TestHandleThread:
    async def test_spawns_subagent(self, op_wrapper):
        """/thread <task> invokes spawn (fake) and returns result."""
        ...

    async def test_degrades_without_spawn(self, op_wrapper):
        """No bot_manager → 'sub-agents not available'."""
        ...

    async def test_no_task_shows_usage(self, op_wrapper):
        """/thread with no arguments → usage message."""
        ...

    async def test_non_operator_blocked(self, op_wrapper):
        """Non-operator gets rejection."""
        ...

    async def test_timeout_handling(self, op_wrapper):
        """Sub-agent exceeds timeout → timeout message."""
        ...
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/FEAT-210-telegram-operator-commands.spec.md` for full context
2. **Check dependencies** — verify TASK-1394 and TASK-1395 are in `sdd/tasks/completed/`
3. **Verify the Codebase Contract** — before writing ANY code:
   - Confirm `operator_commands.py` exists with `OperatorCommandsMixin` (from TASK-1395)
   - Confirm `_is_operator` exists on the wrapper (from TASK-1394)
   - Check if FEAT-208 sub-agent APIs are available (`grep -r SpawnSubAgent parrot/` or `grep -r BotManager parrot/`)
4. **Update status** in `sdd/tasks/index/telegram-operator-commands.json` → `"in-progress"`
5. **Implement** following the scope, codebase contract, and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-1397-thread-command.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none | describe if any
