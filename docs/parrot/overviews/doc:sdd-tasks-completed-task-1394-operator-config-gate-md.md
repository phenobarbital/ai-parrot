---
type: Wiki Overview
title: 'TASK-1394: Operator config fields and authorization gate'
id: doc:sdd-tasks-completed-task-1394-operator-config-gate-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: fields to `TelegramAgentConfig` in `models.py`.
relates_to:
- concept: mod:parrot.integrations.telegram.wrapper
  rel: mentions
---

# TASK-1394: Operator config fields and authorization gate

**Feature**: FEAT-210 — Telegram Operator Commands
**Spec**: `sdd/specs/FEAT-210-telegram-operator-commands.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

> Spec Module 1. The operator gate is the foundation for all 7 operator
> commands. It adds `operator_chat_ids` and `enable_operator_commands` to
> the Telegram config model and implements a fail-closed `_is_operator()`
> method on the wrapper. Every subsequent task depends on this gate.

---

## Scope

- Add `operator_chat_ids: Optional[list[int]]` and `enable_operator_commands: bool = True`
  fields to `TelegramAgentConfig` in `models.py`.
- Implement `_is_operator(self, chat_id: int) -> bool` on `TelegramAgentWrapper`.
  - **Fail-closed**: returns `False` when `operator_chat_ids is None` or empty.
  - Only returns `True` when `chat_id` is in the configured allowlist.
- Write unit tests for the gate logic.

**NOT in scope**: command handlers, registration, mixin — those are TASK-1395 to TASK-1398.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-integrations/src/parrot/integrations/telegram/models.py` | MODIFY | Add `operator_chat_ids` and `enable_operator_commands` fields to `TelegramAgentConfig` |
| `packages/ai-parrot-integrations/src/parrot/integrations/telegram/wrapper.py` | MODIFY | Add `_is_operator(self, chat_id: int) -> bool` method |
| `packages/ai-parrot-integrations/tests/integrations/telegram/test_operator_gate.py` | CREATE | Unit tests for operator gate |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: This section contains VERIFIED code references from the actual codebase.
> The implementing agent MUST use these exact imports, class names, and method signatures.
> **DO NOT** invent, guess, or assume any import, attribute, or method not listed here.

### Verified Imports
```python
from aiogram.types import Message                          # verified: wrapper.py:22
from parrot.integrations.telegram.wrapper import TelegramAgentWrapper  # verified: tests import it
```

### Existing Signatures to Use
```python
# packages/ai-parrot-integrations/src/parrot/integrations/telegram/models.py:39
class TelegramAgentConfig(...):
    allowed_chat_ids: Optional[List[int]] = None   # line 63 — reference for operator_chat_ids pattern

# packages/ai-parrot-integrations/src/parrot/integrations/telegram/wrapper.py:60
class TelegramAgentWrapper:
    self.config    # line 89 — TelegramAgentConfig instance
    def _is_authorized(self, chat_id: int) -> bool:   # line 916 — mirrors this pattern (but fail-open if None)
```

### Does NOT Exist
- ~~`TelegramAgentConfig.operator_chat_ids`~~ — does not exist yet; this task creates it
- ~~`TelegramAgentConfig.enable_operator_commands`~~ — does not exist yet; this task creates it
- ~~`TelegramAgentWrapper._is_operator`~~ — does not exist yet; this task creates it
- ~~`self.operator_ids`~~ or ~~`self.operators`~~ — no such attribute on the wrapper

---

## Implementation Notes

### Pattern to Follow
```python
# _is_authorized pattern (wrapper.py:916) — but OPPOSITE default:
# _is_authorized: None → everyone allowed (fail-open)
# _is_operator:   None → nobody allowed (fail-closed)
def _is_operator(self, chat_id: int) -> bool:
    if not self.config.enable_operator_commands:
        return False
    if not self.config.operator_chat_ids:
        return False
    return chat_id in self.config.operator_chat_ids
```

### Key Constraints
- `_is_operator` MUST be fail-closed (spec G2): `operator_chat_ids=None` → nobody is operator
- Do NOT inherit `_is_authorized`'s permissive behavior (where `None` means "allow all")
- New config fields must have defaults that don't break existing configs (both are optional)
- Use Pydantic typing consistent with existing fields in `models.py`

### References in Codebase
- `models.py:63` — `allowed_chat_ids: Optional[List[int]] = None` (pattern for the new field)
- `wrapper.py:916` — `_is_authorized()` (pattern to mirror with opposite default)

---

## Acceptance Criteria

- [ ] `TelegramAgentConfig` has `operator_chat_ids: Optional[list[int]] = None`
- [ ] `TelegramAgentConfig` has `enable_operator_commands: bool = True`
- [ ] `_is_operator(chat_id)` returns `False` when `operator_chat_ids is None`
- [ ] `_is_operator(chat_id)` returns `False` when `enable_operator_commands is False`
- [ ] `_is_operator(chat_id)` returns `True` only for chat_ids in the allowlist
- [ ] Existing config parsing not broken (new fields have safe defaults)
- [ ] Tests pass: `pytest packages/ai-parrot-integrations/tests/integrations/telegram/test_operator_gate.py -v`

---

## Test Specification

```python
# packages/ai-parrot-integrations/tests/integrations/telegram/test_operator_gate.py
import pytest
from unittest.mock import MagicMock


class TestIsOperator:
    def test_failclosed_none(self):
        """operator_chat_ids=None → _is_operator returns False for everyone."""
        ...

    def test_failclosed_empty(self):
        """operator_chat_ids=[] → _is_operator returns False for everyone."""
        ...

    def test_allowlist_match(self):
        """Chat ID in operator_chat_ids → True."""
        ...

    def test_allowlist_no_match(self):
        """Chat ID NOT in operator_chat_ids → False."""
        ...

    def test_disabled_flag(self):
        """enable_operator_commands=False → _is_operator returns False even if chat_id in list."""
        ...

    def test_authorized_but_not_operator(self):
        """A chat_id in allowed_chat_ids but NOT in operator_chat_ids → _is_operator False."""
        ...
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/FEAT-210-telegram-operator-commands.spec.md` for full context
2. **Check dependencies** — this task has no dependencies
3. **Verify the Codebase Contract** — before writing ANY code:
   - Confirm `TelegramAgentConfig` at `models.py:39` still has `allowed_chat_ids` at line 63
   - Confirm `_is_authorized` at `wrapper.py:916` still exists with same signature
   - If anything has changed, update the contract FIRST, then implement
4. **Update status** in `sdd/tasks/index/telegram-operator-commands.json` → `"in-progress"`
5. **Implement** following the scope, codebase contract, and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-1394-operator-config-gate.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none | describe if any
