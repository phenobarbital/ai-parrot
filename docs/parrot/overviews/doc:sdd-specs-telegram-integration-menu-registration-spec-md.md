---
type: Wiki Overview
title: 'Feature Specification: Telegram Command Menu Registration Parity (IntegrationBotManager)'
id: doc:sdd-specs-telegram-integration-menu-registration-spec-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Agent-driven Telegram bots booted through the **unified integration path**
relates_to:
- concept: mod:parrot.integrations.telegram
  rel: mentions
---

---
# SDD flow type and base branch (FEAT-145).
# - type: feature  (default)  → base_branch: dev (or any non-main branch)
# - type: hotfix              → base_branch MUST be: main
type: feature
base_branch: dev
---

# Feature Specification: Telegram Command Menu Registration Parity (IntegrationBotManager)

**Feature ID**: FEAT-220
**Date**: 2026-06-04
**Author**: Jesus Lara
**Status**: approved
**Target version**: (next minor)

> Source brainstorm: `sdd/proposals/telegram-integration-menu-registration.brainstorm.md`
> (Recommended Option A — move menu registration into the wrapper; both managers call it.)

---

## 1. Motivation & Business Requirements

> Why does this feature exist? What problem does it solve?

### Problem Statement

Agent-driven Telegram bots booted through the **unified integration path**
(`IntegrationBotManager`) never publish their command menu to Telegram.
Commands such as `/connect_jira` and `/disconnect_jira` (provided by a
`JiraSpecialist` agent) **work when typed manually** but **do not appear** in:

- the Telegram Desktop **command menu** (the menu button), nor
- the **`/`-autocomplete** list shown while typing in the chat input.

The standard commands (`/start`, `/help`, `/clear`, `/whoami`, …) *do* appear,
but they are **stale** — left over from an earlier `setMyCommands` push (a prior
code version, a one-off `TelegramBotManager` run, or BotFather). They are never
refreshed on the integration path, which is why newer agent/platform commands
never surface.

**Root cause (verified):** there are two Telegram startup paths and they are not
at parity. `TelegramBotManager.start_bot` calls `_register_bot_menu()` →
`setMyCommands` (gated on `config.register_menu`). `IntegrationBotManager.
_start_telegram_bot` constructs the wrapper and starts polling but **never calls
`_register_bot_menu()`**. `JiraSpecialist.agent_tools()` returns a
`TelegramHumanTool`, which requires the HITL `human_manager` that **only
`IntegrationBotManager` wires** — so `JiraSpecialist` always runs on the path
that skips menu registration. The Jira *handlers* work because the wrapper
constructor calls `_register_jira_commands()` (which registers the aiogram
`Command` handlers and records the commands in `_platform_commands`) when
`app['jira_oauth_manager']` is present; but nothing on this path pushes that
command list to Telegram.

### Goals

- Publish the Telegram command menu (`setMyCommands` + chat menu button) on the
  `IntegrationBotManager` startup path **at parity** with `TelegramBotManager`.
- Ensure the published menu includes **all** command sources the wrapper already
  aggregates: built-ins, login/logout, `_platform_commands`
  (Jira/Office365/MCP), YAML `config.commands`, and `@telegram_command` commands.
- Establish a **single source of truth** for menu registration so the two
  managers can never drift out of parity again.
- Preserve the existing **resilient** registration behavior (scope clearing,
  batch with per-command fallback, menu-button set, graceful failure).

### Non-Goals (explicitly out of scope)

- A `Dispatcher.startup` hook for late-wiring robustness (brainstorm Option C) —
  the current defect is a *missing call*, not an ordering race; `_platform_commands`
  is already populated at wrapper construction. May be layered later.
- Clearing/refreshing **per-chat scoped** command menus (`BotCommandScopeChat`)
  — out of scope unless a deployment is found relying on them (see §8).
- Any change to how commands are *declared* or *handled* — only how the menu is
  *published* changes.
- Runtime/dynamic menu refresh after user login or tool-set changes.

---

## 2. Architectural Design

### Overview

Adopt brainstorm **Option A**: move the menu-registration logic out of
`TelegramBotManager` and onto `TelegramAgentWrapper` as a public coroutine
(`async def register_command_menu(self) -> None`). The wrapper already owns both
the `aiogram.Bot` instance (`self.bot`, `wrapper.py:90`) and the command source
(`self.get_bot_commands()`, `wrapper.py:838`), so it is the natural home for the
publisher.

Both startup paths then call the same coroutine, gated on `config.register_menu`:

- `TelegramBotManager.start_bot` — its existing `_register_bot_menu(name, bot,
  wrapper)` body is moved into the wrapper; the manager either calls
  `await wrapper.register_command_menu()` directly or keeps `_register_bot_menu`
  as a thin delegator (no behavior change).
- `IntegrationBotManager._start_telegram_bot` — gains the previously-missing
  call `await wrapper.register_command_menu()` after the wrapper is fully
  constructed (so `_platform_commands` is populated).

Because the wrapper is fully constructed before the call, the Jira platform
commands are already present in `_platform_commands` and naturally flow into the
published menu — no extra gating is required (resolves the "capability vs
functional" question: Option A publishes exactly what the wrapper has).

### Component Diagram

```
                       ┌─────────────────────────────────────┐
                       │      TelegramAgentWrapper            │
                       │  • self.bot (aiogram.Bot)            │
                       │  • get_bot_commands()  ← all sources │
TelegramBotManager ───▶│  • register_command_menu()  (NEW)    │◀─── IntegrationBotManager
  .start_bot           │      ├─ delete stale scopes          │      ._start_telegram_bot
  (already calls)      │      ├─ set_my_commands (batch)       │      (NEW call site)
                       │      ├─ per-command fallback on 400   │
                       │      └─ set_chat_menu_button(Menu…)   │
                       └──────────────────┬──────────────────┘
                                          │ aiogram Bot API
                                          ▼
                                    Telegram (setMyCommands)
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `IntegrationBotManager._start_telegram_bot` | modifies | Add `await wrapper.register_command_menu()` after wrapper construction, gated on `config.register_menu`. |
| `TelegramBotManager._register_bot_menu` | modifies | Delegates to `wrapper.register_command_menu()` (logic moved); behavior unchanged. |
| `TelegramAgentWrapper` | extends | New public `register_command_menu()` coroutine owning the publish logic (incl. `_register_commands_individually` fallback). |
| `TelegramAgentConfig.register_menu` | uses | Both paths honor this flag (default `True`). |
| `TelegramAgentWrapper.get_bot_commands()` | uses | Unchanged; already aggregates every command source. |

### Data Models

No new data models. The change is behavioral (call-site + method relocation).
Existing `aiogram.types` are reused: `BotCommand`, `BotCommandScopeDefault`,
`BotCommandScopeAllPrivateChats`, `BotCommandScopeAllGroupChats`,
`MenuButtonCommands`.

### New Public Interfaces

```python
# packages/ai-parrot-integrations/src/parrot/integrations/telegram/wrapper.py
class TelegramAgentWrapper(OperatorCommandsMixin):
    async def register_command_menu(self) -> None:
        """Publish this bot's command menu to Telegram (setMyCommands +
        chat menu button). Idempotent, resilient: clears stale scopes,
        batches, falls back per-command on a 400, and never raises on a
        Telegram API failure. No-op semantics are left to the caller via
        ``config.register_menu``.
        """
        ...
```

---

## 3. Module Breakdown

> Maps the single "telegram-integration-menu-registration" capability to the
> concrete files. This is a small, tightly-coupled change — all parts land
> together.

### Module 1: Wrapper menu publisher
- **Path**: `packages/ai-parrot-integrations/src/parrot/integrations/telegram/wrapper.py`
- **Responsibility**: New `async def register_command_menu(self)` containing the
  relocated publish logic (scope clearing → batch `set_my_commands` →
  per-command fallback → `set_chat_menu_button`). Internal helper for the
  per-command fallback (mirrors current `_register_commands_individually`).
- **Depends on**: existing `self.bot`, `self.get_bot_commands()`, `self.logger`.

### Module 2: TelegramBotManager delegation
- **Path**: `packages/ai-parrot-integrations/src/parrot/integrations/telegram/manager.py`
- **Responsibility**: Replace the body of `_register_bot_menu` with a call to
  `await wrapper.register_command_menu()` (or remove and call the wrapper method
  directly at `start_bot:203`). No behavior change on this path.
- **Depends on**: Module 1.

### Module 3: IntegrationBotManager call site
- **Path**: `packages/ai-parrot-integrations/src/parrot/integrations/manager.py`
- **Responsibility**: After `wrapper = TelegramAgentWrapper(...)` (line 197) and
  before/after router inclusion, add `if config.register_menu: await
  wrapper.register_command_menu()`. Wrap in try/except so a menu failure never
  aborts bot startup (consistent with existing resilience).
- **Depends on**: Module 1.

---

## 4. Test Specification

### Unit Tests

| Test | Module | Description |
|---|---|---|
| `test_wrapper_register_command_menu_calls_set_my_commands` | Module 1 | `register_command_menu()` calls `bot.set_my_commands` with the full `get_bot_commands()` list (incl. platform/Jira commands). |
| `test_wrapper_register_command_menu_clears_stale_scopes` | Module 1 | Deletes commands at Default / AllPrivateChats / AllGroupChats scopes before setting. |
| `test_wrapper_register_command_menu_sets_menu_button` | Module 1 | Calls `set_chat_menu_button(MenuButtonCommands())`. |
| `test_wrapper_register_command_menu_batch_400_falls_back` | Module 1 | On a batch 400, falls back to per-command registration, skipping the offending entry; valid commands still registered. |
| `test_wrapper_register_command_menu_api_error_is_swallowed` | Module 1 | A Telegram transport error is logged (`exc_info=True`) and does **not** raise. |
| `test_wrapper_register_command_menu_empty_list_skips` | Module 1 | Empty `get_bot_commands()` → warning, no `set_my_commands` call. |
| `test_integration_manager_registers_menu_when_enabled` | Module 3 | `_start_telegram_bot` invokes `wrapper.register_command_menu()` when `register_menu=True`. |
| `test_integration_manager_skips_menu_when_disabled` | Module 3 | `register_menu=False` → `register_command_menu()` not called. |
| `test_integration_manager_menu_includes_jira_commands` | Module 3 | With `jira_oauth_manager` present, the published command list includes `connect_jira`, `disconnect_jira`, `jira_status`. |
| `test_telegram_bot_manager_still_registers_menu` | Module 2 | `TelegramBotManager.start_bot` path remains behaviorally identical (regression guard). |

### Integration Tests

| Test | Description |
|---|---|
| `test_jira_specialist_menu_published_via_integration_manager` | Boot a `JiraSpecialist`-like wrapper through `IntegrationBotManager` with a fake `Bot`; assert the captured `set_my_commands` payload contains the Jira commands alongside the built-ins. |

### Test Data / Fixtures

```python
# Reuse the existing async fake-Bot pattern from the telegram test suite.
# Reference fixtures/tests already exercising commands:
#   packages/ai-parrot/tests/unit/test_telegram_jira_commands.py
#   packages/ai-parrot-integrations/tests/test_telegram_integration.py
@pytest.fixture
def fake_bot():
    """An aiogram-Bot stand-in that records set_my_commands /
    delete_my_commands / set_chat_menu_button calls (and can be told to
    raise on the batch call to exercise the per-command fallback)."""
    ...
```

---

## 5. Acceptance Criteria

> This feature is complete when ALL of the following are true:

- [ ] `TelegramAgentWrapper.register_command_menu()` exists and contains the
      relocated publish logic (scope clear → batch → per-command fallback →
      menu button).
- [ ] `IntegrationBotManager._start_telegram_bot` calls
      `register_command_menu()` after wrapper construction, gated on
      `config.register_menu`, wrapped so a failure never aborts startup.
- [ ] `TelegramBotManager.start_bot` continues to register the menu with **no
      behavioral change** (delegates to the wrapper method).
- [ ] When `jira_oauth_manager` is present, the published menu includes
      `/connect_jira`, `/disconnect_jira`, `/jira_status` **in addition to** the
      standard commands.
- [ ] `config.register_menu == False` suppresses menu registration on **both**
      paths.
- [ ] A Telegram API failure during menu registration is logged and swallowed
      (does not crash bot startup or polling).
- [ ] All unit tests pass (`pytest packages/ai-parrot-integrations/tests/ -v`
      and `pytest packages/ai-parrot/tests/unit/ -v` for affected suites).
- [ ] No breaking changes to existing public API or to the
      `TelegramBotManager` path.
- [ ] Documentation note added in `docs/telegram_integration.md` describing that
      both managers publish the command menu.

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor.** All references re-verified on
> 2026-06-04 against the working tree (branch `dev`). Line numbers are accurate
> as of verification; agents MUST re-`grep` if they suspect drift.

### Verified Imports

```python
# packages/ai-parrot-integrations/src/parrot/integrations/telegram/manager.py:14-19  (confirmed)
from aiogram.types import (
    BotCommand,
    BotCommandScopeAllGroupChats,
    BotCommandScopeAllPrivateChats,
    BotCommandScopeDefault,
    MenuButtonCommands,
)
from .decorators import discover_telegram_commands       # manager.py:28 (confirmed)

# jira_specialist imports (confirmed):
from parrot.integrations.telegram import TelegramHumanTool, telegram_chat_scope  # jira_specialist.py:47
```

### Existing Class Signatures

```python
# packages/ai-parrot-integrations/src/parrot/integrations/manager.py
class IntegrationBotManager:                                                 # line 46
    async def _start_telegram_bot(self, name: str, config: TelegramAgentConfig):  # line 174
        ...
        wrapper = TelegramAgentWrapper(agent, bot, config, app=app)          # line 197
        # HITL channel wired here (this is why JiraSpecialist uses THIS path):
        human_manager = await self._ensure_human_manager()                   # line 203
        dp.include_router(wrapper.router)                                     # line 217
        # ❗ NO menu registration anywhere in this method (the defect).

# packages/ai-parrot-integrations/src/parrot/integrations/telegram/manager.py
class TelegramBotManager:                                                    # line 39
    async def start_bot(self, name, agent_config) -> bool:                   # line ~149
        wrapper = TelegramAgentWrapper(                                      # line 195
            agent, bot, agent_config, agent_commands=agent_commands, app=app,
        )
        if agent_config.register_menu:                                       # line 202
            await self._register_bot_menu(name, bot, wrapper)                # line 203
    async def _register_bot_menu(self, name, bot, wrapper) -> None:          # line 231
        bot_commands = wrapper.get_bot_commands()                            # line 252
        # clear Default / AllPrivateChats / AllGroupChats scopes             # lines 267-279
        await bot.set_my_commands(bot_commands)                              # line 283
        # fallback → self._register_commands_individually(...)               # line 292
        await bot.set_chat_menu_button(menu_button=MenuButtonCommands())     # line 297
    async def _register_commands_individually(self, name, bot, bot_commands) -> List[BotCommand]:  # line 309

# packages/ai-parrot-integrations/src/parrot/integrations/telegram/wrapper.py
class TelegramAgentWrapper(OperatorCommandsMixin):                           # line 62
    def __init__(self, agent, bot, config, agent_commands=None, *, app=None):  # line 80
        self.bot = bot                                                       # line 90
        self._platform_commands: list[tuple[str, str]] = []                  # line 131
        self._register_handlers()                                            # line 187
    def _register_handlers(self) -> None:                                    # line 189
        self._register_jira_commands()                                       # line 229 (called within)
    def _add_platform_commands(self, entries: list[tuple[str, str]]) -> None:  # line 327
        self._platform_commands.append((command, description))               # line 342
    def _register_jira_commands(self) -> None:                               # line 345
        oauth_manager = self.app.get("jira_oauth_manager") if self.app else None  # line 353
        if oauth_manager is None: return                                     # line 356
        # register_jira_commands(self.router, oauth_manager, ...)            # line 374
        self._add_platform_commands([("connect_jira", ...), ("disconnect_jira", ...), ("jira_status", ...)])  # line 377
    def get_bot_commands(self) -> list:                                      # line 838
        # built-ins + login/logout + _platform_commands + config.commands + _agent_commands

# packages/ai-parrot-integrations/src/parrot/integrations/telegram/models.py
class TelegramAgentConfig(...):
    register_menu: bool = True                                              # line 78 (default True; from_dict default at line 261)

# packages/ai-parrot/src/parrot/bots/jira_specialist.py
class JiraSpecialist(...):
    def agent_tools(self):                                                   # line 268
        return [TelegramHumanTool(source_agent=self.agent_id)]               # line 276 (requires HITL → IntegrationBotManager)
```

### Integration Points

| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `TelegramAgentWrapper.register_command_menu()` (NEW) | `self.bot.set_my_commands / delete_my_commands / set_chat_menu_button` | aiogram Bot API | `telegram/manager.py:283,273,297` (logic source) |
| `TelegramAgentWrapper.register_command_menu()` (NEW) | `self.get_bot_commands()` | method call | `wrapper.py:838` |
| `IntegrationBotManager._start_telegram_bot` | `wrapper.register_command_menu()` (NEW) | awaited call (NEW site) | `integrations/manager.py:197` (insert after) |
| `TelegramBotManager._register_bot_menu` | `wrapper.register_command_menu()` (NEW) | delegation | `telegram/manager.py:203,231` |

### Does NOT Exist (Anti-Hallucination)

- ~~`IntegrationBotManager._register_bot_menu`~~ — does **not** exist; menu
  registration lives only on `TelegramBotManager` today.
- ~~`TelegramAgentWrapper.register_command_menu`~~ — does **not** exist yet; it
  is the method this spec introduces.
- ~~`TelegramAgentWrapper.set_my_commands(...)`~~ — the wrapper never calls
  Telegram's `set_my_commands` today; only `manager._register_bot_menu` does.
- ~~`IntegrationManager`~~ — the class is named **`IntegrationBotManager`**
  (`integrations/manager.py:46`).
- ~~A `register_menu` check inside `IntegrationBotManager`~~ — does not exist;
  `register_menu` is currently only honored in `telegram/manager.py:202`.

---

## 7. Implementation Notes & Constraints

### Patterns to Follow

- async/await throughout; no blocking I/O (Telegram calls are awaited aiogram coroutines).
- Use `self.logger` for all logging; mirror the existing log messages and
  `exc_info=True` on failures (`telegram/manager.py:285-291, 298-301`).
- Move the `_register_commands_individually` fallback alongside
  `register_command_menu` (keep it private on the wrapper, or inline it).
- Honor `config.register_menu` at every call site — do **not** bury the flag
  check inside `register_command_menu` only; the integration path must check it
  too (keeps "no-op semantics left to the caller" consistent and testable).
- Preserve scope-clearing order and the `MenuButtonCommands()` button set.

### Known Risks / Gotchas

- **Edge — empty command list**: keep the existing warn-and-skip behavior
  (`telegram/manager.py:259-263`).
- **Edge — batch 400 wipes menu**: a single invalid `BotCommand` 400s the whole
  batch; the per-command fallback must be retained so one bad entry can't blank
  the menu for everyone.
- **Edge — API/transport failure**: must be caught and logged, never raised, so
  bot startup/polling is unaffected. The integration call site should also
  try/except defensively.
- **Stale per-chat scoped menus**: this change clears only Default /
  AllPrivateChats / AllGroupChats scopes (as today). If any deployment set a
  `BotCommandScopeChat` menu, it would still override — out of scope here (§8).
- **Dual registration**: if both managers ever ran for the same token,
  last-write-wins; harmless because both compute the same list.
- **Cross-feature file contention**: touches recently-merged Telegram areas
  (FEAT-210 operator commands, FEAT-213 voice reply). Rebase on latest `dev`
  before implementing.

### External Dependencies

| Package | Version | Reason |
|---|---|---|
| `aiogram` | (existing, v3.x) | `Bot.set_my_commands`, `delete_my_commands`, `set_chat_menu_button`, `BotCommandScope*`, `MenuButtonCommands` — already a dependency, no new packages. |

---

## Worktree Strategy

- **Default isolation unit**: `per-spec`.
- All tasks run **sequentially in one worktree**: the change is small and
  tightly coupled (one new wrapper method + two call-site edits + tests that
  exercise both). Splitting across worktrees would create artificial coupling.
- **Cross-feature dependencies**: none that must merge first, but the touched
  files overlap with recently-merged FEAT-210 / FEAT-213 work in
  `telegram/wrapper.py` and `telegram/manager.py` — branch from latest `dev`.
- Suggested branch/worktree:
  ```
  git worktree add -b feat-220-telegram-integration-menu-registration \
    .claude/worktrees/feat-220-telegram-integration-menu-registration HEAD
  ```

---

## 8. Open Questions

> Resolved items are carried forward from the brainstorm (decision trail).

- [x] Does `/connect_jira` work when typed manually? — *Resolved in brainstorm*:
      Yes — the handler is registered in the wrapper constructor; only the menu
      advertisement is missing. (Confirms the fix is publish-only, not handler wiring.)
- [x] Is Jira OAuth2 3LO configured (JiraOAuthManager wired)? — *Resolved in
      brainstorm*: Yes — `_platform_commands` is populated at construction, so
      the published menu will include the Jira commands without extra gating.
- [x] Capability-based vs functional-only menu? — *Resolved in brainstorm*:
      Either is fine; Option A publishes whatever the wrapper actually has
      (Jira commands are present), so no additional gating is introduced.
- [ ] Should we also register the menu via an aiogram `dp.startup` hook
      (brainstorm Option C) to harden against future late-wiring of
      `jira_oauth_manager`? Currently a **Non-Goal**; revisit only if a
      late-wiring scenario appears. — *Owner: Jesus*
- [ ] Do any deployments set **per-chat scoped** command menus
      (`BotCommandScopeChat`) that would override the default-scope menu? If so,
      a follow-up is needed to clear/refresh those. — *Owner: Jesus*
- [x] Confirm `register_menu=False` is the only intended opt-out (i.e. no
      deployment relies on `IntegrationBotManager` silently never registering a
      menu). — *Owner: Jesus*: confirmed

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-06-04 | Jesus Lara | Initial draft from brainstorm (Option A). |
