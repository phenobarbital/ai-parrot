# TASK-1823: Delete generic hooks + brokers, rewire integration hooks + `hooks/__init__.py`

**Feature**: FEAT-317 — Parrot EventBus Migration
**Spec**: `sdd/specs/parrot-eventbus-migration.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1821
**Assigned-to**: unassigned

---

## Context

Module 4 of spec §3. The generic hooks layer (`base`, `manager`, `models`,
`mixins`, `scheduler`, `file_watchdog`) and the `brokers/` package were
extracted to `navigator_eventbus.hooks` in FEAT-312 (base/manager/models/
mixins/scheduler/file_watchdog/brokers) and the broker connection layer in
FEAT-316. This task deletes the ai-parrot copies, rewires the 9 **integration
hooks** (which stay) to import `BaseHook`/`HookRegistry`/models absolutely
from the package, and rebuilds `hooks/__init__.py` to preserve its public
surface.

---

## Preflight (BLOCKING)

Verify the package hooks surface (present as of 2026-07-18 for FEAT-312;
brokers submodule depends on FEAT-316):

```bash
source .venv/bin/activate
python -c "from navigator_eventbus.hooks import BaseHook, HookRegistry, MessagingHook, HookManager, HookableAgent"
python -c "from navigator_eventbus.hooks.models import HookEvent, HookType, HOOK_TYPES, JiraWebhookConfig, GitHubWebhookConfig, SharePointHookConfig, WhatsAppRedisHookConfig, MatrixHookConfig, IMAPHookConfig, MessagingHookConfig, PostgresHookConfig, FileUploadHookConfig"
python -c "from navigator_eventbus.hooks.base import BaseHook, HookRegistry"
```

---

## Scope

- Delete from `parrot/core/hooks/`:
  `base.py`, `manager.py`, `models.py`, `mixins.py`, `scheduler.py`,
  `file_watchdog.py`, and the entire `brokers/` directory.
- Rewire the 9 integration hooks (STAY) from relative `.base`/`.models`
  imports to absolute `navigator_eventbus.hooks` imports:
  `github_webhook.py`, `jira_webhook.py`, `sharepoint.py`,
  `whatsapp_redis.py`, `imap.py`, `messaging.py`, `postgres.py`,
  `file_upload.py`, `matrix.py`.
- Rebuild `hooks/__init__.py`:
  - Eager imports (`BaseHook`, `HookRegistry`, `MessagingHook`, `HookManager`,
    `HookableAgent`, `HookEvent`, `HookType`, all `*Config` models,
    `TransitionAction/Type`, `create_*` factory helpers) → from
    `navigator_eventbus.hooks`.
  - Split the lazy `__getattr__` map: generic hooks (`SchedulerHook`,
    `FileWatchdogHook`, `BaseBrokerHook`, `RedisBrokerHook`,
    `RabbitMQBrokerHook`, `MQTTBrokerHook`, `SQSBrokerHook`) →
    `navigator_eventbus.hooks.<submodule>`; integration hooks
    (`JiraWebhookHook`, `GitHubWebhookHook`, `SharePointHook`,
    `WhatsAppRedisHook`, `MatrixHook`, `TelegramHook`, `WhatsAppHook`,
    `MSTeamsHook`, `IMAPWatchdogHook`, `PostgresListenHook`, `FileUploadHook`)
    → local submodules.
  - Preserve the existing `__all__` (see Contract).

**NOT in scope**: bus core (TASK-1821); lifecycle (TASK-1822); consumers in
bots/server/integrations (TASK-1824/1826); tests (TASK-1827).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `.../core/hooks/{base,manager,models,mixins,scheduler,file_watchdog}.py` | DELETE | moved to `navigator_eventbus.hooks` |
| `.../core/hooks/brokers/` | DELETE | moved to package (FEAT-312/316) |
| `.../core/hooks/__init__.py` | MODIFY | eager + lazy re-export facade (see scope) |
| `.../core/hooks/{github_webhook,jira_webhook,sharepoint,whatsapp_redis,imap,messaging,postgres,file_upload,matrix}.py` | MODIFY | `.base`/`.models` → `navigator_eventbus.hooks` |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports (target) — VERIFIED in navigator-eventbus 2026-07-18

```python
from navigator_eventbus.hooks import (
    BaseHook, HookRegistry, MessagingHook, HookManager, HookableAgent,
    HookEvent, HookType, HookTypeRegistry, HOOK_TYPES,
    BrokerHookConfig, FilesystemHookConfig, FileUploadHookConfig,
    FileWatchdogHookConfig, GitHubWebhookConfig, IMAPHookConfig,
    JiraWebhookConfig, MatrixHookConfig, MessagingHookConfig,
    PostgresHookConfig, SchedulerHookConfig, SharePointHookConfig,
    WhatsAppRedisHookConfig, TransitionAction, TransitionActionType,
    create_simple_whatsapp_hook, create_multi_agent_whatsapp_hook,
    create_crew_whatsapp_hook,
)
from navigator_eventbus.hooks.base import BaseHook, HookRegistry
```

### Integration-hook rewrites — VERIFIED current relative imports 2026-07-18

```python
# github_webhook.py:  from .base import BaseHook; from .models import GitHubWebhookConfig, HookType
# jira_webhook.py:    from .base import BaseHook; from .models import HookType, JiraWebhookConfig
# sharepoint.py:      from .base import BaseHook; from .models import HookType, SharePointHookConfig
# whatsapp_redis.py:  from .base import BaseHook; from .models import HookType, WhatsAppRedisHookConfig
# imap.py:            from .base import BaseHook; from .models import HookType, IMAPHookConfig
# messaging.py:       from .base import BaseHook; from .models import HookType, MessagingHookConfig
# postgres.py:        from .base import BaseHook; from .models import HookType, PostgresHookConfig
# file_upload.py:     from .base import BaseHook; from .models import FileUploadHookConfig, HookType
# matrix.py:          from .base import BaseHook, HookRegistry; from .models import HookType, MatrixHookConfig
#   → each becomes: from navigator_eventbus.hooks.base import BaseHook[, HookRegistry]
#                   from navigator_eventbus.hooks.models import <Config>, HookType
```

### Public surface to preserve — VERIFIED current `hooks/__init__.py` `__all__` 2026-07-18

Eager: `BaseHook, HookRegistry, MessagingHook, HookManager, HookableAgent,
HookEvent, HookType`. Lazy hooks: `SchedulerHook, FileWatchdogHook,
PostgresListenHook, IMAPWatchdogHook, JiraWebhookHook, GitHubWebhookHook,
FileUploadHook, SharePointHook, TelegramHook, WhatsAppHook, MSTeamsHook,
WhatsAppRedisHook, MatrixHook, BaseBrokerHook, RedisBrokerHook,
RabbitMQBrokerHook, MQTTBrokerHook, SQSBrokerHook`. Configs (eager):
`SchedulerHookConfig, FileWatchdogHookConfig, PostgresHookConfig,
IMAPHookConfig, JiraWebhookConfig, GitHubWebhookConfig, FileUploadHookConfig,
BrokerHookConfig, SharePointHookConfig, MessagingHookConfig,
WhatsAppRedisHookConfig, MatrixHookConfig`. Plus `TransitionAction,
TransitionActionType, create_simple_whatsapp_hook,
create_multi_agent_whatsapp_hook, create_crew_whatsapp_hook`.

### Does NOT Exist

- ~~`parrot.core.hooks.base` / `.models` / `.manager` after this task~~ — deleted; only `__init__.py` re-exports them from the package.
- ~~generic `TelegramHook/WhatsAppHook/MSTeamsHook` in the package~~ — messaging
  hooks are ai-parrot integration hooks; they lazy-load from local `.messaging`.
- ~~`FilesystemHookConfig` in parrot's old models~~ — it is a package model
  (added FEAT-312); import it from `navigator_eventbus.hooks.models` where needed.

---

## Implementation Notes

### Key Constraints
- Delete with `git rm`.
- The lazy `__getattr__` split is the trickiest part: generic hooks resolve to
  `importlib.import_module("navigator_eventbus.hooks.<mod>")`; integration hooks
  resolve to the local `.` package. Keep the `MessagingHook` base eager from the
  package.
- `matrix.py` in `core/hooks/` is a thin re-export/stub; the real hook is in
  `ai-parrot-integrations` (rewired in TASK-1826). Only fix its imports here.

### References in Codebase
- Spec §3 Module 4, §7 "Known Risks" (relative-import + lazy-map split).

---

## Acceptance Criteria

- [ ] The 6 generic hook files + `brokers/` are deleted.
- [ ] `from parrot.core.hooks import BaseHook, HookManager, HookEvent, HookType` resolves (re-exported from package).
- [ ] `from parrot.core.hooks import JiraWebhookConfig, MatrixHookConfig, TransitionAction` resolves.
- [ ] `parrot.core.hooks.JiraWebhookHook` lazy-loads (local); `parrot.core.hooks.SchedulerHook` lazy-loads (package).
- [ ] Each integration hook imports `BaseHook` from `navigator_eventbus.hooks.base` (no relative `.base`).
- [ ] New `__all__` ⊇ old `__all__`.
- [ ] `ruff check` clean on modified files.

---

## Test Specification

```bash
python - <<'PY'
from parrot.core.hooks import BaseHook, HookManager, HookEvent, HookType, JiraWebhookConfig
import navigator_eventbus.hooks as nh
assert BaseHook is nh.BaseHook
# lazy resolution
from parrot.core.hooks import JiraWebhookHook   # local integration hook
assert issubclass(JiraWebhookHook, nh.BaseHook)
print("hooks facade OK")
PY
```

---

## Agent Instructions

1. Run **Preflight**.
2. Verify TASK-1821 completed and the Codebase Contract.
3. Update index → `in-progress`.
4. Delete generics + brokers; rewire 9 integration hooks; rebuild `__init__.py`.
5. Verify acceptance criteria; move to completed; update index; fill note.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:
**Deviations from spec**: none | describe if any
