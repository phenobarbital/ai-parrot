---
type: Wiki Overview
title: 'TASK-1398: Wiring, registration, and integration tests'
id: doc:sdd-tasks-completed-task-1398-operator-wiring-registration-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: with the router, gated on `enable_operator_commands`.
relates_to:
- concept: mod:parrot.integrations.telegram.operator_commands
  rel: mentions
---

# TASK-1398: Wiring, registration, and integration tests

**Feature**: FEAT-210 — Telegram Operator Commands
**Spec**: `sdd/specs/FEAT-210-telegram-operator-commands.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1394, TASK-1395, TASK-1396, TASK-1397
**Assigned-to**: unassigned

---

## Context

> Spec Module 5. Wires everything together: mixes `OperatorCommandsMixin`
> into `TelegramAgentWrapper`, adds `_register_operator_commands()` to
> register all 7 handlers, updates `/help` to show operator commands to
> operators, and writes integration tests for registration and zero-regression.

---

## Scope

- Mix `OperatorCommandsMixin` into `TelegramAgentWrapper` class hierarchy.
- Add `_register_operator_commands(self)` method to register all 7 Command handlers
  with the router, gated on `enable_operator_commands`.
- Call `_register_operator_commands()` from `_register_handlers()`.
- Update `handle_help` (or `_build_command_entries`) to show operator commands
  only to operator chat_ids.
- Write integration tests:
  - All 7 commands registered when `enable_operator_commands=True`.
  - Zero registered when `enable_operator_commands=False`.
  - Existing commands (`/help`, `/clear`, etc.) still work (zero regression).
- Verify `__init__.py` exports if needed.

**NOT in scope**: individual handler logic (TASK-1395–1397), config/gate (TASK-1394).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-integrations/src/parrot/integrations/telegram/wrapper.py` | MODIFY | Mix in OperatorCommandsMixin, add _register_operator_commands(), call from _register_handlers() |
| `packages/ai-parrot-integrations/src/parrot/integrations/telegram/operator_commands.py` | MODIFY | Add _register_operator_commands() if not already a mixin method |
| `packages/ai-parrot-integrations/tests/integrations/telegram/test_operator_integration.py` | CREATE | Integration tests for registration and zero-regression |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: This section contains VERIFIED code references from the actual codebase.

### Verified Imports
```python
from aiogram.filters import Command, CommandStart           # verified: wrapper.py:32
from aiogram.types import Message, BotCommand               # verified: wrapper.py:22,26
from parrot.integrations.telegram.operator_commands import OperatorCommandsMixin  # TASK-1395 creates this
```

### Existing Signatures to Use
```python
# packages/ai-parrot-integrations/src/parrot/integrations/telegram/wrapper.py:60
class TelegramAgentWrapper:   # line 60
    self.router         # line 95 — aiogram Router
    self.config         # line 89 — TelegramAgentConfig (has enable_operator_commands from TASK-1394)

    def _register_handlers(self) -> None:   # line 180 — command registration hub
        # Pattern (lines 183-207):
        self.router.message.register(self.handle_start, CommandStart())
        self.router.message.register(self.handle_help, Command("help"))
        self.router.message.register(self.handle_whoami, Command("whoami"))
        # ...
        # NEW: self._register_operator_commands() goes here

    async def handle_help(self, message: Message) -> None:  # line 1479
        # Builds command list text — extend for operators

    # Command registration helper pattern (line 303):
    def _register_custom_command(self, cmd_name: str, method_name: str) -> None:
        # self.router.message.register(custom_handler, Command(cmd_name))
```

### Does NOT Exist
- ~~`_register_operator_commands()`~~ — does not exist yet; this task creates it
- ~~Operator commands in `_register_handlers()`~~ — not yet registered; this task adds them
- ~~`OperatorCommandsMixin` in wrapper.py's class bases~~ — not yet mixed in; this task wires it

---

## Implementation Notes

### Pattern to Follow
```python
# In wrapper.py, update class definition:
from parrot.integrations.telegram.operator_commands import OperatorCommandsMixin

class TelegramAgentWrapper(OperatorCommandsMixin, ...):
    ...

    def _register_handlers(self) -> None:
        # ... existing registrations ...
        # Add operator commands (gated)
        if getattr(self.config, 'enable_operator_commands', True):
            self._register_operator_commands()

    def _register_operator_commands(self) -> None:
        self.router.message.register(self.handle_health, Command("health"))
        self.router.message.register(self.handle_status, Command("status"))
        self.router.message.register(self.handle_context, Command("context"))
        self.router.message.register(self.handle_memory, Command("memory"))
        self.router.message.register(self.handle_mission, Command("mission"))
        self.router.message.register(self.handle_model, Command("model"))
        self.router.message.register(self.handle_thread, Command("thread"))
```

### Key Constraints
- `_register_operator_commands()` MUST be called BEFORE the generic text handler registration
  (otherwise `Command("x")` won't catch the messages — they'll be consumed by the text handler first)
- Mixin must not break existing wrapper functionality — test for zero regression
- `/help` should show operator commands only when `_is_operator(chat_id)` is True
- Registration is conditional on `enable_operator_commands` config flag

### References in Codebase
- `wrapper.py:180-207` — existing handler registration sequence (add before generic handlers)
- `wrapper.py:303` — `_register_custom_command()` (alternative registration pattern)
- `wrapper.py:1479` — `handle_help()` (extend to include operator commands for operators)

---

## Acceptance Criteria

- [ ] `OperatorCommandsMixin` mixed into `TelegramAgentWrapper` class
- [ ] `_register_operator_commands()` registers all 7 Command handlers
- [ ] Registration gated on `enable_operator_commands=True`
- [ ] `_register_operator_commands()` called from `_register_handlers()` (before generic text handler)
- [ ] `/help` shows operator commands to operators, hides from non-operators
- [ ] `enable_operator_commands=False` → zero operator commands registered
- [ ] Existing commands (`/help`, `/clear`, `/whoami`, etc.) still work — zero regression
- [ ] Tests pass: `pytest packages/ai-parrot-integrations/tests/integrations/telegram/test_operator_integration.py -v`

---

## Test Specification

```python
# packages/ai-parrot-integrations/tests/integrations/telegram/test_operator_integration.py
import pytest
from unittest.mock import MagicMock, AsyncMock


class TestOperatorRegistration:
    def test_commands_registered_when_enabled(self, op_wrapper):
        """enable_operator_commands=True → 7 operator Commands registered in router."""
        ...

    def test_commands_not_registered_when_disabled(self):
        """enable_operator_commands=False → zero operator commands in router."""
        ...


class TestZeroRegression:
    def test_help_still_works(self, op_wrapper):
        """/help still registered and returns a response."""
        ...

    def test_clear_still_works(self, op_wrapper):
        """/clear still registered and clears conversation."""
        ...

    def test_whoami_still_works(self, op_wrapper):
        """/whoami still registered and shows user info."""
        ...


class TestHelpOperatorVisibility:
    async def test_help_shows_operator_cmds_for_operator(self, op_wrapper):
        """Operator sees operator commands in /help output."""
        ...

    async def test_help_hides_operator_cmds_for_non_operator(self, op_wrapper):
        """Non-operator does not see operator commands in /help output."""
        ...
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/FEAT-210-telegram-operator-commands.spec.md` for full context
2. **Check dependencies** — verify TASK-1394, TASK-1395, TASK-1396, TASK-1397 are all in `sdd/tasks/completed/`
3. **Verify the Codebase Contract** — before writing ANY code:
   - Confirm `OperatorCommandsMixin` exists in `operator_commands.py` (from TASK-1395)
   - Confirm all 7 handler methods exist on the mixin
   - Confirm `_register_handlers()` at `wrapper.py:180` still has the same structure
   - Confirm registration happens before the generic text handler
4. **Update status** in `sdd/tasks/index/telegram-operator-commands.json` → `"in-progress"`
5. **Implement** following the scope, codebase contract, and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-1398-operator-wiring-registration.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none | describe if any
