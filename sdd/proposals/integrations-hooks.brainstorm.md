# Brainstorm: Integrations Hooks

**Date**: 2026-03-10
**Author**: Claude
**Status**: exploration
**Recommended Option**: Option A

---

## Problem Statement

AI-Parrot has two parallel execution contexts for agents:

1. **Integration handlers** (`parrot/integrations/`) — Telegram, Slack, MS Teams, WhatsApp wrappers that react to incoming messages from messaging platforms.
2. **Autonomous orchestrator** (`parrot/autonomous/`) — `AutonomousOrchestrator` with a rich `BaseHook` system (13+ hook types) that enables agents to react to external events: file changes, scheduled tasks, Postgres NOTIFY, IMAP emails, Jira webhooks, message brokers, etc.

**The problem:** These two worlds are isolated. An agent started via a Telegram integration (`TelegramBot`) cannot also react to hooks (e.g., file watchdog, scheduler, external webhook). Conversely, hooks are tightly coupled to `parrot/autonomous/`, making them unavailable to integration-based agents without pulling in the entire orchestrator.

**Who is affected:**
- **Developers** — Cannot compose agents that respond to both messaging platforms AND system events without duplicating infrastructure.
- **Ops teams** — Must run separate autonomous orchestrator processes alongside integration bots, even when the same agent needs both capabilities.
- **End users** — Miss proactive notifications (e.g., a Telegram bot that also monitors a directory and alerts when files change).

## Constraints & Requirements

- **Backward compatibility** — `parrot/autonomous/` must continue working unchanged; existing orchestrator YAML configs must remain valid.
- **Async-first** — All hook lifecycle operations are async (`start()`, `stop()`, `on_event()`).
- **No heavy imports** — Hooks use lazy loading today (`__getattr__`) to avoid pulling in `asyncpg`, `watchdog`, `apscheduler`, etc. This must be preserved.
- **Decoupled from orchestrator** — Hooks should NOT require `AutonomousOrchestrator` to function; the callback pattern (`set_callback`) already supports arbitrary consumers.
- **Integration handlers are diverse** — Telegram uses `aiogram`, Slack uses `slack_bolt`, MS Teams uses `botbuilder`. Hook attachment must work with any handler pattern.
- **Minimal migration effort** — Hundreds of internal import paths reference `parrot.autonomous.hooks.*`; the refactor must not break them.

---

## Options Explored

### Option A: Extract to `parrot/core/hooks/` with Re-exports from `parrot/autonomous/hooks/`

Move the hook infrastructure (`BaseHook`, `HookManager`, `HookEvent`, `HookType`, all config models, and all concrete hook implementations) to a new top-level `parrot/hooks/` package. `parrot/autonomous/hooks/` becomes a thin re-export layer — identical to how `parrot/voice/transcriber/` was refactored from `parrot/integrations/msteams/voice/`.
User comment: Currently parrot/autonomous is not yet deployed into production, any backward-compatible functionality is not required, we can move all imports from `parrot/autonomous/hooks/` to  `parrot/core/hooks/`
- Create `parrot/core/hooks.py` with `HookProtocol`, `HookEventProtocol`, `HookManagerProtocol`
User Comment: move also the `EventBus` to `parrot/core/events/evb.py` and importing in autonomous from there.

**Approach:**
- Create `parrot/core/hooks/` with the same internal structure as `parrot/autonomous/hooks/`
- Move all source files: `base.py`, `models.py`, `manager.py`, `scheduler.py`, `file_watchdog.py`, `postgres.py`, `imap.py`, `jira_webhook.py`, `file_upload.py`, `sharepoint.py`, `messaging.py`, `whatsapp_redis.py`, `matrix.py`, `filesystem.py`, `brokers/`
- Each integration handler can now `from parrot.core.hooks import HookManager, FileWatchdogHook` directly
- Add a `HookMixin` or `HookableAgent` mixin that any bot/handler can inherit to gain hook support

**Pros:**
- Clean separation of concerns — hooks are infrastructure, not orchestrator-specific
- Proven pattern — identical to the voice transcriber refactor (TASK-262/263)
- Full backward compatibility via re-exports
- Integrations can attach hooks without importing `parrot.autonomous`
- Lazy loading preserved (same `__getattr__` pattern)
- `HookManager` already supports arbitrary callbacks — no API changes needed

**Cons:**
- Large file move (15+ files) but mechanically simple
- Need to update internal imports in `AutonomousOrchestrator` to use `parrot.hooks`

**Effort:** Medium

**Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| No new dependencies | — | Hooks are already self-contained |

**Existing Code to Reuse:**
| Path | Description |
|---|---|
| `parrot/autonomous/hooks/` | All hook implementations (13+ hooks) — moved as-is |
| `parrot/autonomous/hooks/base.py` | `BaseHook` ABC — canonical base class |
| `parrot/autonomous/hooks/manager.py` | `HookManager` — registry + lifecycle |
| `parrot/autonomous/hooks/models.py` | `HookEvent`, `HookType`, all config models |
| `parrot/voice/transcriber/` | Reference for the re-export pattern |

---

### Option B: Publish Hooks as a Protocol + Keep in `parrot/autonomous/hooks/`

Instead of moving files, define a `HookProtocol` (typing.Protocol) in a lightweight shared location (e.g., `parrot/core/hooks.py`) and have integrations depend on the protocol, not the concrete implementation.

**Approach:**
- Create `parrot/core/hooks.py` with `HookProtocol`, `HookEventProtocol`, `HookManagerProtocol`
- Integrations type-hint against protocols
- At runtime, integrations receive hook instances from the orchestrator via dependency injection
- `parrot/autonomous/hooks/` stays where it is — it's the only concrete implementation

**Pros:**
- No file moves — minimal code churn
- Strong decoupling via structural subtyping
- Clean dependency direction: integrations → protocol ← autonomous

**Cons:**
- Integrations still can't instantiate hooks independently — they need the orchestrator to provide them
- Doesn't solve the user's core requirement: "un agente iniciado desde integrations aun asi pueda activarse via hooks"
- Protocols add type safety but don't enable runtime composition
- `HookManager` is still in `parrot/autonomous/` — integrations can't use it standalone

**Effort:** Low

**Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| No new dependencies | — | Uses stdlib `typing.Protocol` |

**Existing Code to Reuse:**
| Path | Description |
|---|---|
| `parrot/autonomous/hooks/base.py` | Reference for protocol definition |
| `parrot/autonomous/hooks/models.py` | Reference for event protocol |

---

### Option C: Event Bus as the Shared Layer

Instead of moving hooks, promote the existing `EventBus` (`parrot/autonomous/evb.py`) to a shared location and make both orchestrator and integrations publish/subscribe through it. Hooks stay in `parrot/autonomous/` but emit events to a shared bus that integrations can also listen to.

User Comment: or move also the `EventBus` to `parrot/core/events/evb.py` and importing in autonomous from there.

**Approach:**
- Move `EventBus` to `parrot/events/bus.py`
- Hooks emit `HookEvent` → `EventBus` (instead of direct callback)
- Integrations subscribe to `EventBus` channels relevant to their agents
- Integration handlers create their own `HookManager` instance but route events through the shared bus
- Both autonomous and integration agents consume from the same event stream

**Pros:**
- Fully decoupled — producers and consumers don't know about each other
- Enables multi-consumer patterns (one hook event triggers multiple agents)
- Redis-backed pub/sub already implemented in `EventBus`
- Natural fit for distributed deployments (orchestrator on one machine, integrations on another)

**Cons:**
- Requires Redis as a runtime dependency for hook events
- More complex than direct callback — adds latency and failure modes
- Debugging event flow is harder (events go through Redis, not direct function calls)
- Over-engineered for single-process deployments where integrations and hooks run in the same process
- `EventBus` currently uses glob-pattern matching on channels — would need careful channel design
- Doesn't eliminate the need to also move `HookManager` for integrations that want to instantiate hooks directly

**Effort:** High

**Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `redis`/`aioredis` | Event bus transport | Already in project |

**Existing Code to Reuse:**
| Path | Description |
|---|---|
| `parrot/autonomous/evb.py` | `EventBus` with Redis pub/sub |
| `parrot/autonomous/hooks/` | Hook implementations (stay in place) |

---

### Option D: Hybrid — Move Core + Keep Messaging Hooks in Autonomous

Move only the "infrastructure" hooks (scheduler, file watchdog, postgres, IMAP, brokers, file upload, SharePoint, Jira) to `parrot/hooks/`, but keep the messaging hooks (Telegram, WhatsApp, MS Teams, Matrix) in `parrot/autonomous/hooks/` since they're specifically designed for the orchestrator's webhook-based message routing.

**Approach:**
- `parrot/hooks/` gets: `BaseHook`, `HookManager`, `HookEvent`, `HookType`, models, and all non-messaging hooks
- `parrot/autonomous/hooks/` keeps: messaging hooks + `MessagingHookConfig` + WhatsApp Redis + Matrix
- Messaging hooks import `BaseHook` from `parrot/hooks/` (dependency inversion)
- Integration handlers can use `parrot/hooks/` for infrastructure hooks without touching messaging hooks

**Pros:**
- Smaller move — only infrastructure hooks migrate
- Messaging hooks stay close to their orchestrator context
- Clear separation: "infrastructure hooks" vs. "messaging hooks"

**Cons:**
- Arbitrary split — why is `TelegramHook` (messaging) different from `SchedulerHook` (infrastructure)?
- A Telegram integration bot that also wants WhatsApp Redis hook still needs to import from `parrot/autonomous/`
- Two locations for hooks creates confusion about where to add new hooks
- Breaks the "one place for all hooks" principle

**Effort:** Medium

**Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| No new dependencies | — | — |

---

## Recommendation

**Option A (Extract to `parrot/hooks/` with Re-exports)** is recommended because:

1. **Directly solves the user's requirement** — Integration handlers can `from parrot.hooks import HookManager, FileWatchdogHook, SchedulerHook` and attach hooks to their agents without any dependency on `parrot/autonomous`.

2. **Proven pattern** — This is exactly how the voice transcriber refactor was done (TASK-262/263): move to shared location, re-export from original location. All 103 existing tests passed unchanged.

3. **Full backward compatibility** — `from parrot.autonomous.hooks import BaseHook` continues to work. Existing YAML configs, orchestrator code, and import paths are unaffected.

4. **Minimal complexity** — No new abstractions (protocols, event buses, or arbitrary splits). The same `HookManager` + callback pattern works whether the consumer is `AutonomousOrchestrator` or a `TelegramBot`.

5. **Clean architecture** — Hooks are infrastructure, not orchestrator logic. Placing them at `parrot/hooks/` reflects their true role as reusable event sources.

**Trade-off accepted:** Two import paths will coexist. This is acceptable because:
- The re-export pattern is well-understood in Python (e.g., `os.path` re-exported from `posixpath`)
- Deprecation warnings can be added to the old path in a future release
- New code should use `parrot.hooks`, documented in CONTEXT.md

---

## Feature Description

### User-Facing Behavior

**For developers building integration bots:**
```python
from parrot.hooks import HookManager, SchedulerHook, FileWatchdogHook
from parrot.integrations.telegram import TelegramBot

bot = TelegramBot(config=...)

# Attach hooks to the integration bot
hook_manager = HookManager()
hook_manager.set_event_callback(bot.handle_hook_event)

hook_manager.register(SchedulerHook(
    cron_expression="0 9 * * *",
    target_type="agent",
    target_id="daily-report",
))

hook_manager.register(FileWatchdogHook(
    directory="/data/uploads",
    patterns=["*.csv"],
    target_type="agent",
    target_id="data-processor",
))

# Start both the integration and the hooks
await hook_manager.start_all()
await bot.start()
```

**For developers using `AutonomousOrchestrator`:**
- No changes. Everything works exactly as before.

### Internal Behavior

1. **Package relocation** — All hook source files move from `parrot/autonomous/hooks/` to `parrot/hooks/`.
2. **Re-export layer** — `parrot/autonomous/hooks/__init__.py` re-exports everything from `parrot/hooks/`.
3. **HookableAgent mixin** (optional) — Provides `attach_hooks()`, `start_hooks()`, `stop_hooks()`, `handle_hook_event()` methods for integration handlers.
4. **Callback contract** — The callback signature `async def callback(event: HookEvent) -> None` remains unchanged. Any async function matching this signature can be a hook consumer.

### Edge Cases & Error Handling

| Scenario | Behavior |
|---|---|
| Import from old path (`parrot.autonomous.hooks`) | Works via re-export — no breakage |
| Import from new path (`parrot.hooks`) | Canonical path — recommended |
| Hook started without callback | Logs warning via existing `on_event()` guard |
| Integration bot stops but hooks still running | `HookManager.stop_all()` must be called in bot cleanup |
| Multiple HookManagers for same hook type | Each manager is independent — no conflict |
| Hook event targets nonexistent agent | Consumer (bot/orchestrator) handles routing errors |

---

## Capabilities

### New Capabilities
- `hooks-shared-package`: Top-level `parrot/hooks/` package with all hook infrastructure
- `hooks-backward-compat`: Re-export layer in `parrot/autonomous/hooks/`
- `hooks-integration-mixin`: Optional `HookableAgent` mixin for integration handlers

### Modified Capabilities
- `autonomous-orchestrator`: Import hooks from `parrot.hooks` instead of relative `hooks` subpackage
- `autonomous-hooks-init`: Convert to thin re-export module

---

## Impact & Integration

| Affected Component | Impact Type | Notes |
|---|---|---|
| `parrot/autonomous/hooks/` | transforms | Becomes re-export layer |
| `parrot/autonomous/orchestrator.py` | modifies | Update imports to `parrot.hooks` |
| `parrot/hooks/` (NEW) | creates | New canonical location for all hooks |
| `parrot/integrations/telegram/` | extends | Can optionally attach hooks |
| `parrot/integrations/slack/` | extends | Can optionally attach hooks |
| `parrot/integrations/msteams/` | extends | Can optionally attach hooks |
| `parrot/integrations/whatsapp/` | extends | Can optionally attach hooks |
| `.agent/CONTEXT.md` | modifies | Document new `parrot/hooks/` location |
| `pyproject.toml` | unchanged | No new dependencies |

---

## Open Questions

- [ ] **HookableAgent mixin scope** — Should the mixin live in `parrot/hooks/mixins.py` or `parrot/bots/mixins.py`? It bridges hooks and bots. *Owner: Core team*: on `parrot/core/hooks/mixins.py`
- [ ] **EventBus integration** — Should `HookManager` optionally emit to `EventBus` in addition to the direct callback? This would enable distributed hook consumption. *Owner: Core team*: Yes
- [ ] **Hook configuration in integration YAML** — Should integration YAML configs (e.g., telegram agent YAML) support a `hooks:` section to declare attached hooks? *Owner: Core team*: Yes
- [ ] **Deprecation timeline** — When (if ever) should `parrot.autonomous.hooks` imports emit deprecation warnings? *Owner: Core team*: Not required.
- [ ] **FilesystemHookConfig** — The `FilesystemHookConfig` model exists in models.py but `FilesystemHook` is lazy-loaded. Should this be part of the migration or handled separately? *Owner: Core team*: part of migration.
