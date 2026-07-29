---
type: Wiki Overview
title: 'Brainstorm: Telegram Command Menu Registration Parity (IntegrationBotManager)'
id: doc:sdd-proposals-telegram-integration-menu-registration-brainstorm-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Agent-driven Telegram bots that are booted through the **unified integration
---

---
# SDD flow type and base branch (FEAT-145).
# - type: feature  (default)  → base_branch: dev (or any non-main branch)
# - type: hotfix              → base_branch MUST be: main
type: feature
base_branch: dev
---

# Brainstorm: Telegram Command Menu Registration Parity (IntegrationBotManager)

**Date**: 2026-06-03
**Author**: Jesus Lara
**Status**: exploration
**Recommended Option**: A

---

## Problem Statement

Agent-driven Telegram bots that are booted through the **unified integration
path** never publish their command menu to Telegram. Commands such as
`/connect_jira` and `/disconnect_jira` (provided by a `JiraSpecialist` agent)
**work when typed manually** but **do not appear** in:

- the Telegram Desktop **command menu** (the menu button), nor
- the **`/`-autocomplete** list shown while typing in the chat input.

The standard commands (`/start`, `/help`, `/clear`, `/whoami`, …) *do* appear,
but those are **stale** — left over from an earlier `setMyCommands` push (a
prior code version, a one-off `TelegramBotManager` run, or BotFather). They are
not being refreshed, which is why the newer Jira commands never surface.

### Root cause (verified)

There are **two** Telegram startup paths, and they are **not at parity**:

| Path | Wires HITL channel? | Calls `_register_bot_menu()` (`setMyCommands`)? |
|---|---|---|
| `TelegramBotManager.start_bot` (`telegram/manager.py:202`) | ❌ No | ✅ Yes (gated on `config.register_menu`) |
| `IntegrationBotManager._start_telegram_bot` (`integrations/manager.py:174`) | ✅ Yes | ❌ **No — missing entirely** |

`JiraSpecialist.agent_tools()` returns a `TelegramHumanTool`
(`jira_specialist.py:276`), which requires the HITL `human_manager` that **only
`IntegrationBotManager` wires** (`integrations/manager.py:203-216`).
`TelegramBotManager` does not wire HITL. Therefore `JiraSpecialist` is started
via `IntegrationBotManager` — the exact path that never registers the menu.

Why the commands still *work*: the wrapper constructor calls
`_register_handlers()` → `_register_jira_commands()` (`wrapper.py:229, 345`),
which — because `app['jira_oauth_manager']` is present (OAuth2 3LO is
configured) — registers the aiogram `Command("connect_jira")` handlers **and**
records the commands in `self._platform_commands` (`wrapper.py:377`). So
`wrapper.get_bot_commands()` (`wrapper.py:838`) *would* return the Jira entries
— but nothing on the `IntegrationBotManager` path ever calls `setMyCommands`
to push that list to Telegram.

### Who is affected

- **End users** of Telegram bots (Desktop and mobile): they cannot discover the
  bot's real command surface; commands appear missing/undocumented.
- **Agent authors** (e.g. `JiraSpecialist`, Office365): platform/decorator
  commands they declare silently fail to advertise when the agent runs under
  the integration manager.

---

## Constraints & Requirements

- **No regression** for the `TelegramBotManager.start_bot` path, which already
  registers the menu correctly.
- Must **honor `config.register_menu`** (`TelegramAgentConfig.register_menu`,
  default `True`, `models.py:78`) in *both* paths — some deployments may
  intentionally disable menu registration.
- Must reuse the existing **resilient registration** behavior already built into
  `_register_bot_menu`: clear stale scopes, batch `set_my_commands`, per-command
  fallback on a 400, and `set_chat_menu_button(MenuButtonCommands())`
  (`telegram/manager.py:231-307`).
- Menu must include **all** command sources the wrapper already aggregates:
  built-ins, login/logout, `_platform_commands` (Jira/Office365/MCP), YAML
  `config.commands`, and `@telegram_command` agent commands
  (`wrapper.py:846-888`).
- Async-first, no blocking I/O. Telegram API failures must **degrade
  gracefully** (a failed menu push must never crash bot startup).
- Single source of truth: avoid two divergent copies of the menu-registration
  logic across the two managers.

---

## Options Explored

### Option A: Move menu registration into the wrapper; both managers call it

Extract the menu-registration logic out of `TelegramBotManager` and onto the
`TelegramAgentWrapper` as a public coroutine (e.g.
`async def register_command_menu(self) -> None`). The wrapper already owns both
the `Bot` instance (`self.bot`) and the command source
(`self.get_bot_commands()`), so it is the natural home. Both managers then call
`await wrapper.register_command_menu()` (gated on `config.register_menu`) after
constructing the wrapper. `TelegramBotManager._register_bot_menu` becomes a thin
delegator (or is deleted in favor of the wrapper method).

✅ **Pros:**
- **Single source of truth** — the menu logic lives next to the command list it
  publishes; no drift between the two managers.
- Fixes the actual bug: the integration path gains menu registration, and the
  list naturally includes the Jira `_platform_commands`.
- The wrapper is fully constructed (handlers + `_platform_commands` populated)
  before the call, so ordering is correct by construction.
- Future integrations (Office365, MCP) get menu parity for free.

❌ **Cons:**
- Moves logic across a module boundary (manager → wrapper); slightly larger
  diff than a one-line fix.
- Must preserve the existing resilient delete/batch/fallback behavior verbatim
  during the move.

📊 **Effort:** Low–Medium

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `aiogram` | `Bot.set_my_commands`, `delete_my_commands`, `set_chat_menu_button`, `BotCommandScope*`, `MenuButtonCommands` | already a dependency; v3.x API in use |

🔗 **Existing Code to Reuse:**
- `telegram/manager.py:231-332` — `_register_bot_menu` + `_register_commands_individually` (move bodies into the wrapper).
- `wrapper.py:838-911` — `get_bot_commands()` (already aggregates every source).
- `integrations/manager.py:197` and `telegram/manager.py:202-203` — the two call sites.

---

### Option B: Add the missing call to `IntegrationBotManager` via a shared helper

Keep the existing logic but extract it into a **module-level helper** in the
`telegram` package, e.g. `async def register_bot_menu(name, bot, wrapper)` in
`telegram/menu.py` (or `telegram/manager.py`). `TelegramBotManager` and
`IntegrationBotManager` both import and call it (gated on `config.register_menu`).

✅ **Pros:**
- Smallest behavioral change; lowest regression risk.
- Directly closes the parity gap with no logic rewrite.
- No cross-boundary move of state — helper takes `wrapper` and reads its public
  `get_bot_commands()`.

❌ **Cons:**
- The helper still lives outside the wrapper, so the "where does the menu come
  from" question remains split between helper + wrapper.
- Marginally less cohesive than Option A (the bot + command-source pair lives on
  the wrapper, but the publisher lives elsewhere).

📊 **Effort:** Low

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `aiogram` | same Telegram menu APIs | already a dependency |

🔗 **Existing Code to Reuse:**
- `telegram/manager.py:231-332` — promote to a shared free function.
- `integrations/manager.py:174-233` — add the call after `wrapper` construction.

---

### Option C: Register the menu via an aiogram `dp.startup` hook (ordering-robust)

Instead of imperatively pushing the menu during `start_bot`, the wrapper
registers an aiogram **`Dispatcher.startup`** callback that runs
`setMyCommands` once the dispatcher begins polling — i.e. *after* the app and
all shared services are fully wired. Both managers already build a `Dispatcher`
and `include_router(wrapper.router)`; the wrapper would expose an
`install_startup_hooks(dp)` that registers the menu push (and could also
re-publish on a future config-reload signal).

✅ **Pros:**
- **Immune to startup-ordering races** — even if `jira_oauth_manager` (or any
  service) is wired late, the menu is computed at polling start.
- Opens the door to **on-demand menu refresh** (e.g. after a user authenticates,
  or when an agent's tool set changes).
- Most defensive against the *class* of "menu set before commands existed" bugs.

❌ **Cons:**
- The current bug is a **missing call**, not strictly an ordering race — this is
  arguably over-engineering for the immediate fix.
- More moving parts (dispatcher lifecycle, hook registration); slightly harder
  to reason about and test than a direct call.
- `_platform_commands` is already populated at construction time in this
  codebase, so the extra robustness is mostly future-proofing.

📊 **Effort:** Medium

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `aiogram` | `Dispatcher.startup.register(...)` lifecycle hook | v3.x supports startup/shutdown hooks |

🔗 **Existing Code to Reuse:**
- `integrations/manager.py:187, 217` and `telegram/manager.py:177, 206` — `Dispatcher` creation + `include_router`.
- `wrapper.py:838-911` — `get_bot_commands()`.

---

## Recommendation

**Option A** is recommended.

The bug is fundamentally a **parity / single-source-of-truth** problem: the menu
publisher lives on one manager and was never replicated to the other, even
though both construct the same wrapper that already knows the full command list.
Moving the publisher onto the `TelegramAgentWrapper` — which owns both the `Bot`
and `get_bot_commands()` — fixes the integration path, eliminates the risk of
the two managers drifting again, and gives every current and future integration
(Jira, Office365, MCP, decorator commands) automatic menu parity.

We trade a slightly larger diff (moving the resilient delete/batch/fallback
block) for durable correctness. Option B is the acceptable fallback if we want
the **minimum** diff and prefer not to move state across the module boundary;
its logic is identical, just housed in a shared helper. Option C's startup-hook
robustness is valuable but addresses a race that does not currently occur
(`_platform_commands` is populated at construction); it can be layered on later
if late-wiring scenarios appear, without conflicting with Option A.

---

## Feature Description

### User-Facing Behavior
After this change, a Telegram bot started through the integration manager (the
path `JiraSpecialist` uses) publishes its **complete, current** command set to
Telegram on startup. Users see `/connect_jira`, `/disconnect_jira`,
`/jira_status` (and any Office365/MCP/decorator/YAML commands) in **both** the
command-menu button and the `/`-autocomplete list — alongside the standard
commands, which are now refreshed rather than stale.

### Internal Behavior
1. `IntegrationBotManager._start_telegram_bot` constructs the
   `TelegramAgentWrapper` (which, as today, registers handlers and populates
   `_platform_commands` because `jira_oauth_manager` is present).
2. After construction — and gated on `config.register_menu` — the manager
   `await`s the wrapper's menu-registration coroutine.
3. The coroutine builds the list via `wrapper.get_bot_commands()`, clears stale
   commands at the default / all-private / all-group scopes, calls
   `set_my_commands(...)` (with per-command fallback on a 400), and sets the
   chat menu button to `MenuButtonCommands()`.
4. `TelegramBotManager.start_bot` calls the **same** coroutine, so both paths
   are guaranteed identical behavior.

### Edge Cases & Error Handling
- **`register_menu == False`**: neither path publishes the menu (explicit
  opt-out preserved).
- **No commands to register**: log a warning and skip (existing behavior,
  `telegram/manager.py:259-263`).
- **Telegram 400 on batch**: fall back to per-command registration, skipping the
  offending entry, so one bad command never wipes the menu
  (`telegram/manager.py:309-332`).
- **Telegram API/transport failure**: caught and logged with `exc_info=True`;
  **must not** crash bot startup or polling.
- **Stale scoped menus**: the existing delete across default/all-private/
  all-group scopes still runs; per-chat scoped menus (if any deployment set
  them) are out of scope here — see Open Questions.
- **Both managers run for the same token** (should not happen): last
  `set_my_commands` wins; harmless because both compute the same list.

---

## Capabilities

### New Capabilities
- `telegram-integration-menu-registration`: the unified `IntegrationBotManager`
  Telegram startup path publishes the bot command menu (`setMyCommands` + menu
  button) at parity with `TelegramBotManager`, including agent platform commands
  (Jira/Office365/MCP) and `@telegram_command` commands.

### Modified Capabilities
- `telegram-integrations-auth` (`sdd/specs/telegram-integrations-auth.spec.md`)
  — Jira OAuth commands now reliably advertised on the integration path.
- `FEAT-108-jiratoolkit-auth-telegram` — `/connect_jira` / `/disconnect_jira`
  menu visibility.

---

## Impact & Integration

| Affected Component | Impact Type | Notes |
|---|---|---|
| `IntegrationBotManager._start_telegram_bot` (`integrations/manager.py:174`) | modifies | Add menu-registration call after wrapper construction (gated on `register_menu`). |
| `TelegramAgentWrapper` (`telegram/wrapper.py`) | extends | New public `register_command_menu()` coroutine (Option A) owning the publish logic. |
| `TelegramBotManager` (`telegram/manager.py:39`) | modifies | `_register_bot_menu` delegates to the wrapper method (Option A) or shared helper (Option B). |
| `TelegramAgentConfig.register_menu` (`telegram/models.py:78`) | depends on | Both paths must honor this flag. |
| `get_bot_commands()` (`telegram/wrapper.py:838`) | depends on | Unchanged; already aggregates every command source. |

No breaking changes. No new dependencies. No data-model or schema changes.

---

## Code Context

### User-Provided Code
No code was pasted by the user. The reported symptom (verbatim):

> Agent In Telegram Wrapper is not able to update the command menu in Telegram
> Desktop App; commands declared by Agents as JiraSpecialist (`/connect_jira`,
> `/disconnect_jira`) are not declared in menu or in list when "/" was wrote in
> the text area of Telegram chat.

User-confirmed facts during discovery:
- Standard commands (`/start`, `/help`, …) **do** appear; only Jira commands are missing from the menu/autocomplete.
- Typing `/connect_jira` manually **works** (handler is registered).
- Jira **OAuth2 3LO is configured** (`JiraOAuthManager` wired into the aiohttp app).

### Verified Codebase References

#### Classes & Signatures
```python
# packages/ai-parrot-integrations/src/parrot/integrations/manager.py:46
class IntegrationBotManager:
    async def _start_telegram_bot(self, name: str, config: TelegramAgentConfig):  # line 174
        # ...
        wrapper = TelegramAgentWrapper(agent, bot, config, app=app)              # line 197
        human_manager = await self._ensure_human_manager()                       # line 203 (HITL)
        # NOTE: NO call to _register_bot_menu / set_my_commands anywhere here.
        dp.include_router(wrapper.router)                                         # line 217

# packages/ai-parrot-integrations/src/parrot/integrations/telegram/manager.py:39
class TelegramBotManager:
    async def start_bot(self, name, agent_config) -> bool:                       # line ~149
        wrapper = TelegramAgentWrapper(agent, bot, agent_config, ...)            # line 195
        if agent_config.register_menu:                                           # line 202
            await self._register_bot_menu(name, bot, wrapper)                    # line 203
    async def _register_bot_menu(self, name, bot, wrapper) -> None:              # line 231
        bot_commands = wrapper.get_bot_commands()                                # line 252
        # delete stale scopes (Default / AllPrivateChats / AllGroupChats)        # line 267-279
        await bot.set_my_commands(bot_commands)                                  # line 283
        # fallback: _register_commands_individually(...)                         # line 292, 309
        await bot.set_chat_menu_button(menu_button=MenuButtonCommands())         # line 297

# packages/ai-parrot-integrations/src/parrot/integrations/telegram/wrapper.py:80
class TelegramAgentWrapper:
    def __init__(self, agent, bot, config, agent_commands=None, *, app=None):    # line 80
        self._platform_commands: list[tuple[str, str]] = []                      # line 131
        self._register_handlers()                                                # line 187
    def _register_handlers(self) -> None:                                        # line 189
        self._register_jira_commands()                                           # line 229
    def _register_jira_commands(self) -> None:                                   # line 345
        oauth_manager = self.app.get("jira_oauth_manager") if self.app else None # line 353
        if oauth_manager is None: return                                         # line 356
        register_jira_commands(self.router, oauth_manager, ...)                  # line 374 (registers Command handlers)
        self._add_platform_commands([                                            # line 377
            ("connect_jira", "Connect Jira account"),
            ("disconnect_jira", "Disconnect Jira account"),
            ("jira_status", "Show Jira connection status"),
        ])
    def get_bot_commands(self) -> list:                                          # line 838
        # built-ins + login/logout + _platform_commands + config.commands + _agent_commands

# packages/ai-parrot/src/parrot/bots/jira_specialist.py
class JiraSpecialist(...):
    def agent_tools(self):                                                       # line 268
        return [TelegramHumanTool(source_agent=self.agent_id)]                   # line 276 (requires HITL → IntegrationBotManager)
```

#### Verified Imports
```python
# Confirmed present and used in telegram/manager.py:14-19
from aiogram.types import (
    BotCommand, BotCommandScopeAllGroupChats, BotCommandScopeAllPrivateChats,
    BotCommandScopeDefault, MenuButtonCommands,
)
```

#### Key Attributes & Constants
- `TelegramAgentConfig.register_menu` → `bool = True` (`telegram/models.py:78`)
- `TelegramAgentWrapper._platform_commands` → `list[tuple[str, str]]` (`wrapper.py:131`)
- `TelegramAgentWrapper.bot` → `aiogram.Bot` (set in `__init__`, `wrapper.py:90`)

### Does NOT Exist (Anti-Hallucination)
- ~~`IntegrationBotManager._register_bot_menu`~~ — does **not** exist; menu
  registration lives only on `TelegramBotManager`.
- ~~`TelegramAgentWrapper.register_command_menu`~~ — does **not** exist yet;
  it is the proposed new method (Option A).
- ~~`wrapper.set_my_commands(...)`~~ — the wrapper never calls Telegram's
  `set_my_commands` today; only `manager._register_bot_menu` does.
- ~~`IntegrationManager`~~ — the class is named **`IntegrationBotManager`**
  (`integrations/manager.py:46`).

---

## Parallelism Assessment

- **Internal parallelism**: Low. This is a focused, cohesive change touching the
  two managers + the wrapper. Splitting it across worktrees would create
  artificial coupling (the wrapper method and its two call sites must land
  together).
- **Cross-feature independence**: Touches `telegram/wrapper.py`,
  `telegram/manager.py`, and `integrations/manager.py`. Check for conflicts with
  any in-flight Telegram specs (`FEAT-210-telegram-operator-commands`,
  `FEAT-213-telegram-voice-reply-tts`) before branching — those are recently
  merged but may have follow-ups.
- **Recommended isolation**: `per-spec` (all tasks sequential in one worktree).
- **Rationale**: Small, tightly-coupled change with shared files; one worktree,
  one PR, with tests, is the lowest-risk path.

---

## Open Questions

- [x] Does `/connect_jira` work when typed manually? — *Owner: Jesus*: Yes — the handler is registered in the wrapper constructor; only the menu advertisement is missing.
- [x] Is Jira OAuth2 3LO configured (JiraOAuthManager wired)? — *Owner: Jesus*: Yes — OAuth2 3LO is configured, so `_platform_commands` is populated.
- [x] Capability-based vs functional-only menu? — *Owner: Jesus*: Either is fine; Option A naturally publishes whatever the wrapper actually has (Jira commands are present), so no extra gating needed.
- [ ] Should we *also* register the menu via an aiogram `dp.startup` hook (Option C) to harden against any future late-wiring of `jira_oauth_manager`? — *Owner: Jesus*
- [ ] Do any deployments set **per-chat scoped** command menus (`BotCommandScopeChat`) that would override the default-scope menu? If so, do we need to clear/refresh those too? — *Owner: Jesus*
- [ ] Confirm no deployment intentionally relies on `IntegrationBotManager` **not** registering the menu (i.e. `register_menu=False` is the only opt-out we must honor). — *Owner: Jesus*
