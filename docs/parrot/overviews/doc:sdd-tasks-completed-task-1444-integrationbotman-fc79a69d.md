---
type: Wiki Overview
title: 'TASK-1444: Register the command menu on the IntegrationBotManager path'
id: doc:sdd-tasks-completed-task-1444-integrationbotmanager-register-menu-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Implements spec §3 Module 3 — the actual bug fix. `IntegrationBotManager.
relates_to:
- concept: mod:parrot.integrations.telegram.wrapper
  rel: mentions
---

# TASK-1444: Register the command menu on the IntegrationBotManager path

**Feature**: FEAT-220 — Telegram Command Menu Registration Parity (IntegrationBotManager)
**Spec**: `sdd/specs/telegram-integration-menu-registration.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-1442
**Assigned-to**: unassigned

---

## Context

Implements spec §3 Module 3 — the actual bug fix. `IntegrationBotManager.
_start_telegram_bot` (`integrations/manager.py:174`) constructs the wrapper and
starts polling but **never registers the command menu**. This is the path
`JiraSpecialist` uses (its `TelegramHumanTool` requires the HITL `human_manager`
that only `IntegrationBotManager` wires), which is why `/connect_jira` /
`/disconnect_jira` work when typed but never appear in the menu/autocomplete.

Adding `await wrapper.register_command_menu()` (gated on `config.register_menu`)
closes the parity gap; since the wrapper is fully constructed first,
`_platform_commands` (incl. the Jira commands) is already populated and flows
into the published menu.

---

## Scope

- In `IntegrationBotManager._start_telegram_bot`, after
  `wrapper = TelegramAgentWrapper(agent, bot, config, app=app)`
  (`integrations/manager.py:197`), add:
  ```python
  if config.register_menu:
      try:
          await wrapper.register_command_menu()
      except Exception:
          self.logger.warning(
              "Failed to register Telegram command menu for '%s'", name,
              exc_info=True,
          )
  ```
  Place it before `dp.start_polling` is launched (before/around the
  `dp.include_router(wrapper.router)` at line 217). It does not need to precede
  the HITL channel wiring.
- Add a one-paragraph note to `docs/telegram_integration.md` stating that **both**
  startup managers publish the command menu (so platform/agent commands such as
  Jira appear in Telegram Desktop).
- Write unit + integration tests (see Test Specification).

**NOT in scope**:
- The wrapper method (TASK-1442) or the `TelegramBotManager` delegation (TASK-1443).
- `Dispatcher.startup` hooks or per-chat scoped menus (spec Non-Goals / §8).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-integrations/src/parrot/integrations/manager.py` | MODIFY | Add gated `await wrapper.register_command_menu()` in `_start_telegram_bot`. |
| `docs/telegram_integration.md` | MODIFY | Note that both managers publish the command menu. |
| `packages/ai-parrot-integrations/tests/test_telegram_integration.py` | MODIFY | Unit test: integration path registers menu (and respects `register_menu`). |
| `packages/ai-parrot-integrations/tests/integrations/telegram/test_integration_menu_parity.py` | CREATE | Integration test: Jira commands appear in the published list via the integration path. |

---

## Codebase Contract (Anti-Hallucination)

> Verified against branch `dev` on 2026-06-04.

### Existing Signatures to Use
```python
# packages/ai-parrot-integrations/src/parrot/integrations/manager.py
class IntegrationBotManager:                                    # line 46
    async def _start_telegram_bot(self, name: str, config: TelegramAgentConfig):  # line 174
        ...
        try:
            app = self.bot_manager.get_app()                    # line 194
        except RuntimeError:
            app = None
        wrapper = TelegramAgentWrapper(agent, bot, config, app=app)  # line 197  ← INSERT call after this
        human_manager = await self._ensure_human_manager()      # line 203 (HITL — leave as-is)
        dp.include_router(wrapper.router)                       # line 217
        task = asyncio.create_task(self._run_polling(name, dp, bot), ...)  # line 226
    # self.logger exists on the manager (used elsewhere in this file).

# Config flag — packages/ai-parrot-integrations/src/parrot/integrations/telegram/models.py
class TelegramAgentConfig(...):
    register_menu: bool = True                                  # line 78

# Provided by TASK-1442:
# TelegramAgentWrapper.register_command_menu(self) -> None  (async; never raises on API error,
#   but wrap defensively anyway since startup must not abort)

# Why this path (verification):
# packages/ai-parrot/src/parrot/bots/jira_specialist.py
#   def agent_tools(self): return [TelegramHumanTool(source_agent=self.agent_id)]  # line 268/276
#   → needs HITL human_manager wired only by IntegrationBotManager (manager.py:203-216)
# packages/ai-parrot-integrations/src/parrot/integrations/telegram/wrapper.py
#   _register_jira_commands(): if app.get("jira_oauth_manager") -> _add_platform_commands([...])  # line 345/377
#   get_bot_commands(): includes self._platform_commands                                          # line 838/875
```

### Does NOT Exist
- ~~`IntegrationBotManager._register_bot_menu`~~ — does not exist (the gap this task fixes).
- ~~`IntegrationManager`~~ — the class is `IntegrationBotManager` (`manager.py:46`).
- ~~a `register_menu` check already in `integrations/manager.py`~~ — none today.

---

## Implementation Notes

### Pattern to Follow
- Mirror the gate `TelegramBotManager` uses (`manager.py:202`): only register when
  `config.register_menu` is truthy.
- Defensive try/except around the call so a Telegram failure can never abort
  `_start_telegram_bot` (the method already `create_task`s polling afterward).
- Call AFTER wrapper construction so `_platform_commands` (Jira/Office365/MCP) is populated.

### Key Constraints
- async throughout; `await wrapper.register_command_menu()`.
- Use `self.logger` on the manager for the defensive warning.
- Do not reorder the HITL channel wiring.

### References in Codebase
- `packages/ai-parrot-integrations/src/parrot/integrations/telegram/manager.py:202-203` — the parity gate to mirror.
- `packages/ai-parrot-integrations/src/parrot/integrations/manager.py:174-233` — method to edit.

---

## Acceptance Criteria

- [ ] `_start_telegram_bot` calls `await wrapper.register_command_menu()` after wrapper construction.
- [ ] The call is gated on `config.register_menu` and wrapped so failures don't abort startup.
- [ ] With `jira_oauth_manager` present, the published command list includes `connect_jira`, `disconnect_jira`, `jira_status` alongside built-ins.
- [ ] `register_menu=False` → no menu registration on this path.
- [ ] `docs/telegram_integration.md` notes both managers publish the menu.
- [ ] All tests pass: `pytest packages/ai-parrot-integrations/tests/ -v` (affected files).
- [ ] No linting errors: `ruff check packages/ai-parrot-integrations/src/parrot/integrations/manager.py`

---

## Test Specification

```python
# packages/ai-parrot-integrations/tests/integrations/telegram/test_integration_menu_parity.py
import pytest
from unittest.mock import AsyncMock
from aiogram.types import BotCommand


class TestIntegrationManagerMenuParity:
    async def test_integration_path_registers_menu(self, monkeypatch):
        reg = AsyncMock()
        monkeypatch.setattr(
            "parrot.integrations.telegram.wrapper.TelegramAgentWrapper.register_command_menu",
            reg, raising=True,
        )
        # Drive IntegrationBotManager._start_telegram_bot with register_menu=True
        # (stub get_app / agent / polling so the method runs to the call site).
        ...
        reg.assert_awaited_once()

    async def test_integration_path_skips_when_disabled(self, monkeypatch):
        reg = AsyncMock()
        monkeypatch.setattr(
            "parrot.integrations.telegram.wrapper.TelegramAgentWrapper.register_command_menu",
            reg, raising=True,
        )
        ...  # register_menu=False
        reg.assert_not_awaited()

    async def test_published_list_includes_jira_commands(self, monkeypatch):
        # With app['jira_oauth_manager'] present, build the wrapper and assert
        # get_bot_commands() (the list register_command_menu publishes) contains
        # the Jira platform commands.
        ...
        names = [c.command for c in wrapper.get_bot_commands()]
        assert {"connect_jira", "disconnect_jira", "jira_status"} <= set(names)
```

---

## Agent Instructions

1. **Read the spec** (§1 root cause, §3 Module 3, §6).
2. **Check dependencies** — TASK-1442 must be in `sdd/tasks/completed/`.
3. **Verify the Codebase Contract** before editing.
4. **Update status** in the per-spec index → `in-progress`.
5. **Implement** per scope.
6. **Verify** acceptance criteria (manually confirm the menu appears in Telegram Desktop if possible).
7. **Move this file** to `sdd/tasks/completed/`.
8. **Update index** → `done`.
9. **Fill in the Completion Note**.

---

## Completion Note

**Completed by**: Claude Sonnet 4.6 (sdd-worker)
**Date**: 2026-06-04
**Notes**: Added `if config.register_menu: try: await wrapper.register_command_menu() except Exception: self.logger.warning(...)` 
in `IntegrationBotManager._start_telegram_bot` after wrapper construction (line ~197). Also removed
pre-existing unused `TelegramHumanChannel` TYPE_CHECKING import (bonus fix, not breaking).
Added docs note to `docs/telegram_integration.md`. 4 unit tests in test_telegram_integration.py
(TestIntegrationBotManagerMenuRegistration) + 6 integration parity tests in
test_integration_menu_parity.py all pass. 3 pre-existing TestEnrichQuestion failures confirmed
unrelated.

**Deviations from spec**: none
