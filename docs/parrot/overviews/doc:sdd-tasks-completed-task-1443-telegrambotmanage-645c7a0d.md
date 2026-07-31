---
type: Wiki Overview
title: 'TASK-1443: Delegate TelegramBotManager menu registration to the wrapper'
id: doc:sdd-tasks-completed-task-1443-telegrambotmanager-delegate-menu-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Implements spec §3 Module 2. Now that the publish logic lives on the wrapper
relates_to:
- concept: mod:parrot.integrations.telegram.wrapper
  rel: mentions
---

# TASK-1443: Delegate TelegramBotManager menu registration to the wrapper

**Feature**: FEAT-220 — Telegram Command Menu Registration Parity (IntegrationBotManager)
**Spec**: `sdd/specs/telegram-integration-menu-registration.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-1442
**Assigned-to**: unassigned

---

## Context

Implements spec §3 Module 2. Now that the publish logic lives on the wrapper
(TASK-1442), `TelegramBotManager._register_bot_menu` must delegate to it so there
is exactly one implementation. This path already works today — the goal here is
**no behavioral change**, only de-duplication.

---

## Scope

- Replace the body of `TelegramBotManager._register_bot_menu(name, bot, wrapper)`
  (`telegram/manager.py:231`) with a delegation:
  `await wrapper.register_command_menu()`.
  (The `name`/`bot` params may be kept for signature stability, or the call site
  at `start_bot:203` may call `wrapper.register_command_menu()` directly and the
  method removed — either is acceptable; prefer the smallest diff that keeps the
  `config.register_menu` gate at `start_bot:202` intact.)
- Remove `TelegramBotManager._register_commands_individually`
  (`telegram/manager.py:309`) ONLY if it becomes unused after delegation; if any
  other caller remains, leave it.
- Keep the `if agent_config.register_menu:` gate at `start_bot:202`.
- Add/adjust a regression test asserting `start_bot` still triggers menu
  registration when `register_menu=True` and skips it when `False`.

**NOT in scope**:
- The wrapper method itself (TASK-1442).
- The `IntegrationBotManager` call site (TASK-1444).
- Changing the `register_menu` default or config model.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-integrations/src/parrot/integrations/telegram/manager.py` | MODIFY | `_register_bot_menu` delegates to `wrapper.register_command_menu()`; drop now-dead fallback helper if unused. |
| `packages/ai-parrot-integrations/tests/test_telegram_integration.py` | MODIFY | Regression test: `start_bot` honors `register_menu` and delegates. |

---

## Codebase Contract (Anti-Hallucination)

> Verified against branch `dev` on 2026-06-04.

### Existing Signatures to Use
```python
# packages/ai-parrot-integrations/src/parrot/integrations/telegram/manager.py
class TelegramBotManager:                                       # line 39
    async def start_bot(self, name, agent_config) -> bool:      # line ~149
        wrapper = TelegramAgentWrapper(agent, bot, agent_config, agent_commands=agent_commands, app=app)  # line 195
        if agent_config.register_menu:                          # line 202  ← KEEP this gate
            await self._register_bot_menu(name, bot, wrapper)   # line 203
    async def _register_bot_menu(self, name, bot, wrapper) -> None:  # line 231  ← becomes delegator
    async def _register_commands_individually(self, name, bot, bot_commands):  # line 309  ← remove iff unused

# Provided by TASK-1442:
# TelegramAgentWrapper.register_command_menu(self) -> None  (async)
```

### Does NOT Exist
- ~~`TelegramBotManager.register_command_menu`~~ — the method lives on the **wrapper**, not the manager.
- ~~A `register_menu` field anywhere except `TelegramAgentConfig`~~ (`models.py:78`).

---

## Implementation Notes

### Pattern to Follow
```python
# Smallest-diff delegation:
async def _register_bot_menu(self, name, bot, wrapper) -> None:
    await wrapper.register_command_menu()
# (bot is still available on wrapper.bot; name is only used for logging,
#  which now happens inside the wrapper.)
```

### Key Constraints
- Preserve the `config.register_menu` gate (do NOT move it into the wrapper).
- No behavior change observable to Telegram for this path.
- async throughout.

### References in Codebase
- `packages/ai-parrot-integrations/src/parrot/integrations/telegram/manager.py:149-332`

---

## Acceptance Criteria

- [ ] `_register_bot_menu` delegates to `wrapper.register_command_menu()` (no inline `set_my_commands`).
- [ ] The `if agent_config.register_menu:` gate is preserved at the call site.
- [ ] Dead `_register_commands_individually` removed only if unused; otherwise left intact.
- [ ] Regression test: `register_menu=True` → wrapper menu registration invoked; `register_menu=False` → not invoked.
- [ ] All tests pass: `pytest packages/ai-parrot-integrations/tests/test_telegram_integration.py -v`
- [ ] No linting errors: `ruff check packages/ai-parrot-integrations/src/parrot/integrations/telegram/manager.py`

---

## Test Specification

```python
# packages/ai-parrot-integrations/tests/test_telegram_integration.py (add/extend)
import pytest
from unittest.mock import AsyncMock


class TestTelegramBotManagerMenuDelegation:
    async def test_start_bot_registers_menu_when_enabled(self, monkeypatch):
        # Build a TelegramBotManager + config with register_menu=True.
        # Patch TelegramAgentWrapper.register_command_menu with an AsyncMock and
        # assert it is awaited exactly once during start_bot.
        reg = AsyncMock()
        monkeypatch.setattr(
            "parrot.integrations.telegram.wrapper.TelegramAgentWrapper.register_command_menu",
            reg, raising=True,
        )
        ...  # invoke start_bot path
        reg.assert_awaited_once()

    async def test_start_bot_skips_menu_when_disabled(self, monkeypatch):
        reg = AsyncMock()
        monkeypatch.setattr(
            "parrot.integrations.telegram.wrapper.TelegramAgentWrapper.register_command_menu",
            reg, raising=True,
        )
        ...  # invoke start_bot with register_menu=False
        reg.assert_not_awaited()
```

---

## Agent Instructions

1. **Read the spec** (§2 Integration Points, §3 Module 2).
2. **Check dependencies** — TASK-1442 must be in `sdd/tasks/completed/`.
3. **Verify the Codebase Contract** before editing.
4. **Update status** in the per-spec index → `in-progress`.
5. **Implement** per scope.
6. **Verify** acceptance criteria.
7. **Move this file** to `sdd/tasks/completed/`.
8. **Update index** → `done`.
9. **Fill in the Completion Note**.

---

## Completion Note

**Completed by**: Claude Sonnet 4.6 (sdd-worker)
**Date**: 2026-06-04
**Notes**: Replaced `_register_bot_menu` body with `await wrapper.register_command_menu()`.
Removed now-dead `_register_commands_individually` (only caller was `_register_bot_menu`).
Removed five unused aiogram type imports (BotCommand, BotCommandScope*, MenuButtonCommands)
that were only used by the relocated logic. 3/3 regression tests pass.
Pre-existing `TestEnrichQuestion` failures confirmed unrelated to TASK-1443.

**Deviations from spec**: none | describe if any
