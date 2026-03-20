# Feature Specification: Shared Hooks Infrastructure

**Feature ID**: FEAT-040
**Date**: 2026-03-10
**Author**: Jesus Lara
**Status**: approved
**Target version**: next
**Brainstorm**: `sdd/proposals/integrations-hooks.brainstorm.md`

---

## 1. Motivation & Business Requirements

> Centralize the hook system from `parrot/autonomous/hooks/` into `parrot/core/hooks/` so that both the autonomous orchestrator and integration handlers (Telegram, Slack, MS Teams, WhatsApp) can use hooks to react to external events.

### Problem Statement

AI-Parrot has two parallel execution contexts for agents:

1. **Integration handlers** (`parrot/integrations/`) — Platform-specific wrappers (Telegram/aiogram, Slack/slack_bolt, MS Teams/botbuilder, WhatsApp) that react to incoming messages.
2. **Autonomous orchestrator** (`parrot/autonomous/`) — `AutonomousOrchestrator` with a rich hook system (13+ hook types: scheduler, file watchdog, Postgres LISTEN/NOTIFY, IMAP, Jira webhooks, message brokers, etc.).

These two worlds are isolated. An agent started via Telegram cannot react to hooks (file watchdog, scheduler, external webhook). Hooks are tightly coupled to `parrot/autonomous/`, making them unavailable to integration-based agents without importing the entire orchestrator package.

Since `parrot/autonomous/` is **not yet deployed to production**, there is no backward-compatibility constraint — all imports can be moved directly to the new canonical location.

### Goals

1. **Create `parrot/core/hooks/`** — New canonical location for all hook infrastructure (`BaseHook`, `HookManager`, `HookEvent`, `HookType`, all config models, all concrete hook implementations).
2. **Create `parrot/core/events/`** — Move `EventBus` from `parrot/autonomous/evb.py` to `parrot/core/events/evb.py`.
3. **Update `parrot/autonomous/`** — Change all imports to reference `parrot.core.hooks` and `parrot.core.events`.
4. **Add `HookableAgent` mixin** — In `parrot/core/hooks/mixins.py`, provide `attach_hooks()`, `start_hooks()`, `stop_hooks()`, `handle_hook_event()` for integration handlers.
5. **`HookManager` → `EventBus` integration** — `HookManager` should optionally emit events to `EventBus` in addition to the direct callback, enabling distributed hook consumption.
6. **Integration YAML `hooks:` section** — Integration configs (e.g., Telegram agent YAML) should support declaring attached hooks.

### Non-Goals (explicitly out of scope)

- Creating new hook types (only moving existing ones)
- Modifying hook behavior or API signatures
- Adding hooks to specific integration handlers (that's a follow-up task per integration)
- Backward-compatible re-exports from `parrot/autonomous/hooks/` (not in production)

---

## 2. Architectural Design

### Overview

This is a **structural refactor** following Option A from the brainstorm: extract all hook infrastructure to `parrot/core/hooks/`, move `EventBus` to `parrot/core/events/`, and update all consumers.

### New Package Structure

```
parrot/core/                          # NEW — shared infrastructure
├── __init__.py
├── hooks/                            # Hook system (moved from autonomous/hooks/)
│   ├── __init__.py                   # Lazy-loading exports (same pattern)
│   ├── base.py                       # BaseHook ABC
│   ├── manager.py                    # HookManager registry + lifecycle
│   ├── models.py                     # HookEvent, HookType, all config models
│   ├── mixins.py                     # NEW — HookableAgent mixin
│   ├── scheduler.py                  # SchedulerHook (APScheduler)
│   ├── file_watchdog.py              # FileWatchdogHook (watchdog)
│   ├── file_upload.py                # FileUploadHook (aiohttp)
│   ├── postgres.py                   # PostgresListenHook (asyncpg)
│   ├── imap.py                       # IMAPWatchdogHook (aioimaplib)
│   ├── jira_webhook.py               # JiraWebhookHook (aiohttp)
│   ├── sharepoint.py                 # SharePointHook (azure-identity)
│   ├── messaging.py                  # TelegramHook, WhatsAppHook, MSTeamsHook
│   ├── whatsapp_redis.py             # WhatsAppRedisHook
│   ├── matrix.py                     # MatrixHook
│   ├── filesystem.py                 # FilesystemHook
│   └── brokers/                      # Message broker hooks
│       ├── __init__.py
│       ├── base.py                   # BaseBrokerHook
│       ├── redis.py                  # RedisBrokerHook
│       ├── rabbitmq.py               # RabbitMQBrokerHook
│       ├── mqtt.py                   # MQTTBrokerHook
│       └── sqs.py                    # SQSBrokerHook
└── events/                           # Event bus (moved from autonomous/evb.py)
    ├── __init__.py                   # Exports: EventBus, Event, EventPriority
    └── evb.py                        # EventBus implementation
```

### Modified Structure

```
parrot/autonomous/
├── __init__.py
├── hooks/                            # GUTTED — imports from parrot.core.hooks
│   └── __init__.py                   # from parrot.core.hooks import *
├── orchestrator.py                   # Updated imports → parrot.core.hooks, parrot.core.events
├── evb.py                            # REMOVED or thin import from parrot.core.events.evb
├── redis_jobs.py                     # Unchanged
└── webhooks.py                       # Unchanged
```

### Integration Points

| Component | Relationship | Description |
|---|---|---|
| `parrot/core/hooks/` | **creates** | Canonical hook location |
| `parrot/core/events/` | **creates** | Canonical EventBus location |
| `parrot/autonomous/hooks/` | **replaces** | Becomes thin re-import or deleted |
| `parrot/autonomous/evb.py` | **replaces** | Becomes thin re-import or deleted |
| `parrot/autonomous/orchestrator.py` | **modifies** | Update imports |
| `parrot/autonomous/redis_jobs.py` | **check** | May import EventBus — update if so |
| `parrot/autonomous/webhooks.py` | **check** | May import hooks — update if so |
| Integration handlers | **extends** (future) | Can attach hooks via `HookableAgent` mixin |

### Callback + EventBus Dual-Emit Pattern

`HookManager` gains optional `EventBus` integration:

```
HookEvent → HookManager
              ├── direct callback (existing) → consumer.handle_hook_event()
              └── EventBus.emit() (optional) → distributed subscribers
```

When `HookManager.set_event_bus(bus)` is called, every hook event is also published to the `EventBus` on channel `hooks.<hook_type>.<event_type>`. This enables:
- Multiple consumers for the same hook event
- Distributed deployments (Redis-backed EventBus)
- Observability/logging subscribers

---

## 3. Module Breakdown

### Module 1: `parrot/core/__init__.py`
- Package init for shared infrastructure.
- Minimal — does not eagerly import hooks or events.

### Module 2: `parrot/core/hooks/` (move)
- **All files** from `parrot/autonomous/hooks/` moved here as-is.
- `__init__.py` preserves the lazy-loading `__getattr__` pattern.
- Internal relative imports (e.g., `from .base import BaseHook`) remain valid since directory structure is preserved.
- `models.py` imports updated if any reference `parrot.autonomous`.

### Module 3: `parrot/core/hooks/mixins.py` (new)
- `HookableAgent` mixin class providing:
  - `hook_manager: HookManager` — instance attribute
  - `attach_hook(hook: BaseHook) -> str` — register a hook
  - `start_hooks() -> None` — start all registered hooks
  - `stop_hooks() -> None` — stop all registered hooks
  - `handle_hook_event(event: HookEvent) -> None` — default event handler (logs + passes to agent)
- Designed to be mixed into integration handlers (`TelegramAgentWrapper`, `SlackWrapper`, etc.).

### Module 4: `parrot/core/events/` (move)
- `evb.py` moved from `parrot/autonomous/evb.py`.
- `__init__.py` exports: `EventBus`, `Event`, `EventPriority`, `EventSubscription`.

### Module 5: `parrot/core/hooks/manager.py` (enhance)
- Add `set_event_bus(bus: EventBus) -> None` method.
- When event bus is set, `on_event()` also calls `await bus.emit(f"hooks.{event.hook_type}.{event.event_type}", event.model_dump())`.
- Backward compatible — if no bus is set, behavior is unchanged.

### Module 6: `parrot/autonomous/hooks/__init__.py` (update)
- Replace all definitions with: `from parrot.core.hooks import *`
- Since autonomous is not in production, this can alternatively be deleted entirely, with `orchestrator.py` importing from `parrot.core.hooks` directly.

### Module 7: `parrot/autonomous/evb.py` (update)
- Replace with: `from parrot.core.events.evb import *` (or delete and update orchestrator imports).

### Module 8: `parrot/autonomous/orchestrator.py` (update imports)
- Change `from .hooks import BaseHook, HookManager, HookEvent` → `from parrot.core.hooks import BaseHook, HookManager, HookEvent`
- Change `from .evb import EventBus, Event, EventPriority` → `from parrot.core.events import EventBus, Event, EventPriority`

---

## 4. Data Models

No new Pydantic models are created. All existing models (`HookEvent`, `HookType`, config models) move unchanged. The only addition is the `HookableAgent` mixin which is a plain class, not a Pydantic model.

---

## 5. Acceptance Criteria

### Functional
- [ ] `parrot/core/hooks/` package exists with all hook implementations
- [ ] `parrot/core/events/` package exists with `EventBus`
- [ ] `from parrot.core.hooks import BaseHook, HookManager, HookEvent, HookType` works
- [ ] `from parrot.core.hooks import SchedulerHook, FileWatchdogHook` (lazy) works
- [ ] `from parrot.core.hooks import BrokerHookConfig, FileWatchdogHookConfig` works
- [ ] `from parrot.core.events import EventBus, Event, EventPriority` works
- [ ] `parrot/autonomous/orchestrator.py` imports from `parrot.core.hooks` and `parrot.core.events`
- [ ] All existing autonomous tests pass after migration
- [ ] `HookableAgent` mixin can be attached to a mock integration handler
- [ ] `HookManager.set_event_bus()` dual-emits events to both callback and bus

### Non-Functional
- [ ] Lazy loading preserved — importing `parrot.core.hooks` does NOT pull in `asyncpg`, `watchdog`, `apscheduler`, etc.
- [ ] No circular imports between `parrot.core`, `parrot.autonomous`, and `parrot.integrations`
- [ ] `ruff check` passes on all new/modified files

---

## 6. External Dependencies

No new dependencies. All hook implementations already declare their dependencies in `pyproject.toml`:

| Package | Used By | Notes |
|---|---|---|
| `apscheduler` | `SchedulerHook` | Already in project |
| `watchdog` | `FileWatchdogHook` | Already in project |
| `asyncpg` | `PostgresListenHook` | Already in project |
| `aioimaplib` | `IMAPWatchdogHook` | Already in project |
| `pydantic` | All config models | Already in project |
| `redis`/`aioredis` | `EventBus`, broker hooks | Already in project |

---

## 7. Open Questions (Resolved)

| Question | Decision |
|---|---|
| Where should `HookableAgent` mixin live? | `parrot/core/hooks/mixins.py` |
| Should `HookManager` emit to `EventBus`? | Yes — optional dual-emit |
| Should integration YAML support `hooks:` section? | Yes — follow-up task after core migration |
| Backward-compatible re-exports from `parrot/autonomous/hooks/`? | Not required (not in production) |
| `FilesystemHook` included in migration? | Yes — part of migration |

---

## 8. Testing Strategy

### Unit Tests
- **Import tests**: Verify all public symbols importable from `parrot.core.hooks` and `parrot.core.events`
- **Lazy loading**: Verify that importing `parrot.core.hooks` doesn't eagerly load heavy dependencies
- **HookableAgent mixin**: Verify attach/start/stop/handle lifecycle with mock hooks
- **HookManager EventBus integration**: Verify dual-emit when bus is set, callback-only when not

### Integration Tests
- **Orchestrator smoke test**: `AutonomousOrchestrator` initializes correctly with new import paths
- **Hook → callback flow**: Register hook, fire event, verify callback receives `HookEvent`
- **Hook → EventBus flow**: Register hook + bus, fire event, verify both callback and bus receive event

---

## 9. Migration Plan

Since `parrot/autonomous/` is not in production, this is a clean move:

1. **Create `parrot/core/`** — package init
2. **Move hooks** — `git mv parrot/autonomous/hooks/ parrot/core/hooks/` (or copy + delete)
3. **Move EventBus** — Create `parrot/core/events/`, move `evb.py`
4. **Create `mixins.py`** — `HookableAgent` mixin in `parrot/core/hooks/`
5. **Enhance `manager.py`** — Add `set_event_bus()` method
6. **Update autonomous imports** — `orchestrator.py`, `__init__.py`, any other files referencing hooks or evb
7. **Update `parrot/autonomous/hooks/`** — Either delete or make thin re-import
8. **Run tests** — All existing tests must pass
9. **Update CONTEXT.md** — Document new `parrot/core/` location
