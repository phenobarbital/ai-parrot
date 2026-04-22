# Bot Cleanup Lifecycle

> **Feature**: FEAT-114 — BotManager-driven per-agent teardown
> **Spec**: [sdd/specs/FEAT-114-bot-cleanup-lifecycle.spec.md](../sdd/specs/FEAT-114-bot-cleanup-lifecycle.spec.md)

This document describes how AI-Parrot bots are torn down cleanly during
aiohttp application shutdown, and the contracts agents must follow to
participate in that teardown.

---

## Overview

Every bot registered with `BotManager` via `add_bot()` has its
`AbstractBot.cleanup()` coroutine awaited automatically when the aiohttp
application shuts down.  Cleanups run **concurrently** via
`asyncio.gather`, so one slow agent does not block the rest.  Each
cleanup call is bounded by `BOT_CLEANUP_TIMEOUT` (default 20 s).

---

## Shutdown sequence

When the aiohttp application stops, the following callbacks run in order:

| Phase | Handler | What happens |
|---|---|---|
| `on_shutdown` | `BotManager.on_shutdown` | Cancels background tasks, shuts down integration bots (Telegram / Slack / Matrix / HITL), closes `chat_storage`. |
| `on_cleanup` | `BotManager._cleanup_all_bots` | Iterates every bot in `_bots` concurrently; each cleanup is bounded by `BOT_CLEANUP_TIMEOUT`. |
| `on_cleanup` | `BotManager._cleanup_shared_redis` | Closes the shared Redis client.  Runs **after** bot cleanups so bots can still use Redis during their own teardown. |

> **Note**: `IntegrationBotManager.shutdown()` (Telegram sessions, Slack
> sockets, Matrix transports) runs in `on_shutdown`, *before* bot cleanup.
> This is intentional: integrations close their channels first, then bots
> release their LLM / store / MCP resources.

---

## Writing cleanup-aware agents

### Plain bots

Any subclass of `AbstractBot` gets hook-free cleanup for free:

```python
class MyBot(Agent):
    async def cleanup(self) -> None:
        # Optional: release custom resources first
        await self.my_connection.close()
        # Then chain to the base class (LLM, store, KBs, MCP)
        await super().cleanup()
```

If you do not override `cleanup()`, `AbstractBot.cleanup()` handles:
- Closing the LLM client and its HTTP session
- Closing the vector store
- Closing knowledge-base connections
- Disconnecting all MCP transports

### Agents with hooks (`HookableAgent`)

Agents that use the `HookableAgent` mixin get hook teardown for free —
but **only when the mixin is declared before the bot base in the class
bases**:

```python
# ✅ Correct — HookableAgent FIRST
class JiraTroc(HookableAgent, JiraSpecialist):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._init_hooks()
        self.attach_hook(JiraWebhookHook(...))
```

When `BotManager._cleanup_all_bots` calls `bot.cleanup()`, Python's MRO
dispatches to `HookableAgent.cleanup()` first.  That method calls
`stop_hooks()` (which stops all registered hooks via `HookManager.stop_all`)
and then chains to `super().cleanup()` (which resolves to
`JiraSpecialist.cleanup()` → `AbstractBot.cleanup()`).

```
bot.cleanup()
  └── HookableAgent.cleanup()
        ├── stop_hooks() → HookManager.stop_all() (IMAP, webhooks, schedulers…)
        └── super().cleanup() → AbstractBot.cleanup() (LLM, store, KBs, MCP)
```

**Wrong ordering breaks the chain:**

```python
# ❌ Incorrect — HookableAgent LAST
class JiraTroc(JiraSpecialist, HookableAgent):
    ...
# super().cleanup() inside HookableAgent.cleanup() resolves to object,
# which has no cleanup() method.  The MRO guard prevents an AttributeError,
# but hooks never stop via BotManager's cleanup either.
```

---

## Configuration

| Environment variable | Type | Default | Effect |
|---|---|---|---|
| `BOT_CLEANUP_TIMEOUT` | `int` (seconds) | `20` | Per-bot cleanup timeout. On timeout the bot is logged at `WARNING` and skipped; other bots still complete. |

Set the variable before starting the application:

```bash
BOT_CLEANUP_TIMEOUT=30 python -m myapp
```

Or in `.env` / your config system.

---

## `shutdown()` vs `cleanup()`

`AbstractBot.shutdown()` is **not** the resource-release hook.  It is
a stub that `Agent`, `A2AMixin`, `A2AOrchestrator`, and `MCPIntegration`
override for their own protocol-level teardown (A2A worker shutdown,
MCP server stop).

| Method | Purpose | Called by |
|---|---|---|
| `AbstractBot.cleanup()` | Release LLM sessions, store connections, KBs, MCP transports | `BotManager._cleanup_all_bots` (aiohttp `on_cleanup`) and `AbstractBot.__aexit__` |
| `AbstractBot.shutdown()` | A2A / MCP protocol shutdown | A2A orchestrator, MCP integration |

Do **not** put resource-release logic in `shutdown()`.  Use `cleanup()`.

---

## Double-cleanup safety

If a bot is used both as an async context manager (`async with bot:`) and
registered with `BotManager`, `cleanup()` would normally run twice (once
from `__aexit__`, once from `_cleanup_all_bots`).  `BotManager` guards
against this with a `self._cleaned_up: set[str]` set: a bot whose name
is already in the set will not be cleaned up again.

---

## See also

- `parrot/core/hooks/mixins.py` — `HookableAgent` class and `cleanup()` method
- `parrot/manager/manager.py` — `BotManager._cleanup_all_bots` and `_safe_cleanup`
- `parrot/conf.py` — `BOT_CLEANUP_TIMEOUT` constant
- `parrot/bots/abstract.py` — `AbstractBot.cleanup()` (line ~3134)
- [FEAT-114 spec](../sdd/specs/FEAT-114-bot-cleanup-lifecycle.spec.md) — full design rationale and component diagram
