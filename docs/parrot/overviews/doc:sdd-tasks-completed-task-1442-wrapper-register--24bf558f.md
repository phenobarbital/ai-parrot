---
type: Wiki Overview
title: 'TASK-1442: Add `register_command_menu()` publisher to TelegramAgentWrapper'
id: doc:sdd-tasks-completed-task-1442-wrapper-register-command-menu-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: This is the **foundation** task (spec §3 Module 1). The menu-publish logic
---

# TASK-1442: Add `register_command_menu()` publisher to TelegramAgentWrapper

**Feature**: FEAT-220 — Telegram Command Menu Registration Parity (IntegrationBotManager)
**Spec**: `sdd/specs/telegram-integration-menu-registration.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

This is the **foundation** task (spec §3 Module 1). The menu-publish logic
currently lives only on `TelegramBotManager._register_bot_menu`
(`telegram/manager.py:231`), which is why the `IntegrationBotManager` startup
path never registers a menu. Moving the logic onto `TelegramAgentWrapper` —
which already owns both the `aiogram.Bot` (`self.bot`) and the command source
(`get_bot_commands()`) — creates a **single source of truth** that both
managers can call (TASK-1443, TASK-1444).

Implements spec §2 "New Public Interfaces" and the Module 1 responsibility.

---

## Scope

- Add `async def register_command_menu(self) -> None` to `TelegramAgentWrapper`.
  Relocate the body of `TelegramBotManager._register_bot_menu` into it:
  1. Build `bot_commands = self.get_bot_commands()`; if empty, log a warning and
     return (no `set_my_commands` call).
  2. Clear stale commands at `BotCommandScopeDefault`,
     `BotCommandScopeAllPrivateChats`, `BotCommandScopeAllGroupChats`
     (each in its own try/except — non-fatal).
  3. `await self.bot.set_my_commands(bot_commands)`; on exception, log with
     `exc_info=True` and fall back to per-command registration.
  4. `await self.bot.set_chat_menu_button(menu_button=MenuButtonCommands())`
     (try/except, non-fatal).
  5. Log how many of N commands were registered.
- Add a private fallback helper on the wrapper (e.g.
  `async def _register_commands_individually(self, bot_commands)`), mirroring
  `TelegramBotManager._register_commands_individually` (`telegram/manager.py:309`).
- The method must **never raise** on a Telegram API failure (defensive, so a
  caller's bot startup is unaffected). Whether to call it at all is the
  caller's decision via `config.register_menu` — do NOT check `register_menu`
  inside this method.
- Add the required `aiogram.types` imports to `wrapper.py` if not already present
  (`BotCommandScopeDefault`, `BotCommandScopeAllPrivateChats`,
  `BotCommandScopeAllGroupChats`, `MenuButtonCommands`).
- Write unit tests for the new method (see Test Specification).

**NOT in scope**:
- Editing `TelegramBotManager` to delegate — that is TASK-1443.
- Adding the call site in `IntegrationBotManager` — that is TASK-1444.
- Any `Dispatcher.startup` hook or per-chat scope handling (spec Non-Goals).
- Changing `get_bot_commands()` or how commands are declared/handled.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-integrations/src/parrot/integrations/telegram/wrapper.py` | MODIFY | Add `register_command_menu()` + `_register_commands_individually()`; add aiogram scope/menu-button imports. |
| `packages/ai-parrot-integrations/tests/integrations/telegram/test_wrapper_register_command_menu.py` | CREATE | Unit tests with a fake Bot recording API calls. |

---

## Codebase Contract (Anti-Hallucination)

> Verified against branch `dev` on 2026-06-04. Re-`grep` if you suspect drift.

### Verified Imports
```python
# Already imported in telegram/manager.py:14-19 (copy what wrapper.py lacks):
from aiogram.types import (
    BotCommand,
    BotCommandScopeAllGroupChats,
    BotCommandScopeAllPrivateChats,
    BotCommandScopeDefault,
    MenuButtonCommands,
)
# wrapper.py already imports BotCommand (wrapper.py:26).
```

### Existing Signatures to Use
```python
# packages/ai-parrot-integrations/src/parrot/integrations/telegram/wrapper.py
class TelegramAgentWrapper(OperatorCommandsMixin):              # line 62
    def __init__(self, agent, bot, config, agent_commands=None, *, app=None):  # line 80
        self.bot = bot                                          # line 90  (aiogram.Bot)
        self.logger = logging.getLogger(...)                    # line 99
        self._platform_commands: list[tuple[str, str]] = []     # line 131
    def get_bot_commands(self) -> list:                         # line 838  → returns list[BotCommand]

# SOURCE TO RELOCATE — packages/ai-parrot-integrations/src/parrot/integrations/telegram/manager.py
class TelegramBotManager:                                       # line 39
    async def _register_bot_menu(self, name, bot, wrapper) -> None:  # line 231
        bot_commands = wrapper.get_bot_commands()               # line 252
        # if not bot_commands: warn + return                    # lines 259-263
        # for scope in (Default(), AllPrivateChats(), AllGroupChats()): delete_my_commands  # lines 267-279
        await bot.set_my_commands(bot_commands)                 # line 283
        # except → _register_commands_individually(...)         # line 292
        await bot.set_chat_menu_button(menu_button=MenuButtonCommands())  # line 297
    async def _register_commands_individually(self, name, bot, bot_commands) -> List[BotCommand]:  # line 309
        # for cmd in bot_commands: try set_my_commands([*accepted, cmd]); accepted.append(cmd)  # lines 320-331
```

### Does NOT Exist
- ~~`TelegramAgentWrapper.register_command_menu`~~ — this task creates it.
- ~~`TelegramAgentWrapper.set_my_commands`~~ — the wrapper never called Telegram's `set_my_commands` before this task.
- ~~`TelegramAgentWrapper._register_bot_menu`~~ — only `TelegramBotManager` has `_register_bot_menu`.

---

## Implementation Notes

### Pattern to Follow
```python
# Mirror manager.py:231-332 almost verbatim, but read from `self`:
#   bot  -> self.bot
#   wrapper.get_bot_commands() -> self.get_bot_commands()
#   self.logger stays self.logger
# Keep the same log messages / exc_info=True behavior.
async def register_command_menu(self) -> None:
    try:
        bot_commands = self.get_bot_commands()
    except Exception:
        self.logger.exception("Failed to build Telegram menu commands")
        return
    if not bot_commands:
        self.logger.warning("No Telegram menu commands to register")
        return
    for scope in (BotCommandScopeDefault(), BotCommandScopeAllPrivateChats(),
                  BotCommandScopeAllGroupChats()):
        try:
            await self.bot.delete_my_commands(scope=scope)
        except Exception as e:
            self.logger.debug("delete_my_commands(scope=%s) failed: %s",
                              type(scope).__name__, e)
    try:
        await self.bot.set_my_commands(bot_commands)
        registered = bot_commands
    except Exception:
        self.logger.warning("Batch set_my_commands failed; falling back.",
                            exc_info=True)
        registered = await self._register_commands_individually(bot_commands)
    try:
        await self.bot.set_chat_menu_button(menu_button=MenuButtonCommands())
    except Exception:
        self.logger.warning("Failed to set chat menu button", exc_info=True)
    self.logger.info("Registered %d/%d Telegram menu commands",
                     len(registered), len(bot_commands))
```

### Key Constraints
- async throughout; await all aiogram coroutines.
- Use `self.logger` (already set, `wrapper.py:99`).
- Never raise on Telegram API errors.
- Do not check `config.register_menu` here (caller's responsibility).

### References in Codebase
- `packages/ai-parrot-integrations/src/parrot/integrations/telegram/manager.py:231-332` — logic to relocate.
- `packages/ai-parrot-integrations/tests/test_telegram_integration.py` — existing telegram test patterns / fake Bot.
- `packages/ai-parrot/tests/unit/test_telegram_jira_commands.py` — Jira-command test patterns.

---

## Acceptance Criteria

- [ ] `TelegramAgentWrapper.register_command_menu` exists and is `async`.
- [ ] It calls `self.bot.set_my_commands(self.get_bot_commands())` on the happy path.
- [ ] It clears Default / AllPrivateChats / AllGroupChats scopes before setting.
- [ ] It calls `set_chat_menu_button(MenuButtonCommands())`.
- [ ] On a batch failure it falls back to per-command registration (skips the bad entry).
- [ ] A raised Telegram API error is logged and swallowed (method returns normally).
- [ ] Empty command list → warning, no `set_my_commands` call.
- [ ] All tests pass: `pytest packages/ai-parrot-integrations/tests/integrations/telegram/test_wrapper_register_command_menu.py -v`
- [ ] No linting errors: `ruff check packages/ai-parrot-integrations/src/parrot/integrations/telegram/wrapper.py`

---

## Test Specification

```python
# packages/ai-parrot-integrations/tests/integrations/telegram/test_wrapper_register_command_menu.py
import pytest
from aiogram.types import BotCommand


class _FakeBot:
    """Records Bot API calls; can be told to fail the batch set."""
    def __init__(self, fail_batch=False):
        self.fail_batch = fail_batch
        self.set_calls = []          # each: list[BotCommand]
        self.deleted_scopes = []
        self.menu_button_set = False
        self._batch_done = False

    async def delete_my_commands(self, scope=None):
        self.deleted_scopes.append(type(scope).__name__)

    async def set_my_commands(self, commands, scope=None):
        if self.fail_batch and not self._batch_done:
            self._batch_done = True
            raise RuntimeError("400 Bad Request")
        self.set_calls.append(list(commands))

    async def set_chat_menu_button(self, menu_button=None):
        self.menu_button_set = True


def _make_wrapper(monkeypatch, bot, commands):
    # Construct a minimal wrapper OR build one and monkeypatch get_bot_commands.
    # Reuse the existing wrapper construction helpers in the telegram test suite.
    wrapper = ...  # build TelegramAgentWrapper with a stub agent/config
    wrapper.bot = bot
    monkeypatch.setattr(wrapper, "get_bot_commands", lambda: commands)
    return wrapper


class TestRegisterCommandMenu:
    async def test_happy_path_sets_commands_and_button(self, monkeypatch):
        bot = _FakeBot()
        cmds = [BotCommand(command="start", description="Start"),
                BotCommand(command="connect_jira", description="Connect Jira account")]
        wrapper = _make_wrapper(monkeypatch, bot, cmds)
        await wrapper.register_command_menu()
        assert bot.set_calls and bot.set_calls[-1] == cmds
        assert bot.menu_button_set is True
        assert "BotCommandScopeDefault" in bot.deleted_scopes

    async def test_jira_commands_included(self, monkeypatch):
        bot = _FakeBot()
        cmds = [BotCommand(command="connect_jira", description="Connect Jira account")]
        wrapper = _make_wrapper(monkeypatch, bot, cmds)
        await wrapper.register_command_menu()
        names = [c.command for c in bot.set_calls[-1]]
        assert "connect_jira" in names

    async def test_batch_failure_falls_back(self, monkeypatch):
        bot = _FakeBot(fail_batch=True)
        cmds = [BotCommand(command="start", description="Start"),
                BotCommand(command="help", description="Help")]
        wrapper = _make_wrapper(monkeypatch, bot, cmds)
        await wrapper.register_command_menu()
        # fallback registered commands individually (accepted list grows)
        assert bot.set_calls

    async def test_empty_list_skips(self, monkeypatch):
        bot = _FakeBot()
        wrapper = _make_wrapper(monkeypatch, bot, [])
        await wrapper.register_command_menu()
        assert bot.set_calls == []

    async def test_api_error_is_swallowed(self, monkeypatch):
        class _Boom(_FakeBot):
            async def set_my_commands(self, commands, scope=None):
                raise RuntimeError("network down")
            async def delete_my_commands(self, scope=None):
                raise RuntimeError("network down")
        bot = _Boom()
        cmds = [BotCommand(command="start", description="Start")]
        wrapper = _make_wrapper(monkeypatch, bot, cmds)
        await wrapper.register_command_menu()  # must not raise
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path above for full context (esp. §2 and §6).
2. **Check dependencies** — none.
3. **Verify the Codebase Contract** — confirm the line references in `manager.py`
   and `wrapper.py` before relocating; update the contract if drifted.
4. **Update status** in `sdd/tasks/index/telegram-integration-menu-registration.json` → `in-progress`.
5. **Implement** per scope.
6. **Verify** all acceptance criteria.
7. **Move this file** to `sdd/tasks/completed/`.
8. **Update index** → `done`.
9. **Fill in the Completion Note** below.

---

## Completion Note

**Completed by**: Claude Sonnet 4.6 (sdd-worker)
**Date**: 2026-06-04
**Notes**: Added `register_command_menu()` and `_register_commands_individually()` to
`TelegramAgentWrapper`. Added the four missing aiogram type imports
(`BotCommandScopeDefault`, `BotCommandScopeAllPrivateChats`, `BotCommandScopeAllGroupChats`,
`MenuButtonCommands`). Logic mirrors `TelegramBotManager._register_bot_menu` exactly but
reads from `self.bot` / `self.get_bot_commands()` / `self.logger`. 10/10 unit tests pass.

**Deviations from spec**: none
