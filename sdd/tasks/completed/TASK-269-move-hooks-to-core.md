# TASK-269: Move Hooks to parrot/core/hooks/

**Feature**: Shared Hooks Infrastructure (FEAT-040)
**Spec**: `sdd/specs/integrations-hooks.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-268
**Assigned-to**: claude-session

---

## Context

> Move all hook infrastructure from `parrot/autonomous/hooks/` to `parrot/core/hooks/`.
> This is the core migration task — all 15+ files move as-is, preserving lazy loading.
> Since `parrot/autonomous/` is not in production, no backward-compatible re-exports are needed.

---

## Scope

### Files to Move (parrot/autonomous/hooks/ → parrot/core/hooks/)

| Source | Destination | Notes |
|---|---|---|
| `hooks/__init__.py` | `core/hooks/__init__.py` | Preserve lazy `__getattr__` pattern |
| `hooks/base.py` | `core/hooks/base.py` | `BaseHook` ABC |
| `hooks/manager.py` | `core/hooks/manager.py` | `HookManager` |
| `hooks/models.py` | `core/hooks/models.py` | `HookEvent`, `HookType`, all config models |
| `hooks/scheduler.py` | `core/hooks/scheduler.py` | `SchedulerHook` |
| `hooks/file_watchdog.py` | `core/hooks/file_watchdog.py` | `FileWatchdogHook` |
| `hooks/file_upload.py` | `core/hooks/file_upload.py` | `FileUploadHook` |
| `hooks/postgres.py` | `core/hooks/postgres.py` | `PostgresListenHook` |
| `hooks/imap.py` | `core/hooks/imap.py` | `IMAPWatchdogHook` |
| `hooks/jira_webhook.py` | `core/hooks/jira_webhook.py` | `JiraWebhookHook` |
| `hooks/sharepoint.py` | `core/hooks/sharepoint.py` | `SharePointHook` |
| `hooks/messaging.py` | `core/hooks/messaging.py` | Telegram/WhatsApp/MSTeams hooks |
| `hooks/whatsapp_redis.py` | `core/hooks/whatsapp_redis.py` | `WhatsAppRedisHook` |
| `hooks/matrix.py` | `core/hooks/matrix.py` | `MatrixHook` |
| `hooks/filesystem.py` | `core/hooks/filesystem.py` | `FilesystemHook` |
| `hooks/brokers/__init__.py` | `core/hooks/brokers/__init__.py` | Broker subpackage |
| `hooks/brokers/base.py` | `core/hooks/brokers/base.py` | `BaseBrokerHook` |
| `hooks/brokers/redis.py` | `core/hooks/brokers/redis.py` | `RedisBrokerHook` |
| `hooks/brokers/rabbitmq.py` | `core/hooks/brokers/rabbitmq.py` | `RabbitMQBrokerHook` |
| `hooks/brokers/mqtt.py` | `core/hooks/brokers/mqtt.py` | `MQTTBrokerHook` |
| `hooks/brokers/sqs.py` | `core/hooks/brokers/sqs.py` | `SQSBrokerHook` |

### Files to Modify

| File | Action | Description |
|---|---|---|
| `parrot/autonomous/hooks/__init__.py` | REPLACE | Thin re-import: `from parrot.core.hooks import *` |

### Implementation Notes

- Use `git mv` for file moves to preserve history.
- Internal relative imports (e.g., `from .base import BaseHook` in `__init__.py`) remain valid since directory structure is preserved.
- Check each file for any absolute imports referencing `parrot.autonomous.hooks` and update to `parrot.core.hooks`.
- The `__init__.py` lazy `__getattr__` pattern must be preserved exactly — this prevents pulling in heavy deps like `asyncpg`, `watchdog`, `apscheduler` at import time.
- `parrot/autonomous/hooks/__init__.py` becomes a thin re-import as a transitional step (can be deleted later).

---

## Acceptance Criteria

- [ ] All hook files exist under `parrot/core/hooks/`
- [ ] `from parrot.core.hooks import BaseHook, HookManager, HookEvent, HookType` works
- [ ] `from parrot.core.hooks import SchedulerHook` (lazy) works
- [ ] `from parrot.core.hooks import BrokerHookConfig, FileWatchdogHookConfig` works
- [ ] Lazy loading preserved — `import parrot.core.hooks` does NOT pull in `asyncpg`, `watchdog`, etc.
- [ ] `ruff check parrot/core/hooks/` passes
- [ ] No circular imports

---

## Agent Instructions

1. Read the spec for full context
2. Create `parrot/core/hooks/` directory structure (including `brokers/`)
3. Move all files using `git mv parrot/autonomous/hooks/<file> parrot/core/hooks/<file>`
4. Scan each moved file for absolute imports referencing `parrot.autonomous.hooks` and update
5. Replace `parrot/autonomous/hooks/__init__.py` with thin re-import
6. Verify imports work: `python -c "from parrot.core.hooks import BaseHook, HookManager, HookEvent"`
7. Run `ruff check parrot/core/hooks/`
8. Update status → `done`, move to `sdd/tasks/completed/`

---

## Completion Note

Completed 2026-03-10.

- All 20 files moved via `git mv` from `parrot/autonomous/hooks/` to `parrot/core/hooks/` (preserving git history).
- `brokers/` subpackage moved intact (`__init__`, `base`, `redis`, `rabbitmq`, `mqtt`, `sqs`).
- No absolute `parrot.autonomous.hooks` imports found in any moved file — all internal imports are relative.
- `parrot/autonomous/hooks/__init__.py` replaced with thin re-export shim (`from parrot.core.hooks import *`).
- `parrot/autonomous/hooks/brokers/__init__.py` added as matching shim.
- Lazy `__getattr__` pattern preserved exactly — `asyncpg`, `watchdog`, `apscheduler`, `aioimaplib` not pulled in on bare `import parrot.core.hooks`.
- 7 pre-existing ruff warnings fixed (unused imports); 1 unused `token =` variable removed from `sharepoint.py`.
- `ruff check parrot/core/hooks/` passes clean.
